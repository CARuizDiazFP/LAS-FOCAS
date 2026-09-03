# Nombre de archivo: servicios.py
# Ubicación de archivo: api/app/routes/servicios.py
# Descripción: Endpoints de ingesta y búsqueda paginada para módulo de servicios

from __future__ import annotations

import asyncio
import io
import logging
from datetime import date
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.parsers.servicios_excel import parse_servicios_df
from core.services.prov.client import ProvClientError, ProvServicioNoEncontradoError, get_prov_client
from core.services.prov.config import ProvConfigError
from core.services.prov.ingesta import ingerir_contexto_prov
from core.services.servicios_categoria_service import (
    CategoriaInvalidaError,
    actualizar_categoria_masiva,
    validar_categoria,
)
from core.services.servicios_consolidacion_service import (
    consolidar_identidad_servicio,
    es_verificable_por_tipo_y_estado,
    resolver_estado_servicio,
)
from db.models.infra import Servicio, ServicioEquipoUltimaMilla, ServicioHistorialId, ServicioOrigenDatos
from db.session import AsyncSessionLocal, SessionLocal, get_async_db


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
    categoria: int
    origen_datos: str
    es_verificable: bool
    es_verificable_override: bool | None = None
    alias_ids: list[str] = []
    reclamos: list[dict[str, Any]] | None = None


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
        categoria=svc.categoria,
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
            "categoria": _normalize_value(row.get("categoria")),
            "linea_upgrade_de": _normalize_value(row.get("linea_upgrade_de")),
            "linea_upgrade_a": _normalize_value(row.get("linea_upgrade_a")),
            # 2026-08-14: re-etiqueta también un placeholder Cromo (origen_datos=INFERIDO_CROMO)
            # preexistente cuando el ingest real lo enriquece por el mismo numero_primer_servicio —
            # sin esto quedaría marcado INFERIDO_CROMO para siempre pese a tener datos reales, ver
            # docs/decisiones.md.
            "origen_datos": ServicioOrigenDatos.INGEST_EXCEL.value,
        }

    # Consolidación de identidad (Task 3/4): calcula el servicio_id/numero_linea/alias_ids finales
    # de cada fila contra lo que ya existe en la DB para ese numero_primer_servicio — reemplaza el
    # upsert ciego anterior, que pisaba servicio_id = numero_primer_servicio en cada corrida (bug
    # real que motiva este plan, ver docs del plan de trazabilidad de IDs).
    numeros = list(rows_by_id.keys())
    existentes_por_id: dict[str, Any] = {}
    if numeros:
        existentes_stmt = select(
            Servicio.numero_primer_servicio,
            Servicio.servicio_id,
            Servicio.numero_linea,
            Servicio.alias_ids,
            Servicio.categoria,
            Servicio.es_verificable_override,
            Servicio.estado_servicio,
        ).where(Servicio.numero_primer_servicio.in_(numeros))
        for fila in (await db.execute(existentes_stmt)).all():
            existentes_por_id[fila.numero_primer_servicio] = fila

    ids_reclamados: dict[str, str] = {}
    for numero, row in rows_by_id.items():
        existente = existentes_por_id.get(numero)
        linea_upgrade_de = row.pop("linea_upgrade_de", None)
        linea_upgrade_a = row.pop("linea_upgrade_a", None)

        identidad = consolidar_identidad_servicio(
            numero_primer_servicio=numero,
            numero_linea_excel=row.get("numero_linea"),
            linea_upgrade_de=linea_upgrade_de,
            linea_upgrade_a=linea_upgrade_a,
            servicio_id_actual=existente.servicio_id if existente else None,
            numero_linea_actual=existente.numero_linea if existente else None,
            alias_ids_actual=list(existente.alias_ids) if existente and existente.alias_ids else None,
        )
        row["servicio_id"] = identidad.servicio_id
        row["numero_linea"] = identidad.numero_linea
        row["alias_ids"] = identidad.alias_ids

        # Un Excel que no aporta el ID de línea más alto conocido (`avanza_por_excel=False`, ej.
        # un archivo viejo subido después para completar el histórico de IDs) no puede degradar un
        # servicio ya "Activo" — sólo completa/relaciona el ID vía `alias_ids` arriba. Ver
        # docs/decisiones.md.
        row["estado_servicio"] = resolver_estado_servicio(
            estado_actual=existente.estado_servicio if existente else None,
            estado_excel=row["estado_servicio"],
            avanza_identidad=identidad.avanza_por_excel,
        )

        # `isdigit()` sola no alcanza: "7"/"10" son dígitos pero violan el CHECK
        # `ck_servicios_categoria_valida` (0-6) y el IntegrityError sin manejar tumbaba el archivo
        # completo con un 500. Un valor fuera de rango degrada a fallback y queda loggeado.
        categoria_excel = row.get("categoria")
        categoria_fallback = existente.categoria if existente else 6
        if categoria_excel is not None and str(categoria_excel).isdigit():
            try:
                validar_categoria(int(categoria_excel))
                row["categoria"] = int(categoria_excel)
            except CategoriaInvalidaError:
                logger.warning(
                    "action=servicios_ingest evento=categoria_invalida numero_primer_servicio=%s valor=%s",
                    numero,
                    categoria_excel,
                )
                row["categoria"] = categoria_fallback
        else:
            row["categoria"] = categoria_fallback

        override_actual = existente.es_verificable_override if existente else None
        row["es_verificable"] = (
            override_actual
            if override_actual is not None
            else es_verificable_por_tipo_y_estado(row.get("tipo_servicio"), row["estado_servicio"])
        )

        # Detección de fragmentación: si dos numero_primer_servicio distintos de ESTE mismo archivo
        # reclaman el mismo id (servicio_id/numero_linea/alias) es una señal de datos inconsistentes
        # en el Excel de origen — se deja loggeado para revisión manual, no bloquea la ingesta.
        for candidato in (row["servicio_id"], row["numero_linea"], *row["alias_ids"]):
            dueño_previo = ids_reclamados.get(candidato)
            if dueño_previo and dueño_previo != numero:
                logger.warning(
                    "action=servicios_ingest evento=fragmentacion_detectada id=%s "
                    "numero_primer_servicio_a=%s numero_primer_servicio_b=%s",
                    candidato,
                    dueño_previo,
                    numero,
                )
            else:
                ids_reclamados[candidato] = numero

    # Fusión de placeholders Cromo puros que ya ocupan el servicio_id que esta familia necesita.
    # `app.servicios.servicio_id` tiene índice UNIQUE, así que sin este paso el upsert de más abajo
    # revienta con `duplicate key value violates unique constraint "ix_servicios_servicio_id"` y se
    # pierde el chunk completo de 500 filas (176 casos reales medidos en dev: 161 contra un
    # placeholder INFERIDO_CROMO y 15 contra filas MANUAL).
    # Sólo se fusiona un placeholder INFERIDO_CROMO que de verdad nunca fue tocado — cualquier otra
    # colisión (MANUAL/INGEST_EXCEL, un placeholder divergido, uno con tracking físico encima, o una
    # fila que pertenece a otra familia de ESTE mismo archivo) se degrada sin pisar servicio_id,
    # agregando igual el id a alias_ids, con un warning explícito: fusionar dos registros reales sin
    # confirmación humana está fuera de alcance a propósito.
    candidatos_servicio_id = {row["servicio_id"] for row in rows_by_id.values()}
    colisiones_stmt = select(
        Servicio.id,
        Servicio.servicio_id,
        Servicio.numero_primer_servicio,
        Servicio.origen_datos,
    ).where(Servicio.servicio_id.in_(candidatos_servicio_id))
    colision_por_servicio_id: dict[str, Any] = {}
    for fila in (await db.execute(colisiones_stmt)).all():
        colision_por_servicio_id[fila.servicio_id] = fila

    # Placeholders candidatos a fusión: sólo los que NUNCA fueron tocados por tracking físico (sin
    # filas en rutas_servicio ni en la tabla deprecada servicio_empalme_association) — el flag
    # origen_datos=INFERIDO_CROMO por sí solo NO lo garantiza, porque
    # core/services/infra_service.py::create_new reusa un Servicio ya existente (`if existing:
    # servicio = existing`, puede ser un placeholder Cromo), le cuelga una RutaServicio y le hace
    # `servicio.empalmes.append(...)`, todo SIN cambiarle origen_datos. Un hard delete no puede
    # apoyarse en una medición puntual ("hoy son 0 en dev"), tiene que chequear el hecho.
    ids_placeholder_candidatos = [
        fila.id
        for fila in colision_por_servicio_id.values()
        if fila.origen_datos == ServicioOrigenDatos.INFERIDO_CROMO
        and fila.numero_primer_servicio == fila.servicio_id
    ]
    ids_con_rutas_o_empalmes: set[int] = set()
    if ids_placeholder_candidatos:
        tocados_stmt = text(
            """
            SELECT DISTINCT servicio_id FROM (
                SELECT servicio_id FROM app.rutas_servicio WHERE servicio_id = ANY(:ids)
                UNION
                SELECT servicio_id FROM app.servicio_empalme_association WHERE servicio_id = ANY(:ids)
            ) t
            """
        )
        ids_con_rutas_o_empalmes = {
            fila[0]
            for fila in (await db.execute(tocados_stmt, {"ids": ids_placeholder_candidatos})).all()
        }

    fusiones_pendientes: dict[str, int] = {}  # numero_primer_servicio -> id del placeholder a fusionar
    id_final_pendiente_por_numero: dict[str, str] = {}  # numero_primer_servicio -> servicio_id final real
    for numero, row in rows_by_id.items():
        colision = colision_por_servicio_id.get(row["servicio_id"])
        if colision is None or colision.numero_primer_servicio == numero:
            continue  # sin colisión real, o es la propia fila de esta misma familia

        # Si la fila en colisión es de OTRA familia de este mismo archivo, fusionarla sería borrar una
        # fila que el upsert de más abajo está por escribir. Se degrada (no se fusiona) aunque cumpla
        # el resto del predicado de "placeholder puro".
        colisiona_con_otra_familia_del_batch = colision.numero_primer_servicio in rows_by_id
        es_placeholder_puro = (
            not colisiona_con_otra_familia_del_batch
            and colision.origen_datos == ServicioOrigenDatos.INFERIDO_CROMO
            and colision.numero_primer_servicio == colision.servicio_id
            and colision.id not in ids_con_rutas_o_empalmes
        )

        existente = existentes_por_id.get(numero)
        valor_seguro = existente.servicio_id if existente else numero
        if es_placeholder_puro:
            id_final_pendiente_por_numero[numero] = row["servicio_id"]
            fusiones_pendientes[numero] = colision.id
            row["servicio_id"] = valor_seguro
        else:
            logger.warning(
                "action=servicios_ingest evento=servicio_id_colision_no_fusionable "
                "numero_primer_servicio=%s servicio_id_deseado=%s colision_con_id=%s colision_origen=%s "
                "colision_del_mismo_batch=%s",
                numero,
                row["servicio_id"],
                colision.id,
                colision.origen_datos.value if hasattr(colision.origen_datos, "value") else str(colision.origen_datos),
                colisiona_con_otra_familia_del_batch,
            )
            id_final_no_fusionable = row["servicio_id"]
            row["servicio_id"] = valor_seguro
            # `consolidar_identidad_servicio` había excluido `id_final` de los alias y dejado
            # `valor_seguro` adentro, asumiendo que el servicio_id final iba a ser `id_final`. Al
            # degradar se invierte: `valor_seguro` pasa a ser el servicio_id (no tiene sentido que
            # además figure como su propio alias) y `id_final` baja a alias.
            if valor_seguro in row["alias_ids"]:
                row["alias_ids"].remove(valor_seguro)
            if id_final_no_fusionable != valor_seguro and id_final_no_fusionable not in row["alias_ids"]:
                row["alias_ids"].append(id_final_no_fusionable)

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
            "origen_datos": excluded.origen_datos,
            "categoria": excluded.categoria,
            "es_verificable": excluded.es_verificable,
            "alias_ids": excluded.alias_ids,
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
            Servicio.origen_datos.is_distinct_from(excluded.origen_datos),
            Servicio.categoria.is_distinct_from(excluded.categoria),
            Servicio.es_verificable.is_distinct_from(excluded.es_verificable),
            Servicio.alias_ids.is_distinct_from(excluded.alias_ids),
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

    # Segunda fase de la fusión: recién acá existe con certeza la fila de la familia real (el upsert
    # de arriba la insertó o actualizó), así que ya se le puede reasignar lo que apuntaba al
    # placeholder y liberar el servicio_id.
    #
    # El ORDEN es obligatorio, no cosmético: `app.cromo_servicio_match.servicio_id` referencia
    # `app.servicios.id` SIN `ON DELETE CASCADE` (verificado real con `\d app.cromo_servicio_match`),
    # así que si se borrara el placeholder antes de reasignar, el DELETE fallaría por violación de FK
    # y se caería la ingesta entera. `app.rutas_servicio.servicio_id` sí es `ON DELETE CASCADE`: se
    # reasigna igual porque dejar que la cascada BORRE rutas de un servicio real sería pérdida de
    # datos (en la práctica un placeholder puro nunca tiene rutas — sólo el módulo de tracking
    # físico las crea —, verificado 0 de 9054 en dev, pero reasignar es lo correcto igual).
    if fusiones_pendientes:
        ids_stmt = select(Servicio.id, Servicio.numero_primer_servicio).where(
            Servicio.numero_primer_servicio.in_(list(fusiones_pendientes.keys()))
        )
        id_por_numero = {fila.numero_primer_servicio: fila.id for fila in (await db.execute(ids_stmt)).all()}

        for numero, placeholder_id in fusiones_pendientes.items():
            familia_id = id_por_numero.get(numero)
            if familia_id is None or familia_id == placeholder_id:
                logger.warning(
                    "action=servicios_ingest evento=fusion_no_aplicada numero_primer_servicio=%s "
                    "placeholder_id=%s familia_id=%s",
                    numero,
                    placeholder_id,
                    familia_id,
                )
                continue
            await db.execute(
                text("UPDATE app.cromo_servicio_match SET servicio_id = :familia_id WHERE servicio_id = :placeholder_id"),
                {"familia_id": familia_id, "placeholder_id": placeholder_id},
            )
            await db.execute(
                text("UPDATE app.rutas_servicio SET servicio_id = :familia_id WHERE servicio_id = :placeholder_id"),
                {"familia_id": familia_id, "placeholder_id": placeholder_id},
            )
            # Tercera tabla que referencia app.servicios sin ON DELETE CASCADE. Acá se BORRA en vez de
            # reasignar, a propósito: su PK es compuesta `(servicio_id, empalme_id)` (verificado real),
            # así que reasignar podría chocar contra esa PK si la familia real ya tuviera el mismo
            # empalme_id que el placeholder. La tabla además está DEPRECATED ("mantener por
            # retrocompatibilidad", ver db/models/infra.py:89 y la relación `Servicio.empalmes`), su
            # reemplazo moderno es ruta_empalme_association vía RutaServicio, y en la práctica un
            # placeholder puro nunca tiene filas acá (verificado 0 de 9054 en dev). Perder esta
            # asociación deprecada de un placeholder que igual se está eliminando no tiene impacto.
            await db.execute(
                text("DELETE FROM app.servicio_empalme_association WHERE servicio_id = :placeholder_id"),
                {"placeholder_id": placeholder_id},
            )
            await db.execute(
                text("DELETE FROM app.servicios WHERE id = :placeholder_id"),
                {"placeholder_id": placeholder_id},
            )
            await db.execute(
                text("UPDATE app.servicios SET servicio_id = :id_final WHERE id = :familia_id"),
                {"id_final": id_final_pendiente_por_numero[numero], "familia_id": familia_id},
            )
            logger.warning(
                "action=servicios_ingest evento=placeholder_fusionado numero_primer_servicio=%s "
                "placeholder_id=%s servicio_id_liberado=%s familia_id=%s",
                numero,
                placeholder_id,
                id_final_pendiente_por_numero[numero],
                familia_id,
            )

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
    categoria: str | None = Query(None, description="Categorías separadas por coma, ej. '6' o '0,3,5'"),
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
        try:
            categorias = [int(valor.strip()) for valor in categoria.split(",") if valor.strip()]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="categoria inválida") from exc
        if categorias:
            filters.append(Servicio.categoria.in_(categorias))

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

    svc = await _buscar_servicio_por_id(db, id_consultado)

    item = _to_servicio_item(svc)
    if item is None:
        raise HTTPException(status_code=404, detail="Servicio sin ID origen")

    return ServicioDetailResponse(
        id_consultado=id_consultado,
        id_origen=item.numero_primer_servicio,
        servicio=item,
        historial_ids=_historial_a_response(svc.historial_ids),
        equipos_ultima_milla=_equipos_a_response(svc.equipos_ultima_milla),
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
        raise HTTPException(status_code=502, detail=f"No se pudo consultar PROV: {exc}") from exc

    async with AsyncSessionLocal() as db_write:
        svc = await _buscar_servicio_por_id(db_write, id_consultado)
        await ingerir_contexto_prov(db_write, svc, contexto)
        await db_write.commit()
        await db_write.refresh(svc, attribute_names=["historial_ids", "equipos_ultima_milla"])

        item = _to_servicio_item(svc)
        if item is None:
            raise HTTPException(status_code=404, detail="Servicio sin ID origen")

        return ServicioDetailResponse(
            id_consultado=id_consultado,
            id_origen=item.numero_primer_servicio,
            servicio=item,
            historial_ids=_historial_a_response(svc.historial_ids),
            equipos_ultima_milla=_equipos_a_response(svc.equipos_ultima_milla),
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
    await db.commit()
    await db.refresh(svc)

    item = _to_servicio_item(svc)
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
