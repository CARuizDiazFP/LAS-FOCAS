# Nombre de archivo: tracking_operaciones.py
# Ubicación de archivo: core/services/tracking_operaciones.py
# Descripción: Operaciones de tracking compartidas por el panel y la API (upload, análisis y descarga del original)

"""Lógica de tracking que antes estaba duplicada en `web/app/routers/servicios.py` y
`api/app/routes/infra.py` (P12, Task 10).

Todas las funciones son síncronas y reciben la sesión de SQLAlchemy ya abierta: el panel las llama
directo desde sus endpoints `def` (threadpool) y la API vía `asyncio.to_thread` abriendo
`SessionLocal()` dentro del thread. El formato de error (`{"error"}` vs `{"detail"}`) y los textos
de cada app quedan en los routers; acá sólo se levantan excepciones tipadas.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from core.parsers.tracking_parser import parse_tracking
from core.services.infra_service import (
    AnalysisResult,
    _get_or_create_empalme,
    _resolve_camara_o_registrar_sin_match,
)
from db.models.infra import Camara, Empalme, RutaServicio, Servicio

logger = logging.getLogger(__name__)

# Tope del archivo de tracking subido (panel y API).
MAX_TRACKING_MB = 5


class TrackingSinServicioId(ValueError):
    """El nombre del archivo no permite extraer el ID del servicio."""


class TrackingSinUbicaciones(ValueError):
    """El archivo no tiene empalmes/ubicaciones."""


class TrackingOriginalNoDisponible(LookupError):
    """La ruta existe pero no tiene guardado el archivo original (`raw_file_content`)."""


@dataclass
class ResultadoUploadTracking:
    """Conteos de un upload de tracking procesado."""

    servicio_id: str
    camaras_existentes: int
    ubicaciones_sin_match: int
    empalmes_registrados: int


@dataclass
class TrackingOriginal:
    """Archivo de tracking original de una ruta, listo para descargar."""

    filename: str
    contenido: str


def decodificar_tracking(contenido: bytes) -> str:
    """Decodifica el upload como utf-8 y, si no es válido, como latin-1."""
    try:
        return contenido.decode("utf-8")
    except UnicodeDecodeError:
        return contenido.decode("latin-1")


# --- Upload -----------------------------------------------------------------------------------------

def _obtener_o_crear_servicio(session: Session, servicio_id: str, nombre_archivo: str) -> Servicio:
    """Servicio existente (sólo pisa `nombre_archivo_origen` si cambió) o uno nuevo."""
    servicio = session.query(Servicio).filter(Servicio.servicio_id == servicio_id).first()
    if servicio:
        if nombre_archivo and servicio.nombre_archivo_origen != nombre_archivo:
            servicio.nombre_archivo_origen = nombre_archivo
        return servicio

    servicio = Servicio(servicio_id=servicio_id, nombre_archivo_origen=nombre_archivo)
    session.add(servicio)
    session.flush()
    logger.info("action=crear_servicio servicio_id=%s nombre_archivo=%s", servicio_id, nombre_archivo)
    return servicio


def _registrar_empalme(
    session: Session, servicio: Servicio, empalme_id: str, camara: Camara | None
) -> tuple[Empalme, bool]:
    """Registra el empalme y lo asocia al servicio; `camara` es `None` si la ubicación no matcheó.

    `_get_or_create_empalme` nunca pisa con `None` un `camara_id` previo válido de una corrida
    anterior cuando esta corrida no matchea.
    """
    tracking_id_completo = f"{servicio.servicio_id}_{empalme_id}"
    empalme, es_nuevo = _get_or_create_empalme(session, tracking_id_completo, camara)
    if servicio not in empalme.servicios:
        empalme.servicios.append(servicio)
    if es_nuevo:
        logger.debug(
            "action=registrar_empalme tracking_id=%s camara_id=%s servicio_id=%s",
            tracking_id_completo,
            empalme.camara_id,
            servicio.servicio_id,
        )
    return empalme, es_nuevo


def procesar_tracking_legacy(session: Session, raw_text: str, filename: str) -> ResultadoUploadTracking:
    """Parsea el tracking, crea/actualiza el servicio y registra sus empalmes (commit al final).

    Cromo Red es la fuente de verdad del inventario: nunca se crea una `Camara` nueva. Una ubicación
    sin match queda como `IngresoSinMatch` (dentro de `_resolve_camara_o_registrar_sin_match`) y su
    empalme sin `camara_id`: el procesamiento nunca se bloquea por eso.

    Raises:
        TrackingSinServicioId: el nombre del archivo no trae ID de servicio (no escribe nada).
        TrackingSinUbicaciones: el archivo no trae empalmes/ubicaciones (no escribe nada).
    """
    result = parse_tracking(raw_text, filename)
    if not result.servicio_id:
        raise TrackingSinServicioId(filename)
    topologia = result.get_topologia()
    if not topologia:
        raise TrackingSinUbicaciones(filename)

    logger.info(
        "action=upload_tracking filename=%s servicio_id=%s empalmes=%d",
        filename,
        result.servicio_id,
        len(topologia),
    )
    camaras_existentes = ubicaciones_sin_match = empalmes_registrados = 0
    try:
        servicio = _obtener_o_crear_servicio(session, result.servicio_id, filename)
        servicio.raw_tracking_data = result.to_dict()

        for empalme_id, ubicacion in topologia:
            camara = _resolve_camara_o_registrar_sin_match(
                session, ubicacion, filename=filename, servicio_id=result.servicio_id
            )
            if camara is not None:
                camaras_existentes += 1
            else:
                ubicaciones_sin_match += 1
            _, empalme_nuevo = _registrar_empalme(session, servicio, empalme_id, camara)
            if empalme_nuevo:
                empalmes_registrados += 1

        session.commit()
    except Exception:
        session.rollback()
        logger.exception("action=upload_tracking_error servicio_id=%s", result.servicio_id)
        raise

    logger.info(
        "action=upload_tracking_complete servicio_id=%s camaras_existentes=%d "
        "ubicaciones_sin_match=%d empalmes=%d",
        result.servicio_id,
        camaras_existentes,
        ubicaciones_sin_match,
        empalmes_registrados,
    )
    return ResultadoUploadTracking(
        servicio_id=result.servicio_id,
        camaras_existentes=camaras_existentes,
        ubicaciones_sin_match=ubicaciones_sin_match,
        empalmes_registrados=empalmes_registrados,
    )


# --- Análisis ---------------------------------------------------------------------------------------

# Acción que el panel sugiere para cada estado del análisis.
_ACCION_SUGERIDA = {
    "NEW": "CREATE_NEW",
    "IDENTICAL": "SKIP",
    "CONFLICT": "REPLACE",  # por defecto; el usuario puede elegir otra
    "POTENTIAL_UPGRADE": "CONFIRM_UPGRADE",
}


def serializar_analisis(result: AnalysisResult) -> dict[str, Any]:
    """Dict JSON del análisis: unión de las claves del panel y de la API (`upgrade_info` completo)."""
    datos = result.to_dict()
    datos.update(
        empalmes_nuevos=result.parsed_empalmes_count,
        suggested_action=_ACCION_SUGERIDA.get(result.status.value),
        hash_match=result.ruta_identica_id is not None,
    )
    return datos


# --- Descarga del original --------------------------------------------------------------------------

def obtener_tracking_original(session: Session, ruta_id: int) -> TrackingOriginal | None:
    """Archivo original de la ruta, o `None` si la ruta no existe.

    Raises:
        TrackingOriginalNoDisponible: la ruta existe pero no guardó `raw_file_content`.
    """
    ruta = session.query(RutaServicio).filter(RutaServicio.id == ruta_id).first()
    if ruta is None:
        return None
    if not ruta.raw_file_content:
        raise TrackingOriginalNoDisponible(ruta_id)
    return TrackingOriginal(
        filename=ruta.nombre_archivo_origen or f"tracking_ruta_{ruta_id}.txt",
        contenido=ruta.raw_file_content,
    )
