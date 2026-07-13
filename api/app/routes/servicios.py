# Nombre de archivo: servicios.py
# Ubicación de archivo: api/app/routes/servicios.py
# Descripción: Endpoints de ingesta y búsqueda paginada para módulo de servicios

from __future__ import annotations

import io
import logging
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.parsers.servicios_excel import parse_servicios_df
from db.models.infra import Servicio
from db.session import get_async_db


router = APIRouter(prefix="/servicios", tags=["servicios"])
logger = logging.getLogger(__name__)


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
    reclamos: list[dict[str, Any]] | None = None


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


class IngestServiciosResponse(BaseModel):
    status: str = "ok"
    rows_ok: int
    rows_bad: int
    inserted: int
    updated: int
    unchanged: int


def _chunked(items: list[dict[str, Any]], size: int = 500) -> list[list[dict[str, Any]]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _normalize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        clean = value.strip()
        return clean or None
    # Soporte para pandas.NA y similares
    try:
        if pd.isna(value):
            return None
    except Exception:  # noqa: BLE001
        return value
    return value


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
        reclamos=None,
    )


@router.post("/ingest", response_model=IngestServiciosResponse)
async def ingest_servicios(
    file: UploadFile = File(..., description="Archivo XLSX/CSV con servicios SLA"),
    db: AsyncSession = Depends(get_async_db),
) -> IngestServiciosResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Falta nombre de archivo")

    filename = file.filename.lower()
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Archivo vacio")

    try:
        if filename.endswith((".xlsx", ".xlsm")):
            df = pd.read_excel(io.BytesIO(content), engine="openpyxl", dtype=str, keep_default_na=False)
        elif filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False)
        else:
            raise HTTPException(status_code=415, detail="Formato no soportado (use .xlsx o .csv)")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("action=servicios_ingest_read_error error=%s", exc)
        raise HTTPException(status_code=400, detail="No se pudo leer el archivo") from exc

    df_ok, summary = parse_servicios_df(df)
    if df_ok.empty:
        return IngestServiciosResponse(
            rows_ok=summary.rows_ok,
            rows_bad=summary.rows_bad,
            inserted=0,
            updated=0,
            unchanged=0,
        )

    rows_by_id: dict[str, dict[str, Any]] = {}
    for row in df_ok.to_dict("records"):
        numero_primer_servicio = str(_normalize_value(row.get("numero_primer_servicio")) or "").strip()
        if not numero_primer_servicio:
            continue
        rows_by_id[numero_primer_servicio] = {
            "servicio_id": numero_primer_servicio,
            "numero_primer_servicio": numero_primer_servicio,
            "nombre_cliente": _normalize_value(row.get("nombre_cliente")),
            "numero_linea": _normalize_value(row.get("numero_linea")),
            "tipo_servicio": _normalize_value(row.get("tipo_servicio")),
            "sla_prometido": _normalize_value(row.get("sla_prometido")),
            "direccion": _normalize_value(row.get("direccion")),
            "localidad": _normalize_value(row.get("localidad")),
            "provincia": _normalize_value(row.get("provincia")),
            "direccion_2": _normalize_value(row.get("direccion_2")),
            "estado_servicio": _normalize_value(row.get("estado_servicio")) or "DESCONOCIDO",
        }

    rows = list(rows_by_id.values())

    inserted = 0
    updated = 0

    for chunk in _chunked(rows, size=500):
        stmt = pg_insert(Servicio).values(chunk)
        excluded = stmt.excluded

        set_map = {
            "servicio_id": excluded.servicio_id,
            "nombre_cliente": excluded.nombre_cliente,
            "numero_linea": excluded.numero_linea,
            "tipo_servicio": excluded.tipo_servicio,
            "sla_prometido": excluded.sla_prometido,
            "direccion": excluded.direccion,
            "localidad": excluded.localidad,
            "provincia": excluded.provincia,
            "direccion_2": excluded.direccion_2,
            "estado_servicio": excluded.estado_servicio,
        }

        changed_where = or_(
            Servicio.nombre_cliente.is_distinct_from(excluded.nombre_cliente),
            Servicio.numero_linea.is_distinct_from(excluded.numero_linea),
            Servicio.tipo_servicio.is_distinct_from(excluded.tipo_servicio),
            Servicio.sla_prometido.is_distinct_from(excluded.sla_prometido),
            Servicio.direccion.is_distinct_from(excluded.direccion),
            Servicio.localidad.is_distinct_from(excluded.localidad),
            Servicio.provincia.is_distinct_from(excluded.provincia),
            Servicio.direccion_2.is_distinct_from(excluded.direccion_2),
            Servicio.estado_servicio.is_distinct_from(excluded.estado_servicio),
            Servicio.servicio_id.is_distinct_from(excluded.servicio_id),
        )

        stmt = stmt.on_conflict_do_update(
            index_elements=[Servicio.numero_primer_servicio],
            set_=set_map,
            where=changed_where,
        ).returning(text("xmax = 0 AS inserted"))

        result = await db.execute(stmt)
        flags = result.all()
        inserted += sum(1 for (flag,) in flags if bool(flag))
        updated += sum(1 for (flag,) in flags if not bool(flag))

    await db.commit()

    unchanged = max(len(rows) - inserted - updated, 0)
    return IngestServiciosResponse(
        rows_ok=summary.rows_ok,
        rows_bad=summary.rows_bad,
        inserted=inserted,
        updated=updated,
        unchanged=unchanged,
    )


@router.get("/search", response_model=SearchServiciosResponse)
async def search_servicios(
    q: str | None = Query(None, description="Búsqueda multipropósito"),
    numero_primer_servicio: str | None = Query(None),
    cliente: str | None = Query(None),
    domicilio: str | None = Query(None),
    tipo: str | None = Query(None),
    estado: str | None = Query(None),
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


@router.get("/detail", response_model=ServicioDetailResponse)
async def detail_servicio(
    id: str = Query(..., description="ID de consulta (origen o línea actual)"),
    db: AsyncSession = Depends(get_async_db),
) -> ServicioDetailResponse:
    id_consultado = id.strip()
    if not id_consultado:
        raise HTTPException(status_code=400, detail="ID requerido")

    stmt = (
        select(Servicio)
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

    item = _to_servicio_item(svc)
    if item is None:
        raise HTTPException(status_code=404, detail="Servicio sin ID origen")

    return ServicioDetailResponse(
        id_consultado=id_consultado,
        id_origen=item.numero_primer_servicio,
        servicio=item,
    )
