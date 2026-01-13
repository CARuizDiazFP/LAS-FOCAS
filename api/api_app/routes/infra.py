# Nombre de archivo: infra.py
# Ubicación de archivo: api/api_app/routes/infra.py
# Descripción: Endpoints para sincronizar cámaras, procesar trackings y gestionar rutas de fibra óptica

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy import func, or_

from core.parsers.tracking_parser import parse_tracking
from core.services.infra_sync import sync_camaras_from_sheet
from core.services.infra_service import (
    AnalysisResult,
    AnalysisStatus,
    InfraService,
    ResolveAction,
    ResolveResult,
    StrandInfo,
    UpgradeInfo,
    analyze_tracking_file,
    resolve_tracking_file,
)
from core.services.email_service import EmailAttachment, get_email_service
from db.models.infra import (
    Cable,
    Camara,
    CamaraEstado,
    CamaraOrigenDatos,
    Empalme,
    RutaServicio,
    RutaTipo,
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


# =============================================================================
# ENDPOINTS DE VERSIONADO Y RAMIFICACIÓN DE RUTAS
# =============================================================================


class TrackingAnalyzeRequest(BaseModel):
    """Request opcional para analyze (puede enviar contenido en lugar de archivo)."""
    
    content: Optional[str] = None
    filename: Optional[str] = None


class RutaInfoResponse(BaseModel):
    """Información de una ruta existente."""
    
    id: int
    nombre: str
    tipo: str
    hash_contenido: Optional[str] = None
    empalmes_count: int
    activa: bool
    created_at: Optional[str] = None
    nombre_archivo_origen: Optional[str] = None


class UpgradeInfoResponse(BaseModel):
    """Información de un posible upgrade detectado."""
    
    old_service_id: str
    old_service_db_id: int
    new_service_id: str
    match_reason: str
    punta_a_match: Optional[str] = None
    punta_b_match: Optional[str] = None


class StrandInfoResponse(BaseModel):
    """Información de un nuevo pelo detectado."""
    
    service_id: str
    service_db_id: int
    ruta_id: int
    current_strands: int
    new_strand_pelo: Optional[str] = None
    new_strand_conector: Optional[str] = None


class TrackingAnalyzeResponse(BaseModel):
    """Respuesta del análisis de un archivo de tracking."""
    
    status: str  # NEW, IDENTICAL, CONFLICT, POTENTIAL_UPGRADE, NEW_STRAND, ERROR
    servicio_id: Optional[str] = None
    servicio_db_id: Optional[int] = None
    nuevo_hash: Optional[str] = None
    rutas_existentes: List[RutaInfoResponse] = []
    ruta_identica_id: Optional[int] = None
    parsed_empalmes_count: int = 0
    message: str = ""
    error: Optional[str] = None
    # Nuevos campos para upgrade y strand
    upgrade_info: Optional[UpgradeInfoResponse] = None
    strand_info: Optional[StrandInfoResponse] = None
    # Info de puntas
    punta_a_sitio: Optional[str] = None
    punta_b_sitio: Optional[str] = None
    cantidad_pelos: Optional[int] = None
    alias_id: Optional[str] = None


class TrackingResolveRequest(BaseModel):
    """Request para resolver un tracking."""
    
    action: str  # CREATE_NEW, MERGE_APPEND, REPLACE, BRANCH, CONFIRM_UPGRADE, ADD_STRAND
    content: str
    filename: str
    target_ruta_id: Optional[int] = None
    new_ruta_name: Optional[str] = None
    new_ruta_tipo: Optional[str] = None  # PRINCIPAL, BACKUP, ALTERNATIVA
    old_service_id: Optional[str] = None  # Para CONFIRM_UPGRADE


class TrackingResolveResponse(BaseModel):
    """Respuesta de la resolución de un tracking."""
    
    success: bool
    action: str
    servicio_id: Optional[str] = None
    servicio_db_id: Optional[int] = None
    ruta_id: Optional[int] = None
    ruta_nombre: Optional[str] = None
    camaras_nuevas: int = 0
    camaras_existentes: int = 0
    empalmes_creados: int = 0
    empalmes_asociados: int = 0
    message: str = ""
    error: Optional[str] = None


class ServicioRutasResponse(BaseModel):
    """Respuesta con información de un servicio y sus rutas."""
    
    status: str
    servicio_id: str
    servicio_db_id: int
    cliente: Optional[str] = None
    rutas: List[RutaInfoResponse]
    total_rutas: int


@router.post("/api/infra/trackings/analyze", response_model=TrackingAnalyzeResponse)
async def analyze_tracking_endpoint(
    file: Optional[UploadFile] = File(None),
    content: Optional[str] = None,
    filename: Optional[str] = None,
) -> TrackingAnalyzeResponse:
    """Analiza un archivo de tracking y determina el escenario.
    
    El "Portero" de archivos - Fase 1 (Análisis):
    - Parsea el archivo y extrae ID de servicio y empalmes
    - Busca el servicio en la base de datos
    - Compara hashes con rutas existentes
    
    Escenarios posibles:
    - NEW: El servicio no existe, se puede crear
    - IDENTICAL: El archivo es idéntico a una ruta existente
    - CONFLICT: El servicio existe pero el contenido es diferente
    - ERROR: Hubo un error durante el análisis
    
    Args:
        file: Archivo .txt de tracking (multipart/form-data)
        content: Contenido del archivo (alternativa a subir archivo)
        filename: Nombre del archivo (requerido si se usa content)
    
    Returns:
        TrackingAnalyzeResponse con el resultado del análisis
    """
    # Obtener contenido del archivo o del body
    if file:
        raw_bytes = await file.read()
        try:
            raw_content = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raw_content = raw_bytes.decode("latin-1")
        filename_used = file.filename or "unknown.txt"
    elif content:
        raw_content = content
        filename_used = filename or "unknown.txt"
    else:
        raise HTTPException(
            status_code=400,
            detail="Debe enviar un archivo (file) o contenido (content + filename)",
        )
    
    try:
        with SessionLocal() as session:
            result = analyze_tracking_file(session, raw_content, filename_used)
            
            # Convertir upgrade_info si existe
            upgrade_info_response = None
            if result.upgrade_info:
                upgrade_info_response = UpgradeInfoResponse(
                    old_service_id=result.upgrade_info.old_service_id,
                    old_service_db_id=result.upgrade_info.old_service_db_id,
                    new_service_id=result.upgrade_info.new_service_id,
                    match_reason=result.upgrade_info.match_reason,
                    punta_a_match=result.upgrade_info.punta_a_match,
                    punta_b_match=result.upgrade_info.punta_b_match,
                )
            
            # Convertir strand_info si existe
            strand_info_response = None
            if result.strand_info:
                strand_info_response = StrandInfoResponse(
                    service_id=result.strand_info.service_id,
                    service_db_id=result.strand_info.service_db_id,
                    ruta_id=result.strand_info.ruta_id,
                    current_strands=result.strand_info.current_strands,
                    new_strand_pelo=result.strand_info.new_strand_pelo,
                    new_strand_conector=result.strand_info.new_strand_conector,
                )
            
            return TrackingAnalyzeResponse(
                status=result.status.value,
                servicio_id=result.servicio_id,
                servicio_db_id=result.servicio_db_id,
                nuevo_hash=result.nuevo_hash,
                rutas_existentes=[
                    RutaInfoResponse(
                        id=r.id,
                        nombre=r.nombre,
                        tipo=r.tipo,
                        hash_contenido=r.hash_contenido,
                        empalmes_count=r.empalmes_count,
                        activa=r.activa,
                        created_at=r.created_at,
                        nombre_archivo_origen=r.nombre_archivo_origen,
                    )
                    for r in result.rutas_existentes
                ],
                ruta_identica_id=result.ruta_identica_id,
                parsed_empalmes_count=result.parsed_empalmes_count,
                message=result.message,
                error=result.error,
                upgrade_info=upgrade_info_response,
                strand_info=strand_info_response,
                punta_a_sitio=result.punta_a_sitio,
                punta_b_sitio=result.punta_b_sitio,
                cantidad_pelos=result.cantidad_pelos,
                alias_id=result.alias_id,
            )
            
    except Exception as exc:
        logger.exception("action=analyze_tracking_error filename=%s error=%s", filename_used, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error analizando el archivo: {exc!s}",
        ) from exc


@router.post("/api/infra/trackings/resolve", response_model=TrackingResolveResponse)
async def resolve_tracking_endpoint(
    body: TrackingResolveRequest,
) -> TrackingResolveResponse:
    """Resuelve un tracking ejecutando la acción especificada.
    
    El "Portero" de archivos - Fase 2 (Resolución):
    Ejecuta la acción correspondiente basada en el análisis previo.
    
    Acciones disponibles:
    - CREATE_NEW: Crea un nuevo servicio con una ruta "Principal"
    - MERGE_APPEND: Agrega empalmes nuevos a una ruta existente
    - REPLACE: Reemplaza completamente los empalmes de una ruta
    - BRANCH: Crea una nueva ruta bajo el mismo servicio
    - CONFIRM_UPGRADE: Confirma upgrade, mueve ID viejo a alias
    - ADD_STRAND: Agrega nuevo pelo a ruta existente
    
    Args:
        body: TrackingResolveRequest con:
            - action: Acción a ejecutar
            - content: Contenido del archivo
            - filename: Nombre del archivo
            - target_ruta_id: ID de ruta destino (para MERGE_APPEND/REPLACE/ADD_STRAND)
            - new_ruta_name: Nombre de nueva ruta (para BRANCH)
            - new_ruta_tipo: Tipo de ruta (PRINCIPAL/BACKUP/ALTERNATIVA)
            - old_service_id: ID del servicio viejo (para CONFIRM_UPGRADE)
    
    Returns:
        TrackingResolveResponse con el resultado de la operación
    """
    # Validar acción
    try:
        action = ResolveAction(body.action.upper())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Acción inválida: {body.action}. Opciones: CREATE_NEW, MERGE_APPEND, REPLACE, BRANCH, CONFIRM_UPGRADE, ADD_STRAND",
        )
    
    # Validar tipo de ruta si se especifica
    ruta_tipo = RutaTipo.ALTERNATIVA
    if body.new_ruta_tipo:
        try:
            ruta_tipo = RutaTipo(body.new_ruta_tipo.upper())
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Tipo de ruta inválido: {body.new_ruta_tipo}. Opciones: PRINCIPAL, BACKUP, ALTERNATIVA",
            )
    
    try:
        with SessionLocal() as session:
            result = resolve_tracking_file(
                session,
                action,
                body.content,
                body.filename,
                target_ruta_id=body.target_ruta_id,
                new_ruta_name=body.new_ruta_name,
                new_ruta_tipo=ruta_tipo,
                old_service_id=body.old_service_id,
            )
            
            if not result.success:
                # No es un error HTTP, es un resultado de negocio
                return TrackingResolveResponse(
                    success=False,
                    action=result.action.value,
                    servicio_id=result.servicio_id,
                    error=result.error,
                    message=result.message,
                )
            
            return TrackingResolveResponse(
                success=True,
                action=result.action.value,
                servicio_id=result.servicio_id,
                servicio_db_id=result.servicio_db_id,
                ruta_id=result.ruta_id,
                ruta_nombre=result.ruta_nombre,
                camaras_nuevas=result.camaras_nuevas,
                camaras_existentes=result.camaras_existentes,
                empalmes_creados=result.empalmes_creados,
                empalmes_asociados=result.empalmes_asociados,
                message=result.message,
            )
            
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("action=resolve_tracking_error action=%s error=%s", body.action, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error resolviendo el tracking: {exc!s}",
        ) from exc


@router.get("/api/infra/servicios/{servicio_id}/rutas", response_model=ServicioRutasResponse)
async def get_servicio_rutas(servicio_id: str) -> ServicioRutasResponse:
    """Obtiene las rutas de un servicio.
    
    Args:
        servicio_id: ID del servicio (ej: "111995")
    
    Returns:
        ServicioRutasResponse con información del servicio y sus rutas
    """
    try:
        with SessionLocal() as session:
            servicio = session.query(Servicio).filter(
                Servicio.servicio_id == servicio_id
            ).first()
            
            if not servicio:
                raise HTTPException(
                    status_code=404,
                    detail=f"Servicio {servicio_id} no encontrado",
                )
            
            rutas_info = []
            for ruta in servicio.rutas:
                rutas_info.append(RutaInfoResponse(
                    id=ruta.id,
                    nombre=ruta.nombre,
                    tipo=ruta.tipo.value if ruta.tipo else "PRINCIPAL",
                    hash_contenido=ruta.hash_contenido,
                    empalmes_count=len(ruta.empalmes),
                    activa=bool(ruta.activa),
                    created_at=ruta.created_at.isoformat() if ruta.created_at else None,
                    nombre_archivo_origen=ruta.nombre_archivo_origen,
                ))
            
            return ServicioRutasResponse(
                status="ok",
                servicio_id=servicio.servicio_id,
                servicio_db_id=servicio.id,
                cliente=servicio.cliente,
                rutas=rutas_info,
                total_rutas=len(rutas_info),
            )
            
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("action=get_servicio_rutas_error servicio_id=%s error=%s", servicio_id, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error obteniendo rutas del servicio: {exc!s}",
        ) from exc


@router.get("/api/infra/rutas/{ruta_id}/empalmes")
async def get_ruta_empalmes(ruta_id: int) -> Dict[str, Any]:
    """Obtiene los empalmes de una ruta específica.
    
    Args:
        ruta_id: ID de la ruta
    
    Returns:
        Dict con información de la ruta y sus empalmes ordenados
    """
    try:
        with SessionLocal() as session:
            ruta = session.query(RutaServicio).get(ruta_id)
            
            if not ruta:
                raise HTTPException(
                    status_code=404,
                    detail=f"Ruta {ruta_id} no encontrada",
                )
            
            empalmes_data = []
            for empalme in ruta.empalmes:
                camara_data = None
                if empalme.camara:
                    camara_data = {
                        "id": empalme.camara.id,
                        "nombre": empalme.camara.nombre,
                        "direccion": empalme.camara.direccion,
                        "estado": empalme.camara.estado.value if empalme.camara.estado else None,
                        "latitud": empalme.camara.latitud,
                        "longitud": empalme.camara.longitud,
                    }
                
                empalmes_data.append({
                    "id": empalme.id,
                    "tracking_empalme_id": empalme.tracking_empalme_id,
                    "tipo": empalme.tipo,
                    "camara": camara_data,
                })
            
            return {
                "status": "ok",
                "ruta": {
                    "id": ruta.id,
                    "nombre": ruta.nombre,
                    "tipo": ruta.tipo.value if ruta.tipo else "PRINCIPAL",
                    "servicio_id": ruta.servicio.servicio_id,
                    "activa": bool(ruta.activa),
                },
                "empalmes": empalmes_data,
                "total_empalmes": len(empalmes_data),
            }
            
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("action=get_ruta_empalmes_error ruta_id=%d error=%s", ruta_id, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error obteniendo empalmes de la ruta: {exc!s}",
        ) from exc


@router.delete("/api/infra/servicios/{servicio_id}/empalmes")
async def delete_servicio_empalmes(servicio_id: str) -> Dict[str, Any]:
    """Elimina todas las asociaciones empalmes de un servicio.
    
    Esto permite "limpiar" un servicio para volver a asociarlo con nuevos empalmes.
    Elimina tanto las asociaciones legacy (servicio_empalme_association) como 
    las rutas (rutas_servicio + ruta_empalme_association).
    
    ⚠️ PRECAUCIÓN: Esta operación es destructiva y no se puede deshacer.
    
    Args:
        servicio_id: ID del servicio (ej: "52547")
    
    Returns:
        Dict con información de las asociaciones eliminadas
    """
    try:
        with SessionLocal() as session:
            servicio = session.query(Servicio).filter(
                Servicio.servicio_id == servicio_id
            ).first()
            
            if not servicio:
                raise HTTPException(
                    status_code=404,
                    detail=f"Servicio {servicio_id} no encontrado",
                )
            
            # Contar antes de eliminar
            empalmes_legacy_count = len(servicio.empalmes)
            rutas_count = len(servicio.rutas)
            empalmes_rutas_count = sum(len(r.empalmes) for r in servicio.rutas)
            
            # Eliminar asociaciones legacy (N-a-N servicio_empalme_association)
            servicio.empalmes.clear()
            
            # Eliminar rutas (cascade elimina ruta_empalme_association)
            for ruta in list(servicio.rutas):
                session.delete(ruta)
            
            session.commit()
            
            logger.info(
                "action=delete_servicio_empalmes servicio_id=%s empalmes_legacy=%d rutas=%d empalmes_rutas=%d",
                servicio_id,
                empalmes_legacy_count,
                rutas_count,
                empalmes_rutas_count,
            )
            
            return {
                "status": "ok",
                "servicio_id": servicio_id,
                "message": f"Eliminadas {empalmes_legacy_count} asociaciones legacy y {rutas_count} rutas",
                "empalmes_legacy_eliminados": empalmes_legacy_count,
                "rutas_eliminadas": rutas_count,
                "empalmes_rutas_eliminados": empalmes_rutas_count,
            }
            
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("action=delete_servicio_empalmes_error servicio_id=%s error=%s", servicio_id, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error eliminando asociaciones del servicio: {exc!s}",
        ) from exc


# ══════════════════════════════════════════════════════════════════════════════
# PROTOCOLO DE PROTECCIÓN - BANEO DE CÁMARAS
# ══════════════════════════════════════════════════════════════════════════════


class BanCreateRequest(BaseModel):
    """Request para crear un baneo de cámaras."""
    
    ticket_asociado: Optional[str] = Field(None, max_length=64, description="ID del ticket de soporte")
    servicio_afectado_id: str = Field(..., max_length=64, description="ID del servicio que sufrió el corte")
    servicio_protegido_id: str = Field(..., max_length=64, description="ID del servicio a proteger (banear)")
    ruta_protegida_id: Optional[int] = Field(None, description="ID de ruta específica (opcional)")
    usuario_ejecutor: Optional[str] = Field(None, max_length=128, description="Usuario que ejecuta el baneo")
    motivo: Optional[str] = Field(None, max_length=512, description="Motivo del baneo")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "ticket_asociado": "INC0012345",
                "servicio_afectado_id": "52547",
                "servicio_protegido_id": "52548",
                "usuario_ejecutor": "operador@metrotel.com.ar",
                "motivo": "Corte de fibra principal en Av. Corrientes, protegiendo backup",
            }]
        }
    }


class BanLiftRequest(BaseModel):
    """Request para levantar un baneo."""
    
    incidente_id: int = Field(..., description="ID del incidente de baneo a cerrar")
    usuario_ejecutor: Optional[str] = Field(None, max_length=128, description="Usuario que levanta el baneo")
    motivo_cierre: Optional[str] = Field(None, max_length=512, description="Motivo del cierre")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "incidente_id": 1,
                "usuario_ejecutor": "operador@metrotel.com.ar",
                "motivo_cierre": "Corte reparado, fibra principal operativa",
            }]
        }
    }


class IncidenteBaneoResponse(BaseModel):
    """Respuesta con datos de un incidente de baneo."""
    
    id: int
    ticket_asociado: Optional[str]
    servicio_afectado_id: str
    servicio_protegido_id: str
    ruta_protegida_id: Optional[int]
    usuario_ejecutor: Optional[str]
    motivo: Optional[str]
    fecha_inicio: str
    fecha_fin: Optional[str]
    activo: bool
    duracion_horas: Optional[float]


@router.post("/api/infra/ban/create")
async def create_ban(request: BanCreateRequest) -> Dict[str, Any]:
    """Crea un incidente de baneo y marca las cámaras como BANEADAS.
    
    El Protocolo de Protección permite bloquear el acceso físico a cámaras
    que contienen fibra óptica de respaldo cuando la fibra principal está cortada.
    
    **Redundancia cruzada:** El servicio afectado (el que se cortó) puede ser
    diferente al servicio protegido (cuyas cámaras se banean).
    
    Args:
        request: Datos del baneo a crear
        
    Returns:
        Dict con resultado del baneo (ID de incidente, cámaras afectadas)
    
    Example:
        >>> # Corte en servicio 52547, proteger backup en 52548
        >>> POST /api/infra/ban/create
        >>> {
        ...     "ticket_asociado": "INC0012345",
        ...     "servicio_afectado_id": "52547",
        ...     "servicio_protegido_id": "52548",
        ...     "motivo": "Protección de ruta backup"
        ... }
    """
    from core.services.protection_service import create_ban as do_create_ban
    
    try:
        with SessionLocal() as session:
            result = do_create_ban(
                session,
                ticket_asociado=request.ticket_asociado,
                servicio_afectado_id=request.servicio_afectado_id,
                servicio_protegido_id=request.servicio_protegido_id,
                ruta_protegida_id=request.ruta_protegida_id,
                usuario_ejecutor=request.usuario_ejecutor,
                motivo=request.motivo,
            )
            
            if result.success:
                session.commit()
            else:
                session.rollback()
            
            return result.to_dict()
            
    except Exception as exc:
        logger.exception("action=create_ban_endpoint_error error=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error creando baneo: {exc!s}",
        ) from exc


@router.post("/api/infra/ban/lift")
async def lift_ban(request: BanLiftRequest) -> Dict[str, Any]:
    """Levanta un baneo y restaura el estado de las cámaras.
    
    La lógica de restauración es inteligente:
    - Si la cámara tiene un ingreso activo → OCUPADA
    - Si la cámara está en otro baneo activo → BANEADA (sin cambio)
    - En otro caso → LIBRE
    
    Args:
        request: ID del incidente a cerrar y datos opcionales
        
    Returns:
        Dict con resultado del levantamiento (cámaras restauradas)
    
    Example:
        >>> POST /api/infra/ban/lift
        >>> {"incidente_id": 1, "motivo_cierre": "Corte reparado"}
    """
    from core.services.protection_service import lift_ban as do_lift_ban
    
    try:
        with SessionLocal() as session:
            result = do_lift_ban(
                session,
                request.incidente_id,
                usuario_ejecutor=request.usuario_ejecutor,
                motivo_cierre=request.motivo_cierre,
            )
            
            if result.success:
                session.commit()
            else:
                session.rollback()
            
            return result.to_dict()
            
    except Exception as exc:
        logger.exception("action=lift_ban_endpoint_error error=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error levantando baneo: {exc!s}",
        ) from exc


@router.get("/api/infra/ban/active")
async def get_active_bans() -> Dict[str, Any]:
    """Obtiene todos los incidentes de baneo activos.
    
    Returns:
        Dict con lista de incidentes activos y conteo
    """
    from core.services.protection_service import get_incidentes_activos
    
    try:
        with SessionLocal() as session:
            incidentes = get_incidentes_activos(session)
            
            incidentes_data = []
            for inc in incidentes:
                # Contar cámaras afectadas
                camaras_count = len(inc.camaras_afectadas) if inc.camaras_afectadas else 0
                
                incidentes_data.append({
                    "id": inc.id,
                    "ticket_asociado": inc.ticket_asociado,
                    "servicio_afectado_id": inc.servicio_afectado_id,
                    "servicio_protegido_id": inc.servicio_protegido_id,
                    "ruta_protegida_id": inc.ruta_protegida_id,
                    "usuario_ejecutor": inc.usuario_ejecutor,
                    "motivo": inc.motivo,
                    "fecha_inicio": inc.fecha_inicio.isoformat() if inc.fecha_inicio else None,
                    "activo": inc.activo,
                    "duracion_horas": inc.duracion_horas,
                    "camaras_count": camaras_count,
                })
            
            return {
                "status": "ok",
                "total": len(incidentes_data),
                "incidentes": incidentes_data,
            }
            
    except Exception as exc:
        logger.exception("action=get_active_bans_error error=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error obteniendo baneos activos: {exc!s}",
        ) from exc


@router.get("/api/infra/ban/{incidente_id}")
async def get_ban_detail(incidente_id: int) -> Dict[str, Any]:
    """Obtiene el detalle de un incidente de baneo específico.
    
    Incluye las cámaras afectadas actualmente.
    
    Args:
        incidente_id: ID del incidente
        
    Returns:
        Dict con detalle del incidente y cámaras afectadas
    """
    from core.services.protection_service import ProtectionService
    
    try:
        with SessionLocal() as session:
            service = ProtectionService(session)
            incidente = service.get_incidente_by_id(incidente_id)
            
            if not incidente:
                raise HTTPException(
                    status_code=404,
                    detail=f"Incidente {incidente_id} no encontrado",
                )
            
            # Obtener cámaras afectadas
            camaras = service.get_camaras_for_servicio(
                incidente.servicio_protegido_id,
                incidente.ruta_protegida_id,
            )
            
            camaras_data = []
            for cam in camaras:
                camaras_data.append({
                    "id": cam.id,
                    "nombre": cam.nombre,
                    "fontine_id": cam.fontine_id,
                    "direccion": cam.direccion,
                    "estado": cam.estado.value if cam.estado else "LIBRE",
                })
            
            return {
                "status": "ok",
                "incidente": {
                    "id": incidente.id,
                    "ticket_asociado": incidente.ticket_asociado,
                    "servicio_afectado_id": incidente.servicio_afectado_id,
                    "servicio_protegido_id": incidente.servicio_protegido_id,
                    "ruta_protegida_id": incidente.ruta_protegida_id,
                    "usuario_ejecutor": incidente.usuario_ejecutor,
                    "motivo": incidente.motivo,
                    "fecha_inicio": incidente.fecha_inicio.isoformat() if incidente.fecha_inicio else None,
                    "fecha_fin": incidente.fecha_fin.isoformat() if incidente.fecha_fin else None,
                    "activo": incidente.activo,
                    "duracion_horas": incidente.duracion_horas,
                },
                "camaras_afectadas": camaras_data,
                "total_camaras": len(camaras_data),
            }
            
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("action=get_ban_detail_error incidente_id=%d error=%s", incidente_id, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error obteniendo detalle del baneo: {exc!s}",
        ) from exc


# ══════════════════════════════════════════════════════════════════════════════
# NOTIFICACIÓN POR CORREO - PROTOCOLO DE PROTECCIÓN
# ══════════════════════════════════════════════════════════════════════════════


class EmailNotifyRequest(BaseModel):
    """Request para enviar notificación por email sobre baneos activos."""

    to: List[str] = Field(..., min_length=1, description="Lista de destinatarios")
    cc: Optional[List[str]] = Field(None, description="Lista de destinatarios en copia")
    subject: str = Field(..., min_length=1, max_length=256, description="Asunto del correo")
    body: str = Field(..., min_length=1, description="Cuerpo del mensaje")
    incidente_ids: List[int] = Field(
        ..., min_length=1, description="IDs de los incidentes de baneo a incluir"
    )
    include_xls: bool = Field(True, description="Incluir archivo XLS con resumen de baneos")
    include_txt: bool = Field(True, description="Incluir archivo TXT original del tracking")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "to": ["operador@metrotel.com.ar", "supervisor@metrotel.com.ar"],
                    "cc": ["noc@metrotel.com.ar"],
                    "subject": "Alerta: Protocolo de Protección Activado - Servicio 52548",
                    "body": "Se informa que se ha activado el protocolo de protección...",
                    "incidente_ids": [1, 2],
                    "include_xls": True,
                    "include_txt": True,
                }
            ]
        }
    }


class EmailNotifyResponse(BaseModel):
    """Respuesta del endpoint de notificación por email."""

    success: bool
    message: str
    error: Optional[str] = None
    recipients_count: int = 0


@router.post("/api/infra/notify/email", response_model=EmailNotifyResponse)
async def send_ban_notification_email(request: EmailNotifyRequest) -> EmailNotifyResponse:
    """Envía un correo electrónico con información de baneos activos.

    Incluye:
    - Cuerpo personalizado del mensaje
    - Archivo XLS con resumen de cámaras baneadas (opcional)
    - Archivo TXT original del tracking (opcional, si está disponible)

    Args:
        request: Datos del correo a enviar

    Returns:
        EmailNotifyResponse con el resultado del envío
    """
    import io

    from db.models.infra import IncidenteBaneo

    email_service = get_email_service()

    if not email_service.is_configured():
        return EmailNotifyResponse(
            success=False,
            message="Servicio de email no configurado",
            error="SMTP no está configurado en el servidor",
        )

    try:
        attachments: List[EmailAttachment] = []

        with SessionLocal() as session:
            # Obtener incidentes
            incidentes = (
                session.query(IncidenteBaneo)
                .filter(IncidenteBaneo.id.in_(request.incidente_ids))
                .all()
            )

            if not incidentes:
                return EmailNotifyResponse(
                    success=False,
                    message="No se encontraron incidentes con los IDs especificados",
                    error="incidente_ids vacíos o inválidos",
                )

            # Generar XLS si se solicita
            if request.include_xls:
                try:
                    import pandas as pd

                    rows = []
                    for incidente in incidentes:
                        for camara in incidente.camaras_afectadas:
                            rows.append(
                                {
                                    "Incidente ID": incidente.id,
                                    "Ticket": incidente.ticket_asociado or "-",
                                    "Servicio Afectado": incidente.servicio_afectado_id,
                                    "Servicio Protegido": incidente.servicio_protegido_id,
                                    "Cámara ID": camara.id,
                                    "Cámara Nombre": camara.nombre,
                                    "Estado": camara.estado.value if camara.estado else "-",
                                    "Fecha Inicio": (
                                        incidente.fecha_inicio.strftime("%Y-%m-%d %H:%M")
                                        if incidente.fecha_inicio
                                        else "-"
                                    ),
                                    "Motivo": incidente.motivo or "-",
                                }
                            )

                    if rows:
                        df = pd.DataFrame(rows)
                        output = io.BytesIO()
                        with pd.ExcelWriter(output, engine="openpyxl") as writer:
                            df.to_excel(writer, sheet_name="Baneos_Activos", index=False)
                        output.seek(0)

                        attachments.append(
                            EmailAttachment(
                                filename="baneos_activos.xlsx",
                                content=output.getvalue(),
                                mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            )
                        )

                except ImportError:
                    logger.warning("action=notify_email warning=pandas_not_available skipping_xls=true")

            # Obtener archivo TXT original si se solicita
            if request.include_txt:
                txt_found = False
                for incidente in incidentes:
                    # Buscar la ruta asociada al servicio protegido
                    servicio = (
                        session.query(Servicio)
                        .filter(Servicio.servicio_id == incidente.servicio_protegido_id)
                        .first()
                    )
                    if servicio and servicio.rutas:
                        for ruta in servicio.rutas:
                            if ruta.raw_file_content:
                                txt_found = True
                                filename = (
                                    ruta.nombre_archivo_origen
                                    or f"tracking_{servicio.servicio_id}.txt"
                                )
                                attachments.append(
                                    EmailAttachment(
                                        filename=filename,
                                        content=ruta.raw_file_content.encode("utf-8"),
                                        mime_type="text/plain; charset=utf-8",
                                    )
                                )
                                break  # Solo un TXT por incidente
                        if txt_found:
                            break

                if not txt_found and request.include_txt:
                    logger.warning(
                        "action=notify_email warning=original_txt_not_found incidentes=%s",
                        request.incidente_ids,
                    )

        # Enviar correo
        result = email_service.send_email(
            to=request.to,
            cc=request.cc,
            subject=request.subject,
            body=request.body,
            attachments=attachments if attachments else None,
        )

        return EmailNotifyResponse(
            success=result.success,
            message=result.message,
            error=result.error,
            recipients_count=len(request.to) + len(request.cc or []),
        )

    except Exception as exc:
        logger.exception("action=notify_email_error error=%s", exc)
        return EmailNotifyResponse(
            success=False,
            message="Error al enviar notificación",
            error=str(exc),
        )


@router.get("/api/infra/tracking/{ruta_id}/download")
async def download_tracking_file(ruta_id: int) -> Response:
    """Descarga el archivo de tracking original de una ruta.

    IMPORTANTE: Devuelve el archivo TXT ORIGINAL tal como fue cargado,
    no una reconstrucción del JSON parseado.

    Args:
        ruta_id: ID de la ruta

    Returns:
        Archivo TXT original o error 404 si no está disponible
    """
    try:
        with SessionLocal() as session:
            ruta = session.query(RutaServicio).get(ruta_id)

            if not ruta:
                raise HTTPException(
                    status_code=404,
                    detail=f"Ruta {ruta_id} no encontrada",
                )

            if not ruta.raw_file_content:
                raise HTTPException(
                    status_code=404,
                    detail="Archivo original no disponible para esta ruta. "
                    "Solo las rutas creadas después de la actualización del sistema "
                    "tienen el archivo original guardado.",
                )

            filename = ruta.nombre_archivo_origen or f"tracking_ruta_{ruta_id}.txt"

            return Response(
                content=ruta.raw_file_content.encode("utf-8"),
                media_type="text/plain; charset=utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                },
            )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("action=download_tracking_error ruta_id=%d error=%s", ruta_id, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error descargando archivo de tracking: {exc!s}",
        ) from exc


@router.get("/api/infra/notify/email/config")
async def get_email_config_status() -> Dict[str, Any]:
    """Verifica si el servicio de email está configurado.

    Returns:
        Estado de configuración del servicio de email
    """
    email_service = get_email_service()
    settings = email_service.settings

    return {
        "configured": email_service.is_configured(),
        "from_email": settings.from_email if email_service.is_configured() else None,
        "from_name": settings.from_name if email_service.is_configured() else None,
    }


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTACIÓN DE CÁMARAS
# ══════════════════════════════════════════════════════════════════════════════


class ExportFormat(str, Enum):
    """Formatos de exportación disponibles."""
    CSV = "csv"
    XLSX = "xlsx"


@router.get("/api/infra/export/cameras")
async def export_cameras(
    filter_status: Optional[str] = None,
    servicio_id: Optional[str] = None,
    format: ExportFormat = ExportFormat.CSV,
) -> Any:
    """Exporta listado de cámaras a CSV o XLSX.
    
    Args:
        filter_status: Filtrar por estado (ALL, LIBRE, OCUPADA, BANEADA, DETECTADA)
        servicio_id: Filtrar cámaras de un servicio específico
        format: Formato de salida (csv o xlsx)
        
    Returns:
        Archivo CSV o XLSX para descarga
        
    Example:
        >>> GET /api/infra/export/cameras?filter_status=BANEADA&format=xlsx
    """
    import csv
    import io
    from fastapi.responses import StreamingResponse
    
    try:
        with SessionLocal() as session:
            query = session.query(Camara)
            
            # Filtrar por estado
            if filter_status and filter_status.upper() != "ALL":
                estado_upper = filter_status.upper()
                if estado_upper in [e.value for e in CamaraEstado]:
                    query = query.filter(Camara.estado == CamaraEstado(estado_upper))
            
            # Filtrar por servicio
            if servicio_id:
                servicio = session.query(Servicio).filter(
                    Servicio.servicio_id == servicio_id
                ).first()
                
                if servicio:
                    # Obtener IDs de cámaras del servicio
                    camara_ids = set()
                    for ruta in servicio.rutas_activas:
                        for empalme in ruta.empalmes:
                            if empalme.camara:
                                camara_ids.add(empalme.camara.id)
                    
                    if camara_ids:
                        query = query.filter(Camara.id.in_(camara_ids))
                    else:
                        # Servicio sin cámaras
                        query = query.filter(Camara.id == -1)  # No results
            
            camaras = query.order_by(Camara.nombre).all()
            
            # Obtener tickets de baneo activos para cámaras BANEADAS
            from db.models.infra import IncidenteBaneo
            baneos_activos = session.query(IncidenteBaneo).filter(
                IncidenteBaneo.activo == True
            ).all()
            
            # Crear mapa servicio_protegido -> ticket
            ticket_por_servicio: dict[str, str] = {}
            for baneo in baneos_activos:
                ticket_por_servicio[baneo.servicio_protegido_id] = baneo.ticket_asociado or f"INC-{baneo.id}"
            
            # Preparar datos
            rows = []
            for cam in camaras:
                # Obtener servicios Cat6
                servicios_cat6 = []
                for empalme in cam.empalmes:
                    for srv in empalme.servicios:
                        if srv.servicio_id and srv.servicio_id not in servicios_cat6:
                            servicios_cat6.append(srv.servicio_id)
                
                # Determinar ticket de baneo
                ticket_baneo = ""
                if cam.estado == CamaraEstado.BANEADA:
                    for svc_id in servicios_cat6:
                        if svc_id in ticket_por_servicio:
                            ticket_baneo = ticket_por_servicio[svc_id]
                            break
                
                rows.append({
                    "ID": cam.id,
                    "Nombre": cam.nombre or "",
                    "Fontine_ID": cam.fontine_id or "",
                    "Dirección": cam.direccion or "",
                    "Estado": cam.estado.value if cam.estado else "LIBRE",
                    "Servicios_Cat6": ", ".join(servicios_cat6),
                    "Ticket_Baneo": ticket_baneo,
                    "Latitud": cam.latitud or "",
                    "Longitud": cam.longitud or "",
                    "Origen_Datos": cam.origen_datos.value if cam.origen_datos else "MANUAL",
                })
            
            logger.info(
                "action=export_cameras filter_status=%s servicio=%s format=%s rows=%d",
                filter_status,
                servicio_id,
                format.value,
                len(rows),
            )
            
            # Generar archivo según formato
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            
            if format == ExportFormat.CSV:
                # Generar CSV
                output = io.StringIO()
                if rows:
                    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
                else:
                    output.write("Sin datos\n")
                
                content = output.getvalue().encode("utf-8-sig")  # BOM para Excel
                
                return StreamingResponse(
                    io.BytesIO(content),
                    media_type="text/csv; charset=utf-8",
                    headers={
                        "Content-Disposition": f'attachment; filename="camaras_{timestamp}.csv"',
                    },
                )
            
            else:  # XLSX
                try:
                    import pandas as pd
                    
                    df = pd.DataFrame(rows)
                    output = io.BytesIO()
                    
                    with pd.ExcelWriter(output, engine="openpyxl") as writer:
                        df.to_excel(writer, sheet_name="Cámaras", index=False)
                    
                    output.seek(0)
                    
                    return StreamingResponse(
                        output,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={
                            "Content-Disposition": f'attachment; filename="camaras_{timestamp}.xlsx"',
                        },
                    )
                    
                except ImportError:
                    # Fallback a CSV si no hay pandas/openpyxl
                    logger.warning("action=export_cameras warning=pandas_not_available fallback=csv")
                    
                    output = io.StringIO()
                    if rows:
                        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
                        writer.writeheader()
                        writer.writerows(rows)
                    else:
                        output.write("Sin datos\n")
                    
                    content = output.getvalue().encode("utf-8-sig")
                    
                    return StreamingResponse(
                        io.BytesIO(content),
                        media_type="text/csv; charset=utf-8",
                        headers={
                            "Content-Disposition": f'attachment; filename="camaras_{timestamp}.csv"',
                            "X-Export-Warning": "XLSX no disponible, exportando como CSV",
                        },
                    )
                    
    except Exception as exc:
        logger.exception("action=export_cameras_error error=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error exportando cámaras: {exc!s}",
        ) from exc
