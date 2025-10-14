"""
# Nombre de archivo: reclamos_xlsx.py
# Ubicación de archivo: core/parsers/reclamos_xlsx.py
# Descripción: Normalizador robusto para ingesta de reclamos (XLSX/CSV) con fechas, duración y GEO
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


@dataclass
class IngestSummary:
    rows_ok: int
    rows_bad: int
    date_min: Optional[pd.Timestamp]
    date_max: Optional[pd.Timestamp]
    geo_pct: float


def _to_datetime(s: pd.Series) -> pd.Series:
    # Intenta parseo con múltiples estrategias, dayfirst=True
    x = pd.to_datetime(s, errors="coerce", dayfirst=True)
    # Fallback: strings con formato común
    mask = x.isna() & s.notna()
    if mask.any():
        try:
            x2 = pd.to_datetime(s[mask].astype(str), errors="coerce", utc=False)
            x.loc[mask] = x2
        except Exception:
            pass
    return x


def _to_timedelta(val: Any) -> Optional[pd.Timedelta]:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    # Excel puede representar duración como fecha base 1900-01-01 + delta
    # o como string hh:mm:ss o d hh:mm:ss
    s = str(val).strip()
    if not s:
        return None
    # Caso excel serial en días -> convertir a Timedelta
    try:
        # Algunas planillas exportan como número de días (float)
        num = float(s.replace(",", "."))
        if 0.0 <= num < 100000:  # umbral razonable
            return pd.to_timedelta(num, unit="D")
    except Exception:
        pass
    # Intentar hh:mm[:ss] o d hh:mm[:ss]
    for fmt in ("%H:%M:%S", "%H:%M", "%d %H:%M:%S", "%d %H:%M"):
        try:
            t = pd.to_datetime(s, format=fmt, errors="raise")
            base = pd.Timestamp(0)
            return t - base
        except Exception:
            continue
    # Último recurso: pandas
    try:
        t = pd.to_timedelta(s, errors="coerce")
        return None if pd.isna(t) else t
    except Exception:
        return None


def _clean_float_series(s: pd.Series) -> pd.Series:
    s = s.astype(str).str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors="coerce")


def parse_reclamos_df(df: pd.DataFrame) -> Tuple[pd.DataFrame, IngestSummary]:
    # Normalizar cabeceras
    def norm(c: Any) -> str:
        c = str(c)
        import unicodedata
        c = ''.join(ch for ch in unicodedata.normalize('NFD', c) if unicodedata.category(ch) != 'Mn')
        return c.strip().lower().replace(" ", "_")

    cols = {norm(c): c for c in df.columns}
    alias = {
        "reclamo": "id",
        "tipo_solucion": "solution_type",
        "fecha_inicio": "started_at",
        "fecha_cierre": "finished_at",
        "horas_netas": "net_hours",
        "descripcion_solucion": "solution_desc",
        "numero_de_linea": "line_number",
        "numero_linea": "line_number",
        "cliente": "client_name",
        "latitud_reclamo": "latitude",
        "longitud_reclamo": "longitude",
    }
    rename = {}
    for k, v in alias.items():
        if k in cols:
            rename[cols[k]] = v
    df = df.rename(columns=rename)

    # Coerción de tipos
    if "started_at" in df.columns:
        df["started_at"] = _to_datetime(df["started_at"]).dt.tz_localize(None)
    if "finished_at" in df.columns:
        df["finished_at"] = _to_datetime(df["finished_at"]).dt.tz_localize(None)
    if "net_hours" in df.columns:
        df["net_hours_td"] = df["net_hours"].map(_to_timedelta)
        df["net_hours_seconds"] = df["net_hours_td"].map(lambda x: None if x is None else int(x.total_seconds()))
    for geo in ("latitude", "longitude"):
        if geo in df.columns:
            df[geo] = _clean_float_series(df[geo])

    # Validación mínima
    required = ["id", "started_at", "finished_at"]
    ok_mask = pd.Series(True, index=df.index)
    for r in required:
        if r not in df.columns:
            ok_mask &= False
        else:
            ok_mask &= df[r].notna()

    df_ok = df[ok_mask].copy()
    df_bad = df[~ok_mask].copy()

    date_min = None
    date_max = None
    if "finished_at" in df_ok.columns and not df_ok.empty:
        date_min = pd.to_datetime(df_ok["finished_at"]).min()
        date_max = pd.to_datetime(df_ok["finished_at"]).max()

    geo_pct = 0.0
    if {"latitude", "longitude"}.issubset(df_ok.columns) and not df_ok.empty:
        geo_cnt = (df_ok["latitude"].notna() & df_ok["longitude"].notna()).sum()
        geo_pct = 100.0 * geo_cnt / max(len(df_ok), 1)

    summary = IngestSummary(
        rows_ok=len(df_ok),
        rows_bad=len(df_bad),
        date_min=date_min,
        date_max=date_max,
        geo_pct=geo_pct,
    )
    return df_ok, summary
