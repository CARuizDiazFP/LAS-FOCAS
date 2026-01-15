# Nombre de archivo: parser.py
# Ubicación de archivo: core/sla/parser.py
# Descripción: Normalización de datos de entrada para SLA
"""Normalización de fuentes de datos SLA."""

from __future__ import annotations

from dataclasses import dataclass
from typing import IO, Iterable, Mapping, Optional

import pandas as pd
from pandas import DataFrame

from .config import DEFAULT_TZ


@dataclass(slots=True)
class SLAInput:
    """Contenedor con los datasets listos para el motor."""

    reclamos: DataFrame
    servicios: Optional[DataFrame]


_RECLAMOS_MAP: Mapping[str, str] = {
    "numero reclamo": "ticket_id",
    "n° de ticket": "ticket_id",
    "ticket": "ticket_id",
    "id": "ticket_id",
    "numero línea": "service_id",
    "numero linea": "service_id",
    "numero primer servicio": "service_id",
    "servicio": "service_id",
    "nombre cliente": "cliente",
    "cliente": "cliente",
    "tipo servicio": "tipo_servicio",
    "fecha inicio problema reclamo": "inicio",
    "fecha inicio reclamo": "inicio",
    "fecha apertura": "inicio",
    "apertura": "inicio",
    "fecha cierre problema reclamo": "fin",
    "fecha cierre reclamo": "fin",
    "fecha cierre": "fin",
    "cierre": "fin",
    # IMPORTANTE: Usar columna 'Horas Netas Cierre Problema Reclamo' (columna P del Excel)
    "horas netas cierre problema reclamo": "duracion_h",
    "tipo solución reclamo": "causal",
    "tipo solucion reclamo": "causal",
    "causal": "causal",
    "tipo solución": "causal",
    "descripcion solución reclamo": "descripcion",
    "descripción solución reclamo": "descripcion",
    "descripcion": "descripcion",
    "estado reclamo": "estado",
    "estado": "estado",
    "sla objetivo": "sla_objetivo_h",
    "sla objetivo horas": "sla_objetivo_h",
    "sla_objetivo_horas": "sla_objetivo_h",
    "criticidad": "criticidad",
    "prioridad": "criticidad",
}

_SERVICIOS_MAP: Mapping[str, str] = {
    "numero línea": "service_id",
    "numero linea": "service_id",
    "numero primer servicio": "service_id",
    "servicio": "service_id",
    "tipo servicio": "tipo_servicio",
    "nombre cliente": "cliente",
    "cliente": "cliente",
    "sla entregado": "sla_pct",
    "sla": "sla_pct",
    "horas reclamos todos": "downtime_reportado_h",
    "horas reclamos": "downtime_reportado_h",
}

_RECLAMOS_COLUMNS = [
    "ticket_id",
    "service_id",
    "cliente",
    "tipo_servicio",
    "inicio",
    "fin",
    "duracion_h",
    "causal",
    "descripcion",
    "estado",
    "criticidad",
    "sla_objetivo_h",
]

_SERVICIOS_COLUMNS = [
    "service_id",
    "cliente",
    "tipo_servicio",
    "sla_pct",
    "downtime_reportado_h",
]


def cargar_fuente_excel(
    excel: str | bytes | IO[bytes],
    *,
    tz = DEFAULT_TZ,
    sheet_names: Optional[Iterable[str]] = None,
) -> SLAInput:
    """Lee un Excel con pestañas de reclamos y servicios."""

    workbook = pd.ExcelFile(excel)
    data_reclamos: Optional[DataFrame] = None
    data_servicios: Optional[DataFrame] = None

    nombres = sheet_names or workbook.sheet_names
    for nombre in nombres:
        df = workbook.parse(nombre)
        df.columns = _normalizar_headers(df.columns)
        tipo = _clasificar(df.columns)
        if tipo == "reclamos" and data_reclamos is None:
            data_reclamos = _normalizar_reclamos(df, tz)
        elif tipo == "servicios" and data_servicios is None:
            data_servicios = _normalizar_servicios(df)

    if data_reclamos is None:
        raise ValueError("No se encontraron datos de reclamos en el Excel recibido")

    return SLAInput(reclamos=data_reclamos, servicios=data_servicios)


def _normalizar_headers(columnas: Iterable[str]) -> pd.Index:
    serie = pd.Index(columnas)
    serie = serie.astype(str).str.strip().str.lower()
    serie = serie.str.replace("\\s+", " ", regex=True)
    serie = serie.str.replace("á", "a").str.replace("é", "e").str.replace("í", "i").str.replace("ó", "o").str.replace("ú", "u").str.replace("ñ", "n")
    return serie


def _clasificar(columnas: Iterable[str]) -> str:
    columnas_set = set(columnas)
    if {"numero reclamo", "n° de ticket", "ticket"} & columnas_set:
        return "reclamos"
    if {"sla", "sla entregado", "horas reclamos todos"} & columnas_set:
        return "servicios"
    if {"fecha inicio problema reclamo", "fecha cierre problema reclamo"} <= columnas_set:
        return "reclamos"
    return "desconocido"


def _normalizar_reclamos(df: DataFrame, tz) -> DataFrame:
    mapeadas = {_RECLAMOS_MAP.get(col, col): serie for col, serie in df.items()}
    data = pd.DataFrame(mapeadas)
    for columna in _RECLAMOS_COLUMNS:
        if columna not in data.columns:
            data[columna] = pd.NA

    data = data[_RECLAMOS_COLUMNS]
    data = data.copy()

    data["ticket_id"] = data["ticket_id"].astype(str).str.strip()
    data["ticket_id"].replace({"nan": pd.NA, "": pd.NA}, inplace=True)

    data["service_id"] = data["service_id"].astype(str).str.strip()
    data.loc[data["service_id"].isin(["", "nan", "none"]), "service_id"] = pd.NA

    data["cliente"] = data["cliente"].astype(str).str.strip()
    data.loc[data["cliente"].isin(["", "nan", "none"]), "cliente"] = pd.NA

    data["tipo_servicio"] = data["tipo_servicio"].astype(str).str.strip()
    data.loc[data["tipo_servicio"].isin(["", "nan", "none"]), "tipo_servicio"] = pd.NA

    data["inicio"] = data["inicio"].apply(lambda v: _parse_datetime(v, tz))
    data["fin"] = data["fin"].apply(lambda v: _parse_datetime(v, tz))

    data["duracion_h"] = data.apply(
        lambda fila: _parse_duracion_horas(fila["duracion_h"], fila["inicio"], fila["fin"]),
        axis=1,
    )

    data["sla_objetivo_h"] = data["sla_objetivo_h"].apply(_parse_float_or_none)

    data = data.sort_values(["service_id", "inicio", "fin"], na_position="last")
    if "ticket_id" in data.columns:
        data = data.drop_duplicates(subset="ticket_id", keep="last")

    return data.reset_index(drop=True)


def _normalizar_servicios(df: DataFrame) -> DataFrame:
    mapeadas = {_SERVICIOS_MAP.get(col, col): serie for col, serie in df.items()}
    data = pd.DataFrame(mapeadas)
    for columna in _SERVICIOS_COLUMNS:
        if columna not in data.columns:
            data[columna] = pd.NA

    data = data[_SERVICIOS_COLUMNS].copy()
    data["service_id"] = data["service_id"].astype(str).str.strip()
    data.loc[data["service_id"].isin(["", "nan", "none"]), "service_id"] = pd.NA

    data["cliente"] = data["cliente"].astype(str).str.strip()
    data.loc[data["cliente"].isin(["", "nan", "none"]), "cliente"] = pd.NA

    data["tipo_servicio"] = data["tipo_servicio"].astype(str).str.strip()
    data.loc[data["tipo_servicio"].isin(["", "nan", "none"]), "tipo_servicio"] = pd.NA

    data["sla_pct"] = data["sla_pct"].apply(_parse_percentage)
    data["downtime_reportado_h"] = data["downtime_reportado_h"].apply(_parse_float_or_none)

    return data.reset_index(drop=True)


def _parse_datetime(value, tz) -> Optional[pd.Timestamp]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        ts = pd.to_datetime(value, errors="coerce", dayfirst=True, utc=False)
    except Exception:
        return None
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        return ts.tz_localize(tz)
    return ts.tz_convert(tz)


def _parse_duracion_horas(value, inicio, fin) -> Optional[float]:
    """Parsea duración a horas decimales desde la columna 'Horas Netas Cierre Problema Reclamo'.
    
    IMPORTANTE: Solo usa el valor de la columna P, SIN fallback a fechas.
    
    Maneja múltiples formatos:
    - Timedelta de pandas o Python
    - String "HH:MM:SS" o "H:MM:SS"  
    - Número decimal en horas
    - datetime.time (Excel a veces interpreta así)
    """
    import datetime
    
    # Si no hay valor, retornar None (sin fallback a fechas)
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    
    # Si es timedelta de pandas
    if isinstance(value, pd.Timedelta):
        return round(value.total_seconds() / 3600, 4)
    
    # Si es timedelta de Python
    if isinstance(value, datetime.timedelta):
        return round(value.total_seconds() / 3600, 4)
    
    # Si es datetime.time (Excel a veces interpreta tiempos así)
    if isinstance(value, datetime.time):
        return round(value.hour + value.minute / 60 + value.second / 3600, 4)
    
    text = str(value).strip().lower()
    if not text or text in {"nan", "none"}:
        return None
    
    # Intentar parsear como timedelta (formato HH:MM:SS)
    try:
        td = pd.to_timedelta(text.replace(",", "."))
        if not pd.isna(td):
            return round(td.total_seconds() / 3600, 4)
    except ValueError:
        pass
    
    # Intentar como número decimal directo (ya en horas)
    try:
        num = float(text.replace(",", "."))
        return round(num, 4)
    except Exception:
        pass
    
    return _parse_float_or_none(value)


def _parse_float_or_none(value) -> Optional[float]:
    if value is None:
        return None
    try:
        if isinstance(value, str):
            clean = value.strip().lower().replace(",", ".")
            if not clean or clean in {"nan", "none"}:
                return None
            return float(clean)
        if isinstance(value, (int, float)):
            if pd.isna(value):
                return None
            return float(value)
    except Exception:
        return None
    return None


def _parse_percentage(value) -> Optional[float]:
    parsed = _parse_float_or_none(value)
    if parsed is None:
        return None
    if parsed > 1:
        return round(parsed / 100, 6)
    return round(parsed, 6)
