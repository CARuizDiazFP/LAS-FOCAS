# Nombre de archivo: excel_duraciones.py
# Ubicación de archivo: core/utils/excel_duraciones.py
# Descripción: Convierte celdas Excel ([h]:mm, seriales, texto) a horas decimales y datetimes con tz

from __future__ import annotations

import datetime as dt
import math
import re
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd

TZ_AR = ZoneInfo("America/Argentina/Buenos_Aires")

# openpyxl convierte el serial s en datetime: s < 60 → 1899-12-31 + s; s ≥ 61 → 1899-12-30 + s
# (Excel cuenta el 29/02/1900 inexistente). Una duración [h]:mm es el serial en días.
_EPOCH_CORTO = dt.datetime(1899, 12, 31)
_EPOCH_LARGO = dt.datetime(1899, 12, 30)
_LIMITE_EPOCH = dt.datetime(1900, 3, 1)
_VACIOS = {"", "-", "nan", "none", "null", "nat"}
_HMS_RE = re.compile(r"^(\d+):(\d{1,2})(?::(\d{1,2}(?:\.\d+)?))?$")


def _es_vacio(valor: object) -> bool:
    if valor is None or valor is pd.NaT or valor is pd.NA:
        return True
    if isinstance(valor, float) and math.isnan(valor):
        return True
    return isinstance(valor, str) and valor.strip().lower() in _VACIOS


def duracion_a_horas(valor: object) -> float | None:
    """Horas decimales de una celda de duración. Números puros = serial Excel en días."""
    if _es_vacio(valor):
        return None
    if isinstance(valor, (dt.timedelta, pd.Timedelta)):
        return pd.Timedelta(valor).total_seconds() / 3600
    if isinstance(valor, dt.datetime):  # incluye pd.Timestamp
        ingenuo = pd.Timestamp(valor).tz_localize(None).to_pydatetime()
        epoch = _EPOCH_LARGO if ingenuo >= _LIMITE_EPOCH else _EPOCH_CORTO
        return (ingenuo - epoch).total_seconds() / 3600
    if isinstance(valor, dt.time):
        return valor.hour + valor.minute / 60 + (valor.second + valor.microsecond / 1e6) / 3600
    if isinstance(valor, (int, float, Decimal)) and not isinstance(valor, bool):
        return float(valor) * 24
    texto = str(valor).strip().replace(",", ".")
    coincidencia = _HMS_RE.match(texto)
    if coincidencia:
        horas, minutos, segundos = coincidencia.groups()
        return int(horas) + int(minutos) / 60 + float(segundos or 0) / 3600
    try:
        return float(texto)
    except ValueError:
        pass
    try:
        return pd.to_timedelta(texto).total_seconds() / 3600
    except (ValueError, TypeError):
        return None


def fecha_excel(valor: object, tz: ZoneInfo = TZ_AR) -> pd.Timestamp | None:
    """Datetime con tz a partir de serial Excel, datetime o texto (ISO primero, luego dd/mm/aaaa)."""
    if _es_vacio(valor):
        return None
    if isinstance(valor, (int, float, Decimal)) and not isinstance(valor, bool):
        ts = pd.Timestamp(_EPOCH_LARGO) + pd.to_timedelta(float(valor), unit="D")
        ts = ts.round("s")
    elif isinstance(valor, dt.datetime):
        ts = pd.Timestamp(valor)
    else:
        texto = str(valor).strip()
        dayfirst = not re.match(r"^\d{4}-\d{2}-\d{2}", texto)
        ts = pd.to_datetime(texto, dayfirst=dayfirst, errors="coerce")
        if pd.isna(ts):
            return None
    return ts.tz_localize(tz) if ts.tzinfo is None else ts.tz_convert(tz)
