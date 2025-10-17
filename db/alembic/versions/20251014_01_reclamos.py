"""
# Nombre de archivo: 20251014_01_reclamos.py
# Ubicación de archivo: db/alembic/versions/20251014_01_reclamos.py
# Descripción: Crea tabla app.reclamos con índices y PK única en numero_reclamo
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20251014_01"
down_revision = "20251013_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reclamos",
        sa.Column("numero_reclamo", sa.String(length=64), primary_key=True),
        sa.Column("numero_evento", sa.String(length=64), nullable=True),
        sa.Column("numero_linea", sa.String(length=64), nullable=False),
        sa.Column("tipo_servicio", sa.String(length=80), nullable=True),
        sa.Column("nombre_cliente", sa.String(length=128), nullable=False),
        sa.Column("tipo_solucion", sa.String(length=80), nullable=True),
        sa.Column("fecha_inicio", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fecha_cierre", sa.DateTime(timezone=True), nullable=True),
        sa.Column("horas_netas", sa.Numeric(10, 2), nullable=True),
        sa.Column("descripcion_solucion", sa.Text(), nullable=True),
        sa.Column("latitud", sa.Numeric(9, 6), nullable=True),
        sa.Column("longitud", sa.Numeric(9, 6), nullable=True),
        schema="app",
    )
    op.create_index("ix_reclamos_numero_evento", "reclamos", ["numero_evento"], schema="app")
    op.create_index("ix_reclamos_numero_linea", "reclamos", ["numero_linea"], schema="app")
    op.create_index("ix_reclamos_tipo_servicio", "reclamos", ["tipo_servicio"], schema="app")
    op.create_index("ix_reclamos_nombre_cliente", "reclamos", ["nombre_cliente"], schema="app")
    op.create_index("ix_reclamos_fecha_cierre", "reclamos", ["fecha_cierre"], schema="app")


def downgrade() -> None:
    op.drop_index("ix_reclamos_fecha_cierre", table_name="reclamos", schema="app")
    op.drop_index("ix_reclamos_nombre_cliente", table_name="reclamos", schema="app")
    op.drop_index("ix_reclamos_tipo_servicio", table_name="reclamos", schema="app")
    op.drop_index("ix_reclamos_numero_linea", table_name="reclamos", schema="app")
    op.drop_index("ix_reclamos_numero_evento", table_name="reclamos", schema="app")
    op.drop_table("reclamos", schema="app")
