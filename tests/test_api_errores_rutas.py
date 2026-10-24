# Nombre de archivo: test_api_errores_rutas.py
# Ubicación de archivo: tests/test_api_errores_rutas.py
# Descripción: Las rutas de la API interna (no v1) no exponen el texto de la excepción en los 500

from __future__ import annotations

import logging
import re
from types import SimpleNamespace

from fastapi.testclient import TestClient

from api.app.main import app
from api.app.routes import infra
from db.session import get_async_db

API_HEADERS = {"Authorization": "Bearer test-api-key"}
REF = re.compile(r"^Error interno \(ref ([0-9a-f]{8})\)$")
SECRETO = "password=secreto host=db"


def test_infra_500_con_ref_sin_texto_interno_y_log_con_ref(caplog):
    """GET /api/infra/camaras: la excepción de la DB no sale en la respuesta; el log lleva la ref."""
    caplog.set_level(logging.INFO, logger="api")

    async def _db_rota():
        raise RuntimeError(SECRETO)
        yield  # pragma: no cover

    app.dependency_overrides[get_async_db] = _db_rota
    try:
        res = TestClient(app, raise_server_exceptions=False).get("/api/infra/camaras", headers=API_HEADERS)
    finally:
        app.dependency_overrides.pop(get_async_db, None)

    assert res.status_code == 500
    assert SECRETO not in res.text
    assert list(res.json()) == ["detail"]
    assert REF.match(res.json()["detail"])


def test_notify_email_conserva_200_success_false_con_ref(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="infra")

    def _sesion_rota():
        raise RuntimeError(SECRETO)

    monkeypatch.setattr(infra, "get_email_service", lambda: SimpleNamespace(is_configured=lambda: True))
    monkeypatch.setattr(infra, "SessionLocal", _sesion_rota)
    res = TestClient(app).post(
        "/api/infra/notify/email",
        headers=API_HEADERS,
        json={"to": ["a@b.com"], "subject": "s", "body": "b", "incidente_ids": [1]},
    )

    assert res.status_code == 200
    cuerpo = res.json()
    assert cuerpo["success"] is False
    assert SECRETO not in res.text
    ref = REF.match(cuerpo["error"]).group(1)
    assert any(f"ref={ref}" in r.getMessage() for r in caplog.records)
