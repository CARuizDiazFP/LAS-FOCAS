# Nombre de archivo: 20261017_01_cromo_odf_fusion_conector.py
# Ubicación de archivo: db/alembic/versions/20261017_01_cromo_odf_fusion_conector.py
# Descripción: Columna app.cromo_odf_conectores.fusion_odf_n_id (fusión de ODF clase 141 por la que
# el conector llega a su pelo o a otro conector).

"""cromo_odf_conectores.fusion_odf_n_id

Revision ID: 20261017_01
Revises: 20261016_04
Create Date: 2026-10-17

Cambios:
- Nueva columna ``cromo_odf_conectores.fusion_odf_n_id BIGINT NULL``: n_id de la fusión de ODF
  (clase 141 de Cromo) que une el conector con un pelo (130) o con otro conector (136). Referencia
  blanda, sin FK (las 141 no tienen tabla propia). ``NULL`` = el conector no pasa por una 141.
- Sin backfill: el ``payload_raw`` guardado está desactualizado; la columna (y el ``pelo_n_id``
  que sale de la 141) se completan con una corrida SOLO_ODF.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261017_01"
down_revision = "20261016_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cromo_odf_conectores",
        sa.Column("fusion_odf_n_id", sa.BigInteger(), nullable=True),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("cromo_odf_conectores", "fusion_odf_n_id", schema="app")
