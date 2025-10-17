# Nombre de archivo: reclamos_excel.py
# Ubicación de archivo: core/parsers/reclamos_excel.py
# Descripción: Parser y normalizador de reclamos (Excel/CSV) con mapeo tolerante

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple
import re
import unicodedata

from core.utils.timefmt import value_to_minutes
try:
    from unidecode import unidecode as _unidecode
except Exception:  # noqa: BLE001
    _unidecode = None

import pandas as pd


MAPPER: Dict[str, str] = {
    # Normalizar encabezados al español sin acentos, minúsculas y espacios simples
    "numero reclamo": "numero_reclamo",
    "número reclamo": "numero_reclamo",
    "numero evento": "numero_evento",
    "numero linea": "numero_linea",
    "número linea": "numero_linea",
    "numero línea": "numero_linea",
    "tipo servicio": "tipo_servicio",
    "nombre cliente": "nombre_cliente",
    "tipo solucion reclamo": "tipo_solucion",
    "tipo solución reclamo": "tipo_solucion",
    "fecha inicio problema reclamo": "fecha_inicio",
    "fecha cierre problema reclamo": "fecha_cierre",
    "horas netas problema reclamo": "horas_netas",
    "descripcion solucion reclamo": "descripcion_solucion",
    "descripción solucion reclamo": "descripcion_solucion",
    "descripción solución reclamo": "descripcion_solucion",
    "latitud reclamo": "latitud",
    "longitud reclamo": "longitud",
}

RELEVANT_COLS = [
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
]

MIN_REQUIRED = ["numero_reclamo", "numero_linea", "nombre_cliente"]


@dataclass
class IngestSummary:
    rows_ok: int
    rows_bad: int
    geo_pct: float
    date_min: pd.Timestamp | None
    date_max: pd.Timestamp | None


def _clean_key(s: str) -> str:
    # Normalizar encabezados: Unidecode si está disponible, si no usar unicodedata
    s = str(s)
    if _unidecode is not None:
        s = _unidecode(s)
    else:
        s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    s = s.lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_reclamos_df(df: pd.DataFrame) -> Tuple[pd.DataFrame, IngestSummary]:
    """Normaliza encabezados y valores y devuelve DataFrame filtrado + resumen.

    - Renombra columnas usando MAPPER con claves normalizadas.
    - Filtra solo RELEVANT_COLS (ausentes se agregan como NaN).
    - Convierte fechas (dayfirst=True), horas (coma->punto), lat/lon numéricas.
    - Valida mínimas requeridas y descarta filas inválidas.
    """

    # Renombrar columnas tolerando variantes
    rename: Dict[str, str] = {}
    for col in df.columns:
        key = _clean_key(col)
        if key in MAPPER:
            rename[col] = MAPPER[key]
    df = df.rename(columns=rename)

    # Conservar solo columnas relevantes
    for c in RELEVANT_COLS:
        if c not in df.columns:
            df[c] = pd.NA
    df = df[RELEVANT_COLS].copy()

    # Limpieza básica
    for c in ["numero_reclamo", "numero_evento", "numero_linea", "tipo_servicio", "nombre_cliente", "tipo_solucion"]:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()

    # Fechas
    for c in ["fecha_inicio", "fecha_cierre"]:
        df[c] = pd.to_datetime(df[c], dayfirst=True, errors="coerce")

    # Horas netas (acepta coma decimal)
    df["horas_netas"] = df["horas_netas"].map(value_to_minutes)
    df["horas_netas"] = pd.Series(df["horas_netas"], dtype="Int64")
    df.loc[df["horas_netas"] < 0, "horas_netas"] = pd.NA

    # GEO
    for c in ["latitud", "longitud"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # Rangos válidos
    df.loc[(df["latitud"].notna()) & ~df["latitud"].between(-90, 90), "latitud"] = pd.NA
    df.loc[(df["longitud"].notna()) & ~df["longitud"].between(-180, 180), "longitud"] = pd.NA

    # Filas válidas (mínimo requerido + alguna fecha)
    has_min = df[MIN_REQUIRED].notna().all(axis=1)
    has_any_date = df[["fecha_inicio", "fecha_cierre"]].notna().any(axis=1)
    valid = has_min & has_any_date
    rows_ok = int(valid.sum())
    rows_bad = int((~valid).sum())
    df_ok = df[valid].copy()

    # Resumen
    date_min = None
    date_max = None
    if not df_ok.empty:
        joined_dates = pd.concat([df_ok["fecha_inicio"], df_ok["fecha_cierre"]], axis=0)
        joined_dates = joined_dates.dropna()
        if not joined_dates.empty:
            date_min = joined_dates.min()
            date_max = joined_dates.max()
    geo_valid = df_ok[["latitud", "longitud"]].notna().all(axis=1)
    geo_pct = float(round(100.0 * geo_valid.sum() / max(len(df_ok), 1), 2))

    return df_ok, IngestSummary(rows_ok=rows_ok, rows_bad=rows_bad, geo_pct=geo_pct, date_min=date_min, date_max=date_max)
