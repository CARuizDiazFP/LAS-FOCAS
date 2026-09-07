# Nombre de archivo: 20260831_02_ingreso_cromo_botella.py
# Ubicación de archivo: db/alembic/versions/20260831_02_ingreso_cromo_botella.py
# Descripción: Agregar FK de Cromo Botella a Ingreso para registrar qué botella específica se intervino

"""Ingreso + columna cromo_botella_id

Revision ID: 20260831_02
Revises: 20260831_01
Create Date: 2026-08-31

Cambios:
- Nueva columna ``app.ingresos.cromo_botella_id``: FK nullable a
  ``app.cromo_botellas.n_id`` (``ondelete=SET NULL``). Permite registrar qué
  botella específica de Cromo fue intervenida en un ingreso de técnico a una
  cámara. ``app.ingresos.camara_id`` sigue siendo NOT NULL siempre (cámara
  padre resuelta); esta columna nueva es sólo para saber, dentro de esa cámara,
  qué botella específica se intervino.
- Índice explícito ``ix_ingresos_cromo_botella_id`` para acelerar queries por
  FK.

Nota técnica: ``cromo_botella_id`` es ``BigInteger`` porque ``CromoBotella.n_id``
(la PK real de ``app.cromo_botellas``, columna de db/models/cromo.py) es
``BigInteger``, no ``Integer`` — un FK con tipo distinto al de la PK referenciada
falla en Postgres.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260831_02"
down_revision = "20260831_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingresos",
        sa.Column(
            "cromo_botella_id",
            sa.BigInteger(),
            sa.ForeignKey("app.cromo_botellas.n_id", ondelete="SET NULL"),
            nullable=True,
        ),
        schema="app",
    )
    op.create_index(
        "ix_ingresos_cromo_botella_id",
        "ingresos",
        ["cromo_botella_id"],
        schema="app",
    )


def downgrade() -> None:
    op.drop_index("ix_ingresos_cromo_botella_id", table_name="ingresos", schema="app")
    op.drop_column("ingresos", "cromo_botella_id", schema="app")
