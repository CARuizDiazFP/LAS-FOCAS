# Nombre de archivo: 20260428_02_camara_alias_pendiente.py
# Ubicación de archivo: db/alembic/versions/20260428_02_camara_alias_pendiente.py
# Descripción: Agrega tabla app.camara_alias y el valor PENDIENTE_REVISION al enum camara_estado

"""Agregar camara_alias y estado PENDIENTE_REVISION

Revision ID: 20260428_02
Revises: 20260428_01
Create Date: 2026-04-27

Cambios:
- Nuevo valor en enum ``app.camara_estado``: PENDIENTE_REVISION
  (cámaras auto-registradas por el listener de ingresos Slack que requieren
  revisión y aprobación de un administrador).
- Nueva tabla ``app.camara_alias``: permite registrar nombres alternativos
  (alias) para una cámara, de modo que búsquedas con nomenclatura distinta
  igualmente encuentren la cámara correcta.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260428_02"
down_revision = "20260428_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Agregar valor al enum (PostgreSQL requiere ALTER TYPE) ────────
    # IF NOT EXISTS previene error si se corre dos veces
    op.execute(
        "ALTER TYPE app.camara_estado ADD VALUE IF NOT EXISTS 'PENDIENTE_REVISION'"
    )

    # ── 2. Crear tabla app.camara_alias ──────────────────────────────────
    op.create_table(
        "camara_alias",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "camara_id",
            sa.Integer(),
            sa.ForeignKey("app.camaras.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "alias_nombre",
            sa.String(255),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        schema="app",
    )
    op.create_index(
        "ix_camara_alias_camara_id",
        "camara_alias",
        ["camara_id"],
        schema="app",
    )
    op.create_index(
        "ix_camara_alias_alias_nombre",
        "camara_alias",
        ["alias_nombre"],
        schema="app",
    )


def downgrade() -> None:
    # Eliminar tabla (el ADD VALUE al enum no es reversible en PostgreSQL)
    op.drop_index("ix_camara_alias_alias_nombre", table_name="camara_alias", schema="app")
    op.drop_index("ix_camara_alias_camara_id", table_name="camara_alias", schema="app")
    op.drop_table("camara_alias", schema="app")
    # NOTA: no se puede revertir ADD VALUE en PostgreSQL 11+
    # Para downgrade completo del enum se requeriría recrear el tipo,
    # lo cual es destructivo. La tabla se elimina pero el valor queda.
