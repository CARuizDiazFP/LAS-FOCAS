# Nombre de archivo: repetitividad.py
# Ubicación de archivo: core/services/repetitividad.py
# Descripción: Ingesta (upsert) de reclamos y cálculo de repetitividad desde DB

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Tuple
from datetime import datetime, timezone
import logging

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def _engine() -> Engine:
    """Engine compartido de `db/session.py`: un pool por proceso. Hasta 2026-10-26 cada llamada creaba
    su propio engine (y su pool) sin `dispose()`, así que cada request abría una conexión nueva
    (medido en dev: 10 de 10 llamadas). Import diferido para no acoplar el import de este módulo."""
    from db.session import engine

    return engine


def upsert_reclamos(df: pd.DataFrame) -> Tuple[int, int]:
    """Hace upsert en lote. Devuelve (insertados, actualizados)."""
    if df is None or df.empty:
        return 0, 0
    from core.sla_consumo.persistencia import upsert_reclamos_df

    engine = _engine()
    with engine.begin() as conn:
        insertados, actualizados, _ = upsert_reclamos_df(conn, df, ingesta_id=None, preservar_no_nulos=True)
        return insertados, actualizados


@dataclass
class PeriodMetrics:
    periodo: str
    total_servicios: int
    servicios_repetitivos: int


def _period_range(mes: int, anio: int) -> Tuple[datetime, datetime]:
    start = datetime(anio, mes, 1, tzinfo=timezone.utc)
    if mes == 12:
        end = datetime(anio + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(anio, mes + 1, 1, tzinfo=timezone.utc)
    return start, end


def repetitividad_metrics_from_db(mes: int, anio: int) -> PeriodMetrics:
    engine = _engine()
    start, end = _period_range(mes, anio)
    with engine.begin() as conn:
        # total servicios: líneas únicas con al menos un reclamo en el período
        total = conn.execute(
            text(
                """
                SELECT COUNT(DISTINCT numero_linea)
                FROM app.reclamos
                WHERE fecha_cierre >= :start AND fecha_cierre < :end
                """
            ),
            {"start": start, "end": end},
        ).scalar_one()
        # repetitivos: líneas con 2 o más reclamos en el período
        repetitivos = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM (
                    SELECT numero_linea
                    FROM app.reclamos
                    WHERE fecha_cierre >= :start AND fecha_cierre < :end
                    GROUP BY numero_linea
                    HAVING COUNT(*) >= 2
                ) t
                """
            ),
            {"start": start, "end": end},
        ).scalar_one()
    return PeriodMetrics(
        periodo=f"{anio:04d}-{mes:02d}",
        total_servicios=int(total or 0),
        servicios_repetitivos=int(repetitivos or 0),
    )


RELEVANT_COLUMNS: Sequence[str] = (
    "numero_reclamo",
    "numero_evento",
    "numero_linea",
    "tipo_servicio",
    "nombre_cliente",
    "tipo_solucion",
    "fecha_inicio",
    "fecha_cierre",
    "horas_netas",
    "descripcion_solucion",
    "latitud",
    "longitud",
)


def reclamos_from_db(mes: int, anio: int) -> pd.DataFrame:
    """Obtiene un DataFrame con columnas normalizadas desde la tabla app.reclamos."""

    start, end = _period_range(mes, anio)
    engine = _engine()
    query = text(
        """
        SELECT
            numero_reclamo,
            numero_evento,
            numero_linea,
            tipo_servicio,
            nombre_cliente,
            tipo_solucion,
            fecha_inicio,
            fecha_cierre,
            horas_netas,
            descripcion_solucion,
            latitud,
            longitud
        FROM app.reclamos
        WHERE (
            fecha_cierre IS NOT NULL AND fecha_cierre >= :start AND fecha_cierre < :end
        ) OR (
            fecha_cierre IS NULL AND fecha_inicio IS NOT NULL AND fecha_inicio >= :start AND fecha_inicio < :end
        )
        """
    )
    with engine.begin() as conn:
        rows = conn.execute(query, {"start": start, "end": end}).mappings().all()
    if not rows:
        return pd.DataFrame(columns=RELEVANT_COLUMNS)

    df = pd.DataFrame([dict(row) for row in rows])
    df = df.reindex(columns=RELEVANT_COLUMNS, fill_value=pd.NA)
    return df.copy()


DB_TO_PROCESSOR_MAP = {
    "nombre_cliente": "Nombre Cliente",
    "numero_linea": "Número Línea",
    "numero_reclamo": "Número Reclamo",
    "numero_evento": "Número Evento",
    "tipo_servicio": "Tipo Servicio",
    "tipo_solucion": "Tipo Solución Reclamo",
    "fecha_inicio": "Fecha Inicio Problema Reclamo",
    "fecha_cierre": "Fecha Cierre Problema Reclamo",
    "horas_netas": "Horas Netas Problema Reclamo",
    "descripcion_solucion": "Descripción Solución Reclamo",
    "latitud": "Latitud Reclamo",
    "longitud": "Longitud Reclamo",
}


def db_to_processor_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Renombra las columnas provenientes de la DB al formato esperado por processor."""

    if df is None or df.empty:
        return pd.DataFrame(columns=list(DB_TO_PROCESSOR_MAP.values()))

    work = df.copy()
    for col in RELEVANT_COLUMNS:
        if col not in work.columns:
            work[col] = pd.NA
    work = work[list(RELEVANT_COLUMNS)]
    return work.rename(columns=DB_TO_PROCESSOR_MAP)
