# Nombre de archivo: 20260625_01_report_history.py
# Ubicación de archivo: db/alembic/versions/20260625_01_report_history.py
# Descripción: Crea tabla app.report_history para histórico persistente de informes web

"""Crear historico persistente de reportes web."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260625_01"
down_revision = "20260428_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("period_month", sa.Integer(), nullable=False),
        sa.Column("period_year", sa.Integer(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "input_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "output_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        schema="app",
    )
    op.create_index(
        "ix_report_history_started_at",
        "report_history",
        ["started_at"],
        schema="app",
    )
    op.create_index(
        "ix_report_history_report_type",
        "report_history",
        ["report_type"],
        schema="app",
    )
    op.create_index(
        "ix_report_history_status",
        "report_history",
        ["status"],
        schema="app",
    )
    op.create_index(
        "ix_report_history_username",
        "report_history",
        ["username"],
        schema="app",
    )
    op.create_index(
        "ix_report_history_period",
        "report_history",
        ["period_year", "period_month"],
        schema="app",
    )


def downgrade() -> None:
    op.drop_index("ix_report_history_period", table_name="report_history", schema="app")
    op.drop_index("ix_report_history_username", table_name="report_history", schema="app")
    op.drop_index("ix_report_history_status", table_name="report_history", schema="app")
    op.drop_index("ix_report_history_report_type", table_name="report_history", schema="app")
    op.drop_index("ix_report_history_started_at", table_name="report_history", schema="app")
    op.drop_table("report_history", schema="app")
