# Nombre de archivo: messages.py
# Ubicación de archivo: core/repositories/messages.py
# Descripción: Funciones para insertar mensajes en la base de datos

from __future__ import annotations

import logging

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


def get_last_messages(conn: psycopg.Connection, conversation_id: int, limit: int = 10) -> list[dict]:
    """Recupera los últimos mensajes de una conversación (orden cronológico)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT role, text, intent, confidence, provider, created_at
            FROM app.messages
            WHERE conversation_id=%s
            ORDER BY id DESC
            LIMIT %s
            """,
            (conversation_id, limit),
        )
        rows = cur.fetchall()
    result = [
        {
            "role": r[0],
            "text": r[1],
            "intent": r[2],
            "confidence": float(r[3]) if r[3] is not None else None,
            "provider": r[4],
            "created_at": r[5].isoformat() if r[5] else None,
        }
        for r in reversed(rows)
    ]
    return result
