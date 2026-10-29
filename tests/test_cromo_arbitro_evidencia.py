# Nombre de archivo: test_cromo_arbitro_evidencia.py
# Ubicación de archivo: tests/test_cromo_arbitro_evidencia.py
# Descripción: Tests unitarios de la evidencia de caminos y de la cola del árbitro de Cromo (sin DB ni Redis reales)

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from core.services.cromo import tracking_service
from core.services.cromo.arbitro import cola, evidencia
from core.services.cromo.arbitro.senales import Alcance
from core.services.cromo.servicio_odf_confirmacion import Declaraciones
from core.services.cromo.tracking_service import (
    ExtremoCamino,
    ResumenCamino,
    TrackingGenerado,
    TrackingsPorCamino,
)

AHORA = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def _tracking(pelo: int, resumen=None) -> TrackingGenerado:
    return TrackingGenerado(
        pelo_n_id=pelo,
        nombre_archivo="1 CROMO.txt",
        contenido="x",
        desde_cache=False,
        generado_at=AHORA,
        duracion_ms=1,
        pelos_camino=frozenset({pelo, pelo + 1}),
        extremos=resumen,
    )


def test_entradas_de_trackings_omite_sin_extremos():
    resumen = ResumenCamino(inicio=ExtremoCamino(tipo="PELO", id_cromo=1, clase=130))
    entradas = evidencia.entradas_de_trackings([_tracking(1, resumen), _tracking(2, None)])
    assert [e.pelo_n_id for e in entradas] == [1]
    assert entradas[0].pelos_camino == frozenset({1, 2})
    # La evidencia lleva la fecha real del tracking (puede venir de caché), no la de la consulta.
    assert entradas[0].generado_at == AHORA


class _FakeRedis:
    def __init__(self):
        self.empujados = []

    async def rpush(self, clave, valor):
        self.empujados.append((clave, valor))


@pytest.mark.asyncio
async def test_encolar_evaluacion_payload(monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr(cola, "get_redis", lambda: redis)
    assert await cola.encolar_evaluacion(
        Alcance("SERVICIOS", (5,)), "REGISTRADOR", motivo="evidencia:SLACK"
    ) is True
    (clave, valor), = redis.empujados
    assert clave == cola.QUEUE_KEY
    payload = json.loads(valor)
    assert payload["kind"] == cola.JOB_KIND_ARBITRO == "arbitro_evaluar"
    assert payload["alcance"] == {"tipo": "SERVICIOS", "ids": [5]}
    assert payload["disparo"] == "REGISTRADOR"
    assert payload["motivo"] == "evidencia:SLACK"
    assert payload["evaluacion_id"] is None and payload["reglas"] is None


@pytest.mark.asyncio
async def test_encolar_evaluacion_redis_caido_no_lanza(monkeypatch):
    class _Caido:
        async def rpush(self, *_a):
            raise ConnectionError("redis caído")

    monkeypatch.setattr(cola, "get_redis", lambda: _Caido())
    assert await cola.encolar_evaluacion(Alcance("SERVICIOS", (5,)), "REGISTRADOR") is False


@pytest.mark.asyncio
@pytest.mark.parametrize("fuente", ["WEB", "SLACK"])
@pytest.mark.parametrize("hay_errores", [False, True])
async def test_trackings_del_servicio_registra_evidencia(monkeypatch, fuente, hay_errores):
    resumen = ResumenCamino(inicio=ExtremoCamino(tipo="PELO", id_cromo=1, clase=130))
    llamadas = []

    async def _declaraciones(_s, _id):
        return Declaraciones()

    async def _numero(_s, _id):
        return "1"

    async def _semillas(_s, _id):
        from tests.soporte_cromo_tracking import _semilla

        return [_semilla(10)]

    async def _por_camino(*_a, **_k):
        return TrackingsPorCamino(
            trackings=[_tracking(10, resumen)], errores=["boom"] if hay_errores else []
        )

    async def _registrar(sesion, servicio_id, entradas, *, completo, fuente):
        llamadas.append((servicio_id, [e.pelo_n_id for e in entradas], completo, fuente))

    monkeypatch.setattr(tracking_service, "declaraciones_del_servicio", _declaraciones)
    async def _posiciones(_s, _id, _modo):
        return [], []

    monkeypatch.setattr(tracking_service, "numero_del_servicio", _numero)
    monkeypatch.setattr(tracking_service, "semillas_para_tracking", _semillas)
    monkeypatch.setattr(tracking_service, "posiciones_del_servicio", _posiciones)
    monkeypatch.setattr(tracking_service, "trackings_por_camino", _por_camino)
    monkeypatch.setattr(evidencia, "registrar_y_encolar", _registrar)

    kwargs = {} if fuente == "WEB" else {"fuente_evidencia": fuente}
    await tracking_service.trackings_del_servicio(object(), object(), 7, auditar=False, **kwargs)

    assert llamadas == [(7, [10], not hay_errores, fuente)]


def _entrada_simple() -> evidencia.EvidenciaEntrada:
    return evidencia.EvidenciaEntrada(1, ResumenCamino(), frozenset({1}))


@pytest.mark.asyncio
@pytest.mark.parametrize("escritas,encola", [(0, False), (2, True)])
async def test_registrar_y_encolar_encola_solo_si_escribio(monkeypatch, escritas, encola):
    encolados = []

    async def _registrar(*_a, **_k):
        return escritas

    async def _encolar(alcance, disparo, motivo="", **_k):
        encolados.append((alcance, disparo, motivo))

    monkeypatch.setattr(evidencia, "registrar_evidencia", _registrar)
    monkeypatch.setattr(evidencia, "encolar_evaluacion", _encolar)
    await evidencia.registrar_y_encolar(object(), 9, [_entrada_simple()], completo=True, fuente="SLACK")
    assert encolados == ([(Alcance("SERVICIOS", (9,)), "REGISTRADOR", "evidencia:SLACK")] if encola else [])


@pytest.mark.asyncio
async def test_registrar_y_encolar_auditoria_global_no_encola(monkeypatch):
    encolados = []

    async def _registrar(*_a, **_k):
        return 3

    async def _encolar(*a, **k):
        encolados.append(a)

    monkeypatch.setattr(evidencia, "registrar_evidencia", _registrar)
    monkeypatch.setattr(evidencia, "encolar_evaluacion", _encolar)
    await evidencia.registrar_y_encolar(
        object(), 9, [_entrada_simple()], completo=True, fuente="AUDITORIA_GLOBAL"
    )
    assert encolados == []


@pytest.mark.asyncio
async def test_registrar_y_encolar_no_lanza_si_encolar_falla(monkeypatch):
    async def _registrar(*_a, **_k):
        return 1

    async def _encolar(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(evidencia, "registrar_evidencia", _registrar)
    monkeypatch.setattr(evidencia, "encolar_evaluacion", _encolar)
    await evidencia.registrar_y_encolar(object(), 9, [_entrada_simple()], completo=True, fuente="WEB")
