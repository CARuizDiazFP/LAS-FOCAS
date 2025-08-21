# Nombre de archivo: allowlist.py
# Ubicación de archivo: bot_telegram/filters/allowlist.py
# Descripción: Filtro/Middleware que limita el uso del bot a IDs permitidos desde TELEGRAM_ALLOWED_IDS

import logging
import os

from aiogram import BaseMiddleware
from aiogram.types import Message, Update

logger = logging.getLogger(__name__)


class AllowlistMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        super().__init__()
        raw = os.getenv("TELEGRAM_ALLOWED_IDS", "")
        self.allowed_ids = {int(x.strip()) for x in raw.split(",") if x.strip().isdigit()}

    async def __call__(self, handler, event: Update, data):
        user_id = None
        if hasattr(event, "message") and isinstance(event.message, Message):
            user_id = event.message.from_user.id
        elif hasattr(event, "callback_query") and event.callback_query is not None:
            user_id = event.callback_query.from_user.id

        if user_id is None or (self.allowed_ids and user_id not in self.allowed_ids):
            # Registrar intentos de acceso no autorizados incluyendo el ID de Telegram
            logger.warning(
                "acceso_denegado", extra={"tg_user_id": user_id}
            )
            if hasattr(event, "message") and isinstance(event.message, Message):
                await event.message.answer("Acceso no autorizado")
            elif hasattr(event, "callback_query") and event.callback_query is not None:
                await event.callback_query.answer("Acceso no autorizado")
            return
        return await handler(event, data)
