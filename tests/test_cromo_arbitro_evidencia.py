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


class _FakeRedis:
    def __init__(self):
        self.empujados = []

    async def rpush(self, clave, valor):
        self.empujados.append((clave, valor))


@pytest.mark.asyncio
async def test_encolar_evaluacion_payload(monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr(cola, "get_redis", lambda: redis)
    await cola.encolar_evaluacion(Alcance("SERVICIOS", (5,)), "REGISTRADOR", motivo="evidencia:SLACK")
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
    await cola.encolar_evaluacion(Alcance("SERVICIOS", (5,)), "REGISTRADOR")


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
        from tests.test_cromo_tracking_por_camino import _semilla

        return [_semilla(10)]

    async def _por_camino(*_a, **_k):
        return TrackingsPorCamino(
            trackings=[_tracking(10, resumen)], errores=["boom"] if hay_errores else []
        )

    async def _registrar(sesion, servicio_id, entradas, *, completo, fuente):
        llamadas.append((servicio_id, [e.pelo_n_id for e in entradas], completo, fuente))

    monkeypatch.setattr(tracking_service, "declaraciones_del_servicio", _declaraciones)
    monkeypatch.setattr(tracking_service, "numero_del_servicio", _numero)
    monkeypatch.setattr(tracking_service, "semillas_para_tracking", _semillas)
    monkeypatch.setattr(tracking_service, "trackings_por_camino", _por_camino)
    monkeypatch.setattr(evidencia, "registrar_y_encolar", _registrar)

    kwargs = {} if fuente == "WEB" else {"fuente_evidencia": fuente}
    await tracking_service.trackings_del_servicio(object(), object(), 7, auditar=False, **kwargs)

    assert llamadas == [(7, [10], not hay_errores, fuente)]
