# Nombre de archivo: menu.py
# Ubicación de archivo: bot_telegram/ui/menu.py
# Descripción: Construcción de menús inline para el bot de Telegram

try:  # Opcional para entorno de pruebas sin aiogram
    from aiogram.types import InlineKeyboardMarkup  # type: ignore
    from aiogram.utils.keyboard import InlineKeyboardBuilder  # type: ignore
    _AI_AVAILABLE = True
except Exception:  # pragma: no cover
    _AI_AVAILABLE = False

    class InlineKeyboardMarkup:  # type: ignore
        pass

    class _DummyBuilder:
        def button(self, *_, **__):
            return self

        def adjust(self, *_, **__):
            return self

        def as_markup(self):
            return InlineKeyboardMarkup()

    InlineKeyboardBuilder = _DummyBuilder  # type: ignore


def build_main_menu() -> InlineKeyboardMarkup:
    """Crea el menú principal con opciones disponibles."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📈 Análisis de SLA", callback_data="menu_sla")
    builder.button(text="📊 Informe de Repetitividad", callback_data="menu_repetitividad")
    builder.button(text="❌ Cerrar", callback_data="menu_close")
    builder.adjust(1)
    return builder.as_markup()
