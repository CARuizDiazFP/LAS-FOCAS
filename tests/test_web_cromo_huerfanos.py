# Nombre de archivo: test_web_cromo_huerfanos.py
# Ubicación de archivo: tests/test_web_cromo_huerfanos.py
# Descripción: Pruebas de wiring (admin, CSRF, validación, códigos) de los endpoints del Viewer de
# huérfanos y de la auditoría global — sin DB real ni red

from __future__ import annotations

from typing import Any

import pytest

from core.services.cromo import auditoria_huerfanos, auditoria_huerfanos_global
from core.services.cromo.auditoria_huerfanos import ResultadoRevision
from tests.test_web_cromo_camino_optico import _cliente_admin, _cliente_user, _fake_session

URL = "/api/admin/infra/huerfanos"


@pytest.fixture
def sin_testing(monkeypatch):
    """CSRF real: `_validar_csrf` se saltea con TESTING=true."""
    monkeypatch.delenv("TESTING", raising=False)


@pytest.mark.parametrize(
    "metodo, url, cuerpo",
    [
        ("get", URL, None),
        ("post", f"{URL}/normalizar", {"ids": [1]}),
        ("post", f"{URL}/descartar", {"ids": [1]}),
        ("get", f"{URL}/auditoria-global", None),
        ("post", f"{URL}/auditoria-global", {}),
    ],
)
def test_solo_admin(monkeypatch, metodo, url, cuerpo):
    _fake_session(monkeypatch)
    client = _cliente_user(monkeypatch)
    res = client.get(url) if metodo == "get" else client.post(url, json=cuerpo)
    assert res.status_code == 403


@pytest.mark.parametrize(
    "url, cuerpo",
    [
        (f"{URL}/normalizar", {"ids": [1]}),
        (f"{URL}/descartar", {"ids": [1]}),
        (f"{URL}/auditoria-global", {}),
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
        return {"total": 0, "limit": kw["limit"], "offset": 0, "items": [], "conteos_por_causa": {}}

    monkeypatch.setattr(auditoria_huerfanos, "listar_huerfanos", _listar)
    client = _cliente_admin(monkeypatch)

    assert client.get(f"{URL}?causa=OTRA").status_code == 400
    assert client.get(f"{URL}?estado=OTRO").status_code == 400
    ok = client.get(f"{URL}?servicio_id=1168&causa=CABLE_DESUSO&estado=PENDIENTE&limit=999")
    assert ok.status_code == 200
    assert recibido == {
        "servicio_id": 1168,
        "causa": "CABLE_DESUSO",
        "estado": "PENDIENTE",
        "limit": 200,
        "offset": 0,
    }


def test_normalizar_y_descartar_devuelven_aplicados_y_rechazados(monkeypatch):
    _fake_session(monkeypatch)
    llamadas: list[tuple] = []

    async def _normalizar(_sesion, ids, *, usuario):
        llamadas.append(("normalizar", ids, usuario))
        resultado = ResultadoRevision(aplicados=[1])
        resultado.rechazar(2, "La causa PELO_DANADO todavía es sólo para revisar.")
        return resultado

    async def _descartar(_sesion, ids, *, usuario):
        llamadas.append(("descartar", ids, usuario))
        return ResultadoRevision(aplicados=list(ids))

    monkeypatch.setattr(auditoria_huerfanos, "normalizar", _normalizar)
    monkeypatch.setattr(auditoria_huerfanos, "descartar", _descartar)
    monkeypatch.setenv("TESTING", "true")
    client = _cliente_admin(monkeypatch)

    norm = client.post(f"{URL}/normalizar", json={"ids": [1, 2]})
    desc = client.post(f"{URL}/descartar", json={"ids": [3]})
    vacio = client.post(f"{URL}/normalizar", json={"ids": []})

    assert norm.status_code == 200
    assert norm.json()["aplicados"] == [1]
    assert norm.json()["rechazados"][0]["id"] == 2
    assert desc.json()["aplicados"] == [3]
    assert vacio.status_code == 422
    assert llamadas == [("normalizar", [1, 2], "admin"), ("descartar", [3], "admin")]


class _Corrida:
    id = 41


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


def _auditoria_fakes(monkeypatch, *, en_curso=None, falla_worker=False):
    from web.app import main as web_main

    _fake_session(monkeypatch)
    estado: dict[str, Any] = {"enviados": [], "fallidas": [], "iniciadas": []}

    async def _iniciar(_sesion, *, usuario, max_servicios):
        if en_curso is not None:
            return None, en_curso
        estado["iniciadas"].append((usuario, max_servicios))
        return _Corrida(), None

    async def _fallida(corrida_id, motivo):
        estado["fallidas"].append(corrida_id)

    monkeypatch.setattr(auditoria_huerfanos_global, "iniciar_si_no_hay_otra", _iniciar)
    monkeypatch.setattr(web_main, "_marcar_corrida_fallida", _fallida)
    monkeypatch.setattr(web_main.httpx, "AsyncClient", _HttpxFake(falla_worker, estado["enviados"]))
    monkeypatch.setenv("CROMO_AUDITORIA_MAX_SERVICIOS", "30")
    monkeypatch.setenv("TESTING", "true")
    return estado


def test_auditoria_global_delega_al_worker_con_el_tope(monkeypatch):
    estado = _auditoria_fakes(monkeypatch)
    client = _cliente_admin(monkeypatch)

    res = client.post(f"{URL}/auditoria-global", json={})
    explicito = client.post(f"{URL}/auditoria-global", json={"max_servicios": 5})

    assert res.status_code == 202
    assert res.json() == {"corrida_id": 41, "max_servicios": 30}
    assert estado["iniciadas"] == [("admin", 30), ("admin", 5)]
    assert estado["enviados"][0][1] == {"corrida_id": 41, "usuario": "admin"}
    assert explicito.json()["max_servicios"] == 5


def test_auditoria_global_una_a_la_vez(monkeypatch):
    estado = _auditoria_fakes(monkeypatch, en_curso=40)
    client = _cliente_admin(monkeypatch)

    res = client.post(f"{URL}/auditoria-global", json={})

    assert res.status_code == 409
    assert res.json()["corrida_id"] == 40
    assert estado["iniciadas"] == [] and estado["enviados"] == []


def test_auditoria_global_worker_caido_marca_fallida_503(monkeypatch):
    estado = _auditoria_fakes(monkeypatch, falla_worker=True)
    client = _cliente_admin(monkeypatch)

    res = client.post(f"{URL}/auditoria-global", json={})

    assert res.status_code == 503
    assert estado["fallidas"] == [41]
