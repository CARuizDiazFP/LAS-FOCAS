# Nombre de archivo: 20261005_01_cromo_servicio_pelo_excluido.py
# Ubicación de archivo: db/alembic/versions/20261005_01_cromo_servicio_pelo_excluido.py
# Descripción: Tabla app.cromo_servicio_pelo_excluido — pelos que Cromo sigue etiquetando con un
# Servicio pero que el operador sacó de él en local (huérfanos de un camino).

"""cromo_servicio_pelo_excluido

Revision ID: 20261005_01
Revises: 20260930_01
Create Date: 2026-10-05

Cambios:
- Nueva tabla ``app.cromo_servicio_pelo_excluido`` (``servicio_id`` → ``app.servicios`` con
  ``ON DELETE CASCADE``, ``pelo_n_id`` sin FK dura, ``motivo``, ``excluido_por``, ``created_at``),
  única por ``(servicio_id, pelo_n_id)``.
- Las semillas del camino óptico, los conteos y la cantidad de caminos esperados la filtran: un
  pelo excluido deja de ser del Servicio aunque Cromo conserve la etiqueta. Separada de
  ``cromo_servicio_match`` porque la ingesta reescribe esa tabla en cada corrida.
- Arranca vacía: no hay backfill.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261005_01"
down_revision = "20260930_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cromo_servicio_pelo_excluido",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "servicio_id",
            sa.Integer(),
            sa.ForeignKey("app.servicios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pelo_n_id", sa.BigInteger(), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column("excluido_por", sa.String(128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("servicio_id", "pelo_n_id", name="uq_cromo_servicio_pelo_excluido"),
        schema="app",
    )
    op.create_index(
        "ix_cromo_servicio_pelo_excluido_servicio_id",
        "cromo_servicio_pelo_excluido",
        ["servicio_id"],
        schema="app",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_cromo_servicio_pelo_excluido_servicio_id",
        table_name="cromo_servicio_pelo_excluido",
        schema="app",
    )
    op.drop_table("cromo_servicio_pelo_excluido", schema="app")
