# Nombre de archivo: persistencia.py
# Ubicación de archivo: core/sla_consumo/persistencia.py
# Descripción: Ingesta idempotente de reclamos y fotos de SLA, y lectura de la ventana de 12 meses

from __future__ import annotations

import datetime as dt
import hashlib
import math
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import Connection, Engine, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.sla_consumo.parser import RECLAMOS_COLS, SERVICIOS_COLS, fecha_corte as calcular_fecha_corte
from db.models.reclamo import Reclamo
from db.models.sla_consumo import ServicioSlaSnapshot, SlaIngesta
from db.session import engine as engine_default

VENTANA_DIAS = 365


@dataclass
class ResultadoIngesta:
    ingesta_id: int
    fecha_corte: dt.date
    ya_ingestado: bool
    reclamos_insertados: int
    reclamos_actualizados: int
    servicios_snapshot: int


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _limpio(valor: object) -> object:
    """NaN/NaT/pd.NA → None; Timestamp → datetime; numpy → Python (psycopg no adapta pd.NA)."""
    if valor is None or valor is pd.NA or valor is pd.NaT:
        return None
    if isinstance(valor, float) and math.isnan(valor):
        return None
    if isinstance(valor, pd.Timestamp):
        return valor.to_pydatetime()
    if hasattr(valor, "item"):
        return valor.item()
    return valor


def _registros(df: pd.DataFrame, columnas: list[str]) -> list[dict]:
    return [{c: _limpio(v) for c, v in fila.items()} for fila in df[columnas].to_dict(orient="records")]


def upsert_reclamos_df(conn: Connection, reclamos: pd.DataFrame, ingesta_id: int | None) -> tuple[int, int]:
    if reclamos.empty:
        return 0, 0
    reclamos = reclamos.drop_duplicates(subset="numero_reclamo", keep="last")
    columnas = [c for c in RECLAMOS_COLS + ["latitud", "longitud"] if c in reclamos.columns and c in Reclamo.__table__.c]
    filas = _registros(reclamos, columnas)
    for fila in filas:
        fila["ingesta_id"] = ingesta_id
    insertados = actualizados = 0
    tabla = Reclamo.__table__
    for inicio in range(0, len(filas), 1000):
        stmt = pg_insert(tabla).values(filas[inicio:inicio + 1000])
        # Un reclamo re-exportado trae su estado vigente: se pisa todo menos first_seen_at.
        cambios = {c: stmt.excluded[c] for c in columnas + ["ingesta_id"] if c != "numero_reclamo"}
        cambios["last_seen_at"] = func.now()
        stmt = stmt.on_conflict_do_update(index_elements=[tabla.c.numero_reclamo], set_=cambios)
        for fila in conn.execute(stmt.returning(text("(xmax = 0) AS inserted"))):
            if fila.inserted:
                insertados += 1
            else:
                actualizados += 1
    return insertados, actualizados


def _upsert_snapshot(conn: Connection, servicios: pd.DataFrame, corte: dt.date, ingesta_id: int) -> int:
    if servicios.empty:
        return 0
    filas = _registros(servicios, SERVICIOS_COLS)
    for fila in filas:
        fila.update(fecha_corte=corte, ingesta_id=ingesta_id)
    tabla = ServicioSlaSnapshot.__table__
    total = 0
    for inicio in range(0, len(filas), 1000):
        stmt = pg_insert(tabla).values(filas[inicio:inicio + 1000])
        cambios = {c: stmt.excluded[c] for c in SERVICIOS_COLS + ["ingesta_id"] if c != "numero_linea"}
        cambios["updated_at"] = func.now()
        conn.execute(stmt.on_conflict_do_update(constraint="uq_sla_snapshot_linea_corte", set_=cambios))
        total += len(filas[inicio:inicio + 1000])
    return total


def ingerir(servicios: pd.DataFrame, reclamos: pd.DataFrame, *, hash_servicios: str, hash_reclamos: str,
            usuario: str | None, engine: Engine | None = None) -> ResultadoIngesta:
    engine = engine or engine_default
    corte = calcular_fecha_corte(reclamos)
    with engine.begin() as conn:
        previa = conn.execute(
            select(SlaIngesta).where(SlaIngesta.hash_servicios == hash_servicios,
                                     SlaIngesta.hash_reclamos == hash_reclamos)).first()
        if previa is not None:
            return ResultadoIngesta(previa.id, previa.fecha_corte, True, 0, 0, 0)
        ingesta_id = conn.execute(
            pg_insert(SlaIngesta.__table__).values(
                fecha_corte=corte, hash_servicios=hash_servicios, hash_reclamos=hash_reclamos, usuario=usuario,
            ).returning(SlaIngesta.__table__.c.id)).scalar_one()
        insertados, actualizados = upsert_reclamos_df(conn, reclamos, ingesta_id)
        fotos = _upsert_snapshot(conn, servicios, corte, ingesta_id)
        conn.execute(SlaIngesta.__table__.update().where(SlaIngesta.__table__.c.id == ingesta_id).values(
            reclamos_insertados=insertados, reclamos_actualizados=actualizados, servicios_snapshot=fotos))
    return ResultadoIngesta(ingesta_id, corte, False, insertados, actualizados, fotos)


def cargar_ventana(fecha_corte: dt.date, engine: Engine | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    engine = engine or engine_default
    hasta = pd.Timestamp(fecha_corte + dt.timedelta(days=1), tz="America/Argentina/Buenos_Aires")
    desde = hasta - pd.Timedelta(days=VENTANA_DIAS)
    columnas_r = ", ".join(c for c in RECLAMOS_COLS)
    with engine.connect() as conn:
        reclamos = pd.read_sql(
            text(f"SELECT {columnas_r} FROM app.reclamos WHERE fecha_inicio >= :desde AND fecha_inicio < :hasta"),
            conn, params={"desde": desde.to_pydatetime(), "hasta": hasta.to_pydatetime()})
        servicios = pd.read_sql(
            text(f"SELECT {', '.join(SERVICIOS_COLS)} FROM app.servicio_sla_snapshot WHERE fecha_corte = :c"),
            conn, params={"c": fecha_corte})
    for col in ("horas_netas", "horas_totales_problema", "horas_indisponibilidad_problema",
                "horas_netas_escalamiento_carrier"):
        reclamos[col] = pd.to_numeric(reclamos[col], errors="coerce")
    for col in SERVICIOS_COLS[4:]:
        servicios[col] = pd.to_numeric(servicios[col], errors="coerce")
    reclamos["fecha_inicio"] = pd.to_datetime(reclamos["fecha_inicio"], utc=True).dt.tz_convert("America/Argentina/Buenos_Aires")
    reclamos["fecha_cierre"] = pd.to_datetime(reclamos["fecha_cierre"], utc=True).dt.tz_convert("America/Argentina/Buenos_Aires")
    return reclamos, servicios
