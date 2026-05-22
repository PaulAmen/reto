"""Catálogo de pólizas y evaluación determinística.

Las verificaciones "duras" (vigencia, mora, periodo de carencia) se resuelven
aquí con lógica determinística. El agente de IA recibe estos hechos ya
calculados y se concentra en el juicio clínico-administrativo.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime

from dateutil.relativedelta import relativedelta

from models import EvaluacionPoliza, Poliza, Preexistencia

logger = logging.getLogger("satie.database")

_POLIZAS: dict[str, Poliza] = {}


def cargar_polizas(ruta: str = "seed_polizas.json") -> dict[str, Poliza]:
    """Carga el catálogo y calcula fechas de vigencia relativas a hoy.

    El seed almacena 'antiguedad_meses' y 'vigencia_restante_meses' (en lugar
    de fechas fijas) para que el demo no caduque con el paso del tiempo.
    """
    global _POLIZAS
    with open(ruta, encoding="utf-8") as fh:
        registros = json.load(fh)

    ahora = datetime.now()
    catalogo: dict[str, Poliza] = {}
    for reg in registros:
        inicio = ahora - relativedelta(months=reg["antiguedad_meses"])
        fin = ahora + relativedelta(months=reg["vigencia_restante_meses"])
        poliza = Poliza(
            cedula=reg["cedula"],
            nombre=reg["nombre"],
            numero_poliza=reg["numero_poliza"],
            aseguradora=reg["aseguradora"],
            plan=reg["plan"],
            estado_pago=reg["estado_pago"],
            meses_mora=reg["meses_mora"],
            fecha_inicio=inicio.date().isoformat(),
            fecha_fin=fin.date().isoformat(),
            antiguedad_meses=reg["antiguedad_meses"],
            carencia_general_meses=reg["carencia_general_meses"],
            carencia_preexistencias_meses=reg["carencia_preexistencias_meses"],
            suma_asegurada=reg["suma_asegurada"],
            deducible=reg["deducible"],
            preexistencias=[Preexistencia(**p) for p in reg["preexistencias"]],
            hospitales_red=reg["hospitales_red"],
            descripcion_caso=reg.get("_descripcion_caso", ""),
        )
        catalogo[reg["cedula"]] = poliza

    _POLIZAS = catalogo
    logger.info("Catálogo cargado: %d pólizas", len(_POLIZAS))
    return _POLIZAS


def buscar_poliza(cedula: str) -> Poliza | None:
    return _POLIZAS.get(cedula.strip())


def listar_asegurados() -> list[Poliza]:
    return list(_POLIZAS.values())


def evaluar_poliza(
    poliza: Poliza | None, fecha_ingreso: datetime | date
) -> EvaluacionPoliza:
    """Determina la validez de la póliza y los periodos de carencia."""
    if poliza is None:
        return EvaluacionPoliza(
            validez="NO_ASEGURADO",
            antiguedad_meses=0,
            dentro_carencia_general=False,
            dentro_carencia_preexistencias=False,
            mensaje_estado=(
                "No se encontró ninguna póliza asociada a la cédula ingresada."
            ),
        )

    fecha_ref = (
        fecha_ingreso.date() if isinstance(fecha_ingreso, datetime) else fecha_ingreso
    )
    fin = date.fromisoformat(poliza.fecha_fin)

    if fin < fecha_ref:
        validez = "VENCIDA"
        mensaje = f"La póliza venció el {poliza.fecha_fin}."
    elif poliza.estado_pago == "EN_MORA":
        validez = "EN_MORA"
        mensaje = (
            f"La póliza presenta mora de {poliza.meses_mora} mes(es); "
            "la cobertura puede estar suspendida."
        )
    else:
        validez = "VIGENTE"
        mensaje = "Póliza vigente y al día en sus pagos."

    return EvaluacionPoliza(
        validez=validez,
        antiguedad_meses=poliza.antiguedad_meses,
        dentro_carencia_general=(
            poliza.antiguedad_meses < poliza.carencia_general_meses
        ),
        dentro_carencia_preexistencias=(
            poliza.antiguedad_meses < poliza.carencia_preexistencias_meses
        ),
        mensaje_estado=mensaje,
    )
