# Nombre de archivo: infra.py
# Ubicación de archivo: api/api_app/routes/infra.py
# Descripción: Endpoints para sincronizar cámaras y procesar trackings de fibra óptica

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_

from core.parsers.tracking_parser import parse_tracking
from core.services.infra_sync import sync_camaras_from_sheet
from db.models.infra import (
    Cable,
    Camara,
    CamaraEstado,
    CamaraOrigenDatos,
    Empalme,
    Servicio,
)
from db.session import SessionLocal

router = APIRouter(tags=["infra"])
logger = logging.getLogger(__name__)


class InfraSyncRequest(BaseModel):
    sheet_id: Optional[str] = None
    worksheet_name: Optional[str] = None


class InfraSyncResponse(BaseModel):
    status: str
    processed: int
    updated: int
    created: int


class TrackingUploadResponse(BaseModel):
    """Respuesta del endpoint de carga de tracking."""

    status: str
    servicios_procesados: int
    servicio_id: Optional[str]
    camaras_nuevas: int
    camaras_existentes: int
    empalmes_registrados: int
    mensaje: Optional[str] = None


# ──────────────────────────────────────────────────────────────────────────────
# Búsqueda avanzada - Modelos y tipos
# ──────────────────────────────────────────────────────────────────────────────


class FilterField(str, Enum):
    """Campos disponibles para filtrar en búsqueda avanzada."""

    SERVICE_ID = "service_id"  # Busca cámaras asociadas a un servicio
    ADDRESS = "address"  # Busca por nombre/dirección de cámara
    STATUS = "status"  # Busca por estado (LIBRE, OCUPADA, BANEADA, DETECTADA)
    CABLE = "cable"  # Busca cámaras asociadas a un cable
    ORIGEN = "origen"  # Busca por origen de datos (MANUAL, TRACKING, SHEET)


class FilterOperator(str, Enum):
    """Operadores de comparación para filtros."""

    EQ = "eq"  # Igual exacto
    CONTAINS = "contains"  # Contiene (case-insensitive)
    STARTS_WITH = "starts_with"  # Empieza con
    ENDS_WITH = "ends_with"  # Termina con
    IN = "in"  # Valor en lista


class SearchFilter(BaseModel):
    """Filtro individual para búsqueda avanzada."""

    field: FilterField
    operator: FilterOperator = FilterOperator.CONTAINS
    value: str | list[str]

    model_config = {"json_schema_extra": {"examples": [{"field": "address", "operator": "contains", "value": "rivadavia"}]}}


class SearchRequest(BaseModel):
    """Request para búsqueda avanzada de cámaras con filtros AND."""

    filters: list[SearchFilter] = Field(default_factory=list, min_length=0, max_length=10)
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "filters": [
                        {"field": "service_id", "operator": "eq", "value": "SVC-12345"},
                        {"field": "address", "operator": "contains", "value": "rivadavia"},
                    ],
                    "limit": 50,
                    "offset": 0,
                }
            ]
        }
    }


class SearchResponse(BaseModel):
    """Respuesta de búsqueda avanzada."""

    status: str = "ok"
    total: int
    limit: int
    offset: int
    filters_applied: int
    camaras: list[CamaraResponse]


class SmartSearchRequest(BaseModel):
    """Request para Smart Search con términos libres.

    Cada término se busca en múltiples campos (OR interno),
    y los términos se combinan con AND.
    """

    terms: list[str] = Field(default_factory=list, min_length=0, max_length=20)
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"terms": ["111995", "Corrientes"], "limit": 50}
            ]
        }
    }


class CamaraResponse(BaseModel):
    """Respuesta con datos de una cámara."""

    id: int
    nombre: str
    fontine_id: Optional[str] = None
    direccion: Optional[str] = None
    estado: str
    origen_datos: str
    latitud: Optional[float] = None
    longitud: Optional[float] = None
    servicios: List[str] = []


class CamarasListResponse(BaseModel):
    """Respuesta con lista de cámaras."""

    status: str
    total: int
    camaras: List[CamaraResponse]


@router.get("/api/infra/camaras", response_model=CamarasListResponse)
async def search_camaras(
    q: Optional[str] = None,
    estado: Optional[str] = None,
    limit: int = 100,
) -> CamarasListResponse:
    """Busca cámaras por query (nombre, servicio, dirección) y/o estado.

    Args:
        q: Texto de búsqueda (busca en nombre, dirección, fontine_id, servicios).
        estado: Filtrar por estado (LIBRE, OCUPADA, BANEADA, DETECTADA).
        limit: Máximo de resultados (default 100, max 500).

    Returns:
        Lista de cámaras que coinciden con los criterios.
    """

    limit = min(limit, 500)

    try:
        with SessionLocal() as session:
            query = session.query(Camara)

            # Filtro por estado
            if estado:
                estado_upper = estado.upper()
                if estado_upper in [e.value for e in CamaraEstado]:
                    query = query.filter(Camara.estado == CamaraEstado(estado_upper))

            # Filtro por texto (búsqueda amplia)
            if q and q.strip():
                search_term = f"%{q.strip()}%"
                # Buscar en nombre, dirección, fontine_id
                query = query.filter(
                    (Camara.nombre.ilike(search_term)) |
                    (Camara.direccion.ilike(search_term)) |
                    (Camara.fontine_id.ilike(search_term))
                )

            # Ejecutar query
            camaras_db = query.order_by(Camara.nombre).limit(limit).all()

            # Construir respuesta con servicios asociados
            camaras_response = []
            for cam in camaras_db:
                # Obtener IDs de servicios que pasan por esta cámara
                servicios_ids = []
                for empalme in cam.empalmes:
                    for servicio in empalme.servicios:
                        if servicio.servicio_id and servicio.servicio_id not in servicios_ids:
                            servicios_ids.append(servicio.servicio_id)

                camaras_response.append(CamaraResponse(
                    id=cam.id,
                    nombre=cam.nombre or "",
                    fontine_id=cam.fontine_id,
                    direccion=cam.direccion,
                    estado=cam.estado.value if cam.estado else "LIBRE",
                    origen_datos=cam.origen_datos.value if cam.origen_datos else "MANUAL",
                    latitud=cam.latitud,
                    longitud=cam.longitud,
                    servicios=servicios_ids,
                ))

            # Si se buscó por ID de servicio y no se encontró en cámaras, buscar servicios
            if q and q.strip() and not camaras_response:
                # Intentar buscar por servicio_id
                servicio = session.query(Servicio).filter(
                    Servicio.servicio_id.ilike(f"%{q.strip()}%")
                ).first()

                if servicio:
                    # Obtener cámaras de ese servicio a través de empalmes
                    for empalme in servicio.empalmes:
                        if empalme.camara and empalme.camara.id not in [c.id for c in camaras_response]:
                            cam = empalme.camara
                            servicios_ids = [servicio.servicio_id]
                            # Añadir otros servicios de la misma cámara
                            for emp in cam.empalmes:
                                for svc in emp.servicios:
                                    if svc.servicio_id and svc.servicio_id not in servicios_ids:
                                        servicios_ids.append(svc.servicio_id)

                            camaras_response.append(CamaraResponse(
                                id=cam.id,
                                nombre=cam.nombre or "",
                                fontine_id=cam.fontine_id,
                                direccion=cam.direccion,
                                estado=cam.estado.value if cam.estado else "LIBRE",
                                origen_datos=cam.origen_datos.value if cam.origen_datos else "MANUAL",
                                latitud=cam.latitud,
                                longitud=cam.longitud,
                                servicios=servicios_ids,
                            ))

            logger.info(
                "action=search_camaras query=%s estado=%s results=%d",
                q,
                estado,
                len(camaras_response),
            )

            return CamarasListResponse(
                status="ok",
                total=len(camaras_response),
                camaras=camaras_response,
            )

    except Exception as exc:
        logger.exception("action=search_camaras_error error=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error buscando cámaras: {exc!s}",
        ) from exc


# ──────────────────────────────────────────────────────────────────────────────
# Búsqueda avanzada - Endpoint POST /api/infra/search
# ──────────────────────────────────────────────────────────────────────────────


def _apply_text_filter(value: str, operator: FilterOperator, db_value: Optional[str]) -> bool:
    """Aplica un filtro de texto a un valor de la base de datos.

    Args:
        value: Valor del filtro (lo que busca el usuario).
        operator: Tipo de operación (eq, contains, starts_with, ends_with, in).
        db_value: Valor almacenado en la base de datos.

    Returns:
        True si el valor coincide con el filtro.
    """
    if db_value is None:
        return False

    db_lower = db_value.lower()
    val_lower = value.lower() if isinstance(value, str) else value

    if operator == FilterOperator.EQ:
        return db_lower == val_lower
    elif operator == FilterOperator.CONTAINS:
        return val_lower in db_lower
    elif operator == FilterOperator.STARTS_WITH:
        return db_lower.startswith(val_lower)
    elif operator == FilterOperator.ENDS_WITH:
        return db_lower.endswith(val_lower)
    elif operator == FilterOperator.IN:
        if isinstance(value, list):
            return db_lower in [v.lower() for v in value]
        return db_lower == val_lower
    return False


def _camara_matches_filter(
    camara: Camara,
    flt: SearchFilter,
    servicios_ids: list[str],
    cables_nombres: list[str],
) -> bool:
    """Evalúa si una cámara coincide con un filtro específico.

    Args:
        camara: Objeto Camara de la base de datos.
        flt: Filtro a aplicar.
        servicios_ids: Lista de IDs de servicios asociados a la cámara.
        cables_nombres: Lista de nombres de cables asociados a la cámara.

    Returns:
        True si la cámara coincide con el filtro.
    """
    if flt.field == FilterField.SERVICE_ID:
        # Buscar en servicios asociados
        value = flt.value if isinstance(flt.value, str) else flt.value[0] if flt.value else ""
        for svc_id in servicios_ids:
            if _apply_text_filter(value, flt.operator, svc_id):
                return True
        return False

    elif flt.field == FilterField.ADDRESS:
        # Buscar en nombre y dirección
        value = flt.value if isinstance(flt.value, str) else flt.value[0] if flt.value else ""
        return (
            _apply_text_filter(value, flt.operator, camara.nombre) or
            _apply_text_filter(value, flt.operator, camara.direccion)
        )

    elif flt.field == FilterField.STATUS:
        # Comparar estado
        estado_actual = camara.estado.value if camara.estado else "LIBRE"
        value = flt.value if isinstance(flt.value, str) else flt.value[0] if flt.value else ""
        if flt.operator == FilterOperator.IN and isinstance(flt.value, list):
            return estado_actual.upper() in [v.upper() for v in flt.value]
        return estado_actual.upper() == value.upper()

    elif flt.field == FilterField.CABLE:
        # Buscar en cables asociados
        value = flt.value if isinstance(flt.value, str) else flt.value[0] if flt.value else ""
        for cable_nombre in cables_nombres:
            if _apply_text_filter(value, flt.operator, cable_nombre):
                return True
        return False

    elif flt.field == FilterField.ORIGEN:
        # Comparar origen de datos
        origen_actual = camara.origen_datos.value if camara.origen_datos else "MANUAL"
        value = flt.value if isinstance(flt.value, str) else flt.value[0] if flt.value else ""
        if flt.operator == FilterOperator.IN and isinstance(flt.value, list):
            return origen_actual.upper() in [v.upper() for v in flt.value]
        return origen_actual.upper() == value.upper()

    return False


def _get_camara_servicios(camara: Camara) -> list[str]:
    """Obtiene los IDs de servicios asociados a una cámara."""
    servicios_ids = []
    for empalme in camara.empalmes:
        for servicio in empalme.servicios:
            if servicio.servicio_id and servicio.servicio_id not in servicios_ids:
                servicios_ids.append(servicio.servicio_id)
    return servicios_ids


def _get_camara_cables(camara: Camara) -> list[str]:
    """Obtiene los nombres de cables asociados a una cámara."""
    cables_nombres = []
    for cable in camara.cables:
        if cable.nombre and cable.nombre not in cables_nombres:
            cables_nombres.append(cable.nombre)
    return cables_nombres


def _build_camara_response(camara: Camara, servicios_ids: list[str]) -> CamaraResponse:
    """Construye el objeto de respuesta para una cámara."""
    return CamaraResponse(
        id=camara.id,
        nombre=camara.nombre or "",
        fontine_id=camara.fontine_id,
        direccion=camara.direccion,
        estado=camara.estado.value if camara.estado else "LIBRE",
        origen_datos=camara.origen_datos.value if camara.origen_datos else "MANUAL",
        latitud=camara.latitud,
        longitud=camara.longitud,
        servicios=servicios_ids,
    )


@router.post("/api/infra/search", response_model=SearchResponse)
async def advanced_search_camaras(request: SearchRequest) -> SearchResponse:
    """Búsqueda avanzada de cámaras con filtros combinables (AND).

    Este endpoint permite buscar cámaras aplicando múltiples filtros que se
    combinan con lógica AND (intersección). Por ejemplo, buscar cámaras que:
    - Estén en la calle "Rivadavia" Y
    - Pertenezcan al servicio "SVC-12345" Y
    - Tengan estado "OCUPADA"

    Campos disponibles para filtrar:
    - service_id: ID del servicio (busca cámaras por donde pasa el servicio)
    - address: Nombre o dirección de la cámara
    - status: Estado de la cámara (LIBRE, OCUPADA, BANEADA, DETECTADA)
    - cable: Nombre del cable asociado
    - origen: Origen de datos (MANUAL, TRACKING, SHEET)

    Operadores disponibles:
    - eq: Coincidencia exacta (case-insensitive)
    - contains: El texto contiene el valor (default)
    - starts_with: Empieza con el valor
    - ends_with: Termina con el valor
    - in: El valor está en una lista (usar value como array)

    Args:
        request: Objeto con filtros, limit y offset.

    Returns:
        Lista de cámaras que cumplen TODOS los filtros especificados.

    Examples:
        >>> # Buscar cámaras de un servicio en una calle específica
        >>> {"filters": [
        ...     {"field": "service_id", "operator": "eq", "value": "SVC-12345"},
        ...     {"field": "address", "operator": "contains", "value": "rivadavia"}
        ... ]}

        >>> # Buscar cámaras con múltiples estados
        >>> {"filters": [
        ...     {"field": "status", "operator": "in", "value": ["LIBRE", "DETECTADA"]}
        ... ]}
    """
    try:
        with SessionLocal() as session:
            # Obtener todas las cámaras (optimizado con eager loading si es necesario)
            query = session.query(Camara)

            # Pre-filtro por estado si solo hay filtro de estado (optimización)
            status_filters = [f for f in request.filters if f.field == FilterField.STATUS]
            if len(status_filters) == 1 and len(request.filters) == 1:
                flt = status_filters[0]
                if flt.operator == FilterOperator.EQ:
                    value = flt.value if isinstance(flt.value, str) else flt.value[0]
                    if value.upper() in [e.value for e in CamaraEstado]:
                        query = query.filter(Camara.estado == CamaraEstado(value.upper()))
                elif flt.operator == FilterOperator.IN and isinstance(flt.value, list):
                    estados = [CamaraEstado(v.upper()) for v in flt.value if v.upper() in [e.value for e in CamaraEstado]]
                    if estados:
                        query = query.filter(Camara.estado.in_(estados))

            all_camaras = query.order_by(Camara.nombre).all()

            # Si no hay filtros, devolver todas las cámaras (con paginación)
            if not request.filters:
                total = len(all_camaras)
                paginated = all_camaras[request.offset : request.offset + request.limit]
                camaras_response = [
                    _build_camara_response(cam, _get_camara_servicios(cam))
                    for cam in paginated
                ]

                logger.info(
                    "action=advanced_search filters=0 total=%d returned=%d",
                    total,
                    len(camaras_response),
                )

                return SearchResponse(
                    total=total,
                    limit=request.limit,
                    offset=request.offset,
                    filters_applied=0,
                    camaras=camaras_response,
                )

            # Aplicar filtros con lógica AND
            matching_camaras = []
            for camara in all_camaras:
                servicios_ids = _get_camara_servicios(camara)
                cables_nombres = _get_camara_cables(camara)

                # Verificar que cumpla TODOS los filtros
                matches_all = True
                for flt in request.filters:
                    if not _camara_matches_filter(camara, flt, servicios_ids, cables_nombres):
                        matches_all = False
                        break

                if matches_all:
                    matching_camaras.append((camara, servicios_ids))

            # Aplicar paginación
            total = len(matching_camaras)
            paginated = matching_camaras[request.offset : request.offset + request.limit]
            camaras_response = [
                _build_camara_response(cam, svc_ids)
                for cam, svc_ids in paginated
            ]

            logger.info(
                "action=advanced_search filters=%d total=%d returned=%d offset=%d",
                len(request.filters),
                total,
                len(camaras_response),
                request.offset,
            )

            return SearchResponse(
                total=total,
                limit=request.limit,
                offset=request.offset,
                filters_applied=len(request.filters),
                camaras=camaras_response,
            )

    except Exception as exc:
        logger.exception("action=advanced_search_error error=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error en búsqueda avanzada: {exc!s}",
        ) from exc


# ──────────────────────────────────────────────────────────────────────────────
# Smart Search - Búsqueda libre por términos (texto libre)
# ──────────────────────────────────────────────────────────────────────────────


def _term_matches_camara(
    term: str,
    camara: Camara,
    servicios_ids: list[str],
    cables_nombres: list[str],
) -> bool:
    """Evalúa si un término coincide con algún campo de la cámara (OR).

    Busca el término (case-insensitive) en:
    - nombre de la cámara
    - dirección
    - fontine_id
    - IDs de servicios asociados
    - nombres de cables

    Args:
        term: Término de búsqueda (texto libre).
        camara: Objeto Camara de la base de datos.
        servicios_ids: Lista de IDs de servicios asociados.
        cables_nombres: Lista de nombres de cables asociados.

    Returns:
        True si el término coincide con al menos un campo.
    """
    term_lower = term.lower()

    # Buscar en nombre de cámara
    if camara.nombre and term_lower in camara.nombre.lower():
        return True

    # Buscar en dirección
    if camara.direccion and term_lower in camara.direccion.lower():
        return True

    # Buscar en fontine_id
    if camara.fontine_id and term_lower in camara.fontine_id.lower():
        return True

    # Buscar en IDs de servicios
    for svc_id in servicios_ids:
        if term_lower in svc_id.lower():
            return True

    # Buscar en nombres de cables
    for cable_nombre in cables_nombres:
        if term_lower in cable_nombre.lower():
            return True

    # Buscar en estado (coincidencia exacta o parcial)
    estado_actual = camara.estado.value if camara.estado else "LIBRE"
    if term_lower in estado_actual.lower():
        return True

    # Buscar en origen de datos
    origen_actual = camara.origen_datos.value if camara.origen_datos else "MANUAL"
    if term_lower in origen_actual.lower():
        return True

    return False


@router.post("/api/infra/smart-search", response_model=SearchResponse)
async def smart_search_camaras(request: SmartSearchRequest) -> SearchResponse:
    """Smart Search: búsqueda libre por términos.

    A diferencia de la búsqueda avanzada (filtros tipados), este endpoint
    acepta una lista de términos de texto libre. Cada término se busca
    en múltiples campos simultáneamente:

    - Nombre de la cámara
    - Dirección
    - Fontine ID
    - IDs de servicios asociados
    - Nombres de cables
    - Estado (LIBRE, OCUPADA, BANEADA, DETECTADA)
    - Origen de datos (MANUAL, TRACKING, SHEET)

    **Lógica de búsqueda:**
    - **OR interno:** cada término se busca en todos los campos.
    - **AND entre términos:** la cámara debe coincidir con TODOS los términos.

    **Ejemplos:**
    - `["111995"]` → cámaras con servicio que contenga "111995"
    - `["Corrientes"]` → cámaras en calle "Corrientes"
    - `["111995", "Corrientes"]` → cámaras que cumplan AMBOS criterios

    Args:
        request: Objeto con términos, limit y offset.

    Returns:
        Lista de cámaras que coinciden con todos los términos.
    """
    try:
        with SessionLocal() as session:
            all_camaras = session.query(Camara).order_by(Camara.nombre).all()

            # Si no hay términos, devolver todas las cámaras
            if not request.terms:
                total = len(all_camaras)
                paginated = all_camaras[request.offset : request.offset + request.limit]
                camaras_response = [
                    _build_camara_response(cam, _get_camara_servicios(cam))
                    for cam in paginated
                ]

                logger.info(
                    "action=smart_search terms=0 total=%d returned=%d",
                    total,
                    len(camaras_response),
                )

                return SearchResponse(
                    total=total,
                    limit=request.limit,
                    offset=request.offset,
                    filters_applied=0,
                    camaras=camaras_response,
                )

            # Aplicar términos con lógica AND
            matching_camaras = []
            for camara in all_camaras:
                servicios_ids = _get_camara_servicios(camara)
                cables_nombres = _get_camara_cables(camara)

                # Verificar que cumpla TODOS los términos
                matches_all = True
                for term in request.terms:
                    term_clean = term.strip()
                    if not term_clean:
                        continue
                    if not _term_matches_camara(term_clean, camara, servicios_ids, cables_nombres):
                        matches_all = False
                        break

                if matches_all:
                    matching_camaras.append((camara, servicios_ids))

            # Aplicar paginación
            total = len(matching_camaras)
            paginated = matching_camaras[request.offset : request.offset + request.limit]
            camaras_response = [
                _build_camara_response(cam, svc_ids)
                for cam, svc_ids in paginated
            ]

            terms_count = len([t for t in request.terms if t.strip()])
            logger.info(
                "action=smart_search terms=%d total=%d returned=%d offset=%d",
                terms_count,
                total,
                len(camaras_response),
                request.offset,
            )

            return SearchResponse(
                total=total,
                limit=request.limit,
                offset=request.offset,
                filters_applied=terms_count,
                camaras=camaras_response,
            )

    except Exception as exc:
        logger.exception("action=smart_search_error error=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error en smart search: {exc!s}",
        ) from exc


@router.post("/sync/camaras", response_model=InfraSyncResponse)
async def trigger_infra_sync(payload: InfraSyncRequest | None = None) -> InfraSyncResponse:
    """Sincroniza cámaras desde Google Sheets."""

    sheet_id = payload.sheet_id if payload else None
    worksheet_name = payload.worksheet_name if payload else None
    try:
        result = sync_camaras_from_sheet(sheet_id=sheet_id, worksheet_name=worksheet_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("action=infra_sync endpoint_error=%s", exc)
        raise HTTPException(status_code=500, detail="Falló la sincronización de infraestructura") from exc

    return InfraSyncResponse(
        status="ok",
        processed=result.processed,
        updated=result.updated,
        created=result.created,
    )


def _normalizar_nombre_camara(nombre: str) -> str:
    """Normaliza el nombre de una cámara para comparación."""

    return " ".join(nombre.strip().lower().split())


def _buscar_camara_por_nombre(session, nombre: str) -> Optional[Camara]:
    """Busca una cámara por nombre exacto o normalizado.

    Args:
        session: Sesión de SQLAlchemy.
        nombre: Nombre/dirección de la cámara a buscar.

    Returns:
        Cámara encontrada o None.
    """

    nombre_normalizado = _normalizar_nombre_camara(nombre)

    # Buscar coincidencia exacta primero
    camara = session.query(Camara).filter(Camara.nombre == nombre).first()
    if camara:
        return camara

    # Buscar por nombre normalizado (case-insensitive, espacios normalizados)
    camaras = session.query(Camara).all()
    for c in camaras:
        if c.nombre and _normalizar_nombre_camara(c.nombre) == nombre_normalizado:
            return c

    return None


def _crear_camara_desde_tracking(session, nombre: str) -> Camara:
    """Crea una nueva cámara detectada desde un tracking.

    Args:
        session: Sesión de SQLAlchemy.
        nombre: Nombre/dirección de la cámara.

    Returns:
        Nueva cámara creada.
    """

    camara = Camara(
        nombre=nombre.strip(),
        estado=CamaraEstado.DETECTADA,
        origen_datos=CamaraOrigenDatos.TRACKING,
        last_update=datetime.now(timezone.utc),
    )
    session.add(camara)
    session.flush()  # Para obtener el ID asignado

    logger.info(
        "action=crear_camara_tracking nombre=%s id=%d estado=%s",
        nombre,
        camara.id,
        camara.estado.value,
    )
    return camara


def _obtener_o_crear_servicio(session, servicio_id: str, nombre_archivo: str) -> tuple[Servicio, bool]:
    """Obtiene un servicio existente o crea uno nuevo.

    Args:
        session: Sesión de SQLAlchemy.
        servicio_id: ID único del servicio.
        nombre_archivo: Nombre del archivo de origen.

    Returns:
        Tupla (servicio, es_nuevo).
    """

    servicio = session.query(Servicio).filter(Servicio.servicio_id == servicio_id).first()

    if servicio:
        # Actualizar nombre de archivo si cambió
        if nombre_archivo and servicio.nombre_archivo_origen != nombre_archivo:
            servicio.nombre_archivo_origen = nombre_archivo
        return servicio, False

    servicio = Servicio(
        servicio_id=servicio_id,
        nombre_archivo_origen=nombre_archivo,
    )
    session.add(servicio)
    session.flush()

    logger.info(
        "action=crear_servicio servicio_id=%s nombre_archivo=%s",
        servicio_id,
        nombre_archivo,
    )
    return servicio, True


def _registrar_empalme(
    session,
    servicio: Servicio,
    empalme_id: str,
    camara: Camara,
) -> tuple[Empalme, bool]:
    """Registra un empalme y lo asocia al servicio.

    Args:
        session: Sesión de SQLAlchemy.
        servicio: Servicio al que pertenece el empalme.
        empalme_id: ID del empalme en el tracking.
        camara: Cámara donde se ubica el empalme.

    Returns:
        Tupla (empalme, es_nuevo).
    """

    # Buscar empalme existente por tracking_empalme_id + servicio
    tracking_id_completo = f"{servicio.servicio_id}_{empalme_id}"

    empalme = (
        session.query(Empalme)
        .filter(Empalme.tracking_empalme_id == tracking_id_completo)
        .first()
    )

    if empalme:
        # Actualizar cámara si cambió
        if empalme.camara_id != camara.id:
            empalme.camara_id = camara.id
        # Asegurar asociación con servicio
        if servicio not in empalme.servicios:
            empalme.servicios.append(servicio)
        return empalme, False

    empalme = Empalme(
        tracking_empalme_id=tracking_id_completo,
        camara_id=camara.id,
    )
    session.add(empalme)
    session.flush()

    # Asociar al servicio
    empalme.servicios.append(servicio)

    logger.debug(
        "action=registrar_empalme tracking_id=%s camara_id=%d servicio_id=%s",
        tracking_id_completo,
        camara.id,
        servicio.servicio_id,
    )
    return empalme, True


@router.post("/api/infra/upload_tracking", response_model=TrackingUploadResponse)
async def upload_tracking(file: UploadFile = File(...)) -> TrackingUploadResponse:
    """Procesa un archivo de tracking de fibra óptica y puebla la base de datos.

    El endpoint realiza las siguientes operaciones:
    1. Parsea el archivo para extraer el ID del servicio y la topología (empalmes/ubicaciones).
    2. Crea o actualiza el servicio en la base de datos.
    3. Para cada empalme/ubicación:
       - Busca la cámara por nombre (coincidencia exacta o normalizada).
       - Si no existe, crea una nueva cámara con estado DETECTADA.
       - Registra el paso del servicio por esa cámara.

    Args:
        file: Archivo .txt con el tracking de fibra óptica.

    Returns:
        Resumen del procesamiento con conteos de elementos procesados.

    Raises:
        HTTPException 400: Si el archivo no tiene extensión .txt o no contiene datos válidos.
        HTTPException 500: Si ocurre un error durante el procesamiento.
    """

    # Validar extensión del archivo
    if not file.filename or not file.filename.lower().endswith(".txt"):
        raise HTTPException(
            status_code=400,
            detail="El archivo debe tener extensión .txt",
        )

    try:
        # Leer contenido del archivo
        content = await file.read()
        try:
            raw_text = content.decode("utf-8")
        except UnicodeDecodeError:
            raw_text = content.decode("latin-1")

        # Parsear el tracking
        result = parse_tracking(raw_text, file.filename)

        if not result.servicio_id:
            raise HTTPException(
                status_code=400,
                detail=f"No se pudo extraer el ID del servicio desde el nombre del archivo: {file.filename}",
            )

        topologia = result.get_topologia()
        if not topologia:
            raise HTTPException(
                status_code=400,
                detail="No se encontraron empalmes/ubicaciones en el archivo",
            )

        logger.info(
            "action=upload_tracking filename=%s servicio_id=%s empalmes=%d",
            file.filename,
            result.servicio_id,
            len(topologia),
        )

        # Procesar en base de datos
        camaras_nuevas = 0
        camaras_existentes = 0
        empalmes_registrados = 0

        with SessionLocal() as session:
            try:
                # Obtener o crear servicio
                servicio, servicio_nuevo = _obtener_o_crear_servicio(
                    session,
                    result.servicio_id,
                    file.filename,
                )

                # Guardar datos crudos del tracking
                servicio.raw_tracking_data = result.to_dict()

                # Procesar cada empalme/ubicación
                for empalme_id, ubicacion in topologia:
                    # Buscar o crear cámara
                    camara = _buscar_camara_por_nombre(session, ubicacion)

                    if camara:
                        camaras_existentes += 1
                    else:
                        camara = _crear_camara_desde_tracking(session, ubicacion)
                        camaras_nuevas += 1

                    # Registrar empalme
                    empalme, empalme_nuevo = _registrar_empalme(
                        session,
                        servicio,
                        empalme_id,
                        camara,
                    )
                    if empalme_nuevo:
                        empalmes_registrados += 1

                session.commit()

                logger.info(
                    "action=upload_tracking_complete servicio_id=%s camaras_nuevas=%d "
                    "camaras_existentes=%d empalmes=%d",
                    result.servicio_id,
                    camaras_nuevas,
                    camaras_existentes,
                    empalmes_registrados,
                )

                return TrackingUploadResponse(
                    status="ok",
                    servicios_procesados=1,
                    servicio_id=result.servicio_id,
                    camaras_nuevas=camaras_nuevas,
                    camaras_existentes=camaras_existentes,
                    empalmes_registrados=empalmes_registrados,
                    mensaje=f"Tracking del servicio {result.servicio_id} procesado correctamente",
                )

            except Exception as exc:
                session.rollback()
                logger.exception(
                    "action=upload_tracking_error servicio_id=%s error=%s",
                    result.servicio_id,
                    exc,
                )
                raise

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("action=upload_tracking_error filename=%s error=%s", file.filename, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error procesando el archivo de tracking: {exc!s}",
        ) from exc
