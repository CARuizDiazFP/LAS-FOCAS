# Nombre de archivo: servicios_excel.py
# Ubicación de archivo: core/parsers/servicios_excel.py
# Descripción: Parser robusto para ingesta de servicios SLA desde Excel/CSV

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple
import re
import unicodedata

import pandas as pd

try:
    from unidecode import unidecode as _unidecode
except Exception:  # noqa: BLE001
    _unidecode = None


MAPPER: Dict[str, str] = {
    "nombre cliente": "nombre_cliente",
    "razon social": "nombre_cliente",
    "cliente": "nombre_cliente",
    "nro primer servicio": "numero_primer_servicio",
    "nro de primer servicio": "numero_primer_servicio",
    "nro. primer servicio": "numero_primer_servicio",
    "n primer servicio": "numero_primer_servicio",
    "n de primer servicio": "numero_primer_servicio",
    "n primer servicio id": "numero_primer_servicio",
    "nro servicio": "numero_primer_servicio",
    "nro. servicio": "numero_primer_servicio",
    "numero primer servicio": "numero_primer_servicio",
    "numero de primer servicio": "numero_primer_servicio",
    "n\u00famero primer servicio": "numero_primer_servicio",
    "n\u00famero de primer servicio": "numero_primer_servicio",
    "servicio id": "numero_primer_servicio",
    "id del servicio": "numero_primer_servicio",
    "id servicio": "numero_primer_servicio",
    "id": "numero_primer_servicio",
    "numero linea": "numero_linea",
    "numero de linea": "numero_linea",
    "n\u00famero linea": "numero_linea",
    "numero l\u00ednea": "numero_linea",
    "nro linea": "numero_linea",
    "nro. linea": "numero_linea",
    "linea nro": "numero_linea",
    "linea n": "numero_linea",
    "linea": "numero_linea",
    "tipo servicio": "tipo_servicio",
    "tipo de servicio": "tipo_servicio",
    "sla prometido": "sla_prometido",
    "sla": "sla_prometido",
    "direccion": "direccion",
    "domicilio": "direccion",
    "domicilio cliente": "direccion",
    "localidad": "localidad",
    "provincia": "provincia",
    "direccion 2": "direccion_2",
    "direcci\u00f3n 2": "direccion_2",
    "estado servicio": "estado_servicio",
    "estado del servicio": "estado_servicio",
    "estado": "estado_servicio",
}

RELEVANT_COLS = [
    "nombre_cliente",
    "numero_primer_servicio",
    "numero_linea",
    "tipo_servicio",
    "sla_prometido",
    "direccion",
    "localidad",
    "provincia",
    "direccion_2",
    "estado_servicio",
]

MIN_REQUIRED = ["numero_primer_servicio"]


@dataclass
class IngestServiciosSummary:
    rows_ok: int
    rows_bad: int


def _clean_key(value: str) -> str:
    clean = str(value)
    clean = clean.replace("°", " ").replace("º", " ")
    if _unidecode is not None:
        clean = _unidecode(clean)
    else:
        clean = "".join(c for c in unicodedata.normalize("NFD", clean) if unicodedata.category(c) != "Mn")
    clean = clean.lower()
    clean = re.sub(r"[^a-z0-9]+", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


NORMALIZED_MAPPER: Dict[str, str] = {_clean_key(k): v for k, v in MAPPER.items()}


def parse_servicios_df(df: pd.DataFrame) -> Tuple[pd.DataFrame, IngestServiciosSummary]:
    """Normaliza encabezados del archivo de servicios y valida filas mínimas."""

    rename: Dict[str, str] = {}
    for col in df.columns:
        key = _clean_key(col)
        if key in NORMALIZED_MAPPER:
            rename[col] = NORMALIZED_MAPPER[key]
    df = df.rename(columns=rename)

    for col in RELEVANT_COLS:
        if col not in df.columns:
            df[col] = pd.NA

    df = df[RELEVANT_COLS].copy()

    for col in RELEVANT_COLS:
        df[col] = df[col].astype(str).str.strip()
        df.loc[df[col].isin(["", "nan", "None", "<NA>", "<na>"]), col] = pd.NA

    df["numero_primer_servicio"] = df["numero_primer_servicio"].astype("string")
    df["estado_servicio"] = df["estado_servicio"].fillna("DESCONOCIDO").astype("string")

    valid = df[MIN_REQUIRED].notna().all(axis=1)
    rows_ok = int(valid.sum())
    rows_bad = int((~valid).sum())

    return df[valid].copy(), IngestServiciosSummary(rows_ok=rows_ok, rows_bad=rows_bad)
