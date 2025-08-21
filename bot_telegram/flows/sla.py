# Nombre de archivo: sla.py
# Ubicación de archivo: bot_telegram/flows/sla.py
# Descripción: Flujo unificado para el análisis de SLA del bot

import logging
from aiogram.types import Message

logger = logging.getLogger(__name__)


def build_sla_response() -> str:
    """Genera el texto base para el análisis de SLA."""
    return "📈 Análisis de SLA — implementación pendiente"


async def start_sla_flow(msg: Message, origin: str) -> None:
    """Inicia el flujo de SLA enviando el mensaje estándar."""
    tg_user_id = msg.from_user.id
    logger.info(
        "service=bot route=%s action=start_sla_flow tg_user_id=%s",
        origin,
        tg_user_id,
    )
    await msg.answer(build_sla_response())
