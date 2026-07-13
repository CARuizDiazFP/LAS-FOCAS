# Nombre de archivo: 20260713_01_servicios_sla_fase1.py
# Ubicación de archivo: db/alembic/versions/20260713_01_servicios_sla_fase1.py
# Descripción: Extiende app.servicios con campos SLA para ingesta y búsqueda paginada

"""Extender servicios para fase 1 de modulo SLA."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260713_01"
down_revision = "20260625_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("servicios", sa.Column("numero_primer_servicio", sa.String(length=64), nullable=True), schema="app")
    op.add_column("servicios", sa.Column("nombre_cliente", sa.String(length=255), nullable=True), schema="app")
    op.add_column("servicios", sa.Column("numero_linea", sa.String(length=128), nullable=True), schema="app")
    op.add_column("servicios", sa.Column("tipo_servicio", sa.String(length=128), nullable=True), schema="app")
    op.add_column("servicios", sa.Column("sla_prometido", sa.String(length=128), nullable=True), schema="app")
    op.add_column("servicios", sa.Column("direccion", sa.String(length=255), nullable=True), schema="app")
    op.add_column("servicios", sa.Column("localidad", sa.String(length=128), nullable=True), schema="app")
    op.add_column("servicios", sa.Column("provincia", sa.String(length=128), nullable=True), schema="app")
    op.add_column("servicios", sa.Column("direccion_2", sa.String(length=255), nullable=True), schema="app")
    op.add_column(
        "servicios",
        sa.Column(
            "estado_servicio",
            sa.String(length=128),
            nullable=False,
            server_default=sa.text("'DESCONOCIDO'"),
        ),
        schema="app",
    )

    op.create_index("ix_servicios_numero_primer_servicio", "servicios", ["numero_primer_servicio"], unique=True, schema="app")
    op.create_index("ix_servicios_numero_linea", "servicios", ["numero_linea"], unique=False, schema="app")
    op.create_index("ix_servicios_tipo_servicio", "servicios", ["tipo_servicio"], unique=False, schema="app")
    op.create_index("ix_servicios_estado_servicio", "servicios", ["estado_servicio"], unique=False, schema="app")

    op.execute(
        """
        UPDATE app.servicios
        SET numero_primer_servicio = servicio_id
        WHERE numero_primer_servicio IS NULL
          AND servicio_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_servicios_estado_servicio", table_name="servicios", schema="app")
    op.drop_index("ix_servicios_tipo_servicio", table_name="servicios", schema="app")
    op.drop_index("ix_servicios_numero_linea", table_name="servicios", schema="app")
    op.drop_index("ix_servicios_numero_primer_servicio", table_name="servicios", schema="app")

    op.drop_column("servicios", "estado_servicio", schema="app")
    op.drop_column("servicios", "direccion_2", schema="app")
    op.drop_column("servicios", "provincia", schema="app")
    op.drop_column("servicios", "localidad", schema="app")
    op.drop_column("servicios", "direccion", schema="app")
    op.drop_column("servicios", "sla_prometido", schema="app")
    op.drop_column("servicios", "tipo_servicio", schema="app")
    op.drop_column("servicios", "numero_linea", schema="app")
    op.drop_column("servicios", "nombre_cliente", schema="app")
    op.drop_column("servicios", "numero_primer_servicio", schema="app")
