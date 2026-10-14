# Nombre de archivo: test_fo_monitor_worker.py
# Ubicación de archivo: tests/test_fo_monitor_worker.py
# Descripción: Tests del worker de FO Monitor (health con loop muerto y tick síncrono con fakes)

import asyncio

from core.services.fo_monitor.motor import ResumenTick
from modules.fo_monitor_worker import worker as worker_mod


def test_health_sin_loop_reporta_loop_muerto(monkeypatch):
    monkeypatch.setattr(worker_mod, "_loop_task", None)
    estado = asyncio.run(worker_mod.health())
    assert estado["status"] == "loop_muerto"
    assert estado["service"] == "fo_monitor"


def test_tick_sync_usa_sesion_y_gateway(monkeypatch):
    llamadas = {}

    class _Sesion:
        def __enter__(self):
            return "sesion"

        def __exit__(self, *exc):
            return False

    def _tick(session, gateway):
        llamadas["args"] = (session, gateway)
        return ResumenTick(consultas_enviadas=2)

    monkeypatch.setattr(worker_mod, "SessionLocal", lambda: _Sesion())
    monkeypatch.setattr(worker_mod, "tick", _tick)
    monkeypatch.setattr(worker_mod, "_gateway", "gw")
    resumen = worker_mod._tick_sync()
    assert llamadas["args"] == ("sesion", "gw")
    assert resumen["consultas_enviadas"] == 2
