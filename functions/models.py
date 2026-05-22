"""Modelos de datos del sistema SATIE.

Definen la estructura del payload del webhook, las pólizas, la evaluación
determinística y la respuesta estructurada del agente de IA.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field

# --- Tipos enumerados -------------------------------------------------------

ValidezPoliza = Literal["VIGENTE", "VENCIDA", "EN_MORA", "NO_ASEGURADO"]
NivelTriaje = Literal["CRITICO", "URGENTE", "MODERADO", "LEVE"]
EstadoCobertura = Literal[
    "CUBIERTO", "COBERTURA_PARCIAL", "REQUIERE_REVISION", "NO_CUBIERTO"
]
RiesgoSiniestro = Literal["ALTO", "MEDIO", "BAJO"]


# --- Catálogo de pólizas ----------------------------------------------------

class Preexistencia(BaseModel):
    condicion: str
    fecha_declaracion: str = "al contratar"


class Poliza(BaseModel):
    cedula: str
    nombre: str
    numero_poliza: str
    aseguradora: str
    plan: str
    estado_pago: Literal["AL_DIA", "EN_MORA"]
    meses_mora: int = 0
    fecha_inicio: str  # ISO date
    fecha_fin: str      # ISO date
    antiguedad_meses: int
    carencia_general_meses: int
    carencia_preexistencias_meses: int
    suma_asegurada: float
    deducible: float
    preexistencias: list[Preexistencia] = Field(default_factory=list)
    hospitales_red: list[str] = Field(default_factory=list)
    descripcion_caso: str = ""


# --- Entrada del webhook ----------------------------------------------------

class SignosVitales(BaseModel):
    presion_arterial: Optional[str] = None
    frecuencia_cardiaca: Optional[int] = None
    temperatura: Optional[float] = None
    saturacion_oxigeno: Optional[int] = None


class EmergenciaWebhookPayload(BaseModel):
    """Evento emitido por el sistema de admisión del hospital."""

    evento_id: str = Field(default_factory=lambda: f"evt-{uuid.uuid4().hex[:12]}")
    cedula: str
    nombre_paciente: str
    motivo_ingreso: str
    hospital: str
    triaje_hospital: Optional[str] = None
    signos_vitales: Optional[SignosVitales] = None
    fecha_ingreso: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# --- Evaluación determinística de la póliza --------------------------------

class EvaluacionPoliza(BaseModel):
    validez: ValidezPoliza
    antiguedad_meses: int
    dentro_carencia_general: bool
    dentro_carencia_preexistencias: bool
    mensaje_estado: str


# --- Respuesta estructurada del agente de IA -------------------------------

class AnalisisAgente(BaseModel):
    """Esquema que el modelo Gemini debe devolver en formato JSON."""

    nivel_triaje: NivelTriaje
    preexistencia_relacionada: bool
    detalle_preexistencia: str
    aplica_periodo_carencia: bool
    estado_cobertura_presunta: EstadoCobertura
    riesgo_siniestro: RiesgoSiniestro
    resumen_clinico_administrativo: str
    mensaje_admisiones_hospital: str
    mensaje_gestor_seguro: str
    acciones_recomendadas: list[str]


# --- Caso consolidado y respuesta del webhook ------------------------------

class CasoEmergencia(BaseModel):
    """Registro completo que se escribe en Firebase y alimenta los paneles."""

    evento_id: str
    recibido_en: str
    estado: str = "PROCESADO"
    paciente: dict
    poliza: Optional[dict] = None
    evaluacion_poliza: dict
    analisis_agente: dict
    fuente_analisis: str  # "gemini" o "fallback"
    notificaciones: dict


class RespuestaWebhook(BaseModel):
    evento_id: str
    estado: str
    validez_poliza: ValidezPoliza
    estado_cobertura_presunta: EstadoCobertura
    nivel_triaje: NivelTriaje
    riesgo_siniestro: RiesgoSiniestro
    notificaciones: dict
