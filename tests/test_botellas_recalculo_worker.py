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
async def test_loop_principal_redis_error_resilience(monkeypatch) -> None:
    """Prueba que _loop_principal se RECUPERE de un error de blpop y siga sondeando después.

    El fake sólo falla en la PRIMERA llamada a blpop; desde la segunda responde None (el timeout
    normal de "sin jobs"). Esto es deliberado: un fake que falla en TODAS las llamadas no puede
    distinguir "el loop se recupera y sigue sondeando" de "el loop se rindió para siempre tras el
    primer error" — una implementación rota que deja de sondear después del primer error pasa
    igual con ese fake (ver Fix Round 3 en docs del Task 4). Al recuperarse desde la segunda
    llamada, sólo una implementación que efectivamente vuelve a hacer `continue` y reintentar el
    BLPOP puede acumular llamadas *después* del ciclo de error+backoff.
    """

    class _FakeRedisRecupera:
        def __init__(self) -> None:
            self.calls = 0

        async def blpop(self, key, timeout):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("redis connection lost")
            await asyncio.sleep(timeout)  # simula el bloqueo real de BLPOP hasta el timeout
            return None

    fake_redis = _FakeRedisRecupera()
    monkeypatch.setattr(worker_mod, "get_redis", lambda: fake_redis)
    # Se mockea sólo la CONSTANTE (no asyncio.sleep) para acelerar el backoff sin romper el
    # scheduling real del propio test — mockear asyncio.sleep globalmente impide que el loop
    # ceda el control al event loop y el task nunca llega a ejecutarse (ver Fix Round 2/3).
    monkeypatch.setattr(worker_mod, "BLPOP_TIMEOUT_SECONDS", 0.01)

    loop_task = asyncio.create_task(worker_mod._loop_principal())
    try:
        await asyncio.sleep(0.3)  # ventana real y SIN mockear: tiempo de sobra para varios ciclos
        assert not loop_task.done(), "El loop no debe terminar tras un error de Redis"
        assert fake_redis.calls >= 3, (
            "El loop debe seguir llamando a blpop bien después del ciclo error+backoff, no sólo "
            f"una vez — se registraron {fake_redis.calls} llamadas"
        )
    finally:
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_health_reflects_loop_status(monkeypatch) -> None:
    """Verifica que /health reporta 'ok' si el loop está vivo, 'loop_muerto' si no."""
    try:
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
    finally:
        # Limpiar el estado global para aislamiento de pruebas
        worker_mod._loop_task = None
