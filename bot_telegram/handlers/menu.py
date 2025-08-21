# Nombre de archivo: menu.py
# Ubicación de archivo: bot_telegram/handlers/menu.py
# Descripción: Handlers para el menú principal del bot de Telegram

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot_telegram.diag.counters import inc
from bot_telegram.flows.repetitividad import start_repetitividad_flow
from bot_telegram.flows.sla import start_sla_flow
from bot_telegram.ui.menu import build_main_menu

router = Router()
logger = logging.getLogger(__name__)


@router.message(commands={"menu"})
async def cmd_menu(msg: Message) -> None:
    """Muestra el menú principal cuando se usa /menu."""
    logger.info(
        "service=bot route=command cmd=/menu tg_user_id=%s",
        msg.from_user.id,
    )
    await msg.answer("Seleccioná una opción:", reply_markup=build_main_menu())


@router.callback_query(F.data == "menu_sla")
async def on_menu_sla(cb: CallbackQuery) -> None:
    """Gestiona la opción del menú para SLA."""
    tg_user_id = cb.from_user.id
    logger.info(
        "service=bot route=callback data=menu_sla tg_user_id=%s",
        tg_user_id,
    )
    inc("callbacks_sla")
    await cb.answer()
    await start_sla_flow(cb.message, origin="callback")


@router.callback_query(F.data == "menu_repetitividad")
async def on_menu_repetitividad(cb: CallbackQuery, state: FSMContext) -> None:
    """Gestiona la opción del menú para Repetitividad."""
    tg_user_id = cb.from_user.id
    logger.info(
        "service=bot route=callback data=menu_repetitividad tg_user_id=%s",
        tg_user_id,
    )
    inc("callbacks_rep")
    await cb.answer()
    await start_repetitividad_flow(cb.message, state, origin="callback")


@router.callback_query(F.data == "menu_close")
async def on_menu_close(cb: CallbackQuery) -> None:
    """Cierra el mensaje de menú."""
    logger.info(
        "service=bot route=callback data=menu_close tg_user_id=%s",
        cb.from_user.id,
    )
    await cb.answer()
    await cb.message.edit_text("Menú cerrado")
