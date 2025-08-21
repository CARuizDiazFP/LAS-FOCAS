# Nombre de archivo: reply_keyboard.py
# Ubicación de archivo: bot_telegram/ui/reply_keyboard.py
# Descripción: Constructores de ReplyKeyboard con atajos de comandos

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove


def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    """Teclado principal con atajos de comandos."""
    keyboard = [
        [KeyboardButton(text="/sla"), KeyboardButton(text="/repetitividad")],
        [KeyboardButton(text="/menu"), KeyboardButton(text="/hide")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def get_hide_keyboard() -> ReplyKeyboardRemove:
    """Oculta el ReplyKeyboard."""
    return ReplyKeyboardRemove()
