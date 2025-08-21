# Nombre de archivo: messages.py
# Ubicación de archivo: core/repositories/messages.py
# Descripción: Funciones para insertar mensajes en la base de datos

from __future__ import annotations

import logging
from typing import Optional

import psycopg

logger = logging.getLogger(__name__)


def insert_message(
    conn: psycopg.Connection,
    conversation_id: int,
    tg_user_id: int,
    role: str,
    text: str,
    normalized_text: str,
    intent: str,
    confidence: float,
    provider: str,
) -> None:
    """Inserta un mensaje asociado a una conversación."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO app.messages (
                conversation_id, tg_user_id, role, text, normalized_text,
                intent, confidence, provider
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                conversation_id,
                tg_user_id,
                role,
                text,
                normalized_text,
                intent,
                confidence,
                provider,
            ),
        )
        conn.commit()
    logger.info(
        "mensaje guardado",
        extra={
            "conversation_id": conversation_id,
            "tg_user_id": tg_user_id,
            "intent": intent,
            "confidence": confidence,
        },
    )


