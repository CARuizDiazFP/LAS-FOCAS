# Nombre de archivo: worker.py
# Ubicación de archivo: modules/worker.py
# Descripción: Proceso base para ejecutar tareas en segundo plano
"""Inicio simple del servicio worker."""

from time import sleep
import logging

from core.logging import configure_logging

configure_logging("worker")
logger = logging.getLogger("worker")


def main() -> None:
    """Bucle principal del worker."""
    logger.info("action=worker_iniciado")
    try:
        while True:
            sleep(60)
    except KeyboardInterrupt:
        logger.info("action=worker_detener")


if __name__ == "__main__":
    main()
