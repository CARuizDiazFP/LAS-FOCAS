# Nombre de archivo: 20261102_01_reclamos_horas_netas_cierre.py
# Ubicación de archivo: db/alembic/versions/20261102_01_reclamos_horas_netas_cierre.py
# Descripción: Agrega app.reclamos.horas_netas_cierre (columna P del Excel), base única del cálculo de SLA

"""Columna ``app.reclamos.horas_netas_cierre`` (P25)

El SLA se calcula con "Horas Netas Cierre Problema Reclamo" (columna P del Excel de reclamos): con ella
la suma por servicio reproduce el "SLA Entregado" oficial en 7.228 de 7.228 servicios (medido el
2026-11-02). ``horas_netas`` (columna N) se conserva: la usa el informe de Repetitividad.

Sin migración de datos: las filas existentes quedan en NULL hasta completarlas desde el Excel
(``scripts/sla_completar_horas_cierre.py``, o re-subiendo el mismo par en "SLA consumido").

Revision ID: 20261102_01
Revises: 20261029_01
Create Date: 2026-11-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261102_01"
down_revision = "20261029_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reclamos", sa.Column("horas_netas_cierre", sa.Numeric(12, 4), nullable=True), schema="app")


def downgrade() -> None:
    op.drop_column("reclamos", "horas_netas_cierre", schema="app")
