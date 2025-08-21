# Nombre de archivo: menu.py
# Ubicación de archivo: bot_telegram/handlers/menu.py
# Descripción: Handlers para el menú principal del bot de Telegram

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot_telegram.ui.menu import build_main_menu

router = Router()
logger = logging.getLogger(__name__)


@router.message(commands={"menu"})
async def cmd_menu(msg: Message) -> None:
    """Muestra el menú principal cuando se usa /menu."""
    logger.info("Usuario %s abrió el menú con /menu", msg.from_user.id)
    await msg.answer("Seleccioná una opción:", reply_markup=build_main_menu())


@router.callback_query(F.data.in_({"menu_sla", "menu_repetitividad", "menu_close"}))
async def on_menu_callback(cb: CallbackQuery) -> None:
    """Gestiona las opciones del menú principal."""
    if cb.data == "menu_sla":
        logger.info("Usuario %s seleccionó Análisis de SLA", cb.from_user.id)
        await cb.message.edit_text(
            "📈 Análisis de SLA — implementación pendiente. Se agregará el flujo."
        )
        await start_sla_flow(cb)
    elif cb.data == "menu_repetitividad":
        logger.info("Usuario %s seleccionó Informe de Repetitividad", cb.from_user.id)
        await cb.message.edit_text(
            "📊 Informe de Repetitividad — implementación pendiente. Se agregará el flujo."
        )
        await start_repetitividad_flow(cb)
    elif cb.data == "menu_close":
        logger.info("Usuario %s cerró el menú", cb.from_user.id)
        await cb.message.edit_text("Menú cerrado")
    await cb.answer()


async def start_sla_flow(cb: CallbackQuery) -> None:
    """Hook para conectar con el flujo real de SLA."""
    logger.info("start_sla_flow llamado para %s (pendiente de implementación)", cb.from_user.id)


async def start_repetitividad_flow(cb: CallbackQuery) -> None:
    """Hook para conectar con el flujo real de Repetitividad."""
    logger.info(
        "start_repetitividad_flow llamado para %s (pendiente de implementación)",
        cb.from_user.id,
    )
