# Nombre de archivo: 20261016_02_cromo_tracking_cache_extremos.py
# Ubicación de archivo: db/alembic/versions/20261016_02_cromo_tracking_cache_extremos.py
# Descripción: Columna extremos en app.cromo_tracking_cache — los dos extremos de cada camino y su
# resumen (ODFs y cables), para clasificarlo como TRAMO o RESIDUAL sin volver a Cromo.

"""cromo_tracking_cache.extremos

Revision ID: 20261016_02
Revises: 20261016_01
Create Date: 2026-10-16

Cambios:
- Nueva columna ``extremos JSONB NULL``. El tracking por tramos ya no corta en los caminos
  esperados: pide un camino por cada semilla no cubierta y después clasifica cada uno como
  ``TRAMO`` o ``RESIDUAL`` mirando dónde termina (conector de ODF u ODF Nodo), qué ODFs toca y qué
  cables recorre. Esa información tiene que sobrevivir al caché: si no, clasificar obligaría a
  volver a pagar 4,6-14 s de Cromo por camino.
- ``NULL`` = entrada anterior a este cambio: la capa de servicio la trata como inexistente y la
  regenera una vez (mismo patrón que ``pelos_camino``, 20260929_02). Sin backfill: el TTL es de
  24 h.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261016_02"
down_revision = "20261016_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cromo_tracking_cache",
        sa.Column("extremos", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("cromo_tracking_cache", "extremos", schema="app")
