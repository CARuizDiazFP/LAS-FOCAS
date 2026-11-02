# Nombre de archivo: tracking_operaciones.py
# Ubicación de archivo: core/services/tracking_operaciones.py
# Descripción: Operaciones de tracking compartidas por el panel y la API (upload, análisis, descarga del original, rutas de un servicio y limpieza de empalmes)

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

from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from core.parsers.tracking_parser import parse_tracking
from core.services.infra_service import (
    AnalysisResult,
    AnalysisStatus,
    ResolveAction,
    ResolveResult,
    analyze_tracking_file,
    resolve_tracking_file,
)
from db.models.infra import RutaServicio, RutaTipo, Servicio

logger = logging.getLogger(__name__)

# Tope del archivo de tracking subido (panel y API).
MAX_TRACKING_MB = 5


class TrackingSinServicioId(ValueError):
    """El nombre del archivo no permite extraer el ID del servicio."""


class TrackingSinUbicaciones(ValueError):
    """El archivo no tiene empalmes/ubicaciones."""


class TrackingRequiereResolucion(ValueError):
    """El tracking choca con rutas existentes del servicio (conflicto, posible upgrade o pelo nuevo).

    El upload directo no decide: esos casos van por analyze/resolve."""

    def __init__(self, servicio_id: str, estado: str) -> None:
        super().__init__(f"{servicio_id}: {estado}")
        self.servicio_id = servicio_id
        self.estado = estado


class TrackingOriginalNoDisponible(LookupError):
    """La ruta existe pero no tiene guardado el archivo original (`raw_file_content`)."""


class AccionResolveInvalida(ValueError):
    """La acción pedida no existe (ni es `SKIP`)."""


class RutaTipoInvalido(ValueError):
    """El tipo de ruta pedido no es PRINCIPAL/BACKUP/ALTERNATIVA."""


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

def procesar_tracking_legacy(session: Session, raw_text: str, filename: str) -> ResultadoUploadTracking:
    """Upload directo de un tracking: lo resuelve con el flujo de analyze/resolve del panel.

    Desde P22 (2026-10-29) el tracking termina siempre en una ruta (`ruta_empalme_association`); antes
    asociaba los empalmes sólo por la tabla legada `servicio_empalme_association`, sin ruta.
    - `NEW` (servicio inexistente o sin rutas): `CREATE_NEW`, que crea la ruta principal.
    - `IDENTICAL`: no escribe nada (conteos en 0).
    - Conflicto, posible upgrade o pelo nuevo: `TrackingRequiereResolucion`, sin escribir; esos casos
      piden una decisión humana y van por `POST /api/infra/trackings/analyze` + `resolve`.

    Cromo Red es la fuente de verdad del inventario: nunca se crea una `Camara` nueva (una ubicación sin
    match queda como `IngresoSinMatch` y su empalme sin `camara_id`).

    Raises:
        TrackingSinServicioId: el nombre del archivo no trae ID de servicio (no escribe nada).
        TrackingSinUbicaciones: el archivo no trae empalmes/ubicaciones (no escribe nada).
        TrackingRequiereResolucion: el tracking choca con rutas existentes (no escribe nada).
        RuntimeError: el análisis o la creación fallaron (la creación ya hizo rollback).
    """
    result = parse_tracking(raw_text, filename)
    if not result.servicio_id:
        raise TrackingSinServicioId(filename)
    if not result.get_topologia():
        raise TrackingSinUbicaciones(filename)

    analisis = analyze_tracking_file(session, raw_text, filename)
    if analisis.status == AnalysisStatus.IDENTICAL:
        logger.info("action=upload_tracking servicio_id=%s status=IDENTICAL", result.servicio_id)
        return ResultadoUploadTracking(result.servicio_id, 0, 0, 0)
    if analisis.status == AnalysisStatus.ERROR:
        raise RuntimeError(analisis.error or analisis.message)
    if analisis.status != AnalysisStatus.NEW:
        raise TrackingRequiereResolucion(result.servicio_id, analisis.status.value)

    resuelto = resolve_tracking_file(session, ResolveAction.CREATE_NEW, raw_text, filename)
    if not resuelto.success:
        raise RuntimeError(resuelto.error or resuelto.message)
    logger.info(
        "action=upload_tracking_complete servicio_id=%s ruta_id=%s camaras_existentes=%d "
        "ubicaciones_sin_match=%d empalmes=%d",
        result.servicio_id,
        resuelto.ruta_id,
        resuelto.camaras_existentes,
        resuelto.ubicaciones_sin_match,
        resuelto.empalmes_creados,
    )
    return ResultadoUploadTracking(
        servicio_id=result.servicio_id,
        camaras_existentes=resuelto.camaras_existentes,
        ubicaciones_sin_match=resuelto.ubicaciones_sin_match,
        empalmes_registrados=resuelto.empalmes_creados,
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


# --- Resolución -------------------------------------------------------------------------------------

ACCIONES_RESOLVE = ", ".join([a.value for a in ResolveAction] + ["SKIP"])
RUTA_TIPOS = ", ".join(t.value for t in RutaTipo)


def parsear_accion_resolve(valor: str) -> ResolveAction | None:
    """Acción de `resolve` (sin distinguir mayúsculas); `None` significa `SKIP` (no hace nada).

    Raises:
        AccionResolveInvalida: la acción no existe.
    """
    texto = (valor or "").upper()
    if texto == "SKIP":
        return None
    try:
        return ResolveAction(texto)
    except ValueError:
        raise AccionResolveInvalida(valor) from None


def parsear_ruta_tipo(valor: str | None) -> RutaTipo:
    """Tipo de ruta pedido; vacío cae a `ALTERNATIVA` (D11).

    Raises:
        RutaTipoInvalido: el valor no es un `RutaTipo`.
    """
    if not valor:
        return RutaTipo.ALTERNATIVA
    try:
        return RutaTipo(valor.upper())
    except ValueError:
        raise RutaTipoInvalido(valor) from None


def serializar_resolucion(result: ResolveResult) -> dict[str, Any]:
    """Dict JSON completo de un `ResolveResult` (forma del panel; la API toma las claves que usa)."""
    return {
        "success": result.success,
        "action": result.action.value,
        "servicio_id": result.servicio_id,
        "servicio_db_id": result.servicio_db_id,
        "ruta_id": result.ruta_id,
        "ruta_nombre": result.ruta_nombre,
        "camaras_nuevas": result.camaras_nuevas,
        "camaras_existentes": result.camaras_existentes,
        "empalmes_creados": result.empalmes_creados,
        "empalmes_asociados": result.empalmes_asociados,
        "ubicaciones_sin_match": result.ubicaciones_sin_match,
        "message": result.message,
        "error": result.error,
    }


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


# --- Rutas de un servicio y limpieza de empalmes ----------------------------------------------------

def buscar_servicio_por_identificador(session: Session, identificador: str, *opciones: Any) -> Servicio | None:
    """Resuelve un `Servicio` por `servicio_id`, `numero_primer_servicio` o `numero_linea`.

    Ordena por `Servicio.id` para que, con identificadores ambiguos, gane siempre el de menor id.
    `opciones` son opciones de carga (`selectinload`) opcionales para la consulta.
    """
    consulta = session.query(Servicio).filter(
        or_(
            Servicio.servicio_id == identificador,
            Servicio.numero_primer_servicio == identificador,
            Servicio.numero_linea == identificador,
        )
    )
    if opciones:
        consulta = consulta.options(*opciones)
    return consulta.order_by(Servicio.id).first()


def obtener_rutas_de_servicio(session: Session, identificador: str) -> dict[str, Any] | None:
    """Rutas de un servicio (forma común al panel y a la API), o `None` si no existe.

    Serializa dentro de la sesión: el llamador puede cerrarla al volver.
    """
    servicio = buscar_servicio_por_identificador(
        session, identificador, selectinload(Servicio.rutas).selectinload(RutaServicio.empalmes)
    )
    if servicio is None:
        return None
    rutas = [
        {
            "id": ruta.id,
            "nombre": ruta.nombre,
            "tipo": ruta.tipo.value if ruta.tipo else "PRINCIPAL",
            "hash_contenido": ruta.hash_contenido,
            "empalmes_count": len(ruta.empalmes),
            "activa": bool(ruta.activa),
            "created_at": ruta.created_at.isoformat() if ruta.created_at else None,
            "nombre_archivo_origen": ruta.nombre_archivo_origen,
        }
        for ruta in servicio.rutas
    ]
    return {
        "status": "ok",
        "servicio_id": servicio.servicio_id,
        "servicio_db_id": servicio.id,
        "cliente": servicio.cliente,
        "rutas": rutas,
        "total_rutas": len(rutas),
    }


def limpiar_empalmes_de_servicio(session: Session, servicio_id: str) -> dict[str, Any] | None:
    """Borra las rutas de un servicio (con su cascada ORM a `ruta_empalme_association`); hace commit.

    Los `Empalme` quedan vivos. Devuelve `None` si el servicio no existe (sin escribir).
    """
    servicio = (
        session.query(Servicio)
        .filter(Servicio.servicio_id == servicio_id)
        .options(selectinload(Servicio.rutas).selectinload(RutaServicio.empalmes))
        .first()
    )
    if servicio is None:
        return None

    rutas = len(servicio.rutas)
    empalmes_rutas = sum(len(r.empalmes) for r in servicio.rutas)

    for ruta in list(servicio.rutas):
        session.delete(ruta)
    session.commit()

    logger.info(
        "action=delete_servicio_empalmes servicio_id=%s rutas=%d empalmes_rutas=%d",
        servicio_id, rutas, empalmes_rutas,
    )
    return {
        "status": "ok",
        "servicio_id": servicio_id,
        "message": f"Eliminadas {empalmes_rutas} asociaciones y {rutas} rutas",
        "rutas_eliminadas": rutas,
        "empalmes_rutas_eliminados": empalmes_rutas,
    }
