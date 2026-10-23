# Nombre de archivo: test_web_fo_monitor_errores_depends.py
# Ubicación de archivo: tests/test_web_fo_monitor_errores_depends.py
# Descripción: Rutas de FO Monitor: sesión vía Depends (401/403) detectada por introspección

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from tests.test_web_rutas_contrato import muestra_de_ruta
from web.app.dependencias import usuario_admin, usuario_sesion
from web.app.main import app


def _llama_a(dependant, objetivo) -> bool:
    return any(d.call is objetivo or _llama_a(d, objetivo) for d in dependant.dependencies)


_RUTAS_FOMON = [r for r in app.routes if isinstance(r, APIRoute) and "fo-monitor" in r.path]


def _casos(objetivo):
    return sorted(
        (metodo, r.path) for r in _RUTAS_FOMON if _llama_a(r.dependant, objetivo)
        for metodo in r.methods - {"HEAD", "OPTIONS"}
    )


@pytest.fixture(autouse=True)
def _modo_test(monkeypatch):
    monkeypatch.setenv("TESTING", "true")


def test_toda_ruta_de_fo_monitor_depende_de_la_sesion():
    sin_sesion = [r.path for r in _RUTAS_FOMON if not _llama_a(r.dependant, usuario_sesion)
                  and not _llama_a(r.dependant, usuario_admin)]
    assert len(_RUTAS_FOMON) >= 15 and sin_sesion == []


def test_hay_rutas_admin_detectadas():
    assert len(_casos(usuario_admin)) == 4


@pytest.mark.parametrize(("metodo", "plantilla"), _casos(usuario_admin))
def test_toda_ruta_admin_da_403_a_un_usuario_comun(con_sesion, metodo, plantilla):
    con_sesion("user")
    kwargs = {"json": {}} if metodo in {"POST", "PUT", "PATCH", "DELETE"} else {}
    res = TestClient(app, raise_server_exceptions=False).request(metodo, muestra_de_ruta(plantilla), **kwargs)
    assert res.status_code == 403, f"{metodo} {plantilla} respondió {res.status_code}"
