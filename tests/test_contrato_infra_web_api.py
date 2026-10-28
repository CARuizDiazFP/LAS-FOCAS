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


# --- Panel: validaciones de search (D2: los mismos modelos y límites que la API) -------------------

def test_web_search_field_invalido_422(con_sesion):
    res = cliente_web(con_sesion).post(
        "/api/infra/search", json={"filters": [{"field": "x", "operator": "eq", "value": "a"}], "limit": 5}
    )
    assert res.status_code == 422


def test_web_search_mas_de_10_filtros_422(con_sesion):
    filtros = [{"field": "address", "operator": "contains", "value": "a"}] * 11
    res = cliente_web(con_sesion).post("/api/infra/search", json={"filters": filtros, "limit": 5})
    assert res.status_code == 422


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


def test_web_ban_create_ticket_65_caracteres_422(con_sesion):
    """D2: el panel aplica el mismo límite de la API (antes: 200 success:false 'Error inesperado')."""
    res = cliente_web(con_sesion).post(
        "/api/infra/ban/create",
        json={"ticket_asociado": "T" * 65, "servicio_afectado_id": "1", "servicio_protegido_id": "2"},
    )
    assert res.status_code == 422


def test_api_ban_create_ticket_65_caracteres_422():
    res = cliente_api().post(
        "/api/infra/ban/create",
        json={"ticket_asociado": "T" * 65, "servicio_afectado_id": "1", "servicio_protegido_id": "2"},
    )
    assert res.status_code == 422
    assert_forma(res.json(), {"detail": list})


# --- Aviso de baneo por email (Task 8: D6, config en las dos apps) ---------------------------------

CLAVES_AVISO = {"success": bool, "message": str, "error": (str, type(None)), "recipients_count": int}


def _sin_smtp(monkeypatch) -> None:
    from types import SimpleNamespace

    from core.services import baneo_aviso

    monkeypatch.setattr(baneo_aviso, "get_email_service", lambda: SimpleNamespace(is_configured=lambda: False))


def test_web_notify_email_smtp_sin_configurar_200_success_false(con_sesion, monkeypatch):
    """D6: el panel deja de responder 500 con SMTP sin configurar (igual que la API)."""
    _sin_smtp(monkeypatch)
    res = cliente_web(con_sesion).post(
        "/api/infra/notify/email", json={"to": ["a@b.com"], "subject": "s", "body": "b"}
    )
    assert res.status_code == 200
    assert_forma(res.json(), CLAVES_AVISO)
    assert res.json()["success"] is False


def test_api_notify_email_smtp_sin_configurar_200_success_false(monkeypatch):
    _sin_smtp(monkeypatch)
    res = cliente_api().post(
        "/api/infra/notify/email",
        json={"to": ["a@b.com"], "subject": "s", "body": "b", "incidente_ids": [1]},
    )
    assert res.status_code == 200
    assert_forma(res.json(), CLAVES_AVISO)
    assert res.json()["success"] is False


def test_api_email_config_error_200_configured_false(monkeypatch):
    """Config de la API ante un error interno: 200 `configured:false` con ref (antes 500)."""
    from core.services import baneo_aviso

    def _roto():
        raise RuntimeError("secreto")

    monkeypatch.setattr(baneo_aviso, "get_email_service", _roto)
    res = cliente_api().get("/api/infra/notify/email/config")
    assert res.status_code == 200
    assert_forma(res.json(), {"configured": bool, "error": str})
    assert res.json()["configured"] is False and "secreto" not in res.text
