# Nombre de archivo: worker.py
# Ubicación de archivo: modules/informes_repetitividad/worker.py
# Descripción: Worker placeholder para tareas pesadas de mapas/geopandas

"""Worker encargado de generar mapas de repetitividad.

En futuras iteraciones este módulo se conectará a una cola (Redis/Celery o similar)
para recibir trabajos de generación de mapas cuando `MAPS_ENABLED=true`. Por ahora
sólo expone un comando placeholder para demostrar la separación del stack.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("Worker de repetitividad inicializado. Esperando tareas...")
    while True:  # pragma: no cover - loop controlado externamente
        time.sleep(60)


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level="INFO", format="%(levelname)s|%(name)s|%(message)s")
    main()
