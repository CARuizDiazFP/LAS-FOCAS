# Nombre de archivo: 20260810_01_camara_padre_botella.py
# Ubicación de archivo: db/alembic/versions/20260810_01_camara_padre_botella.py
# Descripción: Jerarquía Cámara→Botella — FK auto-referencial camaras.camara_padre_id + valor INFERIDO en camara_origen_datos

"""Jerarquía Cámara -> Botella

Revision ID: 20260810_01
Revises: 20260807_01
Create Date: 2026-08-10

Cambios:
- Nueva columna ``app.camaras.camara_padre_id``: FK auto-referencial nullable a
  ``app.camaras.id`` (``ondelete=SET NULL``). Una fila con ``camara_padre_id IS NULL``
  es una Cámara (nodo físico); una fila con ``camara_padre_id`` seteado es una
  Botella (caja de empalme) dentro de esa cámara. Jerarquía de exactamente 2
  niveles — nunca cadenas (resuelto en la capa de aplicación, no en la DB).
- CHECK constraint ``ck_camaras_no_self_padre``: evita que una fila se
  referencie a sí misma como padre.
- Nuevo valor en enum ``app.camara_origen_datos``: INFERIDO (cámaras padre
  sintetizadas por el backfill de jerarquía, sin origen de datos externo real
  — se distinguen así de MANUAL/TRACKING/SHEET en exports/auditoría).

Nota de dominio: "Botella" acá es un concepto de `app.camaras` (jerarquía
Cámara/Botella de este módulo de Infraestructura), NO relacionado con
`app.cromo_botellas` (módulo de ingesta Cromo Red, esquema separado, sin FK
entre ambos). Son dos entidades homónimas de dominios distintos.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260810_01"
down_revision = "20260807_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE app.camara_origen_datos ADD VALUE IF NOT EXISTS 'INFERIDO'"
    )

    op.add_column(
        "camaras",
        sa.Column(
            "camara_padre_id",
            sa.Integer(),
            sa.ForeignKey("app.camaras.id", ondelete="SET NULL"),
            nullable=True,
        ),
        schema="app",
    )
    op.create_index(
        "ix_camaras_camara_padre_id",
        "camaras",
        ["camara_padre_id"],
        schema="app",
    )
    op.create_check_constraint(
        "ck_camaras_no_self_padre",
        "camaras",
        "camara_padre_id IS NULL OR camara_padre_id != id",
        schema="app",
    )


def downgrade() -> None:
    op.drop_constraint("ck_camaras_no_self_padre", "camaras", schema="app", type_="check")
    op.drop_index("ix_camaras_camara_padre_id", table_name="camaras", schema="app")
    op.drop_column("camaras", "camara_padre_id", schema="app")
    # NOTA: no se puede revertir ADD VALUE en PostgreSQL 11+ — el valor INFERIDO
    # queda en el enum tras el downgrade, igual que PENDIENTE_REVISION en
    # 20260428_02_camara_alias_pendiente.py.
