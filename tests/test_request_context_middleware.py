# Nombre de archivo: test_request_context_middleware.py
# Ubicación de archivo: tests/test_request_context_middleware.py
# Descripción: Prueba el middleware de contexto de aiogram

import asyncio
import types
import uuid

from bot_telegram.middlewares.request_id import RequestContextMiddleware
from core.logging import request_id_var, tg_user_id_var


def test_request_context_middleware_assigns_ids():
    middleware = RequestContextMiddleware()

    user = types.SimpleNamespace(id=123)
    message = types.SimpleNamespace(from_user=user)
    event = types.SimpleNamespace(message=message, callback_query=None)

    async def handler(event, data):
        return request_id_var.get(), tg_user_id_var.get(), data["request_id"]

    req_id_ctx, tg_id_ctx, req_id_data = asyncio.run(middleware(handler, event, {}))
    uuid.UUID(req_id_ctx)
    assert tg_id_ctx == "123"
    assert req_id_ctx == req_id_data

