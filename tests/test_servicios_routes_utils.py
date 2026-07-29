# Nombre de archivo: test_servicios_routes_utils.py
# Ubicación de archivo: tests/test_servicios_routes_utils.py
# Descripción: Tests unitarios de utilidades internas del router de servicios

import pandas as pd

from api.app.routes.servicios import _chunked, _normalize_value


def test_chunked_particiona_en_bloques() -> None:
    rows = [{"i": idx} for idx in range(5)]

    chunks = _chunked(rows, size=2)

    assert [len(chunk) for chunk in chunks] == [2, 2, 1]
    assert chunks[0][0]["i"] == 0
    assert chunks[-1][0]["i"] == 4


def test_normalize_value_limpia_vacios_y_na() -> None:
    assert _normalize_value(None) is None
    assert _normalize_value("   ") is None
    assert _normalize_value(" hola ") == "hola"
    assert _normalize_value(pd.NA) is None
    assert _normalize_value(10) == 10
