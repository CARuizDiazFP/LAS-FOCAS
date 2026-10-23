# Nombre de archivo: test_web_reports_sesion.py
# Ubicación de archivo: tests/test_web_reports_sesion.py
# Descripción: Hotfix prod — /reports exige sesión y no sale de la carpeta de informes

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.routing import Mount

from web.app import main as web_main
from web.app.main import app


# --- /reports ---------------------------------------------------------------


@pytest.fixture
def informes_tmp(tmp_path, monkeypatch):
    base = tmp_path / "reports"
    base.mkdir()
    (base / "sla.docx").write_bytes(b"contenido-docx")
    (base / "sub").mkdir()
    (base / "sub" / "x.pdf").write_bytes(b"%PDF-x")
    (tmp_path / "secreto.txt").write_text("fuera de la base")
    monkeypatch.setattr(web_main, "_mount_reports", base)
    return base


@pytest.fixture
def client_con_sesion(monkeypatch):
    from tests.test_web_cromo_ingesta import _connect_admin_ok

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
    from types import SimpleNamespace

    from fastapi import HTTPException

    request = SimpleNamespace(session={"username": "admin", "role": "admin"})
    for ruta in ("../secreto.txt", "sub/../../secreto.txt", "/etc/passwd", "sub/../../../etc/passwd"):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(web_main.descargar_informe(ruta, request))
        assert exc.value.status_code == 404, ruta


def test_no_queda_mount_de_reports():
    mounts = [r.path for r in app.router.routes if isinstance(r, Mount)]
    assert set(mounts) <= {"/assets"}
