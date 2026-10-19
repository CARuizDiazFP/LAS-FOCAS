# Nombre de archivo: test_web_arbitro_disparadores.py
# Ubicación de archivo: tests/test_web_arbitro_disparadores.py
# Descripción: Los endpoints del viewer encolan una evaluación del árbitro tras un cambio exitoso y no lo hacen ante un error

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.services.cromo.arbitro.senales import Alcance
from tests.test_web_cromo_camino_optico import _cliente_admin, _fake_session


class _SesionSync:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def commit(self):
        return None

    def rollback(self):
        return None


class _SesionAsync:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def commit(self):
        return None


@pytest.fixture
def encolados(monkeypatch):
    from web.app import main as web_main

    llamadas: list[tuple] = []

    async def _encolar(alcance, disparo, motivo="", **kw):
        llamadas.append((alcance, disparo))

    monkeypatch.setattr("core.services.cromo.arbitro.cola.encolar_evaluacion", _encolar)

    async def _noop(**kw):
        return None

    monkeypatch.setattr(web_main, "encolar_recalculo_duplicados_botellas", _noop)
    monkeypatch.setenv("TESTING", "true")
    return llamadas


def _cliente(monkeypatch):
    _fake_session(monkeypatch)
    return _cliente_admin(monkeypatch)


def test_consolidar_encola_destino_y_origenes(monkeypatch, encolados):
    import core.services.cromo.consolidacion_service as svc

    monkeypatch.setattr("db.session.SessionLocal", lambda: _SesionSync())
    resultado = SimpleNamespace(
        id_destino_cromo=10, alias_creados=1, alias_actualizados=0, alias_repuntados=[],
        alias_dependientes_recableados=0, cables_existentes_recableados=0,
        fusiones_existentes_recableadas=0, legados_migrados=0, cables_migrados=0,
        empalmes_migrados=0, ingresos_migrados=0, camara_aliases_migrados=0,
        nombre_anterior=None, nombre_nuevo=None, legados_con_camara_forzada=[],
    )
    monkeypatch.setattr(svc, "consolidar_grupo_botellas", lambda *a, **k: resultado)
    client = _cliente(monkeypatch)

    res = client.post(
        "/api/infra/botellas/consolidar",
        json={"ids_origen_cromo": [11, 12], "id_destino_cromo": 10},
    )

    assert res.status_code == 200
    assert encolados == [(Alcance("BOTELLAS", (10, 11, 12)), "VIEWER")]


def test_consolidar_con_error_no_encola(monkeypatch, encolados):
    import core.services.cromo.consolidacion_service as svc

    monkeypatch.setattr("db.session.SessionLocal", lambda: _SesionSync())

    def _falla(*a, **k):
        raise svc.ConsolidacionBotellaError("no")

    monkeypatch.setattr(svc, "consolidar_grupo_botellas", _falla)
    client = _cliente(monkeypatch)

    res = client.post(
        "/api/infra/botellas/consolidar",
        json={"ids_origen_cromo": [11], "id_destino_cromo": 10},
    )

    assert res.status_code == 400
    assert encolados == []


def test_asociar_odf_encola_servicio(monkeypatch, encolados):
    from web.app import main as web_main
    import core.services.cromo.servicio_odf_override_service as svc

    monkeypatch.setattr("db.session.AsyncSessionLocal", lambda: _SesionAsync())

    async def _detalle(_s, servicio_id):
        return {
            "servicio": SimpleNamespace(direccion="x"),
            "categoria_causa": "C1",
            "subcategoria": None,
        }

    async def _senal(*a, **k):
        return SimpleNamespace(value="coincide")

    async def _crear(*a, **k):
        return None

    monkeypatch.setattr(web_main, "_obtener_servicio_categorizado", _detalle)
    monkeypatch.setattr(web_main, "_senal_direccion_contra_odf", _senal)
    monkeypatch.setattr(svc, "crear_override", _crear)
    client = _cliente(monkeypatch)

    res = client.post("/api/admin/infra/servicios-odf/77/asociar", json={"odf_n_id": 5})

    assert res.status_code == 200
    assert encolados == [(Alcance("SERVICIOS", (77,)), "VIEWER")]


def test_asociar_odf_servicio_inexistente_no_encola(monkeypatch, encolados):
    from web.app import main as web_main

    monkeypatch.setattr("db.session.AsyncSessionLocal", lambda: _SesionAsync())

    async def _detalle(_s, servicio_id):
        return None

    monkeypatch.setattr(web_main, "_obtener_servicio_categorizado", _detalle)
    client = _cliente(monkeypatch)

    res = client.post("/api/admin/infra/servicios-odf/77/asociar", json={"odf_n_id": 5})

    assert res.status_code == 404
    assert encolados == []


def test_estado_inconsistencias_encola_todo_solo_si_ok(monkeypatch, encolados):
    from core.services.cromo import inconsistencias_cromo as inc

    async def _cambiar(_s, ids, estado, usuario):
        return {"actualizados": [1], "rechazados": []}

    monkeypatch.setattr(inc, "cambiar_estado", _cambiar)
    client = _cliente(monkeypatch)
    monkeypatch.setattr("db.session.AsyncSessionLocal", lambda: _SesionAsync())  # tras _fake_session
    url = "/api/admin/infra/inconsistencias-cromo/estado"

    assert client.post(url, json={"ids": [1], "estado": "CORREGIDA"}).status_code == 400
    assert encolados == []
    assert client.post(url, json={"ids": [1], "estado": "PENDIENTE"}).status_code == 200
    assert encolados == [(Alcance("TODO"), "VIEWER")]
