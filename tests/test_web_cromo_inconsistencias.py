# Nombre de archivo: test_web_cromo_inconsistencias.py
# Ubicación de archivo: tests/test_web_cromo_inconsistencias.py
# Descripción: Pruebas de wiring (admin, CSRF, validación, códigos) de los endpoints del Viewer de
# inconsistencias de Cromo y de su detección manual — sin DB real ni red

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from core.services.cromo import inconsistencias_cromo as inc
from tests.test_web_cromo_camino_optico import _cliente_admin, _cliente_user, _fake_session

URL = "/api/admin/infra/inconsistencias-cromo"


@pytest.fixture
def sin_testing(monkeypatch):
    """CSRF real: `_validar_csrf` se saltea con TESTING=true."""
    monkeypatch.delenv("TESTING", raising=False)


@pytest.mark.parametrize(
    "metodo, url, cuerpo",
    [
        ("get", URL, None),
        ("post", f"{URL}/estado", {"ids": [1], "estado": "ACEPTADA"}),
        ("get", f"{URL}/deteccion", None),
        ("post", f"{URL}/deteccion", {}),
    ],
)
def test_solo_admin(monkeypatch, metodo, url, cuerpo):
    _fake_session(monkeypatch)
    client = _cliente_user(monkeypatch)
    res = client.get(url) if metodo == "get" else client.post(url, json=cuerpo)
    assert res.status_code == 403


def test_sin_sesion_401():
    from fastapi.testclient import TestClient

    from web.app.main import app

    res = TestClient(app).get(URL)
    assert res.status_code in (401, 403)


@pytest.mark.parametrize(
    "url, cuerpo",
    [
        (f"{URL}/estado", {"ids": [1], "estado": "ACEPTADA"}),
        (f"{URL}/deteccion", {}),
    ],
)
def test_post_sin_csrf_403(monkeypatch, sin_testing, url, cuerpo):
    _fake_session(monkeypatch)
    client = _cliente_admin(monkeypatch)
    res = client.post(url, json={**cuerpo, "csrf_token": "otro"})
    assert res.status_code == 403
    assert res.json()["error"] == "CSRF inválido"


def test_listar_valida_filtros_y_pasa_parametros(monkeypatch):
    _fake_session(monkeypatch)
    recibido: dict[str, Any] = {}

    async def _listar(_sesion, **kw):
        recibido.update(kw)
        return {
            "total": 1,
            "pagina": 1,
            "por_pagina": kw["por_pagina"],
            "desplazamiento": kw["desplazamiento"],
            "conteos_por_tipo": {"ISLA_FUSION": 1},
            "items": [{"id": 7, "ultima_vez": datetime(2026, 10, 17, tzinfo=timezone.utc)}],
        }

    monkeypatch.setattr(inc, "listar", _listar)
    client = _cliente_admin(monkeypatch)

    assert client.get(f"{URL}?tipo=OTRO").status_code == 400
    assert client.get(f"{URL}?estado=OTRO").status_code == 400
    assert client.get(f"{URL}?revision=OTRA").status_code == 400
    ok = client.get(
        f"{URL}?tipo=ISLA_FUSION&estado=CUARENTENA&revision=AUTO&localidad=Korn"
        "&servicio=102452&servicio_id=1168&limit=999&offset=-5"
    )
    assert ok.status_code == 200
    assert ok.json()["items"][0]["ultima_vez"].startswith("2026-10-17")
    assert recibido == {
        "tipo": "ISLA_FUSION",
        "estado": "CUARENTENA",
        "revision": "AUTO",
        "localidad": "Korn",
        "servicio": "102452",
        "servicio_id": 1168,
        "por_pagina": 200,
        "desplazamiento": 0,
    }


def test_estado_devuelve_aplicados_y_rechazados_y_valida(monkeypatch):
    _fake_session(monkeypatch)
    llamadas: list[tuple] = []
    commits: list[int] = []

    class _Sesion:
        async def commit(self):
            commits.append(1)

    class _CM:
        async def __aenter__(self):
            return _Sesion()

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr("db.session.AsyncSessionLocal", lambda: _CM())

    async def _cambiar(_sesion, ids, estado, usuario):
        llamadas.append((list(ids), estado, usuario))
        return {"actualizados": [1], "rechazados": [{"id": 2, "motivo": "ya está corregido"}]}

    monkeypatch.setattr(inc, "cambiar_estado", _cambiar)
    monkeypatch.setenv("TESTING", "true")
    client = _cliente_admin(monkeypatch)

    res = client.post(f"{URL}/estado", json={"ids": [1, 2], "estado": "PENDIENTE"})
    assert res.status_code == 200
    assert res.json() == {
        "ok": True,
        "aplicados": [1],
        "rechazados": [{"id": 2, "motivo": "ya está corregido"}],
    }
    assert llamadas == [([1, 2], "PENDIENTE", "admin")]
    # CORREGIDA la pone sólo el detector; sin ids no hay lote.
    assert client.post(f"{URL}/estado", json={"ids": [1], "estado": "CORREGIDA"}).status_code == 400
    assert client.post(f"{URL}/estado", json={"ids": [], "estado": "ACEPTADA"}).status_code == 422
    assert len(llamadas) == 1 and commits == [1]


class _Corrida:
    id = 51


class _HttpxFake:
    def __init__(self, falla: bool, enviados: list) -> None:
        self._falla = falla
        self._enviados = enviados

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None):
        self._enviados.append((url, json))
        if self._falla:
            raise RuntimeError("worker caído")

        class _Resp:
            def raise_for_status(self):
                return None

        return _Resp()


def _deteccion_fakes(monkeypatch, *, en_curso=None, falla_worker=False):
    from web.app import main as web_main

    _fake_session(monkeypatch)
    estado: dict[str, Any] = {"enviados": [], "fallidas": [], "iniciadas": []}

    async def _iniciar(_sesion, *, usuario, origen="MANUAL", corrida_origen_id=None):
        if en_curso is not None:
            return None, en_curso
        estado["iniciadas"].append((usuario, origen))
        return _Corrida(), None

    async def _fallida(corrida_id, motivo):
        estado["fallidas"].append(corrida_id)

    monkeypatch.setattr(inc, "iniciar_si_no_hay_otra", _iniciar)
    monkeypatch.setattr(web_main, "_marcar_corrida_fallida", _fallida)
    monkeypatch.setattr(web_main.httpx, "AsyncClient", _HttpxFake(falla_worker, estado["enviados"]))
    monkeypatch.setenv("TESTING", "true")
    return estado


def test_deteccion_delega_al_worker(monkeypatch):
    estado = _deteccion_fakes(monkeypatch)
    res = _cliente_admin(monkeypatch).post(f"{URL}/deteccion", json={})
    assert res.status_code == 202
    assert res.json() == {"corrida_id": 51}
    assert estado["iniciadas"] == [("admin", "MANUAL")]
    assert estado["enviados"][0][1] == {"corrida_id": 51, "usuario": "admin"}


def test_deteccion_una_a_la_vez_409(monkeypatch):
    estado = _deteccion_fakes(monkeypatch, en_curso=40)
    res = _cliente_admin(monkeypatch).post(f"{URL}/deteccion", json={})
    assert res.status_code == 409
    assert res.json()["corrida_id"] == 40
    assert estado["enviados"] == []


def test_deteccion_worker_caido_marca_fallida_503(monkeypatch):
    estado = _deteccion_fakes(monkeypatch, falla_worker=True)
    res = _cliente_admin(monkeypatch).post(f"{URL}/deteccion", json={})
    assert res.status_code == 503
    assert estado["fallidas"] == [51]


def test_deteccion_estado_devuelve_la_ultima_corrida(monkeypatch):
    _fake_session(monkeypatch)

    async def _ultima(_sesion):
        return None

    monkeypatch.setattr(inc, "ultima_deteccion", _ultima)
    res = _cliente_admin(monkeypatch).get(f"{URL}/deteccion")
    assert res.status_code == 200
    assert res.json() == {"corrida": None}


@pytest.mark.asyncio
async def test_inconsistencias_del_servicio_es_accesorio(monkeypatch):
    from web.app.main import _inconsistencias_del_servicio

    async def _ok(_sesion, servicio_id):
        return {"cuarentena": 2, "en_revision": 1}

    async def _falla(_sesion, servicio_id):
        raise RuntimeError("tabla sin migrar")

    monkeypatch.setattr(inc, "resumen_de_servicio", _ok)
    assert await _inconsistencias_del_servicio(object(), 1168) == {"cuarentena": 2, "en_revision": 1}
    monkeypatch.setattr(inc, "resumen_de_servicio", _falla)
    assert await _inconsistencias_del_servicio(object(), 1168) == {"cuarentena": 0, "en_revision": 0}
