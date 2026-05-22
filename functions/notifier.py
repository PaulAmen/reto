"""Canales de notificación del sistema SATIE.

- Firebase Realtime Database: persiste cada caso y alimenta los paneles en vivo
  (Admisiones del hospital y Gestor de casos de la aseguradora).
- Telegram: envía la alerta de forma inmediata a dos chats/canales distintos.

Todos los canales degradan con elegancia: si falta configuración, el webhook
sigue respondiendo y simplemente se registra el canal como deshabilitado.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import logging
import os

import httpx

logger = logging.getLogger("satie.notifier")

FIREBASE_DB_URL = (
    os.getenv("RTDB_URL", "").strip()
    or os.getenv("FIREBASE_DB_URL", "").strip()
)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ADMISIONES = os.getenv("TELEGRAM_CHAT_ADMISIONES", "").strip()
TELEGRAM_CHAT_GESTOR = os.getenv("TELEGRAM_CHAT_GESTOR", "").strip()

_firebase_listo = False

# Respaldo de idempotencia cuando RTDB no está configurada.
_casos_memoria: dict[str, dict] = {}


def init_firebase() -> bool:
    """Inicializa Firebase Admin. Usa credenciales de servicio si están
    disponibles (GOOGLE_APPLICATION_CREDENTIALS) o las credenciales por defecto
    del entorno (Cloud Run)."""
    global _firebase_listo
    if _firebase_listo:
        return True
    if not FIREBASE_DB_URL:
        logger.warning("FIREBASE_DB_URL no definida: RTDB deshabilitada.")
        return False
    try:
        import firebase_admin
        from firebase_admin import credentials

        if not firebase_admin._apps:
            cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
            opciones = {"databaseURL": FIREBASE_DB_URL}
            if cred_path and os.path.exists(cred_path):
                firebase_admin.initialize_app(
                    credentials.Certificate(cred_path), opciones
                )
            else:
                firebase_admin.initialize_app(options=opciones)
        _firebase_listo = True
        logger.info("Firebase Realtime Database habilitada.")
        return True
    except Exception as exc:  # pragma: no cover
        logger.error("No se pudo inicializar Firebase: %s", exc)
        return False


def caso_existente(evento_id: str) -> dict | None:
    """Devuelve el caso previo si el evento ya fue procesado (idempotencia)."""
    if not _firebase_listo:
        return _casos_memoria.get(evento_id)
    try:
        from firebase_admin import db

        return db.reference(f"casos/{evento_id}").get()
    except Exception as exc:  # pragma: no cover
        logger.error("Error consultando idempotencia: %s", exc)
        return _casos_memoria.get(evento_id)


def escribir_caso(evento_id: str, caso: dict) -> str:
    """Persiste el caso en RTDB bajo /casos/<evento_id>."""
    _casos_memoria[evento_id] = caso  # respaldo de idempotencia
    if not _firebase_listo:
        return "deshabilitado"
    try:
        from firebase_admin import db

        db.reference(f"casos/{evento_id}").set(caso)
        return "ok"
    except Exception as exc:
        logger.error("Error escribiendo caso en RTDB: %s", exc)
        return f"error: {exc}"


def _enviar_telegram(chat_id: str, texto: str) -> str:
    if not (TELEGRAM_BOT_TOKEN and chat_id):
        return "deshabilitado"
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = httpx.post(
            url,
            json={"chat_id": chat_id, "text": texto, "parse_mode": "HTML"},
            timeout=10,
        )
        if resp.status_code == 200:
            return "enviado"
        logger.error("Telegram respondió %s: %s", resp.status_code, resp.text)
        return f"error: {resp.status_code}"
    except Exception as exc:
        logger.error("Error enviando a Telegram: %s", exc)
        return f"error: {exc}"


def _formato_telegram(caso: dict, destino: str) -> str:
    """Construye el mensaje para Telegram según el destinatario."""
    paciente = caso["paciente"]
    ev = caso["evaluacion_poliza"]
    an = caso["analisis_agente"]
    emojis = {"CRITICO": "🔴", "URGENTE": "🟠", "MODERADO": "🟡", "LEVE": "🟢"}
    cabecera = emojis.get(an["nivel_triaje"], "⚪")

    if destino == "admisiones":
        titulo = "🏥 <b>ALERTA DE INGRESO — ADMISIONES HOSPITAL</b>"
        cuerpo = an["mensaje_admisiones_hospital"]
    else:
        titulo = "🛡️ <b>ALERTA DE INGRESO — GESTOR DE CASOS</b>"
        cuerpo = an["mensaje_gestor_seguro"]

    return (
        f"{titulo}\n"
        f"{cabecera} Triaje: <b>{an['nivel_triaje']}</b>\n\n"
        f"<b>Paciente:</b> {paciente['nombre_paciente']} "
        f"(C.I. {paciente['cedula']})\n"
        f"<b>Hospital:</b> {paciente['hospital']}\n"
        f"<b>Motivo:</b> {paciente['motivo_ingreso']}\n"
        f"<b>Póliza:</b> {ev['validez']}\n"
        f"<b>Cobertura presunta:</b> {an['estado_cobertura_presunta']}\n"
        f"<b>Riesgo de siniestro:</b> {an['riesgo_siniestro']}\n\n"
        f"{cuerpo}\n\n"
        f"<i>Evento {caso['evento_id']}</i>"
    )


def notificar_telegram(caso: dict) -> dict:
    """Envía la alerta a los dos canales y devuelve el estado de cada envío."""
    mensajes = {
        "telegram_admisiones": (
            TELEGRAM_CHAT_ADMISIONES,
            _formato_telegram(caso, "admisiones"),
        ),
        "telegram_gestor": (
            TELEGRAM_CHAT_GESTOR,
            _formato_telegram(caso, "gestor"),
        ),
    }
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            canal: executor.submit(_enviar_telegram, chat_id, texto)
            for canal, (chat_id, texto) in mensajes.items()
        }
        return {canal: future.result() for canal, future in futures.items()}


def obtener_casos_memoria() -> dict[str, dict]:
    """Devuelve todos los casos guardados en la memoria local (idempotencia y fallback)."""
    return _casos_memoria
