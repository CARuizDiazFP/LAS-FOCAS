# Nombre de archivo: menu.py
# Ubicación de archivo: bot_telegram/ui/menu.py
# Descripción: Construcción de menús inline para el bot de Telegram

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def build_main_menu() -> InlineKeyboardMarkup:
    """Crea el menú principal con opciones disponibles."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📈 Análisis de SLA", callback_data="menu_sla")
    builder.button(text="📊 Informe de Repetitividad", callback_data="menu_repetitividad")
    builder.button(text="❌ Cerrar", callback_data="menu_close")
    builder.adjust(1)
    return builder.as_markup()
