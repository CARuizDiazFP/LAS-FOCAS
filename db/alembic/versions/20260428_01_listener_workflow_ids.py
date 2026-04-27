# Nombre de archivo: 20260428_01_listener_workflow_ids.py
# Ubicación de archivo: db/alembic/versions/20260428_01_listener_workflow_ids.py
# Descripción: Agrega workflow_ids y solo_workflows a config_servicios para el filtro de Workflow ID del listener

"""Agregar workflow_ids y solo_workflows a config_servicios

Revision ID: 20260428_01
Revises: 20260427_01
Create Date: 2026-04-28

Nuevas columnas en ``app.config_servicios`` para el listener de ingresos
técnicos (``slack_ingreso_listener``):

- ``workflow_ids``: lista de IDs de Workflow de Slack separados por coma
  (NULL = sin restricción).
- ``solo_workflows``: booleano; si True el listener solo procesa mensajes
  cuyo ``workflow_id`` esté en ``workflow_ids``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260428_01"
down_revision = "20260427_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "config_servicios",
        sa.Column(
            "workflow_ids",
            sa.String(512),
            nullable=True,
            comment="IDs de Workflow de Slack permitidos, separados por coma (NULL = sin filtro)",
        ),
        schema="app",
    )
    op.add_column(
        "config_servicios",
        sa.Column(
            "solo_workflows",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="Si True, solo procesa mensajes con workflow_id incluido en workflow_ids",
        ),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("config_servicios", "solo_workflows", schema="app")
    op.drop_column("config_servicios", "workflow_ids", schema="app")
