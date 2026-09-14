# Nombre de archivo: consola.py
# Ubicación de archivo: scripts/agentes/consola.py
# Descripción: Salida estándar y logging de diagnóstico compartidos por las CLIs agénticas

"""Contrato de salida de las CLIs de coordinación agéntica.

Separa dos canales, que es la forma de respetar la regla de ``AGENTS.md`` ("usar
``logging``, no ``print()``") sin romper el contrato de una herramienta de línea de
comandos:

- **stdout**: el resultado que consume el humano o el agente (tablas, JSON). Es el
  producto de la herramienta, no una traza de diagnóstico.
- **stderr vía ``logging``**: diagnóstico, advertencias, conflictos y auditoría.

No se importa ``core.logging`` a propósito: este tooling debe poder ejecutarse con
Python de sistema, sin el venv y desde un worktree recién creado, sin arrastrar la
configuración de la aplicación. Se replica su formato de línea para que los logs sean
homogéneos.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

FORMATO = "%(asctime)s service=%(name)s level=%(levelname)s msg=%(message)s"


def configurar_logging(nombre: str, *, verboso: bool = False) -> logging.Logger:
    """Configura el logger de diagnóstico sobre stderr y lo devuelve.

    Reapunta el handler a ``sys.stderr`` en cada llamada: el módulo se importa una vez
    pero la CLI puede invocarse varias veces en el mismo proceso (tests, orquestadores)
    y el stream vigente puede haber cambiado entre invocaciones.
    """
    logger = logging.getLogger(nombre)
    if not logger.handlers:
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(logging.Formatter(FORMATO))
        logger.addHandler(handler)
        logger.propagate = False
    for handler in logger.handlers:
        if not isinstance(handler, logging.StreamHandler) or handler.stream is sys.stderr:
            continue
        try:
            handler.setStream(sys.stderr)
        except ValueError:
            # El stream anterior ya estaba cerrado y no admite flush: se reemplaza directo.
            handler.stream = sys.stderr
    logger.setLevel(logging.DEBUG if verboso else logging.INFO)
    return logger


def emitir(texto: str = "") -> None:
    """Escribe una línea del resultado en stdout."""
    sys.stdout.write(f"{texto}\n")


def emitir_json(datos: Any) -> None:
    """Escribe el resultado como JSON en stdout (modo ``--json`` de las CLIs)."""
    sys.stdout.write(json.dumps(datos, ensure_ascii=False, indent=2, default=str) + "\n")
