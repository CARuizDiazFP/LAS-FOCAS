# Nombre de archivo: 20251007_01_chat_tables.py
# Ubicación de archivo: db/alembic/versions/20251007_01_chat_tables.py
# Descripción: Migración inicial para tablas de chat del panel web

"""Crear tablas chat_sessions y chat_messages"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20251007_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("last_activity", sa.DateTime(timezone=False), server_default=sa.text("NOW()"), nullable=False),
        schema="app",
    )
    op.create_index(
        "ix_chat_sessions_user_id_last_activity",
        "chat_sessions",
        ["user_id", "last_activity"],
        schema="app",
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=True),
        sa.Column("tool_args", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("attachments", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["app.chat_sessions.id"], ondelete="CASCADE"),
        schema="app",
    )
    op.create_index(
        "ix_chat_messages_session_created",
        "chat_messages",
        ["session_id", "created_at"],
        schema="app",
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_session_created", table_name="chat_messages", schema="app")
    op.drop_table("chat_messages", schema="app")
    op.drop_index("ix_chat_sessions_user_id_last_activity", table_name="chat_sessions", schema="app")
    op.drop_table("chat_sessions", schema="app")
