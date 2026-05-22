import os
from datetime import datetime, timezone

from firebase_functions import https_fn
from pydantic import ValidationError

from agent import GEMINI_MODEL, analizar_ingreso
from database import buscar_poliza, evaluar_poliza, listar_asegurados
from http_utils import json_response
from models import CasoEmergencia, EmergenciaWebhookPayload, RespuestaWebhook
from notifier import (
    caso_existente,
    escribir_caso,
    notificar_telegram,
    obtener_casos_memoria,
)

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()


def raiz():
    return json_response(
        {
            "servicio": "SATIE — Sistema de Alerta Temprana de Ingresos a Emergencias",
            "estado": "activo",
            "modelo_ia": GEMINI_MODEL,
            "endpoints": {
                "webhook": "POST /webhook/emergencia",
                "salud": "GET /health",
                "casos": "GET /casos",
                "asegurados_demo": "GET /asegurados",
            },
        }
    )


def health():
    return json_response({"estado": "ok", "hora": datetime.now(timezone.utc).isoformat()})


def asegurados():
    return json_response(
        [
            {
                "cedula": p.cedula,
                "nombre": p.nombre,
                "plan": p.plan,
                "aseguradora": p.aseguradora,
                "descripcion_caso": p.descripcion_caso,
                "hospitales_red": p.hospitales_red,
            }
            for p in listar_asegurados()
        ]
    )


def casos():
    try:
        from firebase_admin import db
        from notifier import FIREBASE_DB_URL

        if FIREBASE_DB_URL:
            return json_response(db.reference("casos").get() or {})
    except Exception:
        pass
    return json_response(obtener_casos_memoria())


def procesar_webhook(req: https_fn.Request):
    if WEBHOOK_SECRET and req.headers.get("X-Webhook-Secret") != WEBHOOK_SECRET:
        return json_response({"detail": "Webhook secret inválido."}, status=401)

    try:
        payload = EmergenciaWebhookPayload(**(req.get_json(silent=True) or {}))
    except ValidationError as exc:
        return json_response({"detail": exc.errors()}, status=422)

    previo = caso_existente(payload.evento_id)
    if previo:
        return _respuesta_duplicada(payload.evento_id, previo)

    poliza = buscar_poliza(payload.cedula)
    evaluacion = evaluar_poliza(poliza, payload.fecha_ingreso)
    analisis, fuente = analizar_ingreso(payload, poliza, evaluacion)
    caso = _construir_caso(payload, poliza, evaluacion, analisis, fuente)

    notif = notificar_telegram(caso.model_dump())
    caso_dict = caso.model_dump()
    caso_dict["notificaciones"] = notif
    notif["rtdb"] = escribir_caso(payload.evento_id, caso_dict)

    return json_response(
        RespuestaWebhook(
            evento_id=payload.evento_id,
            estado="PROCESADO",
            validez_poliza=evaluacion.validez,
            estado_cobertura_presunta=analisis.estado_cobertura_presunta,
            nivel_triaje=analisis.nivel_triaje,
            riesgo_siniestro=analisis.riesgo_siniestro,
            notificaciones=notif,
        ).model_dump()
    )


def not_found(path: str):
    return json_response({"detail": "Ruta no encontrada.", "path": path}, status=404)


def _respuesta_duplicada(evento_id: str, caso_previo: dict):
    analisis = caso_previo["analisis_agente"]
    return json_response(
        RespuestaWebhook(
            evento_id=evento_id,
            estado="DUPLICADO",
            validez_poliza=caso_previo["evaluacion_poliza"]["validez"],
            estado_cobertura_presunta=analisis["estado_cobertura_presunta"],
            nivel_triaje=analisis["nivel_triaje"],
            riesgo_siniestro=analisis["riesgo_siniestro"],
            notificaciones=caso_previo.get("notificaciones", {}),
        ).model_dump()
    )


def _construir_caso(payload, poliza, evaluacion, analisis, fuente):
    return CasoEmergencia(
        evento_id=payload.evento_id,
        recibido_en=datetime.now(timezone.utc).isoformat(),
        paciente={
            "cedula": payload.cedula,
            "nombre_paciente": payload.nombre_paciente,
            "motivo_ingreso": payload.motivo_ingreso,
            "hospital": payload.hospital,
            "triaje_hospital": payload.triaje_hospital,
            "signos_vitales": (
                payload.signos_vitales.model_dump()
                if payload.signos_vitales else None
            ),
            "fecha_ingreso": payload.fecha_ingreso.isoformat(),
        },
        poliza=(poliza.model_dump() if poliza else None),
        evaluacion_poliza=evaluacion.model_dump(),
        analisis_agente=analisis.model_dump(),
        fuente_analisis=fuente,
        notificaciones={},
    )
