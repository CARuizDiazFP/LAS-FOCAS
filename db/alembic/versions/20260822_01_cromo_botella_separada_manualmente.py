# Nombre de archivo: 20260822_01_cromo_botella_separada_manualmente.py
# Ubicación de archivo: db/alembic/versions/20260822_01_cromo_botella_separada_manualmente.py
# Descripción: Columnas de auditoría para la separación manual de una Botella Cromo de su Cámara padre

"""Auditoría de separación manual de Botella Cromo

Revision ID: 20260822_01
Revises: 20260821_01
Create Date: 2026-08-22

Cambios:
- Nuevas columnas en ``app.cromo_botellas``: ``separada_manualmente BOOLEAN NOT NULL DEFAULT
  false``, ``separada_motivo TEXT NULL``, ``separada_por VARCHAR(128) NULL``,
  ``separada_at TIMESTAMPTZ NULL``. Se ponen desde
  ``POST /api/infra/botellas/{n_id}/separar-padre`` (admin) al separar una Botella agrupada
  erróneamente por nombre bajo una Cámara padre compartida — ver
  ``core/services/cromo/separacion_service.py``.
- ``scripts/cromo_backfill_camara_padre.py`` excluye estas filas de su filtro de idempotencia
  (``AND NOT separada_manualmente``, además de ``camara_id IS NULL``) — blindaje explícito para
  que un futuro cambio del script no las vuelva a agrupar.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260822_01"
down_revision = "20260821_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cromo_botellas",
        sa.Column("separada_manualmente", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="app",
    )
    op.add_column("cromo_botellas", sa.Column("separada_motivo", sa.Text(), nullable=True), schema="app")
    op.add_column(
        "cromo_botellas", sa.Column("separada_por", sa.String(length=128), nullable=True), schema="app"
    )
    op.add_column(
        "cromo_botellas", sa.Column("separada_at", sa.DateTime(timezone=True), nullable=True), schema="app"
    )


def downgrade() -> None:
    op.drop_column("cromo_botellas", "separada_at", schema="app")
    op.drop_column("cromo_botellas", "separada_por", schema="app")
    op.drop_column("cromo_botellas", "separada_motivo", schema="app")
    op.drop_column("cromo_botellas", "separada_manualmente", schema="app")
