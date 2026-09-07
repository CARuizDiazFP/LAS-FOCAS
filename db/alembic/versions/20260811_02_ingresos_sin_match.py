# Nombre de archivo: 20260811_02_ingresos_sin_match.py
# Ubicación de archivo: db/alembic/versions/20260811_02_ingresos_sin_match.py
# Descripción: Tabla app.ingresos_sin_match — reemplaza el auto-registro de Cámara PENDIENTE_REVISION en ingresos de técnicos sin match

"""Ingresos sin match (reemplaza auto-alta PENDIENTE_REVISION)

Revision ID: 20260811_02
Revises: 20260811_01
Create Date: 2026-08-11

Cambios:
- Nueva tabla ``app.ingresos_sin_match``: registra un caso de ingreso de técnico (bot de Slack) o
  ubicación de tracking cuya cámara no matcheó contra el inventario, sin crear ninguna `Camara`
  nueva — reemplaza el auto-registro `PENDIENTE_REVISION` (decisión del usuario: Cromo es la fuente
  de verdad, un caso sin match es un problema de escritura/regex, no una cámara faltante de alta).
  Es sólo información para revisión manual y mejora del regex — el ingreso del técnico nunca se
  bloquea por esto.

No toca `app.camaras` ni ningún enum existente. El flujo `PENDIENTE_REVISION` (endpoints
`/api/admin/infra/camaras/pendientes/*`) sigue intacto para las 34 filas legado ya existentes al
2026-08-11 — sólo deja de recibir filas nuevas (ver `modules/slack_baneo_notifier/listener.py` y
`web/app/main.py::upload_tracking_web`).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260811_02"
down_revision = "20260811_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingresos_sin_match",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("texto_original", sa.String(length=512), nullable=False),
        sa.Column("origen", sa.String(length=32), nullable=False),
        sa.Column("contexto", sa.Text(), nullable=True),
        sa.Column("revisado", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        schema="app",
    )
    op.create_index(
        "ix_ingresos_sin_match_created_at",
        "ingresos_sin_match",
        ["created_at"],
        schema="app",
    )


def downgrade() -> None:
    op.drop_index("ix_ingresos_sin_match_created_at", table_name="ingresos_sin_match", schema="app")
    op.drop_table("ingresos_sin_match", schema="app")
