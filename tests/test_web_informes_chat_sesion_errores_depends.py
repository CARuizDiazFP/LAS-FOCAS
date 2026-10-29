# Nombre de archivo: test_web_informes_chat_sesion_errores_depends.py
# Ubicación de archivo: tests/test_web_informes_chat_sesion_errores_depends.py
# Descripción: Routers de Informes, Chat y Sesión: sesión vía Depends (401/403) y 500 con ref sin exponer el texto de la excepción

from __future__ import annotations

import io
import logging
import re
from types import SimpleNamespace

import psycopg
import pytest
from fastapi.testclient import TestClient

from core.services.report_history import InMemoryReportHistory
from tests.test_web_admin import _connect_admin_ok, _connect_user_ok
from tests.test_web_rutas_contrato import muestra_de_ruta
from web.app.dependencias import usuario_admin
from web.app.main import app
from web.app.routers import chat, informes, sesion

REF = re.compile(r"^Error interno \(ref ([0-9a-f]{8})\)$")
SECRETO = "secreto-interno-xyz"


def _cliente() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _registros(caplog, prefijo: str) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "web" and r.getMessage().startswith(prefijo)]


def _roto(*_args, **_kwargs):
    raise RuntimeError(SECRETO)


def _cliente_logueado(monkeypatch, rol: str = "user") -> tuple[TestClient, str]:
    """Login real (cookie + CSRF): el chat usa su propia dependencia y varios POST validan el CSRF siempre."""
    if rol == "admin":
        monkeypatch.setattr(psycopg, "connect", _connect_admin_ok("admin"))
        credenciales = {"username": "admin", "password": "admin"}
    else:
        monkeypatch.setattr(psycopg, "connect", _connect_user_ok("userpass"))
        credenciales = {"username": "user", "password": "userpass"}
    client = _cliente()
    res = client.post("/api/auth/login", json=credenciales)
    assert res.json()["ok"] is True
    return client, res.json()["csrf"]


@pytest.fixture(autouse=True)
def _modo_test(monkeypatch):
    # Varios POST validan CSRF salvo con TESTING=true; no depender del entorno del que corre pytest.
    monkeypatch.setenv("TESTING", "true")


@pytest.fixture
def historia(monkeypatch) -> InMemoryReportHistory:
    h = InMemoryReportHistory()
    monkeypatch.setattr(informes, "REPORT_HISTORY", h)
    return h


# --- 403 admin (introspección) -----------------------------------------------------------------------


def _llama_a(dependant, objetivo) -> bool:
    return any(d.call is objetivo or _llama_a(d, objetivo) for d in dependant.dependencies)


_RUTAS_ADMIN = sorted(
    (metodo, ruta.path)
    for modulo in (informes, chat, sesion)
    for ruta in modulo.router.routes
    if _llama_a(ruta.dependant, usuario_admin)
    for metodo in ruta.methods - {"HEAD", "OPTIONS"}
)


def test_hay_rutas_admin_detectadas():
    assert ("GET", "/api/admin/me") in _RUTAS_ADMIN


@pytest.mark.parametrize(("metodo", "plantilla"), _RUTAS_ADMIN)
def test_toda_ruta_admin_da_403_a_un_usuario_comun(con_sesion, metodo, plantilla):
    # Introspección: cualquier ruta que dependa de usuario_admin, aunque no tenga test propio.
    con_sesion("user")
    kwargs = {"json": {}} if metodo in {"POST", "PUT", "PATCH", "DELETE"} else {}
    res = _cliente().request(metodo, muestra_de_ruta(plantilla), **kwargs)
    assert res.status_code == 403, f"{metodo} {plantilla} respondió {res.status_code}"


def test_admin_me_con_admin(con_sesion):
    con_sesion("admin", username="jefa")
    res = _cliente().get("/api/admin/me")
    assert res.status_code == 200
    assert res.json() == {"username": "jefa", "role": "admin"}


def test_alta_de_usuario_conserva_su_403_solo_admin(con_sesion):
    # Usa usuario_sesion + su propio chequeo de rol (no usuario_admin) para conservar este cuerpo.
    con_sesion("user")
    res = _cliente().post("/api/admin/users", data={"username": "x", "password": "y", "csrf_token": "z"})
    assert res.status_code == 403
    assert res.json() == {"error": "Solo admin"}


# --- 401 sin sesión ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("metodo", "path", "kwargs"),
    [
        ("POST", "/api/flows/sla", {"json": {}}),
        ("POST", "/api/flows/repetitividad", {"json": {}}),
        ("POST", "/api/tools/alarmas-ciena", {}),
        ("POST", "/api/tools/compare-vlans", {"json": {}}),
        ("POST", "/api/reports/sla", {}),
        ("POST", "/api/reports/sla-consumo", {}),
        ("GET", "/api/reports/history?limit=x", {}),
        ("POST", "/api/flows/comparador-fo", {}),
        ("POST", "/api/users/change-password", {}),
        ("POST", "/api/admin/users", {}),
        ("GET", "/api/admin/me", {}),
        ("GET", "/reports/sla.docx", {}),
    ],
)
def test_sin_sesion_da_401_aunque_el_pedido_sea_invalido(con_sesion, metodo, path, kwargs):
    con_sesion(None)
    res = _cliente().request(metodo, path, **kwargs)
    assert res.status_code == 401
    assert res.json() == {"detail": "No autenticado"}


def test_reports_sin_sesion_no_toca_el_filesystem(monkeypatch):
    llamadas: list[object] = []

    def _path_espia(*args):
        llamadas.append(args)
        raise AssertionError("no debería resolver el path sin sesión")

    monkeypatch.setattr(informes, "Path", _path_espia)
    for metodo in ("GET", "HEAD"):
        assert _cliente().request(metodo, "/reports/sla.docx").status_code == 401
    assert llamadas == []


@pytest.mark.parametrize(
    ("metodo", "path", "kwargs"),
    [
        # El mensaje es válido: antes respondía 200 sin sesión.
        ("POST", "/api/chat/message", {"data": {"text": "hola"}}),
        ("POST", "/api/chat/uploads", {}),
        ("POST", "/mcp/invoke", {"json": {}}),
        ("GET", "/api/chat/history?limit=x", {}),
        ("GET", "/api/chat/metrics", {}),
        ("GET", "/api/chat/ws-history", {}),
    ],
)
def test_chat_sin_sesion_da_401_con_su_cuerpo_de_siempre(metodo, path, kwargs):
    res = _cliente().request(metodo, path, **kwargs)
    assert res.status_code == 401
    assert res.json() == {"error": "No autenticado"}


# --- CSRF conservado -----------------------------------------------------------------------------------


def test_chat_mensaje_conserva_el_csrf(monkeypatch):
    client, _csrf = _cliente_logueado(monkeypatch)
    monkeypatch.setenv("TESTING", "false")
    res = client.post("/api/chat/message", data={"text": "hola", "csrf_token": "malo"})
    assert res.status_code == 403
    assert res.json() == {"error": "CSRF inválido"}


def test_flow_sla_conserva_el_csrf(monkeypatch):
    client, _csrf = _cliente_logueado(monkeypatch)
    monkeypatch.setenv("TESTING", "false")
    res = client.post("/api/flows/sla", data={"mes": "1", "anio": "2025", "csrf_token": "malo"})
    assert res.status_code == 403
    assert res.json() == {"error": "CSRF inválido"}


# --- 500 con ref y sin texto interno -------------------------------------------------------------------


def test_login_error_inesperado_500_con_ref(monkeypatch, caplog):
    monkeypatch.setattr(psycopg, "connect", _roto)
    with caplog.at_level(logging.ERROR, logger="web"):
        res = _cliente().post("/api/auth/login", json={"username": "pepe", "password": "x"})
    assert res.status_code == 500
    assert res.json()["ok"] is False
    ref = REF.match(res.json()["error"]).group(1)
    assert SECRETO not in res.text
    assert _registros(caplog, "action=api_login result=error") == [
        f"action=api_login result=error username=pepe ip=testclient error={SECRETO} ref={ref}"
    ]


def test_cambio_de_contrasena_500_con_ref(monkeypatch, caplog):
    client, csrf = _cliente_logueado(monkeypatch)
    monkeypatch.setattr(psycopg, "connect", _roto)
    with caplog.at_level(logging.ERROR, logger="web"):
        res = client.post(
            "/api/users/change-password",
            data={"current_password": "a", "new_password": "b", "csrf_token": csrf},
        )
    assert res.status_code == 500
    ref = REF.match(res.json()["error"]).group(1)
    assert SECRETO not in res.text
    assert _registros(caplog, "action=change_password_error") == [
        f"action=change_password_error user=user error={SECRETO} ref={ref}"
    ]


def test_alta_de_usuario_500_con_ref(monkeypatch, caplog):
    client, csrf = _cliente_logueado(monkeypatch, "admin")
    monkeypatch.setattr(psycopg, "connect", _roto)
    with caplog.at_level(logging.ERROR, logger="web"):
        res = client.post("/api/admin/users", data={"username": "nuevo", "password": "x", "csrf_token": csrf})
    assert res.status_code == 500
    ref = REF.match(res.json()["error"]).group(1)
    assert SECRETO not in res.text
    assert _registros(caplog, "action=admin_create_user_error") == [
        f"action=admin_create_user_error user=admin username=nuevo error={SECRETO} ref={ref}"
    ]


def test_historial_del_chat_500_con_ref(monkeypatch, caplog):
    client, _csrf = _cliente_logueado(monkeypatch)
    monkeypatch.setattr(chat, "psycopg", SimpleNamespace(connect=_roto))
    with caplog.at_level(logging.WARNING, logger="web"):
        res = client.get("/api/chat/history")
    assert res.status_code == 500
    ref = REF.match(res.json()["error"]).group(1)
    assert SECRETO not in res.text
    assert _registros(caplog, "action=chat_history") == [f"action=chat_history error={SECRETO} ref={ref}"]


class _OrquestadorRoto:
    async def ensure_session(self, user):  # noqa: ANN001
        return "s1"

    async def handle_message(self, **_kwargs):
        raise RuntimeError(SECRETO)
        yield  # pragma: no cover - generador async


def test_mcp_invoke_500_con_ref_conserva_status_y_message(monkeypatch, caplog):
    client, _csrf = _cliente_logueado(monkeypatch)
    monkeypatch.setattr(app.state, "chat_orchestrator", _OrquestadorRoto(), raising=False)
    with caplog.at_level(logging.ERROR, logger="web"):
        res = client.post("/mcp/invoke", json={"tool": "PingTool"})
    assert res.status_code == 500
    body = res.json()
    ref = REF.match(body.pop("error")).group(1)
    assert body == {"status": "error", "message": "Fallo ejecutando la herramienta"}
    assert SECRETO not in res.text
    assert _registros(caplog, "action=mcp_http_invoke_error") == [
        f"action=mcp_http_invoke_error user=user session_id=s1 tool=PingTool error={SECRETO} ref={ref}"
    ]


def _csv(contenido: bytes = b"a,b\n1,2\n"):
    return {"file": ("alarmas.csv", io.BytesIO(contenido), "text/csv")}


def test_alarmas_ciena_500_con_ref(monkeypatch, caplog):
    import core.parsers.alarmas_ciena as parser

    client, csrf = _cliente_logueado(monkeypatch)
    monkeypatch.setattr(parser, "parsear_alarmas_ciena", _roto)
    with caplog.at_level(logging.ERROR, logger="web"):
        res = client.post("/api/tools/alarmas-ciena", data={"csrf_token": csrf}, files=_csv())
    assert res.status_code == 500
    ref = REF.match(res.json()["error"]).group(1)
    assert SECRETO not in res.text
    assert _registros(caplog, "action=alarmas_ciena_error") == [
        f"action=alarmas_ciena_error user=user error={SECRETO} ref={ref}"
    ]


def test_alarmas_ciena_value_error_conserva_415_con_su_mensaje(monkeypatch):
    import core.parsers.alarmas_ciena as parser

    def _formato_no_soportado(_contenido):
        raise ValueError("Formato de CSV no reconocido")

    client, csrf = _cliente_logueado(monkeypatch)
    monkeypatch.setattr(parser, "parsear_alarmas_ciena", _formato_no_soportado)
    res = client.post("/api/tools/alarmas-ciena", data={"csrf_token": csrf}, files=_csv())
    assert res.status_code == 415
    assert res.json() == {"error": "Formato de CSV no reconocido"}


def test_alarmas_ciena_415_no_expone_texto_de_pandas(monkeypatch):
    import core.parsers.alarmas_ciena as parser

    interno = "Error tokenizing data. C error: /srv/interno/pandas.py line 42"

    def _roto(*_a, **_k):
        raise RuntimeError(interno)

    client, csrf = _cliente_logueado(monkeypatch)
    monkeypatch.setattr(parser.pd, "read_csv", _roto)
    contenido = b'"Unit","Class","Severity","Service"\n"a","b","c","d"\n'
    res = client.post("/api/tools/alarmas-ciena", data={"csrf_token": csrf}, files=_csv(contenido))
    assert res.status_code == 415
    assert interno not in res.text and "pandas" not in res.text
    assert "CSV válido de alarmas Ciena" in res.json()["error"]


def test_flow_sla_500_con_ref(monkeypatch, caplog):
    client, csrf = _cliente_logueado(monkeypatch)
    monkeypatch.setattr(informes.sla_service, "compute_from_db", _roto)
    with caplog.at_level(logging.ERROR, logger="web"):
        res = client.post("/api/flows/sla", data={"mes": "3", "anio": "2025", "csrf_token": csrf})
    assert res.status_code == 500
    ref = REF.match(res.json()["error"]).group(1)
    assert SECRETO not in res.text
    assert _registros(caplog, "action=sla_flow stage=unexpected") == [
        f"action=sla_flow stage=unexpected source=db mes=3 anio=2025 error={SECRETO} ref={ref}"
    ]


def test_flow_sla_value_error_conserva_422_con_su_mensaje(monkeypatch):
    def _sin_datos(**_kwargs):
        raise ValueError("No hay datos para el período")

    client, csrf = _cliente_logueado(monkeypatch)
    monkeypatch.setattr(informes.sla_service, "compute_from_db", _sin_datos)
    res = client.post("/api/flows/sla", data={"mes": "3", "anio": "2025", "csrf_token": csrf})
    assert res.status_code == 422
    assert res.json() == {"error": "No hay datos para el período"}


def test_flow_repetitividad_500_registra_el_mismo_mensaje_en_el_historial(monkeypatch, caplog, historia):
    client, csrf = _cliente_logueado(monkeypatch)
    monkeypatch.setattr(informes, "reclamos_from_db", _roto)
    with caplog.at_level(logging.ERROR, logger="web"):
        res = client.post("/api/flows/repetitividad", data={"mes": "7", "anio": "2024", "csrf_token": csrf})
    assert res.status_code == 500
    ref = REF.match(res.json()["error"]).group(1)
    assert SECRETO not in res.text
    (registro,) = historia.list_records(report_type="repetitividad", status="error")
    assert (registro["error_code"], registro["error_message"]) == ("HTTP_500", res.json()["error"])
    assert _registros(caplog, "action=flow_repetitividad stage=unexpected") == [
        f"action=flow_repetitividad stage=unexpected periodo=07/2024 error={SECRETO} ref={ref}"
    ]


def test_flow_repetitividad_value_error_conserva_422_y_el_historial(monkeypatch, historia):
    def _invalido(_mes, _anio):
        raise ValueError("Columnas faltantes")

    client, csrf = _cliente_logueado(monkeypatch)
    monkeypatch.setattr(informes, "reclamos_from_db", _invalido)
    res = client.post("/api/flows/repetitividad", data={"mes": "7", "anio": "2024", "csrf_token": csrf})
    assert res.status_code == 422
    assert res.json() == {"error": "Columnas faltantes"}
    (registro,) = historia.list_records(report_type="repetitividad", status="error")
    assert (registro["error_code"], registro["error_message"]) == ("HTTP_422", "Columnas faltantes")


def test_sla_consumo_500_con_ref_y_mismo_mensaje_en_el_historial(monkeypatch, caplog, historia):
    from tests.test_web_sla_flow import _reclamos_excel_bytes, _servicios_excel_bytes

    client, csrf = _cliente_logueado(monkeypatch)
    monkeypatch.setattr(informes.sla_consumo_service, "generar_informe_sla_consumo", _roto)
    with caplog.at_level(logging.ERROR, logger="web"):
        res = client.post(
            "/api/reports/sla-consumo",
            data={"csrf_token": csrf},
            files=[
                ("files", ("servicios.xlsx", io.BytesIO(_servicios_excel_bytes()))),
                ("files", ("reclamos.xlsx", io.BytesIO(_reclamos_excel_bytes()))),
            ],
        )
    assert res.status_code == 500
    assert res.json()["ok"] is False
    ref = REF.match(res.json()["error"]).group(1)
    assert SECRETO not in res.text
    (registro,) = historia.list_records(report_type="sla_consumo", status="error")
    assert (registro["error_code"], registro["error_message"]) == ("HTTP_500", res.json()["error"])
    assert _registros(caplog, "action=sla_consumo_web stage=unexpected") == [
        f"action=sla_consumo_web stage=unexpected user=user ref={ref}"
    ]
