# Nombre de archivo: test_contrato_infra_web_api.py
# Ubicación de archivo: tests/test_contrato_infra_web_api.py
# Descripción: Contrato web/API de las rutas /api/infra duplicadas que se resuelven antes de tocar la base (P12, Task 1)

"""Fija el contrato actual (status, claves, tipos) de las 16 rutas duplicadas entre `web/app` y
`api/app` ANTES de mover su lógica a `core/services`. Este archivo cubre sólo lo que se decide sin
consultar la base (validaciones 422 de la API y el tope de 6 MB del panel); el resto está en
`test_contrato_infra_web_api_real_db.py`. Las tareas siguientes sólo editan las aserciones que una
decisión D1-D12 cambie."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.app.main import app as app_api
from web.app.main import app as app_web

API_HEADERS = {"Authorization": "Bearer test-api-key"}


def cliente_web(con_sesion, rol: str = "admin") -> TestClient:
    """Cliente del panel con sesión simulada (el CSRF se saltea con TESTING: sólo importa la forma)."""
    con_sesion(rol)
    return TestClient(app_web)


def cliente_api() -> TestClient:
    """Cliente de la API interna con la API key de los tests."""
    return TestClient(app_api, headers=API_HEADERS)


def assert_forma(payload: dict, claves: dict[str, type | tuple[type, ...]]) -> None:
    """Verifica el conjunto EXACTO de claves de `payload` y el tipo de cada valor (`bool` no cuenta como int)."""
    assert isinstance(payload, dict), payload
    assert set(payload) == set(claves), (
        f"sobran {sorted(set(payload) - set(claves))}, faltan {sorted(set(claves) - set(payload))}"
    )
    for clave, esperado in claves.items():
        tipos = esperado if isinstance(esperado, tuple) else (esperado,)
        valor = payload[clave]
        assert isinstance(valor, tipos), f"{clave}: {type(valor).__name__} no es {tipos}"
        if bool not in tipos:
            assert not isinstance(valor, bool), f"{clave}: bool donde se esperaba {tipos}"


# --- API: validaciones 422 (se resuelven antes de abrir la sesión) ---------------------------------

def test_api_search_field_invalido_422():
    res = cliente_api().post(
        "/api/infra/search",
        json={"filters": [{"field": "x", "operator": "eq", "value": "a"}], "limit": 5},
    )
    assert res.status_code == 422
    assert_forma(res.json(), {"detail": list})


def test_api_smart_search_mas_de_20_terminos_422():
    res = cliente_api().post("/api/infra/smart-search", json={"terms": ["a"] * 21, "limit": 5})
    assert res.status_code == 422
    assert_forma(res.json(), {"detail": list})


def test_api_export_format_invalido_422():
    res = cliente_api().get("/api/infra/export/cameras", params={"format": "XLSX"})
    assert res.status_code == 422
    assert_forma(res.json(), {"detail": list})


# --- Panel: validaciones de smart-search (D2: los mismos límites que la API) ----------------------

def test_web_smart_search_limit_cero_422(con_sesion):
    res = cliente_web(con_sesion).post("/api/infra/smart-search", json={"terms": [], "limit": 0})
    assert res.status_code == 422


def test_web_smart_search_mas_de_20_terminos_422(con_sesion):
    res = cliente_web(con_sesion).post("/api/infra/smart-search", json={"terms": ["a"] * 21, "limit": 5})
    assert res.status_code == 422


# --- Web: tope de 5 MB del upload de tracking ------------------------------------------------------

def test_web_upload_tracking_6mb_413(con_sesion):
    grande = b"x" * (6 * 1024 * 1024)
    res = cliente_web(con_sesion).post(
        "/api/infra/upload_tracking", files={"file": ("grande.txt", grande, "text/plain")}
    )
    assert res.status_code == 413
    assert_forma(res.json(), {"error": str})
