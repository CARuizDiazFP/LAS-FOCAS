# Nombre de archivo: test_timefmt.py
# Ubicación de archivo: tests/test_timefmt.py
# Descripción: Pruebas unitarias para utilidades de conversión HH:MM

import pandas as pd

from core.utils.timefmt import minutes_to_hhmm, value_to_minutes


def test_value_to_minutes_accepts_various_formats():
    assert value_to_minutes("2:05") == 125
    assert value_to_minutes("26:40:59") == 1600
    assert value_to_minutes("12,5") == 750
    assert value_to_minutes(5.5) == 330
    assert value_to_minutes(pd.Timedelta(hours=1, minutes=15)) == 75
    assert value_to_minutes(None) is None


def test_minutes_to_hhmm_formats_numbers_and_strings():
    assert minutes_to_hhmm(125) == "2:05"
    assert minutes_to_hhmm("3:07") == "3:07"
    assert minutes_to_hhmm(pd.Timedelta(hours=1, minutes=1, seconds=59)) == "1:01"
    assert minutes_to_hhmm(None) == "-"
