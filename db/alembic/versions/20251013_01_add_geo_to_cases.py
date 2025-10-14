"""
# Nombre de archivo: 20251013_01_add_geo_to_cases.py
# Ubicación de archivo: db/alembic/versions/20251013_01_add_geo_to_cases.py
# Descripción: Migración para agregar columnas latitude/longitude a app.cases (si existe)
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20251013_01"
down_revision = "20251008_01"
branch_labels = None
depends_on = None


def _table_exists(schema: str, table: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table in inspector.get_table_names(schema=schema)


def upgrade() -> None:
    if not _table_exists("app", "cases"):
        # En algunos despliegues puede no existir aún; la creación ocurrirá en otra revisión
        return
    with op.batch_alter_table("cases", schema="app") as batch_op:
        try:
            batch_op.add_column(sa.Column("latitude", sa.Float(), nullable=True))
        except Exception:
            pass
        try:
            batch_op.add_column(sa.Column("longitude", sa.Float(), nullable=True))
        except Exception:
            pass


def downgrade() -> None:
    if not _table_exists("app", "cases"):
        return
    with op.batch_alter_table("cases", schema="app") as batch_op:
        try:
            batch_op.drop_column("longitude")
        except Exception:
            pass
        try:
            batch_op.drop_column("latitude")
        except Exception:
            pass
