# Nombre de archivo: repetitividad.py
# Ubicación de archivo: core/services/repetitividad.py
# Descripción: Ingesta (upsert) de reclamos y cálculo de repetitividad desde DB

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence, Tuple
from datetime import datetime, timezone
from pathlib import Path
import logging
import math

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from os import getenv
from typing import Optional

from core.maps.static_map import build_static_map_png

from db.models.reclamo import Reclamo


logger = logging.getLogger(__name__)


def _engine_url() -> str:
    return getenv(
        "ALEMBIC_URL",
        getenv(
            "DATABASE_URL",
            f"postgresql+psycopg://{getenv('POSTGRES_USER','lasfocas')}:{getenv('POSTGRES_PASSWORD','superseguro')}@{getenv('POSTGRES_HOST','postgres')}:{getenv('POSTGRES_PORT','5432')}/{getenv('POSTGRES_DB','lasfocas')}",
        ),
    )


def upsert_reclamos(df: pd.DataFrame) -> Tuple[int, int]:
    """Hace upsert en lote. Devuelve (insertados, actualizados)."""
    if df is None or df.empty:
        return 0, 0
    engine = create_engine(_engine_url())
    rows = df.to_dict(orient="records")
    inserted = 0
    updated = 0
    with engine.begin() as conn:
        table = Reclamo.__table__
        stmt = pg_insert(table).values(rows)
        update_cols = {
            c.name: stmt.excluded[c.name]
            for c in table.columns
            if c.name not in ("numero_reclamo",)
        }
        # Evitar sobreescribir con NULL/None: usar COALESCE(excluded.col, table.col)
        for k in list(update_cols.keys()):
            update_cols[k] = text(f"COALESCE(excluded.{k}, {table.name}.{k})")
        stmt = stmt.on_conflict_do_update(
            index_elements=[table.c.numero_reclamo], set_=update_cols
        ).returning(text("xmax = 0 as inserted"))
        result = conn.execute(stmt)
        for row in result:
            if row.inserted:
                inserted += 1
            else:
                updated += 1
    return inserted, updated


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
    engine = create_engine(_engine_url())
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


# --- Nuevo modelo de datos para informes ---


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


@dataclass(slots=True)
class ReclamoRow:
    numero_reclamo: str
    numero_evento: Optional[str]
    fecha_inicio: Optional[pd.Timestamp]
    fecha_cierre: Optional[pd.Timestamp]
    tipo_solucion: Optional[str]
    horas_netas: Optional[float]
    descripcion_solucion: Optional[str]
    latitud: Optional[float]
    longitud: Optional[float]


@dataclass(slots=True)
class ServiceReport:
    numero_linea: str
    nombre_cliente: Optional[str]
    tipo_servicio: Optional[str]
    reclamos: List[ReclamoRow]
    map_path: Optional[Path] = None
    map_image_path: Optional[Path] = None

    @property
    def casos(self) -> int:
        return len({r.numero_reclamo for r in self.reclamos if r.numero_reclamo})

    @property
    def has_geo(self) -> bool:
        return any(r.latitud is not None and r.longitud is not None for r in self.reclamos)


@dataclass(slots=True)
class RepetitividadReport:
    servicios: List[ServiceReport] = field(default_factory=list)
    total_servicios: int = 0
    total_repetitivos: int = 0
    periodos: List[str] = field(default_factory=list)


def reclamos_from_db(mes: int, anio: int) -> pd.DataFrame:
    """Obtiene un DataFrame con columnas normalizadas desde la tabla app.reclamos."""

    start, end = _period_range(mes, anio)
    engine = create_engine(_engine_url())
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


def _parse_float(value: object) -> Optional[float]:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):  # noqa: PERF203 - prefer explicit mapping
        return None


def _ensure_timestamp(value: object) -> Optional[pd.Timestamp]:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, pd.Timestamp):
        return value
    try:
        ts = pd.to_datetime(value, errors="coerce")
        return ts if not pd.isna(ts) else None
    except Exception:  # noqa: BLE001 - defensivo
        return None


def compute_repetitividad_model(df: pd.DataFrame) -> RepetitividadReport:
    """Calcula servicios repetitivos desde un DataFrame normalizado."""

    if df is None or df.empty:
        return RepetitividadReport()

    work = df.copy()
    for col in RELEVANT_COLUMNS:
        if col not in work.columns:
            work[col] = pd.NA

    work["numero_linea"] = work["numero_linea"].astype(str).str.strip()
    work["numero_reclamo"] = work["numero_reclamo"].astype(str).str.strip()

    work.loc[work["numero_linea"] == "", "numero_linea"] = pd.NA
    work.loc[work["numero_reclamo"] == "", "numero_reclamo"] = pd.NA

    total_servicios = int(work["numero_linea"].dropna().nunique())

    servicios: List[ServiceReport] = []
    periodos: set[str] = set()

    for _, row in work.iterrows():
        for col in ("fecha_inicio", "fecha_cierre"):
            ts = _ensure_timestamp(row[col])
            if ts is not None:
                periodos.add(ts.strftime("%Y-%m"))

    grouped = work.dropna(subset=["numero_linea"]).groupby("numero_linea", sort=True)
    for numero_linea, grupo in grouped:
        reclamos_validos = grupo.dropna(subset=["numero_reclamo"])
        if reclamos_validos["numero_reclamo"].nunique() < 2:
            continue
        reclamos: List[ReclamoRow] = []
        for _, fila in grupo.iterrows():
            reclamos.append(
                ReclamoRow(
                    numero_reclamo=str(fila.get("numero_reclamo") or ""),
                    numero_evento=(str(fila.get("numero_evento")) if pd.notna(fila.get("numero_evento")) else None),
                    fecha_inicio=_ensure_timestamp(fila.get("fecha_inicio")),
                    fecha_cierre=_ensure_timestamp(fila.get("fecha_cierre")),
                    tipo_solucion=(str(fila.get("tipo_solucion")) if pd.notna(fila.get("tipo_solucion")) else None),
                    horas_netas=_parse_float(fila.get("horas_netas")),
                    descripcion_solucion=(str(fila.get("descripcion_solucion"))[:600] if pd.notna(fila.get("descripcion_solucion")) else None),
                    latitud=_parse_float(fila.get("latitud")),
                    longitud=_parse_float(fila.get("longitud")),
                )
            )
        primer = grupo.iloc[0]
        servicios.append(
            ServiceReport(
                numero_linea=str(numero_linea),
                nombre_cliente=(str(primer.get("nombre_cliente")) if pd.notna(primer.get("nombre_cliente")) else None),
                tipo_servicio=(str(primer.get("tipo_servicio")) if pd.notna(primer.get("tipo_servicio")) else None),
                reclamos=reclamos,
            )
        )

    servicios.sort(key=lambda s: s.numero_linea)
    return RepetitividadReport(
        servicios=servicios,
        total_servicios=total_servicios,
        total_repetitivos=len(servicios),
        periodos=sorted(periodos),
    )


def attach_service_maps(
    report: RepetitividadReport,
    periodo_mes: int,
    periodo_anio: int,
    output_dir: Path,
    with_geo: bool,
) -> List[Path]:
    """Genera mapas PNG por servicio cuando `with_geo=True` y devuelve la lista."""

    if not with_geo or not report.servicios:
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    maps_dir = output_dir / "maps"
    maps_dir.mkdir(parents=True, exist_ok=True)

    periodo_label = f"{periodo_anio:04d}{periodo_mes:02d}"
    generated: List[Path] = []

    for servicio in report.servicios:
        servicio.map_path = None
        servicio.map_image_path = None
        if not servicio.has_geo:
            continue

        coords = [
            (r.latitud, r.longitud)
            for r in servicio.reclamos
            if r.latitud is not None and r.longitud is not None
        ]
        if not coords:
            continue

        safe_name = "".join(ch if ch.isalnum() else "_" for ch in servicio.numero_linea)[:50]
        png_path = maps_dir / f"repetitividad_{periodo_label}_{safe_name}.png"

        try:
            build_static_map_png(coords, png_path)
        except Exception as exc:  # noqa: BLE001
            servicio.map_image_path = None
            logger.warning(
                "action=attach_service_maps stage=static_map_failed servicio=%s error=%s",
                servicio.numero_linea,
                exc,
            )
            continue

        servicio.map_image_path = png_path
        generated.append(png_path)

    return generated


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
