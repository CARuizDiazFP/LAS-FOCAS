# Nombre de archivo: 20260821_01_cromo_botella_nombre_editado_manual.py
# Ubicación de archivo: db/alembic/versions/20260821_01_cromo_botella_nombre_editado_manual.py
# Descripción: Flag de protección de nombre editado a mano en Botellas Cromo — impide que una re-ingesta futura pise una corrección manual

"""Nombre editado manual en Botellas Cromo

Revision ID: 20260821_01
Revises: 20260819_01
Create Date: 2026-08-21

Cambios:
- Nueva columna ``app.cromo_botellas.nombre_editado_manual``: ``BOOLEAN NOT NULL
  DEFAULT false``, metadata-only en PG11+ (no reescribe las filas existentes).
  Cuando está en ``True``, ``core/services/cromo/ingesta.py``
  (``_procesar_botella_completa``) deja de pisar ``nombre`` en corridas
  futuras — mismo criterio de exclusión ya usado para ``camara_id``/``estado``
  (ver ``20260811_01_cromo_botella_camara_padre.py``), pero condicional en vez
  de estructural: acá "nombre" sí debe seguir viniendo de Cromo para el 100%
  de las botellas nunca editadas a mano (default ``false``).
- Se pone en ``True`` únicamente desde ``PATCH /api/infra/botellas/{n_id}/nombre``
  (admin, Verificador Cromo) — es la única vía de escritura de este flag.

Motivación: Verificador Cromo (Repoblar Cables + nombre editable), caso real
"ID dual" B2-FO-CAR (n_id=9057909/next_id=9057952) — ver docs/decisiones.md,
entrada 2026-08-21.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260821_01"
down_revision = "20260819_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cromo_botellas",
        sa.Column("nombre_editado_manual", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("cromo_botellas", "nombre_editado_manual", schema="app")
