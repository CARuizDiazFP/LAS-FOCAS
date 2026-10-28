# Nombre de archivo: servicios.py
# Ubicación de archivo: api/app/routes/servicios.py
# Descripción: Endpoints de ingesta y búsqueda paginada para módulo de servicios

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.services.prov.client import ProvClientError, ProvServicioNoEncontradoError, get_prov_client
from core.services.prov.config import ProvConfigError
from core.services.prov.ingesta import ingerir_contexto_prov
from core.services.clientes_categoria_hooks import sincronizar_clientes_post_ingesta
from core.services.clientes_categoria_service import (
    bloquear_categorias_clientes,
    normalizar_clave_cliente,
    sincronizar_categorias,
)
from core.services.servicios_categoria_service import (
    CategoriaInvalidaError,
    actualizar_categoria_masiva,
    validar_categoria,
)
from core.services.servicios_ingesta_service import (
    ArchivoIlegible,
    FormatoNoSoportado,
    ResultadoIngesta,
    ingerir_servicios,
)
from core.sla_consumo.clasificador import GRUPO_CLIENTE
from core.sla_consumo.engine import presupuesto_horas
from db.models.infra import Servicio, ServicioEquipoUltimaMilla, ServicioHistorialId
from db.models.reclamo import Reclamo
from db.models.sla_consumo import ServicioSlaSnapshot
from db.session import AsyncSessionLocal, SessionLocal, get_async_db


router = APIRouter(prefix="/servicios", tags=["servicios"])
logger = logging.getLogger(__name__)


class ReclamoServicioResponse(BaseModel):
    numero_reclamo: str
    numero_evento: str | None = None
    numero_linea: str
    fecha_inicio: datetime | None = None
    fecha_cierre: datetime | None = None
    tipo_solucion: str | None = None
    grupo_cierre: str | None = None
    codigo_cierre: int | None = None
    horas_netas: float | None = None
    cuenta_sla: bool = True
    pct_presupuesto: float | None = None
    carrier: str | None = None
    descripcion_solucion: str | None = None


class SlaSnapshotResponse(BaseModel):
    numero_linea: str
    fecha_corte: date
    sla_prometido: float | None = None
    sla_entregado: float | None = None
    horas_reclamos_todos: float | None = None
    horas_restantes: float | None = None
    cantidad_reclamos_todos: int | None = None


class ServicioItemResponse(BaseModel):
    id: int
    numero_primer_servicio: str
    nombre_cliente: str | None = None
    numero_linea: str | None = None
    tipo_servicio: str | None = None
    sla_prometido: str | None = None
    direccion: str | None = None
    localidad: str | None = None
    provincia: str | None = None
    direccion_2: str | None = None
    estado_servicio: str
    categoria: int | None = None
    # True = categoría fijada a mano en el servicio: la propagación desde el cliente no la pisa.
    categoria_excepcion: bool = False
    origen_datos: str
    es_verificable: bool
    es_verificable_override: bool | None = None
    alias_ids: list[str] = []
    reclamos: list[ReclamoServicioResponse] | None = None


class ServicioHistorialIdItemResponse(BaseModel):
    numero_id: str
    orden: int
    fecha_instalacion: date | None = None
    fecha_baja: date | None = None
    estado_comercial: str | None = None
    motivo_baja: str | None = None
    es_vigente: bool


class ServicioEquipoUltimaMillaItemResponse(BaseModel):
    extremo: int
    nodo: str | None = None
    equipo: str | None = None
    puerto: str | None = None
    direccion: str | None = None
    provincia: str | None = None


class SearchServiciosResponse(BaseModel):
    status: str = "ok"
    total: int
    limit: int
    offset: int
    servicios: list[ServicioItemResponse]


class ServicioDetailResponse(BaseModel):
    status: str = "ok"
    id_consultado: str
    id_origen: str
    servicio: ServicioItemResponse
    historial_ids: list[ServicioHistorialIdItemResponse] = []
    equipos_ultima_milla: list[ServicioEquipoUltimaMillaItemResponse] = []
    sla_historico: list[SlaSnapshotResponse] = []


class IngestServiciosResponse(BaseModel):
    status: str = "ok"
    rows_ok: int
    rows_bad: int
    inserted: int
    updated: int
    unchanged: int
    # Resumen de la sincronización de categorías de los clientes del archivo (`ResumenSync`).
    # `None` si el archivo no trae clientes o si la sync falló (la ingesta igual queda guardada; ver
    # `action=clientes_sync_error` en el log y "Re-sincronizar" en el módulo de clientes).
    clientes_sync: dict[str, int] | None = None
    # True si la sync de clientes falló (distingue "falló" de "el archivo no trae clientes").
    clientes_sync_error: bool = False


def _to_servicio_item(svc: Servicio) -> ServicioItemResponse | None:
    numero_origen = (svc.numero_primer_servicio or svc.servicio_id or "").strip()
    if not numero_origen:
        return None

    return ServicioItemResponse(
        id=svc.id,
        numero_primer_servicio=numero_origen,
        nombre_cliente=svc.nombre_cliente,
        numero_linea=svc.numero_linea,
        tipo_servicio=svc.tipo_servicio,
        sla_prometido=svc.sla_prometido,
        direccion=svc.direccion,
        localidad=svc.localidad,
        provincia=svc.provincia,
        direccion_2=svc.direccion_2,
        estado_servicio=svc.estado_servicio,
        categoria=svc.categoria,
        categoria_excepcion=svc.categoria_excepcion is True,
        origen_datos=svc.origen_datos.value if hasattr(svc.origen_datos, "value") else str(svc.origen_datos),
        es_verificable=svc.es_verificable,
        es_verificable_override=svc.es_verificable_override,
        alias_ids=list(svc.alias_ids or []),
        reclamos=None,
    )


def _historial_a_response(historial: list[ServicioHistorialId]) -> list[ServicioHistorialIdItemResponse]:
    return [
        ServicioHistorialIdItemResponse(
            numero_id=item.numero_id,
            orden=item.orden,
            fecha_instalacion=item.fecha_instalacion,
            fecha_baja=item.fecha_baja,
            estado_comercial=item.estado_comercial,
            motivo_baja=item.motivo_baja,
            es_vigente=item.es_vigente,
        )
        for item in sorted(historial, key=lambda item: item.orden)
    ]


def _equipos_a_response(equipos: list[ServicioEquipoUltimaMilla]) -> list[ServicioEquipoUltimaMillaItemResponse]:
    return [
        ServicioEquipoUltimaMillaItemResponse(
            extremo=item.extremo,
            nodo=item.nodo,
            equipo=item.equipo,
            puerto=item.puerto,
            direccion=item.direccion,
            provincia=item.provincia,
        )
        for item in sorted(equipos, key=lambda item: item.extremo)
    ]


async def _buscar_servicio_por_id(db: AsyncSession, id_consultado: str) -> Servicio:
    stmt = (
        select(Servicio)
        .options(selectinload(Servicio.historial_ids), selectinload(Servicio.equipos_ultima_milla))
        .where(
            or_(
                Servicio.numero_primer_servicio == id_consultado,
                Servicio.numero_linea == id_consultado,
                Servicio.servicio_id == id_consultado,
            )
        )
        .order_by(Servicio.id.desc())
        .limit(1)
    )
    svc = (await db.execute(stmt)).scalars().first()
    if svc is None:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    return svc


@router.post("/ingest", response_model=IngestServiciosResponse)
async def ingest_servicios(
    file: UploadFile = File(..., description="Archivo XLSX/CSV con servicios SLA"),
) -> IngestServiciosResponse:
    """Ingesta de la planilla SLA. Lectura, consolidación, upsert y fusión de placeholders corren en
    un thread aparte (`core/services/servicios_ingesta_service.py`, B11 de P12): pandas/openpyxl y
    los loops de consolidación son CPU puro y bloqueaban el event loop."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Falta nombre de archivo")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Archivo vacio")

    filename = file.filename

    def _run() -> ResultadoIngesta:
        with SessionLocal() as session:
            return ingerir_servicios(session, filename, content)

    try:
        resultado = await asyncio.to_thread(_run)
    except FormatoNoSoportado as exc:
        raise HTTPException(status_code=415, detail="Formato no soportado (use .xlsx o .csv)") from exc
    except ArchivoIlegible as exc:
        raise HTTPException(status_code=400, detail="No se pudo leer el archivo") from exc

    respuesta = IngestServiciosResponse(
        rows_ok=resultado.rows_ok,
        rows_bad=resultado.rows_bad,
        inserted=resultado.inserted,
        updated=resultado.updated,
        unchanged=resultado.unchanged,
    )
    if not resultado.nombres_tocados:
        # Sin filas ingeridas (el archivo no trajo ninguna válida): no hay clientes que sincronizar.
        return respuesta

    # Categoría por cliente: sólo los clientes de este archivo (nombre nuevo y, si la planilla
    # renombró un servicio, también el anterior). Nunca tumba la ingesta ya commiteada.
    resultado_sync = await sincronizar_clientes_post_ingesta(resultado.nombres_tocados, origen="ingest_excel")
    respuesta.clientes_sync = resultado_sync.resumen
    respuesta.clientes_sync_error = resultado_sync.error
    return respuesta


@router.get("/search", response_model=SearchServiciosResponse)
async def search_servicios(
    q: str | None = Query(None, description="Búsqueda multipropósito"),
    numero_primer_servicio: str | None = Query(None),
    cliente: str | None = Query(None),
    domicilio: str | None = Query(None),
    tipo: str | None = Query(None),
    estado: str | None = Query(None),
    categoria: str | None = Query(
        None, description="Categorías separadas por coma, ej. '6' o '0,3,5'; `sin` = sin categorizar"
    ),
    limit: int = Query(default=30, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_async_db),
) -> SearchServiciosResponse:
    filters = []

    if q and q.strip():
        like = f"%{q.strip()}%"
        filters.append(
            or_(
                Servicio.numero_primer_servicio.ilike(like),
                Servicio.nombre_cliente.ilike(like),
                Servicio.numero_linea.ilike(like),
                Servicio.tipo_servicio.ilike(like),
                Servicio.direccion.ilike(like),
                Servicio.localidad.ilike(like),
                Servicio.provincia.ilike(like),
                Servicio.estado_servicio.ilike(like),
            )
        )

    if numero_primer_servicio and numero_primer_servicio.strip():
        filters.append(Servicio.numero_primer_servicio.ilike(f"%{numero_primer_servicio.strip()}%"))
    if cliente and cliente.strip():
        filters.append(Servicio.nombre_cliente.ilike(f"%{cliente.strip()}%"))
    if domicilio and domicilio.strip():
        filters.append(
            or_(
                Servicio.direccion.ilike(f"%{domicilio.strip()}%"),
                Servicio.direccion_2.ilike(f"%{domicilio.strip()}%"),
                Servicio.localidad.ilike(f"%{domicilio.strip()}%"),
                Servicio.provincia.ilike(f"%{domicilio.strip()}%"),
            )
        )
    if tipo and tipo.strip():
        filters.append(Servicio.tipo_servicio.ilike(f"%{tipo.strip()}%"))
    if estado and estado.strip():
        filters.append(Servicio.estado_servicio.ilike(f"%{estado.strip()}%"))
    if categoria and categoria.strip():
        # Tokens separados por coma: números 0-6 y/o `sin` (= sin categorizar, `categoria IS NULL`).
        tokens = [valor.strip().lower() for valor in categoria.split(",") if valor.strip()]
        incluir_sin = "sin" in tokens
        try:
            categorias = [int(token) for token in tokens if token != "sin"]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="categoria inválida") from exc
        condiciones = []
        if incluir_sin:
            condiciones.append(Servicio.categoria.is_(None))
        if categorias:
            condiciones.append(Servicio.categoria.in_(categorias))
        if condiciones:
            filters.append(or_(*condiciones))

    where_clause = and_(*filters) if filters else None

    count_stmt = select(func.count(Servicio.id))
    if where_clause is not None:
        count_stmt = count_stmt.where(where_clause)
    total = int((await db.execute(count_stmt)).scalar_one())

    data_stmt = select(Servicio).order_by(Servicio.id.desc()).limit(limit).offset(offset)
    if where_clause is not None:
        data_stmt = data_stmt.where(where_clause)

    servicios = (await db.execute(data_stmt)).scalars().all()

    items = [item for item in (_to_servicio_item(svc) for svc in servicios) if item is not None]

    return SearchServiciosResponse(total=total, limit=limit, offset=offset, servicios=items)


def _lineas_del_servicio(svc: Servicio) -> list[str]:
    candidatas = {svc.numero_linea, svc.numero_primer_servicio, svc.servicio_id, *(svc.alias_ids or [])}
    return sorted(c.strip() for c in candidatas if c and c.strip())


def _parse_sla_prometido(valor: str | None) -> float | None:
    """Tolera "99,7", "99.7%", "" y basura: devuelve None si no hay un número utilizable."""
    if not valor:
        return None
    limpio = valor.strip().replace("%", "").replace(",", ".").strip()
    if not re.fullmatch(r"\d+(\.\d+)?", limpio):
        return None
    return float(limpio)


def _float_o_none(v: Any) -> float | None:
    return float(v) if v is not None else None


async def _reclamos_del_servicio(db: AsyncSession, svc: Servicio) -> list[ReclamoServicioResponse]:
    lineas = _lineas_del_servicio(svc)
    if not lineas:
        return []
    desde = datetime.now().astimezone() - timedelta(days=365)
    filas = (
        await db.execute(
            select(Reclamo)
            .where(
                or_(Reclamo.numero_linea.in_(lineas), Reclamo.numero_primer_servicio.in_(lineas)),
                Reclamo.fecha_inicio >= desde,
            )
            .order_by(Reclamo.fecha_inicio.desc())
        )
    ).scalars().all()
    presupuesto = presupuesto_horas(_parse_sla_prometido(svc.sla_prometido))
    salida: list[ReclamoServicioResponse] = []
    for r in filas:
        horas = _float_o_none(r.horas_netas)
        cuenta = r.grupo_cierre != GRUPO_CLIENTE
        pct = (horas / presupuesto * 100) if (horas is not None and presupuesto and cuenta) else None
        salida.append(
            ReclamoServicioResponse(
                numero_reclamo=r.numero_reclamo, numero_evento=r.numero_evento, numero_linea=r.numero_linea,
                fecha_inicio=r.fecha_inicio, fecha_cierre=r.fecha_cierre, tipo_solucion=r.tipo_solucion,
                grupo_cierre=r.grupo_cierre, codigo_cierre=r.codigo_cierre, horas_netas=horas, cuenta_sla=cuenta,
                pct_presupuesto=pct, carrier=r.carrier, descripcion_solucion=r.descripcion_solucion,
            )
        )
    return salida


async def _sla_historico(db: AsyncSession, svc: Servicio) -> list[SlaSnapshotResponse]:
    lineas = _lineas_del_servicio(svc)
    if not lineas:
        return []
    filas = (
        await db.execute(
            select(ServicioSlaSnapshot)
            .where(ServicioSlaSnapshot.numero_linea.in_(lineas))
            .order_by(ServicioSlaSnapshot.fecha_corte, ServicioSlaSnapshot.numero_linea)
        )
    ).scalars().all()
    return [
        SlaSnapshotResponse(
            numero_linea=f.numero_linea, fecha_corte=f.fecha_corte, sla_prometido=_float_o_none(f.sla_prometido),
            sla_entregado=_float_o_none(f.sla_entregado),
            horas_reclamos_todos=_float_o_none(f.horas_reclamos_todos),
            horas_restantes=_float_o_none(f.horas_restantes),
            cantidad_reclamos_todos=f.cantidad_reclamos_todos,
        )
        for f in filas
    ]


@router.get("/detail", response_model=ServicioDetailResponse)
async def detail_servicio(
    id: str = Query(..., description="ID de consulta (origen o línea actual)"),
    db: AsyncSession = Depends(get_async_db),
) -> ServicioDetailResponse:
    id_consultado = id.strip()
    if not id_consultado:
        raise HTTPException(status_code=400, detail="ID requerido")

    svc = await _buscar_servicio_por_id(db, id_consultado)

    item = _to_servicio_item(svc)
    if item is None:
        raise HTTPException(status_code=404, detail="Servicio sin ID origen")

    item.reclamos = await _reclamos_del_servicio(db, svc)

    return ServicioDetailResponse(
        id_consultado=id_consultado,
        id_origen=item.numero_primer_servicio,
        servicio=item,
        historial_ids=_historial_a_response(svc.historial_ids),
        equipos_ultima_milla=_equipos_a_response(svc.equipos_ultima_milla),
        sla_historico=await _sla_historico(db, svc),
    )


# 2 intentos totales (1 reintento) en vez de los 4 del default (`_REINTENTOS_MAX=3`): esta es una
# llamada interactiva disparada por un click de usuario, no el backfill masivo — ~127s de peor caso
# es demasiado para alguien esperando frente al navegador. Peor caso con este límite: ~61s (2 ×
# timeout 30s del cliente + 1s de backoff). Ver docs/decisiones.md.
_PROV_REFRESCAR_MAX_REINTENTOS = 1


@router.post("/prov/refrescar", response_model=ServicioDetailResponse)
async def refrescar_servicio_desde_prov(
    id: str = Query(..., description="ID de consulta (origen o línea actual)"),
) -> ServicioDetailResponse:
    """No usa `Depends(get_async_db)`: a diferencia del resto de este router, esta ruta hace una
    llamada de red de duración variable (hasta ~61s con `_PROV_REFRESCAR_MAX_REINTENTOS`) a mitad
    del handler. Abre dos sesiones cortas -antes y después de la llamada a PROV- para no retener
    una conexión del pool ociosa mientras se espera la respuesta (limitación conocida encontrada
    en la revisión final de esta integración, ver docs/decisiones.md).

    Edge case aceptado: si la fila se borra entre la primera y la segunda sesión, esta ruta
    responde 404 pese a que la consulta a PROV fue exitosa — carrera ya latente hoy (nadie bloquea
    la fila), no algo nuevo que este cambio deba resolver.
    """
    id_consultado = id.strip()
    if not id_consultado:
        raise HTTPException(status_code=400, detail="ID requerido")

    async with AsyncSessionLocal() as db_lookup:
        svc = await _buscar_servicio_por_id(db_lookup, id_consultado)
        numero_prov = svc.numero_primer_servicio or svc.servicio_id

    try:
        # `get_prov_client()` construye la config al primer uso y levanta `ProvConfigError` si
        # faltan `PROV_BASE_URL`/los secrets — el estado esperado hoy en producción, que todavía no
        # tiene los secrets de PROV desplegados (ver docs/decisiones.md). Se responde 503 (servicio
        # no disponible en este entorno) en vez de dejarlo escapar como un 500 sin explicación.
        cliente = get_prov_client()
        contexto = await cliente.obtener_contexto_servicio(
            numero_prov, max_reintentos=_PROV_REFRESCAR_MAX_REINTENTOS
        )
    except ProvConfigError as exc:
        logger.warning("action=servicios_prov_refrescar evento=prov_no_configurado id=%s error=%s", id_consultado, exc)
        raise HTTPException(status_code=503, detail="PROV no está configurado en este entorno") from exc
    except ProvServicioNoEncontradoError as exc:
        logger.warning("action=servicios_prov_refrescar evento=no_encontrado id=%s", id_consultado)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProvClientError as exc:
        logger.error("action=servicios_prov_refrescar evento=error_cliente id=%s error=%s", id_consultado, exc)
        raise HTTPException(status_code=502, detail="No se pudo consultar PROV") from exc

    async with AsyncSessionLocal() as db_write:
        svc = await _buscar_servicio_por_id(db_write, id_consultado)
        nombre_anterior = svc.nombre_cliente
        await ingerir_contexto_prov(db_write, svc, contexto)
        nombre_nuevo = svc.nombre_cliente
        await db_write.commit()
        # Categoría por cliente: el (posible) cliente nuevo que trajo PROV y el anterior si PROV lo
        # renombró. Corre en su propia sesión y nunca tumba el refresco ya commiteado; por eso se
        # refresca también `categoria`, que la sync puede haber reescrito.
        await sincronizar_clientes_post_ingesta([nombre_anterior, nombre_nuevo], origen="prov_refrescar")
        await db_write.refresh(svc, attribute_names=["historial_ids", "equipos_ultima_milla", "categoria"])

        item = _to_servicio_item(svc)
        if item is None:
            raise HTTPException(status_code=404, detail="Servicio sin ID origen")

        item.reclamos = await _reclamos_del_servicio(db_write, svc)

        return ServicioDetailResponse(
            id_consultado=id_consultado,
            id_origen=item.numero_primer_servicio,
            servicio=item,
            historial_ids=_historial_a_response(svc.historial_ids),
            equipos_ultima_milla=_equipos_a_response(svc.equipos_ultima_milla),
            sla_historico=await _sla_historico(db_write, svc),
        )


class ServicioCategoriaUpdateRequest(BaseModel):
    categoria: int


class ServiciosCategoriaMasivaRequest(BaseModel):
    servicio_ids: list[int]
    categoria: int


class ServiciosCategoriaMasivaResponse(BaseModel):
    status: str = "ok"
    categoria_nueva: int
    actualizados: int
    no_encontrados: list[int]


@router.patch("/bulk-categoria", response_model=ServiciosCategoriaMasivaResponse)
async def actualizar_categoria_servicios_masivo(
    body: ServiciosCategoriaMasivaRequest,
) -> ServiciosCategoriaMasivaResponse:
    """Cambia la categoría de un lote de Servicios. Usa `SessionLocal` (sync) en un thread aparte
    — mismo patrón que `api/app/routes/infra.py` para servicios que reusan una capa sync existente
    dentro de un endpoint async (`asyncio.to_thread`, no bloquea el event loop)."""

    def _actualizar() -> Any:
        with SessionLocal() as session:
            resultado = actualizar_categoria_masiva(session, body.servicio_ids, body.categoria)
            session.commit()
            return resultado

    try:
        resultado = await asyncio.to_thread(_actualizar)
    except CategoriaInvalidaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ServiciosCategoriaMasivaResponse(**resultado.to_dict())


@router.patch("/{id}/categoria", response_model=ServicioItemResponse)
async def actualizar_categoria_servicio(
    id: int,
    body: ServicioCategoriaUpdateRequest,
    db: AsyncSession = Depends(get_async_db),
) -> ServicioItemResponse:
    try:
        validar_categoria(body.categoria)
    except CategoriaInvalidaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    svc = await db.get(Servicio, id)
    if svc is None:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")

    svc.categoria = body.categoria
    svc.categoria_excepcion = True  # fijada a mano: la propagación desde el cliente no la pisa
    await db.commit()
    await db.refresh(svc)

    item = _to_servicio_item(svc)
    if item is None:
        raise HTTPException(status_code=404, detail="Servicio sin ID origen")
    return item


@router.patch("/{id}/categoria/heredar", response_model=ServicioItemResponse)
async def heredar_categoria_servicio(id: int) -> ServicioItemResponse:
    """Quita la excepción de categoría del servicio y re-sincroniza su cliente, así vuelve a
    heredar la categoría del cliente. Sync en un thread aparte (mismo patrón que `bulk-categoria`).

    Un servicio sin cliente (`nombre_cliente` vacío) no tiene de quién heredar → 409, y la
    excepción queda como estaba."""

    def _heredar() -> tuple[int, ServicioItemResponse | None]:
        with SessionLocal() as session:
            bloquear_categorias_clientes(session)
            svc = session.get(Servicio, id)
            if svc is None:
                return 404, None
            clave = normalizar_clave_cliente(svc.nombre_cliente)
            if clave is None:
                return 409, None
            svc.categoria_excepcion = False
            session.flush()
            sincronizar_categorias(session, {clave})
            session.commit()
            session.refresh(svc)
            return 200, _to_servicio_item(svc)

    estado, item = await asyncio.to_thread(_heredar)
    if estado == 404:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    if estado == 409:
        raise HTTPException(status_code=409, detail="El servicio no tiene cliente: sin cliente para heredar")
    if item is None:
        raise HTTPException(status_code=404, detail="Servicio sin ID origen")
    return item


class ServicioVerificableUpdateRequest(BaseModel):
    es_verificable: bool


@router.patch("/{id}/verificable", response_model=ServicioItemResponse)
async def actualizar_verificable_servicio(
    id: int,
    body: ServicioVerificableUpdateRequest,
    db: AsyncSession = Depends(get_async_db),
) -> ServicioItemResponse:
    svc = await db.get(Servicio, id)
    if svc is None:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")

    svc.es_verificable_override = body.es_verificable
    svc.es_verificable = body.es_verificable
    await db.commit()
    await db.refresh(svc)

    item = _to_servicio_item(svc)
    if item is None:
        raise HTTPException(status_code=404, detail="Servicio sin ID origen")
    return item
