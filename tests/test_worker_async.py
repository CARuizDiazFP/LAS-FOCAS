# Nombre de archivo: test_worker_async.py
# Ubicación de archivo: tests/test_worker_async.py
# Descripción: Verifica que el worker procese tareas en la cola
"""Prueba de integración del worker usando una cola real en memoria."""

import fakeredis
from rq import Queue, SimpleWorker

from modules import worker


def sumar(x: int, y: int) -> int:
    """Función simple para sumar dos números."""
    return x + y


def test_worker_procesa_job(monkeypatch):
    """Encola un trabajo y verifica que el worker lo ejecute."""
    redis = fakeredis.FakeRedis()
    queue = Queue("informes", connection=redis)
    monkeypatch.setattr(worker, "redis_conn", redis)
    monkeypatch.setattr(worker, "queue", queue)

    job = worker.enqueue_informe(sumar, 1, 2)
    assert job.get_status() == "queued"

    w = SimpleWorker([queue], connection=redis)
    w.work(burst=True)

    job.refresh()
    assert job.result == 3
