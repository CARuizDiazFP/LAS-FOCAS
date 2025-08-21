# Nombre de archivo: commands.py
# Ubicación de archivo: bot_telegram/handlers/commands.py
# Descripción: Handlers de comandos del bot que reutilizan flujos unificados

import logging
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot_telegram.diag.counters import inc, snapshot
from bot_telegram.flows.repetitividad import start_repetitividad_flow
from bot_telegram.flows.sla import start_sla_flow

router = Router()
logger = logging.getLogger(__name__)


@router.message(Command("sla"))
async def cmd_sla(message: Message) -> None:
    """Inicia el flujo de SLA desde el comando /sla."""
    tg_user_id = message.from_user.id
    logger.info(
        "service=bot route=command cmd=/sla tg_user_id=%s",
        tg_user_id,
    )
    inc("commands_sla")
    await start_sla_flow(message, origin="command")


@router.message(Command("repetitividad"))
async def cmd_repetitividad(message: Message) -> None:
    """Inicia el flujo de Repetitividad desde el comando /repetitividad."""
    tg_user_id = message.from_user.id
    logger.info(
        "service=bot route=command cmd=/repetitividad tg_user_id=%s",
        tg_user_id,
    )
    inc("commands_rep")
    await start_repetitividad_flow(message, origin="command")


@router.message(Command("diag"))
async def cmd_diag(message: Message) -> None:
    """Muestra los contadores de comandos y callbacks recibidos."""
    tg_user_id = message.from_user.id
    logger.info(
        "service=bot route=command cmd=/diag tg_user_id=%s",
        tg_user_id,
    )
    counts = snapshot()
    text = (
        f"commands_sla: {counts.get('commands_sla', 0)} | callbacks_sla: {counts.get('callbacks_sla', 0)}\n"
        f"commands_rep: {counts.get('commands_rep', 0)} | callbacks_rep: {counts.get('callbacks_rep', 0)}"
    )
    await message.answer(text)
