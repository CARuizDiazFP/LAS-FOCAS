# Nombre de archivo: 20251007_01_chat_tables.py
# Ubicación de archivo: db/alembic/versions/20251007_01_chat_tables.py
# Descripción: Migración inicial para tablas de chat del panel web

"""Crear tablas chat_sessions y chat_messages"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa  # noqa: F401
from sqlalchemy.dialects import postgresql  # noqa: F401


revision = "20251007_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotente: usar IF NOT EXISTS para evitar fallos si init.sql ya creó tablas
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.chat_sessions (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(255) NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            last_activity TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_chat_sessions_user_id_last_activity
        ON app.chat_sessions (user_id, last_activity)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.chat_messages (
            id SERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL REFERENCES app.chat_sessions(id) ON DELETE CASCADE,
            role VARCHAR(32) NOT NULL,
            content TEXT NOT NULL,
            tool_name VARCHAR(128),
            tool_args JSONB,
            attachments JSONB,
            error_code VARCHAR(64),
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_chat_messages_session_created
        ON app.chat_messages (session_id, created_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS app.ix_chat_messages_session_created")
    op.execute("DROP TABLE IF EXISTS app.chat_messages")
    op.execute("DROP INDEX IF EXISTS app.ix_chat_sessions_user_id_last_activity")
    op.execute("DROP TABLE IF EXISTS app.chat_sessions")
