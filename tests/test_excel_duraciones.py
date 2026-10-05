# Nombre de archivo: test_excel_duraciones.py
# Ubicación de archivo: tests/test_excel_duraciones.py
# Descripción: Conversión de celdas Excel [h]:mm y fechas seriales a horas/datetime

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pandas as pd
import pytest

from core.utils.excel_duraciones import TZ_AR, duracion_a_horas, fecha_excel


@pytest.mark.parametrize(
    "valor, esperado",
    [
        (dt.time(11, 41, 6), 11 + 41 / 60 + 6 / 3600),
        (dt.datetime(1900, 1, 1, 17, 55, 47), 24 + 17 + 55 / 60 + 47 / 3600),   # 41.93 h
        (dt.datetime(1900, 1, 16, 6, 3, 32), 16 * 24 + 6 + 3 / 60 + 32 / 3600),  # 390.06 h
        (dt.datetime(1900, 3, 1, 0, 0), 61 * 24.0),  # serial 61: epoch corrido por el 29/02/1900
        (pd.Timestamp("1900-01-02 06:00:00"), 54.0),
        (dt.timedelta(hours=30), 30.0),
        (0.5, 12.0),                   # serial en días
        (Decimal("1.25"), 30.0),
        ("030:15:00", 30.25),
        ("1,5", 1.5),                  # texto decimal = horas
        ("1 days 06:00:00", 30.0),
        ("-", None), ("", None), (None, None), (float("nan"), None),
    ],
)
def test_duracion_a_horas(valor, esperado):
    resultado = duracion_a_horas(valor)
    if esperado is None:
        assert resultado is None
    else:
        assert resultado == pytest.approx(esperado, abs=1e-6)


def test_fecha_excel_serial_y_iso_no_invierte_dia_mes():
    serial = fecha_excel(45957.5)
    assert serial == pd.Timestamp("2025-10-27 12:00:00", tz=TZ_AR)
    assert fecha_excel("2025-12-09 12:00:00") == pd.Timestamp("2025-12-09 12:00:00", tz=TZ_AR)
    assert fecha_excel("09/12/2025 12:00") == pd.Timestamp("2025-12-09 12:00:00", tz=TZ_AR)
    assert fecha_excel(dt.datetime(2026, 1, 5, 7, 44)) == pd.Timestamp("2026-01-05 07:44", tz=TZ_AR)
    assert fecha_excel("-") is None
    assert fecha_excel(None) is None
