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

    async def _fake_handler(payload):
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
async def test_recalculo_no_bloquea_el_event_loop(monkeypatch) -> None:
    """El cómputo pesado va a un hilo (`asyncio.to_thread`): mientras corre, el event loop debe
    seguir atendiendo — es lo que mantiene vivo el `GET /health` que Docker consulta. Antes se
    ejecutaba directo en el loop y el contenedor se marcaba `unhealthy` durante cada recálculo
    (~100s medidos contra el dev real, 2026-08-22)."""
    import threading
    import time

    hilo_del_computo: dict = {}

    def _detectar_lento(session):
        hilo_del_computo["thread"] = threading.current_thread()
        time.sleep(0.2)  # bloqueante a propósito: si corriera en el loop, lo congelaría
        return []

    async def _fake_guardar(grupos):
        return None

    class _FakeSessionLocal:
        def __enter__(self):
            return None

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(worker_mod, "detectar_grupos_duplicados_botellas", _detectar_lento)
    monkeypatch.setattr(worker_mod, "guardar_cache_duplicados", _fake_guardar)
    monkeypatch.setattr(worker_mod, "SessionLocal", lambda: _FakeSessionLocal())
    monkeypatch.setattr(worker_mod, "get_redis", lambda: _FakeRedisPublish())

    hilo_principal = threading.current_thread()
    latidos = {"veces": 0}

    async def _latir():
        # Simula al endpoint /health: si el loop está bloqueado, esta corrutina no avanza.
        while True:
            latidos["veces"] += 1
            await asyncio.sleep(0.01)

    latido_task = asyncio.create_task(_latir())
    try:
        await worker_mod._recalcular_botellas_duplicados()
    finally:
        latido_task.cancel()

    assert hilo_del_computo["thread"] is not hilo_principal, "el cómputo debe correr en otro hilo"
    assert latidos["veces"] >= 5, (
        "el event loop debió seguir atendiendo durante el recálculo — "
        f"sólo avanzó {latidos['veces']} veces"
    )


@pytest.mark.asyncio
async def test_loop_principal_sobrevive_a_un_get_redis_que_falla(monkeypatch) -> None:
    """`get_redis()` se construye DENTRO del try del loop: si construir el cliente falla (config o
    secreto ilegible), el loop debe loguear, esperar y reintentar como con cualquier otro fallo —
    no morir antes del primer BLPOP, que es lo que pasaba con el cliente creado fuera del `while`."""

    class _FakeRedisOk:
        def __init__(self) -> None:
            self.calls = 0

        async def blpop(self, key, timeout):
            self.calls += 1
            await asyncio.sleep(timeout)
            return None

    fake_redis = _FakeRedisOk()
    intentos = {"get_redis": 0}

    def _get_redis_falla_la_primera():
        intentos["get_redis"] += 1
        if intentos["get_redis"] == 1:
            raise RuntimeError("no se pudo leer el secreto de Redis")
        return fake_redis

    monkeypatch.setattr(worker_mod, "get_redis", _get_redis_falla_la_primera)
    monkeypatch.setattr(worker_mod, "BLPOP_TIMEOUT_SECONDS", 0.01)

    loop_task = asyncio.create_task(worker_mod._loop_principal())
    try:
        await asyncio.sleep(0.3)
        assert not loop_task.done(), "el loop no debe morir si get_redis() falla"
        assert intentos["get_redis"] >= 2, "debe volver a construir el cliente en el siguiente ciclo"
        assert fake_redis.calls >= 1, "tras recuperarse debe llegar al BLPOP"
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


# --- árbitro de Cromo: job `arbitro_evaluar` ---------------------------------------------------

from types import SimpleNamespace  # noqa: E402

from core.services.cromo.arbitro import aviso as aviso_mod  # noqa: E402
from core.services.cromo.arbitro import motor as motor_mod  # noqa: E402


class _SesionFake:
    """Sesión async mínima: `get` devuelve filas por id, `add` las registra, cuenta commits."""

    filas: dict = {}
    commits = 0
    rollbacks = 0
    _seq = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, _modelo, id_):
        return type(self).filas.get(id_)

    def add(self, fila):
        type(self)._seq += 1
        fila.id = 1000 + type(self)._seq
        type(self).filas[fila.id] = fila

    async def flush(self):
        return None

    async def commit(self):
        type(self).commits += 1

    async def rollback(self):
        type(self).rollbacks += 1


@pytest.fixture
def arbitro_env(monkeypatch):
    class Sesion(_SesionFake):
        filas: dict = {}
        commits = 0
        rollbacks = 0
        _seq = 0

    avisos = []

    async def _en_curso(i):
        avisos.append(("en_curso", i))

    async def _evaluado(resumen, i):
        avisos.append(("evaluado", i))

    monkeypatch.setattr(worker_mod, "AsyncSessionLocal", lambda: Sesion())
    monkeypatch.setattr(worker_mod, "avisar_en_curso", _en_curso)
    monkeypatch.setattr(worker_mod, "avisar_evaluacion", _evaluado)
    return SimpleNamespace(Sesion=Sesion, avisos=avisos)


def _payload(**extra):
    base = {
        "kind": "arbitro_evaluar",
        "alcance": {"tipo": "TODO"},
        "disparo": "VIEWER",
        "motivo": "",
        "evaluacion_id": None,
        "reglas": None,
    }
    base.update(extra)
    return base


def _fila_en_cola(Sesion, id_=7):
    from db.models.cromo import CromoArbitroEvaluacion

    fila = CromoArbitroEvaluacion(
        id=id_, disparo="VIEWER", alcance={"tipo": "TODO"}, estado="EN_COLA"
    )
    Sesion.filas[id_] = fila
    return fila


@pytest.mark.asyncio
async def test_dispatch_arbitro_llama_evaluar(monkeypatch, arbitro_env) -> None:
    llamadas = []

    async def _evaluar(sesion, alcance, disparo, *, reglas=None, codigos=None):
        llamadas.append((alcance, disparo, codigos))
        return motor_mod.ResumenEvaluacion()

    monkeypatch.setattr(motor_mod, "evaluar", _evaluar)
    await worker_mod._procesar_job(json.dumps(_payload(reglas=["R1"])))
    assert len(llamadas) == 1
    assert llamadas[0][0].a_dict() == {"tipo": "TODO", "ids": []}
    assert llamadas[0][1:] == ("VIEWER", ["R1"])
    assert arbitro_env.Sesion.commits >= 3  # EN_CURSO, evaluación, cierre


@pytest.mark.asyncio
async def test_dispatch_arbitro_payload_invalido_no_llama(monkeypatch, arbitro_env) -> None:
    async def _evaluar(*a, **k):
        raise AssertionError("no debía llamarse")

    monkeypatch.setattr(motor_mod, "evaluar", _evaluar)
    await worker_mod._procesar_job(json.dumps(_payload(alcance={"tipo": "X"})))
    await worker_mod._procesar_job(json.dumps(_payload(disparo="NOPE")))
    assert arbitro_env.Sesion.commits == 0


@pytest.mark.asyncio
async def test_dispatch_arbitro_cierra_evaluacion_ok(monkeypatch, arbitro_env) -> None:
    fila = _fila_en_cola(arbitro_env.Sesion)

    async def _evaluar(sesion, alcance, disparo, *, reglas=None, codigos=None):
        return motor_mod.ResumenEvaluacion(nuevas=2, aplicadas_auto=[1])

    monkeypatch.setattr(motor_mod, "evaluar", _evaluar)
    await worker_mod._procesar_job(json.dumps(_payload(evaluacion_id=7)))
    assert fila.estado == "OK"
    assert fila.resumen["nuevas"] == 2
    assert fila.iniciada_en is not None and fila.terminada_en is not None
    assert arbitro_env.avisos == [("en_curso", 7), ("evaluado", 7)]


@pytest.mark.asyncio
async def test_dispatch_arbitro_omitida(monkeypatch, arbitro_env) -> None:
    fila = _fila_en_cola(arbitro_env.Sesion)

    async def _evaluar(sesion, alcance, disparo, *, reglas=None, codigos=None):
        return motor_mod.ResumenEvaluacion(omitida="ingesta_en_curso")

    monkeypatch.setattr(motor_mod, "evaluar", _evaluar)
    await worker_mod._procesar_job(json.dumps(_payload(evaluacion_id=7)))
    assert fila.estado == "OMITIDA"


@pytest.mark.asyncio
async def test_dispatch_arbitro_excepcion_marca_fallida(monkeypatch, arbitro_env) -> None:
    fila = _fila_en_cola(arbitro_env.Sesion)

    async def _evaluar(*a, **k):
        raise RuntimeError("SELECT secreto FROM x")

    monkeypatch.setattr(motor_mod, "evaluar", _evaluar)
    await worker_mod._procesar_job(json.dumps(_payload(evaluacion_id=7)))
    assert fila.estado == "FALLIDA"
    assert fila.error.startswith("RuntimeError")
    assert "SELECT" not in fila.error
    assert arbitro_env.Sesion.rollbacks == 1


@pytest.mark.asyncio
async def test_dispatch_arbitro_codigos_invalidos(monkeypatch, arbitro_env) -> None:
    fila = _fila_en_cola(arbitro_env.Sesion)

    async def _evaluar(*a, **k):
        raise ValueError("código desconocido")

    monkeypatch.setattr(motor_mod, "evaluar", _evaluar)
    await worker_mod._procesar_job(json.dumps(_payload(evaluacion_id=7, reglas=["ZZZ"])))
    assert fila.estado == "FALLIDA" and fila.error == "codigos_invalidos"


@pytest.mark.asyncio
async def test_dispatch_arbitro_sin_evaluacion_id_crea_fila(monkeypatch, arbitro_env) -> None:
    async def _evaluar(*a, **k):
        return motor_mod.ResumenEvaluacion()

    monkeypatch.setattr(motor_mod, "evaluar", _evaluar)
    await worker_mod._procesar_job(json.dumps(_payload()))
    (fila,) = arbitro_env.Sesion.filas.values()
    assert fila.estado == "OK"
    assert fila.solicitada_por == "arbitro-cromo"
    assert fila.disparo == "VIEWER"


@pytest.mark.asyncio
async def test_dispatch_botellas_duplicados_sigue_funcionando(monkeypatch) -> None:
    llamado = []

    async def _recalcular():
        llamado.append(True)

    monkeypatch.setattr(worker_mod, "_recalcular_botellas_duplicados", _recalcular)
    await worker_mod._procesar_job(json.dumps({"kind": JOB_KIND_BOTELLAS_DUPLICADOS}))
    assert llamado == [True]


@pytest.mark.asyncio
async def test_avisar_evaluacion_sin_cambios_no_va_a_slack(monkeypatch) -> None:
    fake_redis = _FakeRedisPublish()
    import core.cache.redis_client as rc

    monkeypatch.setattr(rc, "get_redis", lambda: fake_redis)
    from core.services.cromo import inconsistencias_reporte as rep

    def _no(*a, **k):
        raise AssertionError("no debía ir a Slack")

    monkeypatch.setattr(rep, "_enviar_slack_sync", _no)
    await aviso_mod.avisar_evaluacion(motor_mod.ResumenEvaluacion(nuevas=3), 5)
    assert json.loads(fake_redis.published[0][1])["type"] == "arbitro_cromo_evaluado"


@pytest.mark.asyncio
async def test_avisar_evaluacion_nunca_lanza(monkeypatch) -> None:
    import core.cache.redis_client as rc

    def _boom():
        raise RuntimeError("redis caído")

    monkeypatch.setattr(rc, "get_redis", _boom)
    await aviso_mod.avisar_evaluacion(motor_mod.ResumenEvaluacion(aplicadas_auto=[1]), 5)
