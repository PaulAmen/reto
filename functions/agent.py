"""Agente de análisis de ingresos a emergencias.

Usa Gemini para cruzar el motivo de ingreso con la póliza, las preexistencias
declaradas y los periodos de carencia. Si no hay clave de API o la llamada
falla, recurre a un análisis determinístico de respaldo para que el sistema
nunca deje de responder al webhook.
"""
from __future__ import annotations

import json
import logging
import os
import unicodedata

from models import AnalisisAgente, EmergenciaWebhookPayload, EvaluacionPoliza, Poliza

logger = logging.getLogger("satie.agent")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

_cliente = None
if GEMINI_API_KEY:
    try:
        from google import genai

        _cliente = genai.Client(api_key=GEMINI_API_KEY)
        logger.info("Agente Gemini habilitado (modelo: %s)", GEMINI_MODEL)
    except Exception as exc:  # pragma: no cover
        logger.warning("No se pudo inicializar Gemini: %s", exc)
else:
    logger.warning("GEMINI_API_KEY no definida: se usará el análisis de respaldo.")


SYSTEM_PROMPT = """\
Eres un analista de siniestros de seguros de salud que asiste, en tiempo real,
al área de admisiones de un hospital y al gestor de casos de una aseguradora
cuando un asegurado ingresa a emergencias.

Tu tarea es evaluar el caso de forma inmediata y emitir un análisis estructurado.

Reglas estrictas:
- Básate ÚNICAMENTE en los datos provistos. No inventes condiciones, montos ni fechas.
- No emitas diagnósticos ni recomendaciones médicas; tu enfoque es administrativo
  y de cobertura.
- La evaluación de cobertura es PRELIMINAR y no vinculante; cuando haya dudas,
  marca el estado como REQUIERE_REVISION.
- Determina si el motivo de ingreso guarda relación clínica con alguna
  preexistencia declarada (p. ej. dolor torácico con cardiopatía declarada).
- Si el motivo se relaciona con una preexistencia y la póliza aún está dentro
  del periodo de carencia para preexistencias, marca aplica_periodo_carencia=true
  y el estado de cobertura como REQUIERE_REVISION o COBERTURA_PARCIAL.
- Si la póliza está VENCIDA o el paciente NO_ASEGURADO, el estado de cobertura
  es NO_CUBIERTO. Si está EN_MORA, es REQUIERE_REVISION.
- Redacta dos mensajes con destinatarios distintos:
  * mensaje_admisiones_hospital: operativo y breve, dirigido al personal de
    admisiones. Indica validez de la póliza y qué hacer con el paciente.
  * mensaje_gestor_seguro: analítico, dirigido al gestor de casos del seguro.
    Resalta riesgo, preexistencias, carencia y qué documentación revisar.
- Escribe en español, en tono profesional, claro y conciso (3 a 5 oraciones por
  mensaje). No uses listas dentro de los mensajes.
"""


def _construir_prompt(
    payload: EmergenciaWebhookPayload,
    poliza: Poliza | None,
    evaluacion: EvaluacionPoliza,
) -> str:
    if poliza is not None:
        preex = (
            "; ".join(p.condicion for p in poliza.preexistencias)
            or "ninguna declarada"
        )
        datos_poliza = (
            f"Número de póliza: {poliza.numero_poliza}\n"
            f"Aseguradora: {poliza.aseguradora}\n"
            f"Plan: {poliza.plan}\n"
            f"Suma asegurada: USD {poliza.suma_asegurada:,.2f}\n"
            f"Deducible: USD {poliza.deducible:,.2f}\n"
            f"Estado de pago: {poliza.estado_pago} "
            f"(mora: {poliza.meses_mora} mes/es)\n"
            f"Vigencia: {poliza.fecha_inicio} a {poliza.fecha_fin}\n"
            f"Antigüedad de la póliza: {poliza.antiguedad_meses} meses\n"
            f"Carencia general: {poliza.carencia_general_meses} meses\n"
            f"Carencia para preexistencias: "
            f"{poliza.carencia_preexistencias_meses} meses\n"
            f"Preexistencias declaradas: {preex}\n"
            f"Hospitales en red: {', '.join(poliza.hospitales_red)}"
        )
    else:
        datos_poliza = "No se encontró póliza para esta cédula."

    sv = payload.signos_vitales
    signos = "No reportados"
    if sv is not None:
        signos = (
            f"PA {sv.presion_arterial or '-'}, "
            f"FC {sv.frecuencia_cardiaca or '-'}, "
            f"T {sv.temperatura or '-'}, "
            f"SatO2 {sv.saturacion_oxigeno or '-'}"
        )

    return (
        "INGRESO A EMERGENCIAS\n"
        f"Paciente: {payload.nombre_paciente} (cédula {payload.cedula})\n"
        f"Hospital: {payload.hospital}\n"
        f"Motivo de ingreso: {payload.motivo_ingreso}\n"
        f"Triaje inicial del hospital: {payload.triaje_hospital or 'no indicado'}\n"
        f"Signos vitales: {signos}\n\n"
        "DATOS DE LA PÓLIZA\n"
        f"{datos_poliza}\n\n"
        "EVALUACIÓN DETERMINÍSTICA YA REALIZADA (no la recalcules)\n"
        f"Validez de la póliza: {evaluacion.validez}\n"
        f"Estado: {evaluacion.mensaje_estado}\n"
        f"Dentro de carencia general: {evaluacion.dentro_carencia_general}\n"
        f"Dentro de carencia para preexistencias: "
        f"{evaluacion.dentro_carencia_preexistencias}\n\n"
        "Analiza el caso y devuelve el JSON solicitado."
    )


def _analisis_gemini(
    payload: EmergenciaWebhookPayload,
    poliza: Poliza | None,
    evaluacion: EvaluacionPoliza,
) -> AnalisisAgente:
    from google.genai import types

    prompt = _construir_prompt(payload, poliza, evaluacion)
    respuesta = _cliente.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=AnalisisAgente,
            temperature=0.3,
        ),
    )
    if getattr(respuesta, "parsed", None):
        return respuesta.parsed
    return AnalisisAgente(**json.loads(respuesta.text))


# --- Respaldo determinístico ------------------------------------------------

_PALABRAS_CRITICAS = (
    "paro", "infarto", "inconsciente", "no responde", "convuls",
    "hemorragia masiva", "shock",
)
_PALABRAS_URGENTES = (
    "dolor torácico", "dolor de pecho", "dificultad respiratoria",
    "fractura", "trauma", "sangrado", "fiebre alta", "accidente",
)


def _normalizar(texto: str) -> str:
    """Minúsculas sin acentos, para comparaciones robustas."""
    nfkd = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _triaje_por_palabras(motivo: str) -> str:
    texto = _normalizar(motivo)
    if any(_normalizar(p) in texto for p in _PALABRAS_CRITICAS):
        return "CRITICO"
    if any(_normalizar(p) in texto for p in _PALABRAS_URGENTES):
        return "URGENTE"
    return "MODERADO"


# Asociaciones clínicas básicas para el respaldo: por cada palabra clave de la
# preexistencia, términos del motivo de ingreso que sugieren relación.
_ASOCIACIONES = {
    ("cardio", "hipertens", "cardiac"): (
        "toracic", "torácic", "pecho", "corazon", "corazón", "infarto",
        "cardiac", "cardíac", "palpitac", "arritmia", "presion", "presión",
    ),
    ("diabet",): (
        "diabet", "glucem", "glucosa", "azucar", "azúcar", "descompens",
        "hipergluc", "hipogluc", "cetoacid",
    ),
    ("asma", "respiratori", "bronqui"): (
        "respiratori", "disnea", "asma", "ahogo", "broncoespasmo", "bronqui",
        "dificultad respiratoria", "tos",
    ),
    ("oncolog", "cancer", "cáncer", "tumor"): (
        "tumor", "cancer", "cáncer", "oncolog", "masa", "metastas", "metástas",
        "quimioterap",
    ),
    ("embarazo", "gestac", "obstetr"): (
        "obstetr", "obstétr", "parto", "embaraz", "contracci", "gestac",
        "sangrado vaginal", "preeclampsia",
    ),
}


def _preexistencia_relacionada(motivo: str, condicion: str) -> bool:
    """Heurística de respaldo: coincidencia de tokens o asociación clínica."""
    m, c = _normalizar(motivo), _normalizar(condicion)
    # Coincidencia directa de tokens significativos.
    if any(t in m for t in (tok for tok in c.split() if len(tok) > 4)):
        return True
    # Asociación clínica conocida.
    for claves_pre, terminos_motivo in _ASOCIACIONES.items():
        if any(_normalizar(k) in c for k in claves_pre) and any(
            _normalizar(t) in m for t in terminos_motivo
        ):
            return True
    return False


def _analisis_respaldo(
    payload: EmergenciaWebhookPayload,
    poliza: Poliza | None,
    evaluacion: EvaluacionPoliza,
) -> AnalisisAgente:
    triaje = _triaje_por_palabras(payload.motivo_ingreso)

    relacionada = False
    detalle = "Sin preexistencias declaradas relacionadas con el motivo."
    if poliza and poliza.preexistencias:
        for pre in poliza.preexistencias:
            if _preexistencia_relacionada(payload.motivo_ingreso, pre.condicion):
                relacionada = True
                detalle = (
                    f"El motivo de ingreso podría relacionarse con la "
                    f"preexistencia declarada: {pre.condicion}."
                )
                break

    aplica_carencia = relacionada and evaluacion.dentro_carencia_preexistencias

    if evaluacion.validez in ("VENCIDA", "NO_ASEGURADO"):
        cobertura = "NO_CUBIERTO"
        riesgo = "ALTO"
    elif evaluacion.validez == "EN_MORA":
        cobertura = "REQUIERE_REVISION"
        riesgo = "ALTO"
    elif aplica_carencia:
        cobertura = "REQUIERE_REVISION"
        riesgo = "ALTO"
    elif relacionada:
        cobertura = "COBERTURA_PARCIAL"
        riesgo = "MEDIO"
    else:
        cobertura = "CUBIERTO"
        riesgo = "BAJO"

    nombre = payload.nombre_paciente
    msg_hospital = (
        f"Paciente {nombre} ingresa a {payload.hospital} por "
        f"{payload.motivo_ingreso}. Estado de póliza: {evaluacion.validez}. "
        f"{evaluacion.mensaje_estado} "
        + (
            "Proceda con la atención de emergencia y registre el caso."
            if cobertura != "NO_CUBIERTO"
            else "Atienda la emergencia e informe al paciente que su cobertura "
            "no está vigente para fines de facturación."
        )
    )
    msg_gestor = (
        f"Ingreso a emergencias de {nombre}. Validez de póliza: "
        f"{evaluacion.validez}. {detalle} "
        f"Cobertura presunta: {cobertura}; riesgo de siniestro: {riesgo}. "
        + (
            "Verifique la historia clínica por posible aplicación de carencia."
            if aplica_carencia
            else "Asigne gestor de caso y dé seguimiento al ingreso."
        )
    )

    acciones = ["Asignar gestor de caso", "Confirmar datos del ingreso con el hospital"]
    if evaluacion.validez == "EN_MORA":
        acciones.append("Verificar estado de pagos y notificar al asegurado")
    if aplica_carencia:
        acciones.append("Revisar historia clínica para evaluar periodo de carencia")
    if evaluacion.validez in ("VENCIDA", "NO_ASEGURADO"):
        acciones.append("Notificar a admisiones que la atención no tiene cobertura")

    return AnalisisAgente(
        nivel_triaje=triaje,
        preexistencia_relacionada=relacionada,
        detalle_preexistencia=detalle,
        aplica_periodo_carencia=aplica_carencia,
        estado_cobertura_presunta=cobertura,
        riesgo_siniestro=riesgo,
        resumen_clinico_administrativo=(
            f"Ingreso por {payload.motivo_ingreso}. {evaluacion.mensaje_estado}"
        ),
        mensaje_admisiones_hospital=msg_hospital,
        mensaje_gestor_seguro=msg_gestor,
        acciones_recomendadas=acciones,
    )


def analizar_ingreso(
    payload: EmergenciaWebhookPayload,
    poliza: Poliza | None,
    evaluacion: EvaluacionPoliza,
) -> tuple[AnalisisAgente, str]:
    """Devuelve (análisis, fuente). fuente es 'gemini' o 'fallback'."""
    if _cliente is not None:
        try:
            return _analisis_gemini(payload, poliza, evaluacion), "gemini"
        except Exception as exc:
            logger.error("Fallo en Gemini, se usa respaldo: %s", exc)
    return _analisis_respaldo(payload, poliza, evaluacion), "fallback"
