# Nombre de archivo: correccion_ingreso.py
# Ubicación de archivo: modules/slack_baneo_notifier/correccion_ingreso.py
# Descripción: Shim de re-exports de los comandos de corrección de ingreso (vive en core/services)

"""Shim de compatibilidad: el parser y los constructores de respuesta viven en
`core/services/ingreso_correccion_comandos.py` (P11). Este módulo sólo re-exporta."""

from __future__ import annotations

from core.services.ingreso_correccion_comandos import *  # noqa: F401,F403
from core.services.ingreso_correccion_comandos import __all__  # noqa: F401
