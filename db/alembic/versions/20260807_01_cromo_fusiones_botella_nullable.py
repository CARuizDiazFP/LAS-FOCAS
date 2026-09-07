# Nombre de archivo: 20260807_01_cromo_fusiones_botella_nullable.py
# Ubicación de archivo: db/alembic/versions/20260807_01_cromo_fusiones_botella_nullable.py
# Descripción: cromo_fusiones.botella_n_id pasa a nullable — el fetch directo de clase 132 no trae "parent" (Etapa 8)

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260807_01"
down_revision = "20260806_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "cromo_fusiones",
        "botella_n_id",
        existing_type=sa.BigInteger(),
        nullable=True,
        schema="app",
    )


def downgrade() -> None:
    # Sólo revertible si no quedaron filas con botella_n_id NULL (las sembradas por fase_fusiones sí
    # lo tendrán) — a criterio de quien haga el downgrade, no se borran datos automáticamente acá.
    op.alter_column(
        "cromo_fusiones",
        "botella_n_id",
        existing_type=sa.BigInteger(),
        nullable=False,
        schema="app",
    )
