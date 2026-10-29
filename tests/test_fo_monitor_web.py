# Nombre de archivo: test_fo_monitor_web.py
# Ubicación de archivo: tests/test_fo_monitor_web.py
# Descripción: Tests de las rutas /api/fo-monitor/* (auth, admin, CSRF, Range 206/416 del mapa base) sin DB

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from web import fo_monitor_routes as rutas
from web.app.errores import ErrorDeDominio, manejar_error_de_dominio


@pytest.fixture
def cliente(monkeypatch, tmp_path):
    monkeypatch.setenv("TESTING", "false")
    monkeypatch.setattr(rutas, "BASEMAP_DIR", tmp_path)
    (tmp_path / "amba.pmtiles").write_bytes(bytes(range(256)) * 4)  # 1024 bytes
    (tmp_path / "fonts").mkdir()
    (tmp_path.parent / "secreto.txt").write_text("no")

    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test")
    # Como en web/app/main.py: `requiere_csrf` responde 403 vía ErrorDeDominio.
    app.add_exception_handler(ErrorDeDominio, manejar_error_de_dominio)

    @app.get("/_login/{rol}")
    def _ruta_login(request: Request, rol: str):
        request.session.update({"username": f"u-{rol}", "role": rol, "csrf": "tok"})
        return {"ok": True}

    rutas.mount_fo_monitor_routes(app)
    return TestClient(app)


def test_lectura_requiere_sesion(cliente):
    assert cliente.get("/api/fo-monitor/intervenciones").status_code == 401
    assert cliente.get("/api/fo-monitor/basemap/amba.pmtiles").status_code == 401


def test_range_devuelve_206_con_content_range(cliente):
    cliente.get("/_login/invitado")
    r = cliente.get("/api/fo-monitor/basemap/amba.pmtiles", headers={"Range": "bytes=0-15"})
    assert r.status_code == 206
    assert r.headers["content-range"] == "bytes 0-15/1024"
    assert r.headers["accept-ranges"] == "bytes"
    assert r.content == bytes(range(16))


def test_range_sufijo_y_abierto(cliente):
    cliente.get("/_login/invitado")
    r = cliente.get("/api/fo-monitor/basemap/amba.pmtiles", headers={"Range": "bytes=-4"})
    assert r.status_code == 206 and r.content == bytes([252, 253, 254, 255])
    r = cliente.get("/api/fo-monitor/basemap/amba.pmtiles", headers={"Range": "bytes=1020-"})
    assert r.headers["content-range"] == "bytes 1020-1023/1024"


def test_range_invalido_416_y_sin_range_200(cliente):
    cliente.get("/_login/invitado")
    assert cliente.get("/api/fo-monitor/basemap/amba.pmtiles", headers={"Range": "bytes=5000-6000"}).status_code == 416
    r = cliente.get("/api/fo-monitor/basemap/amba.pmtiles")
    assert r.status_code == 200 and len(r.content) == 1024


def test_path_traversal_no_sale_del_directorio(cliente):
    cliente.get("/_login/invitado")
    assert cliente.get("/api/fo-monitor/basemap/../secreto.txt").status_code == 404
    assert cliente.get("/api/fo-monitor/basemap/%2e%2e/secreto.txt").status_code == 404


def test_mapa_config_local_si_existe_pmtiles(cliente, monkeypatch, tmp_path):
    cliente.get("/_login/invitado")
    assert cliente.get("/api/fo-monitor/mapa/config").json()["modo"] == "local"
    (tmp_path / "amba.pmtiles").unlink()
    assert cliente.get("/api/fo-monitor/mapa/config").json()["modo"] == "osm"


def test_mutaciones_solo_admin_con_csrf(cliente, monkeypatch):
    llamadas = []
    monkeypatch.setattr(rutas.consultas_web, "reconocer", lambda s, i, **kw: llamadas.append((i, kw)) or {"id": 1})

    class _S:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(rutas, "_sesion_local", lambda: _S())
    body = {"motivo": "corte ajeno de Telecom", "csrf_token": "tok"}
    cliente.get("/_login/invitado")
    assert cliente.post("/api/fo-monitor/intervenciones/5/reconocimientos", json=body).status_code == 403
    cliente.get("/_login/admin")
    assert cliente.post("/api/fo-monitor/intervenciones/5/reconocimientos", json={**body, "csrf_token": "x"}).status_code == 403
    r = cliente.post("/api/fo-monitor/intervenciones/5/reconocimientos", json=body)
    assert r.status_code == 200
    assert llamadas == [(5, {"usuario": "u-admin", "motivo": "corte ajeno de Telecom", "servicio_pk": None})]


def test_config_valida_rangos(cliente):
    cliente.get("/_login/admin")
    r = cliente.put("/api/admin/fo-monitor/config", json={"csrf_token": "tok", "max_ids_por_mensaje": 50})
    assert r.status_code == 422
