# Nombre de archivo: 20260929_02_cromo_tracking_cache_pelos_camino.py
# Ubicación de archivo: db/alembic/versions/20260929_02_cromo_tracking_cache_pelos_camino.py
# Descripción: Columna pelos_camino en app.cromo_tracking_cache — los pelos que recorre cada
# tracking, para entregar un .txt por camino distinto y no uno por posición de ODF.

"""cromo_tracking_cache.pelos_camino

Revision ID: 20260929_02
Revises: 20260929_01
Create Date: 2026-09-29

Cambios:
- Nueva columna ``pelos_camino BIGINT[] NULL``. Un Servicio tiene posición de ODF en varias ODF
  del recorrido (extremos e intermedias), y cada posición es una semilla de ``/path``; todas las
  del mismo hilo recorren el MISMO camino. Para entregar un ``.txt`` por camino hay que saber qué
  pelos recorre cada uno, también cuando el tracking sale del caché (si no, descartar repetidos
  obligaría a volver a pagar 4,6-14 s de Cromo por pelo).
- ``NULL`` = entrada anterior a este cambio: la capa de servicio la trata como inexistente y la
  regenera una vez. Sin backfill: el TTL es de 24 h.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260929_02"
down_revision = "20260929_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cromo_tracking_cache",
        sa.Column("pelos_camino", postgresql.ARRAY(sa.BigInteger()), nullable=True),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("cromo_tracking_cache", "pelos_camino", schema="app")
