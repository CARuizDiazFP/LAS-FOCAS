# Nombre de archivo: conversations.py
# Ubicación de archivo: core/repositories/conversations.py
# Descripción: Funciones para gestionar la tabla de conversaciones

from __future__ import annotations

import logging

import psycopg

logger = logging.getLogger(__name__)


def insert_conversation(conn: psycopg.Connection, tg_user_id: int) -> int:
    """Inserta una nueva conversación y devuelve su ID."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO app.conversations (tg_user_id) "
            "VALUES (%s) RETURNING id",
            (tg_user_id,),
        )
        new_id = cur.fetchone()[0]
        conn.commit()
    logger.info(
        "conversación creada",
        extra={"tg_user_id": tg_user_id, "conversation_id": new_id},
    )
    return new_id
