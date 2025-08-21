# Nombre de archivo: basic.py
# Ubicación de archivo: bot_telegram/handlers/basic.py
# Descripción: Comandos básicos (/start, /help, /ping) y handler de fallback

from aiogram import Router
from aiogram.types import Message

router = Router()


@router.message(commands={"start"})
async def cmd_start(msg: Message):
    await msg.answer("🦭 ¡Hola! Soy el bot de LAS-FOCAS. Probá /ping o /help.")


@router.message(commands={"help"})
async def cmd_help(msg: Message):
    await msg.answer("Comandos disponibles:\n/start – bienvenida\n/ping – prueba de latencia\n/help – esta ayuda")


@router.message(commands={"ping"})
async def cmd_ping(msg: Message):
    await msg.answer("pong 🏓")


@router.message()
async def fallback(msg: Message):
    await msg.answer("No entendí. Probá /help 🤖")
