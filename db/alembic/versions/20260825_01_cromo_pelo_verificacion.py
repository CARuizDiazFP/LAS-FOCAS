# Nombre de archivo: 20260825_01_cromo_pelo_verificacion.py
# Ubicación de archivo: db/alembic/versions/20260825_01_cromo_pelo_verificacion.py
# Descripción: Campos de verificación manual (verificable/status/fecha_hora_status) en cromo_pelos

"""Verificación manual de pelos Cromo

Revision ID: 20260825_01
Revises: 20260823_01
Create Date: 2026-08-25

Cambios:
- Nuevas columnas en ``app.cromo_pelos``: ``verificable`` (``BOOLEAN``, nullable),
  ``status`` (``TEXT``, nullable), ``fecha_hora_status`` (``TIMESTAMPTZ``, nullable).
  Las 3 nacen ``NULL`` en todas las filas existentes (metadata-only en PG11+, no
  reescribe la tabla).

Deliberadamente NO se agregan a ``PELO_CAMPOS``
(``core/services/cromo/ingesta.py``): estos 3 campos no vienen del payload de
Cromo (no hay ``at.NN`` que los origine) — si se agregaran a esa tupla, la
próxima re-ingesta los pisaría a ``NULL`` en cada corrida, igual que pasaba con
``camara_id``/``estado``/``nombre`` de ``cromo_botellas`` antes de excluirlos
(ver ``20260811_01_cromo_botella_camara_padre.py``,
``20260821_01_cromo_botella_nombre_editado_manual.py``).

No existe todavía ningún proceso (admin, worker, integración externa) que
calcule estos 3 valores — este ticket sólo agrega el esquema y el plumbing de
lectura/escritura pasiva (endpoint + frontend + Slack). Poblarlos queda
declarado como deuda técnica a futuro (ver docs/decisiones.md, entrada
2026-08-25).

Motivación: ampliación de la tabla de detalle de cables (Inventario Cromo) con
datos de verificación de campo, más fix del bot de Slack `slack_baneo_notifier`.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260825_01"
down_revision = "20260823_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cromo_pelos", sa.Column("verificable", sa.Boolean(), nullable=True), schema="app")
    op.add_column("cromo_pelos", sa.Column("status", sa.Text(), nullable=True), schema="app")
    op.add_column(
        "cromo_pelos",
        sa.Column("fecha_hora_status", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("cromo_pelos", "fecha_hora_status", schema="app")
    op.drop_column("cromo_pelos", "status", schema="app")
    op.drop_column("cromo_pelos", "verificable", schema="app")
