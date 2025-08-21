# Nombre de archivo: repetitividad.py
# Ubicación de archivo: bot_telegram/flows/repetitividad.py
# Descripción: Flujo unificado para el informe de repetitividad del bot

import logging
from aiogram.types import Message

logger = logging.getLogger(__name__)


def build_repetitividad_response() -> str:
    """Genera el texto base para el informe de repetitividad."""
    return "📊 Informe de Repetitividad — implementación pendiente"


async def start_repetitividad_flow(msg: Message, origin: str) -> None:
    """Inicia el flujo de Repetitividad enviando el mensaje estándar."""
    tg_user_id = msg.from_user.id
    logger.info(
        "service=bot route=%s action=start_repetitividad_flow tg_user_id=%s",
        origin,
        tg_user_id,
    )
    await msg.answer(build_repetitividad_response())
