# Nombre de archivo: test_tracking_resolve_rutas.py
# Ubicación de archivo: tests/test_tracking_resolve_rutas.py
# Descripción: POST /api/infra/trackings/resolve del panel y de la API comparten parseo y serialización (P12, Task 11)

from __future__ import annotations

from contextlib import contextmanager

from fastapi.testclient import TestClient

from api.app.main import app as app_api
from api.app.routes import infra as api_infra
from core.services.infra_service import ResolveAction, ResolveResult
from web.app.main import app as app_web
from web.app.routers import servicios as web_servicios

API_HEADERS = {"Authorization": "Bearer test-api-key"}
URL = "/api/infra/trackings/resolve"


@contextmanager
def _sesion_falsa():
    yield object()


def _parchear(monkeypatch, modulo, resultado: ResolveResult) -> list[dict]:
    """Reemplaza `resolve_tracking_file` y `SessionLocal` del módulo; devuelve las llamadas."""
    llamadas: list[dict] = []

    def _falso(_sesion, accion, contenido, nombre, **kw):
        llamadas.append({"accion": accion, "contenido": contenido, "nombre": nombre, **kw})
        return resultado

    monkeypatch.setattr(modulo, "resolve_tracking_file", _falso)
    monkeypatch.setattr(modulo, "SessionLocal", _sesion_falsa)
    return llamadas


def _web(con_sesion) -> TestClient:
    con_sesion("admin")
    return TestClient(app_web)


def test_panel_confirm_upgrade_solo_old_service_id_no_da_400(monkeypatch, con_sesion):
    """B1: el SPA manda sólo `old_service_id`; antes el panel exigía también `old_service_db_id`."""
    llamadas = _parchear(
        monkeypatch,
        web_servicios,
        ResolveResult(success=True, action=ResolveAction.CONFIRM_UPGRADE, servicio_id="2", ruta_id=5),
    )
    res = _web(con_sesion).post(
        URL,
        json={"action": "confirm_upgrade", "content": "x", "filename": "f.txt", "old_service_id": "1"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["success"] is True and res.json()["action"] == "CONFIRM_UPGRADE"
    assert llamadas[0]["accion"] is ResolveAction.CONFIRM_UPGRADE
    assert llamadas[0]["old_service_id"] == "1"


def test_panel_confirm_upgrade_viejo_inexistente_success_false_sin_excepcion(monkeypatch, con_sesion):
    _parchear(
        monkeypatch,
        web_servicios,
        ResolveResult(
            success=False,
            action=ResolveAction.CONFIRM_UPGRADE,
            servicio_id="2",
            error="Servicio viejo 'ZZ-NO-EXISTE' no encontrado",
        ),
    )
    res = _web(con_sesion).post(
        URL,
        json={"action": "CONFIRM_UPGRADE", "content": "x", "filename": "f.txt", "old_service_id": "ZZ-NO-EXISTE"},
    )
    assert res.status_code == 200
    assert res.json()["success"] is False
    assert res.json()["error"] == "Servicio viejo 'ZZ-NO-EXISTE' no encontrado"


def test_panel_ruta_tipo_invalido_400(monkeypatch, con_sesion):
    _parchear(monkeypatch, web_servicios, ResolveResult(success=True, action=ResolveAction.BRANCH))
    res = _web(con_sesion).post(
        URL, json={"action": "BRANCH", "content": "x", "filename": "f.txt", "new_ruta_tipo": "x"}
    )
    assert res.status_code == 400
    assert list(res.json()) == ["error"]


def test_panel_skip_200_con_su_forma(con_sesion):
    res = _web(con_sesion).post(URL, json={"action": "skip", "content": "x", "filename": "f.txt"})
    assert res.status_code == 200
    assert res.json() == {"success": True, "action": "SKIP", "message": "Operación omitida por el usuario"}


def test_api_skip_200_con_response_model(monkeypatch):
    llamadas = _parchear(monkeypatch, api_infra, ResolveResult(success=True, action=ResolveAction.CREATE_NEW))
    res = TestClient(app_api, headers=API_HEADERS).post(
        URL, json={"action": "SKIP", "content": "x", "filename": "f.txt"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["success"] is True and res.json()["action"] == "SKIP"
    assert llamadas == []


def test_api_ruta_tipo_invalido_y_accion_invalida_400(monkeypatch):
    _parchear(monkeypatch, api_infra, ResolveResult(success=True, action=ResolveAction.BRANCH))
    cliente = TestClient(app_api, headers=API_HEADERS)
    res = cliente.post(URL, json={"action": "BRANCH", "content": "x", "filename": "f.txt", "new_ruta_tipo": "x"})
    assert res.status_code == 400 and list(res.json()) == ["detail"]
    res = cliente.post(URL, json={"action": "NO_EXISTE", "content": "x", "filename": "f.txt"})
    assert res.status_code == 400 and list(res.json()) == ["detail"]


def test_api_confirm_upgrade_pasa_old_service_id(monkeypatch):
    llamadas = _parchear(
        monkeypatch, api_infra, ResolveResult(success=True, action=ResolveAction.CONFIRM_UPGRADE, servicio_id="2")
    )
    res = TestClient(app_api, headers=API_HEADERS).post(
        URL, json={"action": "CONFIRM_UPGRADE", "content": "x", "filename": "f.txt", "old_service_id": "1"}
    )
    assert res.status_code == 200
    assert llamadas[0]["old_service_id"] == "1"
