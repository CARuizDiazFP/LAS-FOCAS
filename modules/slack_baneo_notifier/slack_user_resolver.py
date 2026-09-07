# Nombre de archivo: slack_user_resolver.py
# Ubicación de archivo: modules/slack_baneo_notifier/slack_user_resolver.py
# Descripción: Resuelve el nombre real de un técnico a partir de su Slack user ID (users.info)

"""Resuelve `slack_user_id` (ej. 'U03DPFK0Q69') al nombre visible del técnico, vía la Slack Web API
`users.info` — hasta la Tarea 3 del refactor de baneo/Slack (2026-09-04), `Ingreso.tecnico_id`
guardaba el ID crudo porque nada en el repo llamaba `users.info` (ver docs/bot.md, sección
"Registro de movimiento Ingreso/Egreso").

El `client` recibido es el mismo `slack_sdk.WebClient` que Slack Bolt inyecta en cada handler de
evento (`IngresoListener._handle_message(self, event, client)`) — esta función no crea un cliente
nuevo, reusa el token/sesión ya autenticada del listener.

Requiere el scope `users:read` en la Slack App (agregar en el panel de Slack — no verificable desde
código, mismo criterio que `app_mentions:read` documentado en `listener.py`).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("slack_baneo_worker.slack_user_resolver")

__all__ = ["resolver_nombre_tecnico"]


def resolver_nombre_tecnico(client: Any, slack_user_id: str | None) -> str | None:
    """Devuelve el nombre visible del técnico (`display_name` o, si está vacío, `real_name`) para
    `slack_user_id`, o `None` si `slack_user_id` es `None` (nadie que resolver).

    Nunca lanza: cualquier error de la API (token sin scope `users:read`, usuario borrado, timeout de
    red) se loguea como warning y cae al ID crudo de Slack — preferible una fila con el ID crudo
    (comportamiento previo a esta tarea) a que un fallo de red bloquee el registro de ingreso.
    """
    if not slack_user_id:
        return None
    try:
        respuesta = client.users_info(user=slack_user_id)
        usuario = (respuesta or {}).get("user") or {}
        perfil = usuario.get("profile") or {}
        nombre = perfil.get("display_name") or perfil.get("real_name") or usuario.get("real_name")
        return nombre or slack_user_id
    except Exception as exc:
        logger.warning("No se pudo resolver nombre para slack_user_id=%s: %s", slack_user_id, exc)
        return slack_user_id
