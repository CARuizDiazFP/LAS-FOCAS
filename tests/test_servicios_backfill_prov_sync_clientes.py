# Nombre de archivo: test_servicios_backfill_prov_sync_clientes.py
# Ubicación de archivo: tests/test_servicios_backfill_prov_sync_clientes.py
# Descripción: El backfill PROV corre una sync global de categorías de clientes al final, sólo con --apply y si hubo cambios

from __future__ import annotations

import asyncio

import pytest

from scripts import servicios_backfill_prov as backfill


class _ServicioFalso:
    numero_primer_servicio = "1"
    servicio_id = "1"


class _SesionFalsa:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def execute(self, *_a, **_k):
        class _R:
            def scalars(self_inner):
                class _S:
                    def first(self_s):
                        return _ServicioFalso()

                return _S()

        return _R()

    async def commit(self):
        return None

    async def rollback(self):
        return None


class _ProvFalso:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def obtener_contexto_servicio(self, _numero):
        if self.error:
            raise self.error
        return {}


@pytest.fixture
def corrida(monkeypatch):
    llamadas: list = []

    async def candidatos(_solo_ids, _limit):
        return [1]

    async def ingerir(_session, _servicio, _contexto):
        return None

    monkeypatch.setattr(backfill, "_obtener_candidatos", candidatos)
    monkeypatch.setattr(backfill, "AsyncSessionLocal", lambda: _SesionFalsa())
    monkeypatch.setattr(backfill, "ingerir_contexto_prov", ingerir)
    monkeypatch.setattr(
        backfill, "sincronizar_clientes_en_sesion_propia", lambda claves, *, origen: llamadas.append((claves, origen))
    )

    def correr(apply: bool, error: Exception | None = None) -> list:
        monkeypatch.setattr(backfill, "ProvClient", lambda: _ProvFalso(error))
        asyncio.run(backfill.main(apply=apply, solo_ids=None, limit=None))
        return llamadas

    return correr


def test_apply_con_exitos_sincroniza_todos_los_clientes_una_vez(corrida):
    assert corrida(True) == [(None, "backfill_prov")]


def test_dry_run_no_sincroniza_clientes(corrida):
    assert corrida(False) == []


def test_apply_sin_exitos_no_sincroniza_clientes(corrida):
    assert corrida(True, error=backfill.ProvServicioNoEncontradoError("1", "sin contexto")) == []
