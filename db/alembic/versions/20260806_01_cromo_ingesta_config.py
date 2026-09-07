# Nombre de archivo: 20260806_01_cromo_ingesta_config.py
# Ubicación de archivo: db/alembic/versions/20260806_01_cromo_ingesta_config.py
# Descripción: Crea app.cromo_ingesta_config — configuración persistente del scheduler de ingesta automática (Etapa 7)

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260806_01"
down_revision = "20260805_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cromo_ingesta_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("habilitado", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("intervalo_horas", sa.Integer(), nullable=False, server_default=sa.text("24")),
        sa.Column("hora_inicio", sa.SmallInteger(), nullable=True),
        sa.Column("psize", sa.Integer(), nullable=False, server_default=sa.text("5")),
        sa.Column("max_paginas", sa.Integer(), nullable=True),
        sa.Column("clases", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ultima_ejecucion", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ultimo_error", sa.Text(), nullable=True),
        schema="app",
    )

    # Fila única sembrada: el worker nunca arranca sin config (evita el caso "no encontrada, uso defaults").
    op.execute(
        "INSERT INTO app.cromo_ingesta_config (habilitado, intervalo_horas, psize, clases) "
        "VALUES (false, 24, 5, '[68,121,122,123,125]'::jsonb)"
    )


def downgrade() -> None:
    op.drop_table("cromo_ingesta_config", schema="app")
