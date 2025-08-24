# Nombre de archivo: worker.py
# Ubicación de archivo: modules/worker.py
# Descripción: Cola de tareas con RQ para generar informes de forma asíncrona
"""Módulo que configura la cola y el worker basado en RQ."""

import logging
import os
from typing import Any, Callable

from redis import Redis
from rq import Queue, Worker

from core.logging import configure_logging

configure_logging("worker")
logger = logging.getLogger("worker")

REDIS_URL = os.getenv(
    "REDIS_URL",
    f"redis://:{os.getenv('REDIS_PASSWORD', '')}@redis:6379/0",
)
IS_ASYNC = os.getenv("WORKER_ASYNC", "true").lower() == "true"
redis_conn = Redis.from_url(REDIS_URL)
queue = Queue("informes", connection=redis_conn, is_async=IS_ASYNC)


def enqueue_informe(func: Callable[..., Any], *args: Any, **kwargs: Any):
    """Encola una función para su ejecución en segundo plano."""
    return queue.enqueue(func, *args, **kwargs)


def main() -> None:
    """Inicia un worker que procesa la cola de informes."""
    worker = Worker([queue], connection=redis_conn)
    logger.info("action=worker_iniciado queue=%s", queue.name)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
