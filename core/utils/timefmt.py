# Nombre de archivo: timefmt.py
# Ubicación de archivo: core/utils/timefmt.py
# Descripción: Conversión y formateo de valores horarios en minutos y texto HH:MM

from __future__ import annotations

import math
import re
from datetime import time, timedelta
from typing import Optional

import numpy as np
import pandas as pd

HHMM_RE = re.compile(r"^\s*(?P<h>\d{1,3}):(?P<m>\d{2})(?::(?P<s>\d{2}))?\s*$")
DECIMAL_RE = re.compile(r"^\s*\d+(?:[\.,]\d+)?\s*$")


def value_to_minutes(value: object) -> Optional[int]:
    """Convierte distintos formatos de duración a minutos enteros.

    Admite strings `HH:MM[:SS]`, números decimales (horas) y `timedelta`.
    Retorna ``None`` cuando no es posible parsear un valor válido.
    """

    if value is None or value is pd.NA:
        return None

    if isinstance(value, pd.Series):  # pragma: no cover - defensivo
        value = value.iloc[0]

    if isinstance(value, pd.Timedelta):
        return int(value.total_seconds() // 60)

    if isinstance(value, timedelta):
        return int(value.total_seconds() // 60)

    if hasattr(value, "total_seconds"):
        try:
            return int(value.total_seconds() // 60)
        except Exception:  # noqa: BLE001 - no es un timedelta válido
            return None

    if isinstance(value, time):
        return value.hour * 60 + value.minute

    if isinstance(value, (pd.Timestamp,)):
        # Un timestamp no representa una duración
        return None

    if isinstance(value, (int, np.integer)):
        return int(value)

    if isinstance(value, float):
        if math.isnan(value):
            return None
        frac, _ = math.modf(value)
        if frac:
            return int(round(value * 60))
        if value <= 24:  # valores enteros pequeños suelen representar horas
            return int(round(value * 60))
        # Valores enteros grandes (>= 24) se interpretan como minutos directos
        return int(value)

    text = str(value).strip()
    if not text:
        return None

    match = HHMM_RE.match(text)
    if match:
        hours = int(match.group("h"))
        minutes = int(match.group("m"))
        return hours * 60 + minutes

    if DECIMAL_RE.match(text):
        normalized = text.replace(",", ".")
        try:
            hours_float = float(normalized)
        except ValueError:  # pragma: no cover - ya validado con regex
            return None
        return int(round(hours_float * 60))

    return None


def minutes_to_hhmm(value: object) -> str:
    """Formatea un valor en minutos como ``HH:MM`` (sin segundos)."""

    if value is None or value is pd.NA:
        return "-"

    minutes: Optional[int]
    if isinstance(value, str):
        minutes = value_to_minutes(value)
    elif isinstance(value, (int, float, pd.Timedelta, timedelta)):
        minutes = value_to_minutes(value)
    else:
        minutes = value_to_minutes(value)

    if minutes is None:
        return "-"

    hours = minutes // 60
    mins = minutes % 60
    return f"{hours:d}:{mins:02d}"
