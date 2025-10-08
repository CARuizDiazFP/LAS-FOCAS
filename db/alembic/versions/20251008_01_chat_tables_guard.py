# Nombre de archivo: 20251008_01_chat_tables_guard.py
# Ubicación de archivo: db/alembic/versions/20251008_01_chat_tables_guard.py
# Descripción: Refuerzo de tablas e índices para chat_sessions y chat_messages

"""Garantizar tablas e índices de chat para entornos desfasados."""

from __future__ import annotations

from alembic import op

revision = "20251008_01"
down_revision = "20251007_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
        CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_sessions_user_active
        ON app.chat_sessions (user_id)
        WHERE is_active IS TRUE
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_chat_sessions_last_activity
        ON app.chat_sessions (last_activity DESC)
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
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_chat_messages_role_created
        ON app.chat_messages (role, created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS app.ix_chat_messages_role_created")
    op.execute("DROP INDEX IF EXISTS app.ix_chat_sessions_last_activity")
    op.execute("DROP INDEX IF EXISTS app.uq_chat_sessions_user_active")
