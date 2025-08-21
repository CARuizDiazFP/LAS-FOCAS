# Nombre de archivo: request_id.py
# Ubicación de archivo: bot_telegram/middlewares/request_id.py
# Descripción: Middleware que genera request_id y captura tg_user_id para logging

import uuid

from aiogram import BaseMiddleware
from aiogram.types import Update

from core.logging import request_id_var, tg_user_id_var


class RequestContextMiddleware(BaseMiddleware):
    """Asigna `request_id` y `tg_user_id` usando contextvars."""

    async def __call__(self, handler, event: Update, data: dict):
        request_id = str(uuid.uuid4())
        token_req = request_id_var.set(request_id)

        tg_user_id = None
        if getattr(event, "message", None):
            tg_user_id = event.message.from_user.id
        elif getattr(event, "callback_query", None):
            tg_user_id = event.callback_query.from_user.id
        token_user = tg_user_id_var.set(str(tg_user_id) if tg_user_id is not None else "-")

        data["request_id"] = request_id
        try:
            return await handler(event, data)
        finally:
            request_id_var.reset(token_req)
            tg_user_id_var.reset(token_user)

