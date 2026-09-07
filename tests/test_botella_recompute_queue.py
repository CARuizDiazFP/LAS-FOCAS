# Nombre de archivo: test_botella_recompute_queue.py
# Ubicación de archivo: tests/test_botella_recompute_queue.py
# Descripción: Pruebas de la caché/cola de recálculo de Botellas duplicadas — Redis mockeado, sin instancia real

from __future__ import annotations

import json

import pytest

from core.services import botella_recompute_queue as queue_mod
from core.services.botella_duplicados_service import BotellaDuplicadaItem, GrupoBotellasDuplicadas


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}
        self.fail = False

    async def get(self, key: str):
        if self.fail:
            raise ConnectionError("redis caído")
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None):
        if self.fail:
            raise ConnectionError("redis caído")
        self.store[key] = value

    async def delete(self, key: str):
        if self.fail:
            raise ConnectionError("redis caído")
        self.store.pop(key, None)

    async def rpush(self, key: str, value: str):
        if self.fail:
            raise ConnectionError("redis caído")
        self.lists.setdefault(key, []).append(value)


def _grupo() -> GrupoBotellasDuplicadas:
    return GrupoBotellasDuplicadas(
        camara_padre_id=1,
        camara_padre_nombre="Camara Test",
        clave_normalizada="bot 1",
        criterio="nombre",
        miembros=[BotellaDuplicadaItem(origen="cromo", id=100, nombre="Bot 1", estado="LIBRE")],
        estados_en_conflicto=False,
        estado_mas_restrictivo="LIBRE",
        resoluble=False,
    )


@pytest.fixture()
def fake_redis(monkeypatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr(queue_mod, "get_redis", lambda: fake)
    return fake


@pytest.mark.asyncio
async def test_cache_miss_devuelve_none(fake_redis: _FakeRedis) -> None:
    assert await queue_mod.leer_cache_duplicados() is None


@pytest.mark.asyncio
async def test_guardar_y_leer_cache_roundtrip(fake_redis: _FakeRedis) -> None:
    grupos = [_grupo()]
    await queue_mod.guardar_cache_duplicados(grupos)
    leidos = await queue_mod.leer_cache_duplicados()
    assert leidos is not None
    assert leidos[0].camara_padre_id == 1
    assert leidos[0].miembros[0].nombre == "Bot 1"


@pytest.mark.asyncio
async def test_redis_caido_no_rompe_lectura(fake_redis: _FakeRedis) -> None:
    fake_redis.fail = True
    assert await queue_mod.leer_cache_duplicados() is None


@pytest.mark.asyncio
async def test_redis_caido_no_rompe_encolado(fake_redis: _FakeRedis) -> None:
    fake_redis.fail = True
    await queue_mod.encolar_recalculo_duplicados_botellas(motivo="test")  # no debe lanzar


@pytest.mark.asyncio
async def test_encolar_invalida_y_encola(fake_redis: _FakeRedis) -> None:
    fake_redis.store[queue_mod.CACHE_KEY] = json.dumps([])
    await queue_mod.encolar_recalculo_duplicados_botellas(motivo="consolidar n_id=1")
    assert queue_mod.CACHE_KEY not in fake_redis.store
    jobs = fake_redis.lists[queue_mod.QUEUE_KEY]
    assert len(jobs) == 1
    payload = json.loads(jobs[0])
    assert payload == {"kind": "botellas_duplicados", "motivo": "consolidar n_id=1"}
