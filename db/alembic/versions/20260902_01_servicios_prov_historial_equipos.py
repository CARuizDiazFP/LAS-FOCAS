# Nombre de archivo: 20260902_01_servicios_prov_historial_equipos.py
# Ubicación de archivo: db/alembic/versions/20260902_01_servicios_prov_historial_equipos.py
# Descripción: Nuevo valor INGEST_PROV en app.servicio_origen_datos + tablas servicios_historial_id y servicios_equipos_ultima_milla para la integración con la API PROV

"""INGEST_PROV + servicios_historial_id + servicios_equipos_ultima_milla

Revision ID: 20260902_01
Revises: 20260831_02
Create Date: 2026-09-02

Cambios:
- Nuevo valor en enum app.servicio_origen_datos: INGEST_PROV. El enum ya existe (creado en
  20260814_02) — este es un ALTER TYPE ... ADD VALUE, no una creación. No se usa dentro de esta
  misma migración, así que en rigor no hace falta autocommit_block (mismo caso ya documentado en
  20260810_01_camara_padre_botella.py para INFERIDO) — se envuelve igual por consistencia con el
  resto del repo.
- Tabla nueva app.servicios_historial_id: un eslabón por elemento de `cadena_upgrade` de PROV (o
  una fila sintética si PROV no trae el array).
- Tabla nueva app.servicios_equipos_ultima_milla: un equipo/puerto por extremo de última milla
  (1 o 2 según el payload de PROV).

Downgrade: elimina ambas tablas. INGEST_PROV no se puede quitar del enum en PostgreSQL 11+ (mismo
caso ya documentado en 20260811_01_cromo_botella_camara_padre.py).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260902_01"
down_revision = "20260831_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE app.servicio_origen_datos ADD VALUE IF NOT EXISTS 'INGEST_PROV'")

    op.create_table(
        "servicios_historial_id",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "servicio_id",
            sa.Integer(),
            sa.ForeignKey("app.servicios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("numero_id", sa.String(64), nullable=False),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("fecha_instalacion", sa.Date(), nullable=True),
        sa.Column("fecha_baja", sa.Date(), nullable=True),
        sa.Column("estado_comercial", sa.String(128), nullable=True),
        sa.Column("motivo_baja", sa.String(255), nullable=True),
        sa.Column("es_vigente", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="app",
    )
    op.create_index(
        "ix_servicios_historial_id_servicio_id",
        "servicios_historial_id",
        ["servicio_id"],
        schema="app",
    )

    op.create_table(
        "servicios_equipos_ultima_milla",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "servicio_id",
            sa.Integer(),
            sa.ForeignKey("app.servicios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("extremo", sa.Integer(), nullable=False),
        sa.Column("nodo", sa.String(255), nullable=True),
        sa.Column("equipo", sa.String(255), nullable=True),
        sa.Column("puerto", sa.String(128), nullable=True),
        sa.Column("direccion", sa.String(255), nullable=True),
        sa.Column("provincia", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="app",
    )
    op.create_index(
        "ix_servicios_equipos_ultima_milla_servicio_id",
        "servicios_equipos_ultima_milla",
        ["servicio_id"],
        schema="app",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_servicios_equipos_ultima_milla_servicio_id", table_name="servicios_equipos_ultima_milla", schema="app"
    )
    op.drop_table("servicios_equipos_ultima_milla", schema="app")
    op.drop_index("ix_servicios_historial_id_servicio_id", table_name="servicios_historial_id", schema="app")
    op.drop_table("servicios_historial_id", schema="app")
    # NOTA: no se puede revertir ADD VALUE en PostgreSQL 11+ — INGEST_PROV queda en el enum tras
    # el downgrade, mismo caso ya documentado en 20260811_01_cromo_botella_camara_padre.py.
