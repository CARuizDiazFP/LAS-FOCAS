# Nombre de archivo: 20260823_01_ingreso_seguimiento_empalme.py
# Ubicación de archivo: db/alembic/versions/20260823_01_ingreso_seguimiento_empalme.py
# Descripción: Columnas de seguimiento por hilo en IngresoSinMatch + índice en CromoBotella.nombre

"""Seguimiento de empalme en ingresos sin match + índice CromoBotella.nombre

Revision ID: 20260823_01
Revises: 20260822_01
Create Date: 2026-08-23

Cambios (Tarea 2 del plan de refactor de ingreso de técnicos):

- Nuevas columnas en ``app.ingresos_sin_match``: ``thread_ts VARCHAR(32) NULL`` (ts del hilo de
  Slack donde se registró el caso) y ``resuelto_via_empalme BOOLEAN NOT NULL DEFAULT false``.
  Sostienen el mecanismo de "hilo esperando ID de empalme": cuando el listener de ingresos
  (`modules/slack_baneo_notifier/listener.py`) no encuentra una cámara por nombre, invita al
  técnico a responder en el mismo hilo con el ID de empalme más cercano; si el técnico lo hace, el
  listener resuelve la Botella dueña de esa fusión (`core/services/cromo/empalme_resolucion.py`) y
  marca `resuelto_via_empalme=True` para no reprocesar el mismo hilo dos veces.
- Nuevo índice ``ix_cromo_botellas_nombre_btree`` (btree simple) sobre ``app.cromo_botellas.nombre``
  — la cascada ILIKE/tokens de `core/services/cromo/camara_botella_busqueda.py` (Tarea 1 del mismo
  plan) hace table scan sobre esta tabla en cada búsqueda.
  **Nombre explícito, distinto al que generaría `index=True` por convención** (``ix_cromo_botellas_
  nombre``): verificado real contra ``lasfocasdev-postgres`` que ese nombre YA está tomado desde la
  Etapa 2 (`20260805_01_cromo_ingesta.py`) por un índice GIN sobre ``to_tsvector('spanish', nombre)``
  para full-text search (sin consumidores hoy en el repo, `grep to_tsvector` no encuentra ninguno,
  pero no se toca/renombra acá — fuera de alcance). `op.create_index()` con el nombre "natural"
  falla con `DuplicateTable` contra la DB real — confirmado al intentar aplicar esta migración antes
  de corregir el nombre. El docstring de `camara_botella_busqueda.py` ("CromoBotella.nombre no tiene
  índice") es impreciso a la luz de este hallazgo: sí tenía uno, sólo que de un tipo que la cascada
  ILIKE no puede aprovechar.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260823_01"
down_revision = "20260822_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingresos_sin_match",
        sa.Column("thread_ts", sa.String(length=32), nullable=True),
        schema="app",
    )
    op.add_column(
        "ingresos_sin_match",
        sa.Column("resuelto_via_empalme", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="app",
    )
    op.create_index(
        "ix_cromo_botellas_nombre_btree",
        "cromo_botellas",
        ["nombre"],
        schema="app",
    )


def downgrade() -> None:
    op.drop_index("ix_cromo_botellas_nombre_btree", table_name="cromo_botellas", schema="app")
    op.drop_column("ingresos_sin_match", "resuelto_via_empalme", schema="app")
    op.drop_column("ingresos_sin_match", "thread_ts", schema="app")
