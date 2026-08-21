# Nombre de archivo: test_botellas_recalculo_worker.py
# Ubicación de archivo: tests/test_botellas_recalculo_worker.py
# Descripción: Pruebas del dispatch de jobs del worker de recálculo de Botellas duplicadas — sin Redis/DB reales

from __future__ import annotations

import asyncio
import json

import pytest

from core.services.botella_recompute_queue import JOB_KIND_BOTELLAS_DUPLICADOS
from modules.botellas_recalculo_worker import worker as worker_mod


class _FakeRedisPublish:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str):
        self.published.append((channel, message))


@pytest.mark.asyncio
async def test_procesar_job_desconocido_no_lanza(monkeypatch) -> None:
    await worker_mod._procesar_job(json.dumps({"kind": "algo_inexistente"}))  # no debe lanzar


@pytest.mark.asyncio
async def test_procesar_job_invalido_no_lanza() -> None:
    await worker_mod._procesar_job("no es json")  # no debe lanzar


@pytest.mark.asyncio
async def test_recalcular_botellas_duplicados_publica_evento(monkeypatch) -> None:
    fake_redis = _FakeRedisPublish()
    monkeypatch.setattr(worker_mod, "get_redis", lambda: fake_redis)
    monkeypatch.setattr(worker_mod, "detectar_grupos_duplicados_botellas", lambda session: [])

    async def _fake_guardar(grupos):
        return None

    monkeypatch.setattr(worker_mod, "guardar_cache_duplicados", _fake_guardar)

    class _FakeSessionLocal:
        def __enter__(self):
            return None

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(worker_mod, "SessionLocal", lambda: _FakeSessionLocal())

    await worker_mod._recalcular_botellas_duplicados()

    assert len(fake_redis.published) == 1
    channel, message = fake_redis.published[0]
    assert channel == "admin-notifications"
    payload = json.loads(message)
    assert payload["type"] == "botellas_duplicados_recalculado"
    assert "at" in payload


@pytest.mark.asyncio
async def test_procesar_job_kind_valido_actualiza_status(monkeypatch) -> None:
    llamado = {"veces": 0}

    async def _fake_handler():
        llamado["veces"] += 1

    monkeypatch.setitem(worker_mod.DISPATCH, JOB_KIND_BOTELLAS_DUPLICADOS, _fake_handler)
    await worker_mod._procesar_job(json.dumps({"kind": JOB_KIND_BOTELLAS_DUPLICADOS}))
    assert llamado["veces"] == 1


@pytest.mark.asyncio
async def test_procesar_job_payload_null_no_lanza() -> None:
    """Payload JSON válido pero no es dict (null): debe logguear warning y retornar, no lanzar."""
    await worker_mod._procesar_job("null")  # no debe lanzar


@pytest.mark.asyncio
async def test_procesar_job_payload_numero_no_lanza() -> None:
    """Payload JSON válido pero no es dict (número): debe logguear warning y retornar, no lanzar."""
    await worker_mod._procesar_job("42")  # no debe lanzar


@pytest.mark.asyncio
async def test_procesar_job_payload_array_no_lanza() -> None:
    """Payload JSON válido pero no es dict (array): debe logguear warning y retornar, no lanzar."""
    await worker_mod._procesar_job("[1, 2, 3]")  # no debe lanzar


@pytest.mark.asyncio
async def test_procesar_job_kind_no_hasheable_no_lanza() -> None:
    """Kind no es hasheable (lista): DISPATCH.get() lanzaría TypeError, debe catchearse."""
    await worker_mod._procesar_job(json.dumps({"kind": ["array", "as", "kind"]}))  # no debe lanzar


@pytest.mark.asyncio
async def test_procesar_job_loop_error_handling(monkeypatch) -> None:
    """Verifica que _loop_principal sobreviva a un error en _procesar_job."""
    call_count = {"blpop": 0, "procesar": 0}

    class _FakeRedisResilience:
        async def blpop(self, key, timeout):
            call_count["blpop"] += 1
            if call_count["blpop"] == 1:
                # Primera llamada: retornar un job válido
                return (key, json.dumps({"kind": JOB_KIND_BOTELLAS_DUPLICADOS}))
            else:
                # Segunda y posteriores: simular error
                raise RuntimeError("Redis connection lost")

    async def _fake_procesar_job_que_falla(raw):
        call_count["procesar"] += 1
        if call_count["procesar"] > 1:
            raise RuntimeError("Unexpected second call")
        # Primera llamada: sucede sin error

    monkeypatch.setattr(worker_mod, "get_redis", lambda: _FakeRedisResilience())
    monkeypatch.setattr(worker_mod, "_procesar_job", _fake_procesar_job_que_falla)

    # Ejecutar el loop y interrumpirlo tras algunos intentos
    loop_task = asyncio.create_task(worker_mod._loop_principal())
    await asyncio.sleep(0.5)  # Dejar que el loop procese un ciclo
    loop_task.cancel()
    try:
        await loop_task
    except asyncio.CancelledError:
        pass

    # Verificar que al menos hizo un blpop y luego reintentó
    assert call_count["blpop"] >= 2, f"Expected at least 2 blpop calls, got {call_count['blpop']}"


@pytest.mark.asyncio
async def test_health_reflects_loop_status(monkeypatch) -> None:
    """Verifica que /health reporta 'ok' si el loop está vivo, 'loop_muerto' si no."""
    # Caso 1: loop está vivo
    worker_mod._loop_task = asyncio.create_task(asyncio.sleep(10))
    try:
        health_response = await worker_mod.health()
        assert health_response["status"] == "ok", "Loop vivo debe reportar 'ok'"
    finally:
        worker_mod._loop_task.cancel()
        try:
            await worker_mod._loop_task
        except asyncio.CancelledError:
            pass

    # Caso 2: loop está muerto (task completada/cancelada)
    worker_mod._loop_task = asyncio.create_task(asyncio.sleep(0))
    await asyncio.sleep(0.1)  # Permitir que complete
    health_response = await worker_mod.health()
    assert health_response["status"] == "loop_muerto", "Loop muerto debe reportar 'loop_muerto'"
    assert "time" in health_response
