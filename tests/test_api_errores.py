# Nombre de archivo: test_api_errores.py
# Ubicación de archivo: tests/test_api_errores.py
# Descripción: Errores tipados + error_interno con ref en la API interna; la API v1 conserva su 500 de siempre

from __future__ import annotations

import json
import logging
import re

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.app import main as api_main
from api.app.errores import (
    Conflicto,
    DatoInvalido,
    ErrorDeDominio,
    NoEncontrado,
    error_interno,
    manejar_error_de_dominio,
    manejar_error_no_controlado,
)
from api.app.routes import health
from api.app.routes.v1.oauth import router as v1_oauth_router
from db.session import get_async_db

REF = re.compile(r"^Error interno \(ref ([0-9a-f]{8})\)$")
FORM_TOKEN = {"grant_type": "client_credentials", "client_id": "lf_noc", "client_secret": "x"}


def _registros(caplog, accion: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "api" and r.getMessage().startswith(f"action={accion}_error")]


def test_app_api_registra_handlers_y_no_toca_los_de_fastapi():
    for app in (api_main.app, api_main.create_app()):
        handlers = app.exception_handlers
        assert handlers[ErrorDeDominio] is manejar_error_de_dominio
        assert handlers[Exception] is manejar_error_no_controlado
        assert handlers[StarletteHTTPException] is http_exception_handler
        assert handlers[RequestValidationError] is request_validation_exception_handler


def _mini_app() -> FastAPI:
    mini = FastAPI()
    mini.add_exception_handler(ErrorDeDominio, manejar_error_de_dominio)
    mini.add_exception_handler(Exception, manejar_error_no_controlado)

    @mini.get("/dominio/{tipo}")
    async def dominio(tipo: str):
        clases = {"404": NoEncontrado, "422": DatoInvalido, "409": Conflicto, "400": ErrorDeDominio}
        raise clases[tipo](f"mensaje {tipo}")

    @mini.get("/http")
    async def http():
        raise HTTPException(status_code=404, detail="No existe")

    return mini


@pytest.mark.parametrize(("tipo", "status"), [("404", 404), ("422", 422), ("409", 409), ("400", 400)])
def test_error_de_dominio_responde_detail_y_status(tipo, status):
    res = TestClient(_mini_app()).get(f"/dominio/{tipo}")
    assert (res.status_code, res.json()) == (status, {"detail": f"mensaje {tipo}"})


def test_http_exception_sigue_como_fastapi():
    res = TestClient(_mini_app()).get("/http")
    assert (res.status_code, res.json()) == (404, {"detail": "No existe"})


def test_500_no_controlado_en_api_interna_con_ref_sin_texto_interno(monkeypatch, caplog):
    """App real: /health (fuera de v1) revienta → 500 JSON con ref; la ref queda en el log."""
    caplog.set_level(logging.INFO, logger="api")

    async def _db_health_roto():
        raise RuntimeError("password=secreto host=db")

    monkeypatch.setattr(health, "db_health", _db_health_roto)
    res = TestClient(api_main.app, raise_server_exceptions=False).get("/health")

    assert res.status_code == 500
    assert res.headers["content-type"] == "application/json"
    assert list(res.json()) == ["detail"]
    ref = REF.match(res.json()["detail"]).group(1)
    assert "secreto" not in res.text
    (registro,) = _registros(caplog, "unhandled")
    assert registro.getMessage() == (
        f"action=unhandled_error method=GET path=/health error=password=secreto host=db ref={ref}"
    )
    assert registro.exc_info and isinstance(registro.exc_info[1], RuntimeError)


def _post_token_con_db_rota(app: FastAPI) -> object:
    async def _db_rota():
        raise RuntimeError("secreto-v1")

    app.dependency_overrides[get_async_db] = _db_rota
    try:
        return TestClient(app, raise_server_exceptions=False).post("/api/v1/oauth/token", data=FORM_TOKEN)
    finally:
        app.dependency_overrides.pop(get_async_db, None)


def test_500_no_controlado_en_v1_es_identico_al_de_starlette_sin_handler(caplog):
    caplog.set_level(logging.INFO, logger="api")
    sin_handler = FastAPI()
    sin_handler.include_router(v1_oauth_router)

    antes = _post_token_con_db_rota(sin_handler)
    ahora = _post_token_con_db_rota(api_main.app)

    assert (ahora.status_code, ahora.content) == (antes.status_code, antes.content) == (500, b"Internal Server Error")
    assert ahora.headers["content-type"] == antes.headers["content-type"]
    # Igual se loguea con ref para poder rastrearlo.
    (registro,) = _registros(caplog, "unhandled")
    assert registro.getMessage().startswith("action=unhandled_error method=POST path=/api/v1/oauth/token error=secreto-v1 ref=")


def test_error_interno_formato_de_log_y_cuerpo_extra(caplog):
    caplog.set_level(logging.INFO, logger="api")
    exc = ValueError("boom")
    res = error_interno("get_servicio_rutas", exc, cuerpo={"ok": False, "detail": "pisado"}, servicio_id=7)
    cuerpo = json.loads(res.body)

    assert res.status_code == 500
    assert list(cuerpo) == ["ok", "detail"] and cuerpo["ok"] is False
    ref = REF.match(cuerpo["detail"]).group(1)
    (registro,) = _registros(caplog, "get_servicio_rutas")
    assert registro.getMessage() == f"action=get_servicio_rutas_error servicio_id=7 error=boom ref={ref}"
    assert registro.exc_info[1] is exc
