# Nombre de archivo: 20261017_02_cromo_inconsistencias.py
# Ubicación de archivo: db/alembic/versions/20261017_02_cromo_inconsistencias.py
# Descripción: Tablas app.cromo_inconsistencia (casos del detector de inconsistencias de Cromo) y
# app.cromo_inconsistencia_pelo (pelos en uso afectados por cada caso)

"""cromo_inconsistencia + cromo_inconsistencia_pelo

Revision ID: 20261017_02
Revises: 20261017_01
Create Date: 2026-10-17

Cambios:
- Nueva tabla ``app.cromo_inconsistencia``: un caso por objeto de Cromo inconsistente que detecta
  ``core/services/cromo/inconsistencias_cromo.py``. ``UNIQUE(tipo, objeto_n_id)``: re-detectar es
  idempotente (upsert).
  - ``tipo``: ``ISLA_FUSION`` | ``CABLE_SIN_EXTREMO`` | ``ELEMENTO_ISLA`` (Text + CHECK).
  - ``revision``: ``AUTO`` (isla pura confirmada en vivo) | ``MANUAL`` (todo lo demás).
  - ``estado``: ``PENDIENTE`` | ``CUARENTENA`` | ``REPORTADA`` | ``CORREGIDA`` | ``ACEPTADA``.
  - ``objeto_n_id`` es referencia blanda (n_id de linaje de Cromo: fusión, cable o elemento).
- Nueva tabla ``app.cromo_inconsistencia_pelo``: PK ``(inconsistencia_id, pelo_n_id)``, FK
  ``ON DELETE CASCADE`` al caso e índice por pelo (la vista de cuarentena busca por pelo).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261017_02"
down_revision = "20261017_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cromo_inconsistencia",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tipo", sa.Text(), nullable=False),
        sa.Column("objeto_n_id", sa.BigInteger(), nullable=False),
        sa.Column("objeto_clase", sa.SmallInteger(), nullable=True),
        sa.Column("nombre", sa.Text(), nullable=True),
        sa.Column("localidad", sa.Text(), nullable=True),
        sa.Column("revision", sa.Text(), nullable=False),
        sa.Column("estado", sa.Text(), nullable=False),
        sa.Column("evidencia", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "primera_vez",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "ultima_vez",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("actualizado_por", sa.String(length=128), nullable=True),
        sa.Column(
            "actualizado_en",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "tipo IN ('ISLA_FUSION', 'CABLE_SIN_EXTREMO', 'ELEMENTO_ISLA')",
            name="ck_cromo_inconsistencia_tipo_valido",
        ),
        sa.CheckConstraint(
            "revision IN ('AUTO', 'MANUAL')",
            name="ck_cromo_inconsistencia_revision_valida",
        ),
        sa.CheckConstraint(
            "estado IN ('PENDIENTE', 'CUARENTENA', 'REPORTADA', 'CORREGIDA', 'ACEPTADA')",
            name="ck_cromo_inconsistencia_estado_valido",
        ),
        sa.UniqueConstraint("tipo", "objeto_n_id", name="uq_cromo_inconsistencia_tipo_objeto"),
        schema="app",
    )
    op.create_index(
        "ix_cromo_inconsistencia_estado_tipo",
        "cromo_inconsistencia",
        ["estado", "tipo"],
        schema="app",
    )
    op.create_table(
        "cromo_inconsistencia_pelo",
        sa.Column(
            "inconsistencia_id",
            sa.BigInteger(),
            sa.ForeignKey("app.cromo_inconsistencia.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pelo_n_id", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint(
            "inconsistencia_id", "pelo_n_id", name="pk_cromo_inconsistencia_pelo"
        ),
        schema="app",
    )
    op.create_index(
        "ix_cromo_inconsistencia_pelo_pelo",
        "cromo_inconsistencia_pelo",
        ["pelo_n_id"],
        schema="app",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_cromo_inconsistencia_pelo_pelo",
        table_name="cromo_inconsistencia_pelo",
        schema="app",
    )
    op.drop_table("cromo_inconsistencia_pelo", schema="app")
    op.drop_index(
        "ix_cromo_inconsistencia_estado_tipo",
        table_name="cromo_inconsistencia",
        schema="app",
    )
    op.drop_table("cromo_inconsistencia", schema="app")
