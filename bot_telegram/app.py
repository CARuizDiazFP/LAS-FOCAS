# Nombre de archivo: app.py
# Ubicación de archivo: bot_telegram/app.py
# Descripción: Entrypoint del bot (aiogram 3.x) con long polling y Allowlist

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot_telegram.filters.allowlist import AllowlistMiddleware
from bot_telegram.handlers.basic import router as basic_router
from bot_telegram.handlers.commands import router as commands_router
from bot_telegram.flows.repetitividad import router as rep_router
from bot_telegram.handlers.intent import router as intent_router
from bot_telegram.handlers.menu import router as menu_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger("bot")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


async def main():
    if not TOKEN:
        raise RuntimeError("Falta TELEGRAM_BOT_TOKEN en el entorno")

    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # Allowlist
    allowlist = AllowlistMiddleware()
    dp.message.middleware(allowlist)
    dp.callback_query.middleware(allowlist)

    # Routers
    dp.include_router(rep_router)
    dp.include_router(menu_router)
    dp.include_router(commands_router)
    dp.include_router(intent_router)
    dp.include_router(basic_router)

    allowed_updates = dp.resolve_used_update_types()
    logger.info(
        "service=bot action=start_polling allowed_updates=%s", allowed_updates
    )
    await dp.start_polling(bot, allowed_updates=allowed_updates)


if __name__ == "__main__":
    asyncio.run(main())
