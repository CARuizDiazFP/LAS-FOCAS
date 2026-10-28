# Nombre de archivo: infra.py
# Ubicación de archivo: api/app/routes/infra.py
# Descripción: Endpoints para sincronizar cámaras, procesar trackings y gestionar rutas de fibra óptica

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.services.baneo_operaciones import (
    LARGO_MOTIVO,
    LARGO_SERVICIO,
    LARGO_TICKET,
    LARGO_USUARIO,
    crear_baneo_y_notificar,
    levantar_baneo_y_notificar,
    listar_incidentes_activos,
)
from core.services.baneo_aviso import (
    EmailNotifyResultado,
    armar_eml_baneo,
    enviar_aviso_baneo,
    estado_config_email,
    guardar_plantilla_aviso,
    parsear_destinatarios,
)
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
    ResolveAction,
    ResolveResult,
    analyze_tracking_file,
    resolve_tracking_file,
)
from core.services.tracking_operaciones import (
    MAX_TRACKING_MB,
    ResultadoUploadTracking,
    TrackingOriginal,
    TrackingOriginalNoDisponible,
    TrackingSinServicioId,
    TrackingSinUbicaciones,
    decodificar_tracking,
    obtener_tracking_original,
    procesar_tracking_legacy,
    serializar_analisis,
)
from db.models.infra import (
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


async def _leer_tracking(file: UploadFile) -> str:
    """Lee el upload con tope de `MAX_TRACKING_MB` (413 si lo supera) y lo decodifica."""
    limite = MAX_TRACKING_MB * 1024 * 1024
    contenido = await file.read(limite + 1)
    if len(contenido) > limite:
        logger.warning("action=upload_rechazado reason=tamano archivo=%s limite=%s", file.filename, limite)
        raise HTTPException(
            status_code=413,
            detail=f"{Path(file.filename or 'El archivo').name} supera el límite de {MAX_TRACKING_MB} MB",
        )
    return decodificar_tracking(contenido)


@router.post("/api/infra/upload_tracking", response_model=TrackingUploadResponse)
async def upload_tracking(file: UploadFile = File(...)) -> TrackingUploadResponse:
    """Procesa un archivo de tracking de fibra óptica y puebla la base de datos.

    Delega en `core.services.tracking_operaciones.procesar_tracking_legacy`: parsea el archivo,
    crea o actualiza el servicio y registra cada empalme contra el inventario real (Cromo Red es la
    fuente de verdad: una ubicación sin match no crea cámara, queda en `IngresoSinMatch` con
    `origen="tracking"` y el empalme sin `camara_id`).

    Args:
        file: Archivo .txt con el tracking de fibra óptica (máximo `MAX_TRACKING_MB`).

    Returns:
        Resumen del procesamiento con conteos de elementos procesados.

    Raises:
        HTTPException 400: Si el archivo no tiene extensión .txt o no contiene datos válidos.
        HTTPException 413: Si el archivo supera el tope.
        HTTPException 500: Si ocurre un error durante el procesamiento.
    """

    # Validar extensión del archivo
    if not file.filename or not file.filename.lower().endswith(".txt"):
        raise HTTPException(
            status_code=400,
            detail="El archivo debe tener extensión .txt",
        )

    filename = file.filename

    def _procesar(raw_text: str) -> ResultadoUploadTracking:
        with SessionLocal() as session:
            return procesar_tracking_legacy(session, raw_text, filename)

    try:
        raw_text = await _leer_tracking(file)
        resultado = await asyncio.to_thread(_procesar, raw_text)
    except TrackingSinServicioId:
        raise HTTPException(
            status_code=400,
            detail=f"No se pudo extraer el ID del servicio desde el nombre del archivo: {filename}",
        )
    except TrackingSinUbicaciones:
        raise HTTPException(
            status_code=400,
            detail="No se encontraron empalmes/ubicaciones en el archivo",
        )
    except HTTPException:
        raise
    except Exception as exc:
        return error_interno("upload_tracking", exc, filename=filename)

    return TrackingUploadResponse(
        status="ok",
        servicios_procesados=1,
        servicio_id=resultado.servicio_id,
        camaras_nuevas=0,
        camaras_existentes=resultado.camaras_existentes,
        empalmes_registrados=resultado.empalmes_registrados,
        ubicaciones_sin_match=resultado.ubicaciones_sin_match,
        mensaje=f"Tracking del servicio {resultado.servicio_id} procesado correctamente",
    )


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
        raw_content = await _leer_tracking(file)
        filename_used = file.filename or "unknown.txt"
    elif content:
        raw_content = content
        filename_used = filename or "unknown.txt"
    else:
        raise HTTPException(
            status_code=400,
            detail="Debe enviar un archivo (file) o contenido (content + filename)",
        )

    def _analyze() -> dict[str, Any]:
        with SessionLocal() as session:
            return serializar_analisis(analyze_tracking_file(session, raw_content, filename_used))

    try:
        # Las claves que `TrackingAnalyzeResponse` no declara (sugerencias del panel) se descartan
        # solas; `UpgradeInfoResponse` ignora los `terminal_*` extra.
        return TrackingAnalyzeResponse(**await asyncio.to_thread(_analyze))
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
    
    ticket_asociado: Optional[str] = Field(None, max_length=LARGO_TICKET, description="ID del ticket de soporte")
    servicio_afectado_id: str = Field(..., max_length=LARGO_SERVICIO, description="ID del servicio que sufrió el corte")
    servicio_protegido_id: str = Field(..., max_length=LARGO_SERVICIO, description="ID del servicio a proteger (banear)")
    ruta_protegida_id: Optional[int] = Field(None, description="ID de ruta específica (opcional)")
    usuario_ejecutor: Optional[str] = Field(None, max_length=LARGO_USUARIO, description="Usuario que ejecuta el baneo")
    motivo: Optional[str] = Field(None, max_length=LARGO_MOTIVO, description="Motivo del baneo")

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
    usuario_ejecutor: Optional[str] = Field(None, max_length=LARGO_USUARIO, description="Usuario que levanta el baneo")
    motivo_cierre: Optional[str] = Field(None, max_length=LARGO_MOTIVO, description="Motivo del cierre")

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
    def _do_ban() -> Dict[str, Any]:
        with SessionLocal() as session:
            return crear_baneo_y_notificar(
                session,
                ticket_asociado=request.ticket_asociado,
                servicio_afectado_id=request.servicio_afectado_id,
                servicio_protegido_id=request.servicio_protegido_id,
                ruta_protegida_id=request.ruta_protegida_id,
                motivo=request.motivo,
                usuario_ejecutor=request.usuario_ejecutor,
            ).to_dict()

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
    def _do_lift() -> Dict[str, Any]:
        with SessionLocal() as session:
            return levantar_baneo_y_notificar(
                session,
                request.incidente_id,
                usuario_ejecutor=request.usuario_ejecutor,
                motivo_cierre=request.motivo_cierre,
            ).to_dict()

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
    def _get_bans() -> Dict[str, Any]:
        with SessionLocal() as session:
            return listar_incidentes_activos(session)

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
    def _enviar() -> EmailNotifyResultado:
        """Adjuntos y SMTP en un thread: ni la DB ni el envío (hasta 15 s) bloquean el event loop (B3)."""
        with SessionLocal() as session:
            return enviar_aviso_baneo(
                session,
                to=request.to,
                cc=request.cc,
                subject=request.subject,
                body=request.body,
                incidente_ids=request.incidente_ids,
                include_xls=request.include_xls,
                include_txt=request.include_txt,
            )

    try:
        resultado = await asyncio.to_thread(_enviar)
        return EmailNotifyResponse(**asdict(resultado))

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
async def download_tracking_file(ruta_id: int) -> Response:
    """Descarga el archivo de tracking original de una ruta.

    IMPORTANTE: Devuelve el archivo TXT ORIGINAL tal como fue cargado,
    no una reconstrucción del JSON parseado.

    Args:
        ruta_id: ID de la ruta

    Returns:
        Archivo TXT original o error 404 si no está disponible
    """

    def _leer() -> TrackingOriginal | None:
        with SessionLocal() as session:
            return obtener_tracking_original(session, ruta_id)

    try:
        original = await asyncio.to_thread(_leer)
    except TrackingOriginalNoDisponible:
        raise HTTPException(
            status_code=404,
            detail="Archivo original no disponible para esta ruta. "
            "Solo las rutas creadas después de la actualización del sistema "
            "tienen el archivo original guardado.",
        )
    except Exception as exc:
        return error_interno("download_tracking", exc, ruta_id=ruta_id)

    if original is None:
        raise HTTPException(status_code=404, detail=f"Ruta {ruta_id} no encontrada")

    return Response(
        content=original.contenido.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{original.filename}"'},
    )


@router.get("/api/infra/notify/email/config")
async def get_email_config_status() -> Dict[str, Any]:
    """Verifica si el servicio de email está configurado.

    Returns:
        Estado de configuración del servicio de email; ante un error interno 200 con
        `configured: false` y la ref del log (misma forma que el panel).
    """
    try:
        return estado_config_email()
    except Exception as exc:
        ref = nueva_ref()
        logger.exception("action=get_email_config_error error=%s ref=%s", exc, ref)
        return {"configured": False, "error": f"Error interno (ref {ref})"}


@router.post("/api/infra/notify/download-eml")
async def download_ban_eml(
    incident_id: int = Form(...),
    recipients: Optional[str] = Form(None),
    subject: Optional[str] = Form(None),
    html_body: Optional[str] = Form(None),
):
    """Genera y descarga un archivo .eml con el aviso de baneo y adjuntos."""

    def _armar():
        with SessionLocal() as session:
            eml = armar_eml_baneo(
                session,
                incident_id,
                destinatarios=parsear_destinatarios(recipients),
                subject=subject,
                html_body=html_body,
            )
            # Guarda las ediciones de asunto/cuerpo que llegan en el formulario
            if eml is not None and (subject is not None or html_body is not None):
                guardar_plantilla_aviso(session, incident_id, subject, html_body)
            return eml

    try:
        eml = await asyncio.to_thread(_armar)
    except Exception as exc:
        return error_interno("download_eml_generar", exc)

    if eml is None:
        raise HTTPException(status_code=404, detail="Incidente no encontrado")

    return Response(
        content=eml.contenido,
        media_type="message/rfc822",
        headers={"Content-Disposition": f'attachment; filename="{eml.nombre_archivo}"'},
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
