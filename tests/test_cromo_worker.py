# Nombre de archivo: test_cromo_worker.py
# Ubicación de archivo: tests/test_cromo_worker.py
# Descripción: Tests del worker dedicado de ingesta Cromo (scheduler, reconciliación, endpoints), sin red ni DB real

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest
from fastapi.testclient import TestClient

from modules.cromo_worker import worker


# ── Fakes ────────────────────────────────────────────────────────────────────


@dataclass
class _ConfigFake:
    id: int = 1
    habilitado: bool = False
    intervalo_horas: int = 24
    hora_inicio: Optional[int] = None
    psize: int = 5
    max_paginas: Optional[int] = None
    clases: list = field(default_factory=lambda: [68, 121, 122, 123, 125])
    ultima_ejecucion: Any = None
    ultimo_error: Any = None


@dataclass
class _CorridaFake:
    id: int
    estado: str = "EN_CURSO"
    params: dict = field(default_factory=dict)
    finalizada_at: Any = None


class _ResultadoScalars:
    def __init__(self, filas: list) -> None:
        self._filas = filas

    def scalars(self):
        return self

    def all(self):
        return self._filas


class _SesionFake:
    def __init__(self, config: Optional[_ConfigFake] = None, corridas: Optional[dict[int, _CorridaFake]] = None) -> None:
        self._config = config
        self._corridas = corridas or {}
        self.agregados: list = []
        self.commits = 0

    async def get(self, modelo_cls, pk):
        if modelo_cls.__name__ == "CromoIngestaConfig":
            return self._config
        return self._corridas.get(pk)

    async def execute(self, stmt, params=None):
        en_curso = [c for c in self._corridas.values() if c.estado == "EN_CURSO"]
        return _ResultadoScalars(en_curso)

    def add(self, obj) -> None:
        self.agregados.append(obj)

    async def commit(self) -> None:
        self.commits += 1


def _fake_session_local(sesion: _SesionFake):
    class _CM:
        async def __aenter__(self):
            return sesion

        async def __aexit__(self, *a):
            return False

    return lambda: _CM()


class _SchedulerFake:
    def __init__(self, jobs: Optional[set] = None) -> None:
        self._jobs = jobs or set()
        self.added: list = []
        self.rescheduled: list = []
        self.removed: list = []

    def get_job(self, job_id):
        return object() if job_id in self._jobs else None

    def add_job(self, func, trigger=None, id=None, max_instances=None):
        self._jobs.add(id)
        self.added.append(id)

    def reschedule_job(self, job_id, trigger=None):
        self.rescheduled.append(job_id)

    def remove_job(self, job_id):
        self._jobs.discard(job_id)
        self.removed.append(job_id)


# ── _build_trigger ───────────────────────────────────────────────────────────


def test_build_trigger_sin_hora_inicio_usa_default_de_apscheduler():
    """Sin hora_inicio, no se fija `start_date` explícito: APScheduler usa su propio default
    (primera corrida a un intervalo de distancia de "ahora"), sin el ancla horaria."""
    trigger = worker._build_trigger(24, None)
    assert trigger.interval == timedelta(hours=24)
    esperado = datetime.now(timezone.utc) + timedelta(hours=24)
    assert abs((trigger.start_date - esperado).total_seconds()) < 5


def test_build_trigger_con_hora_inicio_futura_no_suma_intervalo():
    ahora = datetime.now(worker.TZ_ARG)
    hora_futura = (ahora + timedelta(hours=2)).hour
    trigger = worker._build_trigger(24, hora_futura)

    esperado = ahora.replace(hour=hora_futura, minute=0, second=0, microsecond=0)
    if esperado <= ahora:
        esperado += timedelta(hours=24)

    assert trigger.interval == timedelta(hours=24)
    assert abs((trigger.start_date - esperado).total_seconds()) < 1


def test_build_trigger_con_hora_inicio_pasada_suma_un_intervalo():
    ahora = datetime.now(worker.TZ_ARG)
    hora_pasada = (ahora - timedelta(hours=1)).hour
    trigger = worker._build_trigger(24, hora_pasada)

    esperado = ahora.replace(hour=hora_pasada, minute=0, second=0, microsecond=0) + timedelta(hours=24)
    if esperado <= ahora:
        esperado += timedelta(hours=24)

    assert abs((trigger.start_date - esperado).total_seconds()) < 1


# ── _sincronizar_configuracion ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sincronizar_sin_config_devuelve_error(monkeypatch):
    monkeypatch.setattr(worker, "_leer_config", _mk_leer_config(None))
    resultado = await worker._sincronizar_configuracion()
    assert resultado == {"ok": False, "error": "Configuración no encontrada"}


@pytest.mark.asyncio
async def test_sincronizar_agrega_job_si_habilitado_y_no_existe(monkeypatch):
    config = _ConfigFake(habilitado=True, intervalo_horas=12)
    monkeypatch.setattr(worker, "_leer_config", _mk_leer_config(config))
    scheduler = _SchedulerFake()
    worker._scheduler = scheduler
    try:
        resultado = await worker._sincronizar_configuracion()
    finally:
        worker._scheduler = None

    assert resultado["ok"] is True
    assert resultado["habilitado"] is True
    assert scheduler.added == [worker.JOB_ID]


@pytest.mark.asyncio
async def test_sincronizar_remueve_job_si_deshabilitado(monkeypatch):
    config = _ConfigFake(habilitado=False)
    monkeypatch.setattr(worker, "_leer_config", _mk_leer_config(config))
    scheduler = _SchedulerFake(jobs={worker.JOB_ID})
    worker._scheduler = scheduler
    try:
        await worker._sincronizar_configuracion()
    finally:
        worker._scheduler = None

    assert scheduler.removed == [worker.JOB_ID]


def _mk_leer_config(config):
    async def _fake():
        return config

    return _fake


# ── _reconciliar_corridas_huerfanas ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconciliar_cierra_corridas_en_curso_como_fallida(monkeypatch):
    corrida = _CorridaFake(id=42, estado="EN_CURSO")
    sesion = _SesionFake(corridas={42: corrida})
    monkeypatch.setattr(worker, "AsyncSessionLocal", _fake_session_local(sesion))

    await worker._reconciliar_corridas_huerfanas()

    assert corrida.estado == "FALLIDA"
    assert corrida.finalizada_at is not None
    assert len(sesion.agregados) == 1
    assert sesion.agregados[0].accion == "ERROR"
    assert sesion.commits == 1


@pytest.mark.asyncio
async def test_reconciliar_no_hace_nada_sin_corridas_huerfanas(monkeypatch):
    sesion = _SesionFake(corridas={})
    monkeypatch.setattr(worker, "AsyncSessionLocal", _fake_session_local(sesion))

    await worker._reconciliar_corridas_huerfanas()

    assert sesion.commits == 0


# ── _crear_corrida_desde_config / _continuar_en_bg / _job_programado ────────


@pytest.mark.asyncio
async def test_crear_corrida_desde_config_usa_los_valores_guardados(monkeypatch):
    config = _ConfigFake(psize=10, max_paginas=1, clases=[68])
    monkeypatch.setattr(worker, "_leer_config", _mk_leer_config(config))
    sesion = _SesionFake()
    monkeypatch.setattr(worker, "AsyncSessionLocal", _fake_session_local(sesion))

    llamada = {}

    async def _iniciar_corrida_fake(sesion_arg, *, usuario, psize, max_paginas, clases):
        llamada.update(usuario=usuario, psize=psize, max_paginas=max_paginas, clases=clases)
        return _CorridaFake(id=99)

    monkeypatch.setattr(worker, "iniciar_corrida", _iniciar_corrida_fake)

    corrida_id = await worker._crear_corrida_desde_config("admin2")

    assert corrida_id == 99
    assert llamada == {"usuario": "admin2", "psize": 10, "max_paginas": 1, "clases": [68]}


@pytest.mark.asyncio
async def test_crear_corrida_desde_config_sin_config_lanza_error(monkeypatch):
    monkeypatch.setattr(worker, "_leer_config", _mk_leer_config(None))
    with pytest.raises(RuntimeError):
        await worker._crear_corrida_desde_config("admin2")


@pytest.mark.asyncio
async def test_job_programado_omite_si_deshabilitado(monkeypatch):
    config = _ConfigFake(habilitado=False)
    monkeypatch.setattr(worker, "_leer_config", _mk_leer_config(config))
    llamado = {"crear": False}

    async def _no_deberia_llamarse(usuario):
        llamado["crear"] = True
        return 1

    monkeypatch.setattr(worker, "_crear_corrida_desde_config", _no_deberia_llamarse)

    await worker._job_programado()

    assert llamado["crear"] is False


@pytest.mark.asyncio
async def test_job_programado_dispara_si_habilitado(monkeypatch):
    config = _ConfigFake(habilitado=True)
    monkeypatch.setattr(worker, "_leer_config", _mk_leer_config(config))

    async def _crear_fake(usuario):
        assert usuario == worker.USUARIO_SCHEDULER
        return 55

    continuado = {}

    async def _continuar_fake(corrida_id):
        continuado["id"] = corrida_id

    monkeypatch.setattr(worker, "_crear_corrida_desde_config", _crear_fake)
    monkeypatch.setattr(worker, "_continuar_en_bg", _continuar_fake)

    await worker._job_programado()

    assert continuado["id"] == 55


# ── Endpoints HTTP (FastAPI TestClient) ──────────────────────────────────────


def test_health_devuelve_estado_actual(monkeypatch):
    monkeypatch.setitem(worker._worker_status, "status", "ok")
    monkeypatch.setitem(worker._worker_status, "habilitado", True)
    client = TestClient(worker.app)

    res = client.get("/health")

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["habilitado"] is True
    assert body["service"] == worker.NOMBRE_SERVICIO


def test_reload_devuelve_500_si_no_hay_config(monkeypatch):
    async def _sin_config():
        return {"ok": False, "error": "Configuración no encontrada"}

    monkeypatch.setattr(worker, "_sincronizar_configuracion", _sin_config)
    client = TestClient(worker.app)

    res = client.post("/reload")

    assert res.status_code == 500


def test_run_con_corrida_id_dispara_continuar_en_bg(monkeypatch):
    llamados = []

    async def _continuar_fake(corrida_id):
        llamados.append(corrida_id)

    monkeypatch.setattr(worker, "_continuar_en_bg", _continuar_fake)
    client = TestClient(worker.app)

    res = client.post("/run", json={"corrida_id": 7})

    assert res.status_code == 202
    assert res.json() == {"ok": True, "corrida_id": 7}


def test_run_sin_corrida_id_crea_una_nueva(monkeypatch):
    async def _crear_fake(usuario):
        assert usuario == "admin2"
        return 123

    async def _continuar_fake(corrida_id):
        pass

    monkeypatch.setattr(worker, "_crear_corrida_desde_config", _crear_fake)
    monkeypatch.setattr(worker, "_continuar_en_bg", _continuar_fake)
    client = TestClient(worker.app)

    res = client.post("/run", json={"usuario": "admin2"})

    assert res.status_code == 202
    assert res.json() == {"ok": True, "corrida_id": 123}


def test_run_sin_corrida_id_503_si_no_hay_config(monkeypatch):
    async def _sin_config(usuario):
        raise RuntimeError("No hay configuración de ingesta Cromo persistida")

    monkeypatch.setattr(worker, "_crear_corrida_desde_config", _sin_config)
    client = TestClient(worker.app)

    res = client.post("/run", json={})

    assert res.status_code == 503
