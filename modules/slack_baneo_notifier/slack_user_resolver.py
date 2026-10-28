# Nombre de archivo: slack_user_resolver.py
# Ubicación de archivo: modules/slack_baneo_notifier/slack_user_resolver.py
# Descripción: Shim de re-exports de la resolución de usuario de Slack (vive en core/services)

"""Shim de compatibilidad: la resolución vive en `core/services/slack_usuarios.py` (P11).
Este módulo sólo re-exporta."""

from __future__ import annotations

from core.services.slack_usuarios import *  # noqa: F401,F403
from core.services.slack_usuarios import __all__  # noqa: F401
