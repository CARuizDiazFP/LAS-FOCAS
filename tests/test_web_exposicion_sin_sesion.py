# Nombre de archivo: test_web_exposicion_sin_sesion.py
# Ubicación de archivo: tests/test_web_exposicion_sin_sesion.py
# Descripción: Red de seguridad: ninguna ruta de la SPA (salvo las públicas) responde 2xx sin sesión; y /reports exige sesión.

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.routing import Mount, WebSocketRoute

from tests.test_web_rutas_contrato import muestra_de_ruta
from web.app import main as web_main
from web.app.main import app
from web.app.routers import informes

# Rutas que por diseño no exigen sesión (plantilla tal como está registrada).
PUBLICAS = {
    "/health",
    "/health/version",
    "/api/auth/session",
    "/api/auth/login",
    "/api/auth/logout",
    "/logout",
    "/reports/index",
    "/{path:path}",
}

# Rutas que validaban el body antes que la sesión (422 sin sesión). Formato: (metodo, plantilla).
# Vacío desde la migración de todos los routers a Depends (plan 2026-10-23, Tasks 9-14): toda ruta
# no pública da 401/403 sin sesión antes de validar el pedido. No volver a agregar entradas.
PENDIENTES_DEPENDS: set[tuple[str, str]] = set()

# WebSocketRoute: no se prueban acá (el handshake sin sesión requiere un flujo propio de cada socket).
_METODOS_CON_BODY = {"POST", "PUT", "PATCH", "DELETE"}


def _casos() -> list[tuple[str, str]]:
    casos = []
    for ruta in app.router.routes:
        if isinstance(ruta, WebSocketRoute) or not isinstance(ruta, APIRoute):
            continue
        if ruta.path in PUBLICAS:
            continue
        for metodo in sorted(ruta.methods - {"HEAD", "OPTIONS"}):
            casos.append((metodo, ruta.path))
    return casos


@pytest.mark.parametrize(("metodo", "plantilla"), _casos())
def test_ruta_no_publica_exige_sesion(metodo, plantilla):
    client = TestClient(app, raise_server_exceptions=False)
    kwargs = {"json": {}} if metodo in _METODOS_CON_BODY else {}
    res = client.request(metodo, muestra_de_ruta(plantilla), follow_redirects=False, **kwargs)
    assert not (200 <= res.status_code < 300), f"{metodo} {plantilla} respondió {res.status_code} sin sesión"
    if (metodo, plantilla) in PENDIENTES_DEPENDS and res.status_code == 422:
        return
    assert res.status_code in (401, 403), f"{metodo} {plantilla} respondió {res.status_code} sin sesión"


def test_unico_mount_es_assets_del_spa():
    # El bug original era un Mount de StaticFiles sin sesión: el recorrido de APIRoute no lo ve.
    mounts = [r.path for r in app.router.routes if isinstance(r, Mount)]
    # /assets sólo se monta si existe web/frontend/dist (no en todos los entornos de test).
    assert set(mounts) <= {"/assets"}


def test_pendientes_depends_son_rutas_reales():
    existentes = set(_casos())
    assert PENDIENTES_DEPENDS <= existentes


# --- /reports ---------------------------------------------------------------


@pytest.fixture
def informes_tmp(tmp_path, monkeypatch):
    base = tmp_path / "reports"
    base.mkdir()
    (base / "sla.docx").write_bytes(b"contenido-docx")
    (base / "sub").mkdir()
    (base / "sub" / "x.pdf").write_bytes(b"%PDF-x")
    (tmp_path / "secreto.txt").write_text("fuera de la base")
    monkeypatch.setattr(informes, "_mount_reports", base)
    return base


@pytest.fixture
def client_con_sesion(monkeypatch):
    from tests.test_web_baneos import _connect_admin_ok

    client = TestClient(app)
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok("admin"))
    res = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert res.json()["ok"] is True
    return client


def test_reports_sin_sesion_401(informes_tmp):
    res = TestClient(app).get("/reports/sla.docx")
    assert res.status_code == 401


def test_reports_con_sesion_200(informes_tmp, client_con_sesion):
    res = client_con_sesion.get("/reports/sla.docx")
    assert res.status_code == 200
    assert res.content == b"contenido-docx"
    assert res.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert client_con_sesion.get("/reports/sub/x.pdf").content == b"%PDF-x"


def test_reports_head_sin_sesion_401_y_con_sesion_200(informes_tmp, client_con_sesion):
    # StaticFiles aceptaba HEAD: se conserva.
    assert TestClient(app).head("/reports/sla.docx").status_code == 401
    assert client_con_sesion.head("/reports/sla.docx").status_code == 200


@pytest.mark.parametrize(
    "ruta",
    ["..%2Fsecreto.txt", "%2e%2e/secreto.txt", "%2e%2e%2fsecreto.txt", "sub/%2e%2e/%2e%2e/secreto.txt",
     "sub", "sub/", "no-existe.docx"],
)
def test_reports_traversal_directorio_e_inexistente_404(informes_tmp, client_con_sesion, ruta):
    res = client_con_sesion.get(f"/reports/{ruta}")
    assert res.status_code == 404
    assert b"fuera de la base" not in res.content


def test_reports_index_sigue_redirigiendo():
    res = TestClient(app).get("/reports/index", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"] == "/reports-history"


def test_reports_traversal_con_barra_literal_404(informes_tmp, monkeypatch):
    """httpx normaliza `../`; se invoca la ruta con el path crudo (como llega desde el servidor ASGI)."""
    import asyncio

    from fastapi import HTTPException

    # La sesión es una dependencia de la ruta (se resuelve antes): acá se prueba sólo la resolución del path.
    for ruta in ("../secreto.txt", "sub/../../secreto.txt", "/etc/passwd", "sub/../../../etc/passwd"):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(informes.descargar_informe(ruta))
        assert exc.value.status_code == 404, ruta
