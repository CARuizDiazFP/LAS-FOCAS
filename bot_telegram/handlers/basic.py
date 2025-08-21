# Nombre de archivo: basic.py
# Ubicación de archivo: bot_telegram/handlers/basic.py
# Descripción: Comandos básicos (/start, /help, /ping) y handler de fallback

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from bot_telegram.ui.reply_keyboard import get_main_reply_keyboard

router = Router()


@router.message(CommandStart())
async def cmd_start(msg: Message):
    """Mensaje de bienvenida opcional mostrando el teclado de atajos."""
    await msg.answer(
        "🦭 ¡Hola! Soy el bot de LAS-FOCAS. Probá /ping o /help.",
        reply_markup=get_main_reply_keyboard(),
    )


@router.message(Command("help"))
async def cmd_help(msg: Message):
    await msg.answer("Comandos disponibles:\n/start – bienvenida\n/ping – prueba de latencia\n/help – esta ayuda")


@router.message(Command("ping"))
async def cmd_ping(msg: Message):
    await msg.answer("pong 🏓")


@router.message()
async def fallback(msg: Message):
    await msg.answer("No entendí. Probá /help 🤖")
