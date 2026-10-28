# Nombre de archivo: infra.py
# Ubicación de archivo: api/app/routes/infra.py
# Descripción: Endpoints para sincronizar cámaras, procesar trackings y gestionar rutas de fibra óptica

from __future__ import annotations

import asyncio
import logging
from enum import Enum
from typing import Any, Dict, List, Optional

from core.utils.tz import TZ_ARG

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.parsers.tracking_parser import parse_tracking
from core.services.camaras_busqueda_avanzada import SearchRequest, buscar_camaras_avanzada
from core.services.camaras_exportacion import (
    AVISO_SIN_XLSX,
    a_csv,
    a_xlsx,
    filas_exportacion,
    nombre_archivo_exportacion,
)
from core.services.camaras_consulta import (
    buscar_camaras_por_terminos,
    listar_camaras,
    serializar_camara_basica,
)
from core.services.infra_sync import sync_camaras_from_sheet
from core.services.infra_service import (
    AnalysisResult,
    ResolveAction,
    ResolveResult,
    _get_or_create_empalme,
    _resolve_camara_o_registrar_sin_match,
    analyze_tracking_file,
    resolve_tracking_file,
)
from core.services.email_service import EmailAttachment, get_email_service, EmailService
from db.models.infra import (
    Camara,
    Empalme,
    RutaServicio,
    RutaTipo,
    Servicio,
)
from db.session import SessionLocal, get_async_db

from api.app.errores import error_interno, nueva_ref

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
    # Desde la Tarea 3 del refactor "Adjuntar tracking" (2026-08-23): `camaras_nuevas` queda
    # siempre en 0 (Cromo Red es la fuente de verdad, este endpoint ya no crea `Camara`) — se
    # mantiene el campo por compatibilidad con el contrato público documentado. Las ubicaciones que
    # no matchearon contra Camara/CromoBotella se cuentan acá y quedan registradas en
    # `IngresoSinMatch` (origen="tracking") para revisión manual.
    ubicaciones_sin_match: int = 0
    mensaje: Optional[str] = None


# ──────────────────────────────────────────────────────────────────────────────
# Búsqueda avanzada - Modelos y tipos
# ──────────────────────────────────────────────────────────────────────────────


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

    def _run() -> list[dict[str, Any]]:
        # Sesión síncrona propia del thread; se serializa antes de cerrarla (relaciones ya cargadas).
        with SessionLocal() as session:
            return [serializar_camara_basica(e) for e in listar_camaras(session, q=q, estado=estado, limit=limit)]

    try:
        camaras = await asyncio.to_thread(_run)

        logger.info(
            "action=search_camaras query=%s estado=%s results=%d",
            q,
            estado,
            len(camaras),
        )

        return CamarasListResponse(
            status="ok",
            total=len(camaras),
            camaras=[CamaraResponse(**c) for c in camaras],
        )

    except HTTPException:
        raise
    except Exception as exc:
        return error_interno("search_camaras", exc)


# ──────────────────────────────────────────────────────────────────────────────
# Búsqueda avanzada - Endpoint POST /api/infra/search
# ──────────────────────────────────────────────────────────────────────────────


@router.post("/api/infra/search", response_model=SearchResponse)
async def advanced_search_camaras(
    request: SearchRequest,
) -> SearchResponse:
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
    def _run() -> tuple[int, list[dict[str, Any]]]:
        # Sesión síncrona propia del thread; se serializa antes de cerrarla (relaciones ya cargadas).
        with SessionLocal() as session:
            resultado = buscar_camaras_avanzada(session, request.filters, limit=request.limit, offset=request.offset)
            return resultado.total, [serializar_camara_basica(e) for e in resultado.camaras]

    try:
        total, camaras = await asyncio.to_thread(_run)

        logger.info(
            "action=advanced_search filters=%d total=%d returned=%d offset=%d",
            len(request.filters),
            total,
            len(camaras),
            request.offset,
        )

        return SearchResponse(
            total=total,
            limit=request.limit,
            offset=request.offset,
            filters_applied=len(request.filters),
            camaras=[CamaraResponse(**c) for c in camaras],
        )

    except HTTPException:
        raise
    except Exception as exc:
        return error_interno("advanced_search", exc)


# ──────────────────────────────────────────────────────────────────────────────
# Smart Search - Búsqueda libre por términos (texto libre)
# ──────────────────────────────────────────────────────────────────────────────


@router.post("/api/infra/smart-search", response_model=SearchResponse)
async def smart_search_camaras(
    request: SmartSearchRequest,
    db: AsyncSession = Depends(get_async_db),
) -> SearchResponse:
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
    def _run() -> tuple[Any, list[dict[str, Any]]]:
        # Sesión propia del thread: la consulta y la serialización terminan antes de cerrarla.
        with SessionLocal() as session:
            resultado = buscar_camaras_por_terminos(
                session,
                request.terms,
                estado=None,
                incluir_no_operativas=True,
                limit=request.limit,
                offset=request.offset,
                solo_raiz=False,  # la API conserva su universo: Botellas y NO_OPERATIVA incluidas
            )
            return resultado, [serializar_camara_basica(c) for c in resultado.camaras]

    try:
        resultado, camaras = await asyncio.to_thread(_run)
        logger.info(
            "action=smart_search terms=%d total=%d returned=%d offset=%d",
            resultado.terminos_aplicados,
            resultado.total,
            len(camaras),
            request.offset,
        )
        return SearchResponse(
            total=resultado.total,
            limit=request.limit,
            offset=request.offset,
            filters_applied=resultado.terminos_aplicados,
            camaras=[CamaraResponse(**c) for c in camaras],
        )
    except HTTPException:
        raise
    except Exception as exc:
        return error_interno("smart_search", exc)


@router.post("/sync/camaras", response_model=InfraSyncResponse)
async def trigger_infra_sync(payload: InfraSyncRequest | None = None) -> InfraSyncResponse:
    """Sincroniza cámaras desde Google Sheets."""

    sheet_id = payload.sheet_id if payload else None
    worksheet_name = payload.worksheet_name if payload else None
    try:
        result = await asyncio.to_thread(
            sync_camaras_from_sheet,
            sheet_id=sheet_id,
            worksheet_name=worksheet_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        return error_interno("infra_sync_endpoint", exc)

    return InfraSyncResponse(
        status="ok",
        processed=result.processed,
        updated=result.updated,
        created=result.created,
    )


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
    camara: Optional[Camara],
) -> tuple[Empalme, bool]:
    """Registra un empalme y lo asocia al servicio.

    Delega la resolución de `camara_id` en `_get_or_create_empalme` (mismo helper que usa
    `InfraService`, Tarea 3 del refactor "Adjuntar tracking"): `camara` puede ser `None` (ubicación
    sin match — ver `_resolve_camara_o_registrar_sin_match`) y un reproceso sin match no pisa un
    `camara_id` previo válido de una corrida anterior.

    Args:
        session: Sesión de SQLAlchemy.
        servicio: Servicio al que pertenece el empalme.
        empalme_id: ID del empalme en el tracking.
        camara: Cámara donde se ubica el empalme, o `None` si no matcheó.

    Returns:
        Tupla (empalme, es_nuevo).
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


@router.post("/api/infra/upload_tracking", response_model=TrackingUploadResponse)
async def upload_tracking(file: UploadFile = File(...)) -> TrackingUploadResponse:
    """Procesa un archivo de tracking de fibra óptica y puebla la base de datos.

    El endpoint realiza las siguientes operaciones:
    1. Parsea el archivo para extraer el ID del servicio y la topología (empalmes/ubicaciones).
    2. Crea o actualiza el servicio en la base de datos.
    3. Para cada empalme/ubicación:
       - Busca la cámara/botella contra el inventario real (Camara y CromoBotella — Cromo Red es
         la fuente de verdad desde 2026-08-11).
       - Si no matchea, **no crea una cámara nueva**: registra un `IngresoSinMatch`
         (`origen="tracking"`) para revisión manual y deja el empalme sin `camara_id`. El
         procesamiento nunca se bloquea por esto.
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

        # Procesar en base de datos (bloqueante — usa SessionLocal en thread)
        _servicio_id = result.servicio_id
        _topologia = topologia
        _filename = file.filename

        def _persist() -> tuple[int, int, int]:
            camaras_existentes = 0
            ubicaciones_sin_match = 0
            empalmes_registrados = 0

            with SessionLocal() as session:
                try:
                    servicio, _ = _obtener_o_crear_servicio(session, _servicio_id, _filename)
                    servicio.raw_tracking_data = result.to_dict()

                    for empalme_id, ubicacion in _topologia:
                        # Cromo Red es la fuente de verdad del inventario: nunca se crea una
                        # Camara nueva. Sin match, se registra un IngresoSinMatch (dentro de
                        # `_resolve_camara_o_registrar_sin_match`) y el empalme queda sin
                        # camara_id — el procesamiento del tracking nunca se bloquea por esto.
                        camara = _resolve_camara_o_registrar_sin_match(
                            session, ubicacion, filename=_filename, servicio_id=_servicio_id
                        )
                        if camara is not None:
                            camaras_existentes += 1
                        else:
                            ubicaciones_sin_match += 1

                        _, empalme_nuevo = _registrar_empalme(session, servicio, empalme_id, camara)
                        if empalme_nuevo:
                            empalmes_registrados += 1

                    session.commit()
                    logger.info(
                        "action=upload_tracking_complete servicio_id=%s camaras_existentes=%d "
                        "ubicaciones_sin_match=%d empalmes=%d",
                        _servicio_id,
                        camaras_existentes,
                        ubicaciones_sin_match,
                        empalmes_registrados,
                    )
                    return camaras_existentes, ubicaciones_sin_match, empalmes_registrados

                except Exception as exc:
                    session.rollback()
                    logger.exception(
                        "action=upload_tracking_error servicio_id=%s error=%s", _servicio_id, exc
                    )
                    raise

        camaras_existentes, ubicaciones_sin_match, empalmes_registrados = await asyncio.to_thread(_persist)

        return TrackingUploadResponse(
            status="ok",
            servicios_procesados=1,
            servicio_id=result.servicio_id,
            camaras_nuevas=0,
            camaras_existentes=camaras_existentes,
            empalmes_registrados=empalmes_registrados,
            ubicaciones_sin_match=ubicaciones_sin_match,
            mensaje=f"Tracking del servicio {result.servicio_id} procesado correctamente",
        )

    except HTTPException:
        raise
    except Exception as exc:
        return error_interno("upload_tracking", exc, filename=file.filename)


# =============================================================================
# ENDPOINTS DE VERSIONADO Y RAMIFICACIÓN DE RUTAS
# =============================================================================


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
    # Campo nuevo (Tarea 3, 2026-08-23) — opcional/backward-compatible: ubicaciones del tracking
    # que no matchearon contra Camara/CromoBotella y quedaron registradas en `IngresoSinMatch`
    # (origen="tracking") para revisión manual. Ver `ResolveResult.ubicaciones_sin_match`.
    ubicaciones_sin_match: int = 0
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
    
    def _analyze() -> AnalysisResult:
        with SessionLocal() as session:
            return analyze_tracking_file(session, raw_content, filename_used)

    try:
        result = await asyncio.to_thread(_analyze)

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

    except HTTPException:
        raise
    except Exception as exc:
        return error_interno("analyze_tracking", exc, filename=filename_used)


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
    
    _action = action
    _body = body
    _ruta_tipo = ruta_tipo

    def _resolve() -> ResolveResult:
        with SessionLocal() as session:
            return resolve_tracking_file(
                session,
                _action,
                _body.content,
                _body.filename,
                target_ruta_id=_body.target_ruta_id,
                new_ruta_name=_body.new_ruta_name,
                new_ruta_tipo=_ruta_tipo,
                old_service_id=_body.old_service_id,
            )

    try:
        result = await asyncio.to_thread(_resolve)

        if not result.success:
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
            ubicaciones_sin_match=result.ubicaciones_sin_match,
            message=result.message,
        )

    except HTTPException:
        raise
    except Exception as exc:
        return error_interno("resolve_tracking", exc, action=body.action)


@router.get("/api/infra/servicios/{servicio_id}/rutas", response_model=ServicioRutasResponse)
async def get_servicio_rutas(
    servicio_id: str,
    db: AsyncSession = Depends(get_async_db),
) -> ServicioRutasResponse:
    """Obtiene las rutas de un servicio.
    
    Args:
        servicio_id: ID del servicio (ej: "111995")
    
    Returns:
        ServicioRutasResponse con información del servicio y sus rutas
    """
    try:
        stmt = (
            select(Servicio)
            .where(Servicio.servicio_id == servicio_id)
            .options(
                selectinload(Servicio.rutas).selectinload(RutaServicio.empalmes)
            )
        )
        servicio = (await db.execute(stmt)).scalars().first()

        if not servicio:
            raise HTTPException(
                status_code=404,
                detail=f"Servicio {servicio_id} no encontrado",
            )

        rutas_info = [
            RutaInfoResponse(
                id=ruta.id,
                nombre=ruta.nombre,
                tipo=ruta.tipo.value if ruta.tipo else "PRINCIPAL",
                hash_contenido=ruta.hash_contenido,
                empalmes_count=len(ruta.empalmes),
                activa=bool(ruta.activa),
                created_at=ruta.created_at.isoformat() if ruta.created_at else None,
                nombre_archivo_origen=ruta.nombre_archivo_origen,
            )
            for ruta in servicio.rutas
        ]

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
        return error_interno("get_servicio_rutas", exc, servicio_id=servicio_id)


@router.get("/api/infra/rutas/{ruta_id}/empalmes")
async def get_ruta_empalmes(
    ruta_id: int,
    db: AsyncSession = Depends(get_async_db),
) -> Dict[str, Any]:
    """Obtiene los empalmes de una ruta específica.
    
    Args:
        ruta_id: ID de la ruta
    
    Returns:
        Dict con información de la ruta y sus empalmes ordenados
    """
    try:
        stmt = (
            select(RutaServicio)
            .where(RutaServicio.id == ruta_id)
            .options(
                selectinload(RutaServicio.empalmes).selectinload(Empalme.camara),
                selectinload(RutaServicio.servicio),
            )
        )
        ruta = (await db.execute(stmt)).scalars().first()

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
        return error_interno("get_ruta_empalmes", exc, ruta_id=ruta_id)


@router.delete("/api/infra/servicios/{servicio_id}/empalmes")
async def delete_servicio_empalmes(
    servicio_id: str,
    db: AsyncSession = Depends(get_async_db),
) -> Dict[str, Any]:
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
        stmt = (
            select(Servicio)
            .where(Servicio.servicio_id == servicio_id)
            .options(
                selectinload(Servicio.empalmes),
                selectinload(Servicio.rutas).selectinload(RutaServicio.empalmes),
            )
        )
        servicio = (await db.execute(stmt)).scalars().first()

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
        servicio.empalmes = []

        # Eliminar rutas (cascade elimina ruta_empalme_association)
        for ruta in list(servicio.rutas):
            await db.delete(ruta)

        await db.commit()

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
        return error_interno("delete_servicio_empalmes", exc, servicio_id=servicio_id)


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

    def _do_ban() -> Dict[str, Any]:
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
                try:
                    from core.config import get_settings
                    from modules.slack_baneo_notifier.eventos import notificar_evento_baneo
                    datos_evento = result.to_dict()
                    datos_evento["servicio_afectado_id"] = request.servicio_afectado_id
                    datos_evento["servicio_protegido_id"] = request.servicio_protegido_id
                    datos_evento["ticket_asociado"] = request.ticket_asociado
                    datos_evento["usuario_ejecutor"] = request.usuario_ejecutor
                    datos_evento["motivo"] = request.motivo
                    notificar_evento_baneo(session, "create", datos_evento, get_settings().slack.bot_token)
                except Exception as slack_exc:
                    logger.warning("Error enviando aviso Slack de baneo creado: %s", slack_exc)
            else:
                session.rollback()
            return result.to_dict()

    try:
        return await asyncio.to_thread(_do_ban)
    except HTTPException:
        raise
    except Exception as exc:
        return error_interno("create_ban_endpoint", exc)


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

    def _do_lift() -> Dict[str, Any]:
        with SessionLocal() as session:
            result = do_lift_ban(
                session,
                request.incidente_id,
                usuario_ejecutor=request.usuario_ejecutor,
                motivo_cierre=request.motivo_cierre,
            )
            if result.success:
                session.commit()
                try:
                    from core.config import get_settings
                    from modules.slack_baneo_notifier.eventos import notificar_evento_baneo
                    datos_evento = result.to_dict()
                    datos_evento["usuario_ejecutor"] = request.usuario_ejecutor
                    datos_evento["motivo_cierre"] = request.motivo_cierre
                    notificar_evento_baneo(session, "lift", datos_evento, get_settings().slack.bot_token)
                except Exception as slack_exc:
                    logger.warning("Error enviando aviso Slack de baneo levantado: %s", slack_exc)
            else:
                session.rollback()
            return result.to_dict()

    try:
        return await asyncio.to_thread(_do_lift)
    except HTTPException:
        raise
    except Exception as exc:
        return error_interno("lift_ban_endpoint", exc)


@router.get("/api/infra/ban/active")
async def get_active_bans() -> Dict[str, Any]:
    """Obtiene todos los incidentes de baneo activos.
    
    Returns:
        Dict con lista de incidentes activos y conteo
    """
    from core.services.protection_service import get_incidentes_activos, ProtectionService

    def _get_bans() -> Dict[str, Any]:
        with SessionLocal() as session:
            incidentes = get_incidentes_activos(session)
            protection_svc = ProtectionService(session)

            incidentes_data = []
            for inc in incidentes:
                camaras = protection_svc.get_camaras_for_servicio(
                    inc.servicio_protegido_id, inc.ruta_protegida_id
                )
                camaras_count = len(camaras)

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

            return {"status": "ok", "total": len(incidentes_data), "incidentes": incidentes_data}

    try:
        return await asyncio.to_thread(_get_bans)
    except HTTPException:
        raise
    except Exception as exc:
        return error_interno("get_active_bans", exc)


@router.get("/api/infra/ban/{incidente_id}")
async def get_ban_detail(incidente_id: int) -> Dict[str, Any]:
    """Obtiene el detalle de un incidente de baneo con datos de correo y conteo de cámaras."""
    from core.services.protection_service import ProtectionService

    def _get_detail() -> Optional[Dict[str, Any]]:
        with SessionLocal() as session:
            service = ProtectionService(session)
            incidente = service.get_incidente_by_id(incidente_id)
            if not incidente:
                return None
            camaras = service.get_camaras_for_servicio(
                incidente.servicio_protegido_id,
                incidente.ruta_protegida_id,
            )
            return {
                "id": incidente.id,
                "ticket": incidente.ticket_asociado,
                "servicio_afectado": incidente.servicio_afectado_id,
                "servicio_protegido": incidente.servicio_protegido_id,
                "email_subject": incidente.email_subject,
                "email_body": incidente.email_body,
                "cantidad_camaras": len(camaras),
            }

    try:
        result = await asyncio.to_thread(_get_detail)
        if result is None:
            raise HTTPException(
                status_code=404,
                detail=f"Incidente {incidente_id} no encontrado",
            )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        return error_interno("get_ban_detail", exc, incidente_id=incidente_id)


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
    from core.services.protection_service import ProtectionService

    email_service = get_email_service()

    if not email_service.is_configured():
        return EmailNotifyResponse(
            success=False,
            message="Servicio de email no configurado",
            error="SMTP no está configurado en el servidor",
        )

    def _build_attachments() -> Optional[List[EmailAttachment]]:
        """Construye los adjuntos en un thread bloqueante."""
        attachments: List[EmailAttachment] = []

        with SessionLocal() as session:
            protection_svc = ProtectionService(session)
            incidentes = (
                session.query(IncidenteBaneo)
                .filter(IncidenteBaneo.id.in_(request.incidente_ids))
                .all()
            )

            if not incidentes:
                return None  # Señal de "no encontrado"

            if request.include_xls:
                try:
                    import pandas as pd

                    rows = []
                    for incidente in incidentes:
                        camaras = protection_svc.get_camaras_for_servicio(
                            incidente.servicio_protegido_id, incidente.ruta_protegida_id
                        )
                        for camara in camaras:
                            rows.append({
                                "Incidente ID": incidente.id,
                                "Ticket": incidente.ticket_asociado or "-",
                                "Servicio Afectado": incidente.servicio_afectado_id,
                                "Servicio Protegido": incidente.servicio_protegido_id,
                                "Cámara ID": camara.id,
                                "Cámara Nombre": camara.nombre,
                                "Estado": camara.estado.value if camara.estado else "-",
                                "Fecha Inicio": (
                                    incidente.fecha_inicio.astimezone(TZ_ARG).strftime("%d/%m/%Y %H:%M")
                                    if incidente.fecha_inicio else "-"
                                ),
                                "Motivo": incidente.motivo or "-",
                            })

                    if rows:
                        df = pd.DataFrame(rows)
                        output = io.BytesIO()
                        with pd.ExcelWriter(output, engine="openpyxl") as writer:
                            df.to_excel(writer, sheet_name="Baneos_Activos", index=False)
                        output.seek(0)
                        attachments.append(EmailAttachment(
                            filename="baneos_activos.xlsx",
                            content=output.getvalue(),
                            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        ))

                except ImportError:
                    logger.warning("action=notify_email warning=pandas_not_available skipping_xls=true")

            if request.include_txt:
                for incidente in incidentes:
                    servicio = (
                        session.query(Servicio)
                        .filter(Servicio.servicio_id == incidente.servicio_protegido_id)
                        .first()
                    )
                    if servicio and servicio.rutas:
                        for ruta in servicio.rutas:
                            if ruta.raw_file_content:
                                filename_txt = ruta.nombre_archivo_origen or f"tracking_{servicio.servicio_id}.txt"
                                attachments.append(EmailAttachment(
                                    filename=filename_txt,
                                    content=ruta.raw_file_content.encode("utf-8"),
                                    mime_type="text/plain; charset=utf-8",
                                ))
                                break

        return attachments

    try:
        attachments = await asyncio.to_thread(_build_attachments)

        if attachments is None:
            return EmailNotifyResponse(
                success=False,
                message="No se encontraron incidentes con los IDs especificados",
                error="incidente_ids vacíos o inválidos",
            )

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
        # Se conserva el 200 con success=False que consume la SPA (InfraTab); sólo cambia
        # el texto de `error`: ya no expone la excepción, lleva la ref del log.
        ref = nueva_ref()
        logger.exception("action=notify_email_error error=%s ref=%s", exc, ref)
        return EmailNotifyResponse(
            success=False,
            message="Error al enviar notificación",
            error=f"Error interno (ref {ref})",
        )


@router.get("/api/infra/tracking/{ruta_id}/download")
async def download_tracking_file(
    ruta_id: int,
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    """Descarga el archivo de tracking original de una ruta.

    IMPORTANTE: Devuelve el archivo TXT ORIGINAL tal como fue cargado,
    no una reconstrucción del JSON parseado.

    Args:
        ruta_id: ID de la ruta

    Returns:
        Archivo TXT original o error 404 si no está disponible
    """
    try:
        stmt = select(RutaServicio).where(RutaServicio.id == ruta_id)
        ruta = (await db.execute(stmt)).scalars().first()

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
        return error_interno("download_tracking", exc, ruta_id=ruta_id)


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


@router.post("/api/infra/notify/download-eml")
async def download_ban_eml(
    incident_id: int = Form(...),
    recipients: Optional[str] = Form(None),
    subject: Optional[str] = Form(None),
    html_body: Optional[str] = Form(None),
):
    """Genera y descarga un archivo .eml con el aviso de baneo y adjuntos."""
    from core.services.protection_service import ProtectionService
    from db.models.infra import Servicio, RutaServicio

    _incident_id = incident_id
    _recipients = recipients
    _subject = subject
    _html_body = html_body

    def _prepare():
        with SessionLocal() as session:
            protection_svc = ProtectionService(session)
            incidente = protection_svc.get_incidente_by_id(_incident_id)

            if not incidente:
                return None, None, None, None, None

            # 1.b Guardar ediciones de asunto/cuerpo si llegan en el formulario
            datos_actualizados = False
            if _subject is not None:
                incidente.email_subject = _subject
                datos_actualizados = True
            if _html_body is not None:
                incidente.email_body = _html_body
                datos_actualizados = True

            if datos_actualizados:
                session.commit()
                session.refresh(incidente)

            # 2. Recuperar las cámaras afectadas
            camaras = protection_svc.get_camaras_for_servicio(
                servicio_id=incidente.servicio_protegido_id,
                ruta_id=incidente.ruta_protegida_id,
            )

            # 2.b Buscar tracking original
            tracking_content = None
            tracking_filename = None
            servicio = (
                session.query(Servicio)
                .filter(Servicio.servicio_id == incidente.servicio_protegido_id)
                .first()
            )
            if servicio and servicio.rutas:
                ruta_candidates = []
                if incidente.ruta_protegida_id:
                    ruta_sel = session.query(RutaServicio).filter(
                        RutaServicio.id == incidente.ruta_protegida_id
                    ).first()
                    if ruta_sel:
                        ruta_candidates.append(ruta_sel)
                ruta_candidates.extend([r for r in servicio.rutas if r not in ruta_candidates])

                for ruta in ruta_candidates:
                    if ruta.raw_file_content:
                        tracking_content = ruta.raw_file_content.encode("utf-8", errors="ignore")
                        tracking_filename = ruta.nombre_archivo_origen or f"tracking_{ruta.id}.txt"
                        break

            return incidente, camaras, tracking_content, tracking_filename, None

    try:
        incidente, camaras, tracking_content, tracking_filename, _ = await asyncio.to_thread(_prepare)
    except Exception as exc:
        return error_interno("download_eml_datos", exc)

    if incidente is None:
        raise HTTPException(status_code=404, detail="Incidente no encontrado")

    # 3. Generar el EML (CPU-bound but short, OK in thread)
    email_svc = EmailService()
    try:
        eml_stream = email_svc.generate_ban_eml(
            incidente=incidente,
            camaras_afectadas=camaras,
            html_body=_html_body,
            subject=_subject,
            recipients=_recipients,
            tracking_content=tracking_content,
            tracking_filename=tracking_filename,
        )
    except Exception as exc:
        return error_interno("download_eml_generar", exc)

    filename = f"Aviso_Baneo_{incidente.ticket_asociado}.eml"
    return StreamingResponse(
        eml_stream,
        media_type="message/rfc822",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
        Archivo CSV o XLSX para descarga; sin pandas/openpyxl el XLSX sale como CSV con `X-Export-Warning`.

    Example:
        >>> GET /api/infra/export/cameras?filter_status=BANEADA&format=xlsx
    """

    def _export() -> tuple[bytes, str, str, dict[str, str]]:
        with SessionLocal() as session:
            rows = filas_exportacion(session, filter_status=filter_status, servicio_id=servicio_id)
        logger.info(
            "action=export_cameras filter_status=%s servicio=%s format=%s rows=%d",
            filter_status, servicio_id, format.value, len(rows),
        )
        cabeceras: dict[str, str] = {}
        if format == ExportFormat.XLSX:
            contenido = a_xlsx(rows)
            if contenido is not None:
                return (
                    contenido,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    nombre_archivo_exportacion("xlsx"),
                    cabeceras,
                )
            logger.warning("action=export_cameras warning=pandas_not_available fallback=csv")
            cabeceras["X-Export-Warning"] = AVISO_SIN_XLSX
        return a_csv(rows), "text/csv; charset=utf-8", nombre_archivo_exportacion("csv"), cabeceras

    try:
        contenido, media_type, nombre, cabeceras = await asyncio.to_thread(_export)
    except HTTPException:
        raise
    except Exception as exc:
        return error_interno("export_cameras", exc)

    return Response(
        content=contenido,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{nombre}"', **cabeceras},
    )
