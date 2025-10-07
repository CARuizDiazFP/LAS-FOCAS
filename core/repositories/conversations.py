# Nombre de archivo: conversations.py
# Ubicación de archivo: core/repositories/conversations.py
# Descripción: Funciones para gestionar la tabla de conversaciones

from __future__ import annotations

import logging
import hashlib
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


def get_or_create_conversation_for_web_user(conn: psycopg.Connection, username: str) -> int:
    """Obtiene (o crea) una conversación asociada a un usuario web.

    Reutiliza la columna tg_user_id usando un hash derivado del username para no cambiar el schema.
    """
    pseudo_id = int(hashlib.sha256(username.encode()).hexdigest()[:12], 16)  # 48 bits
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM app.conversations WHERE tg_user_id=%s ORDER BY id DESC LIMIT 1",
            (pseudo_id,),
        )
        row = cur.fetchone()
        if row:
            return row[0]
    return insert_conversation(conn, pseudo_id)
