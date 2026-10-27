# Nombre de archivo: 20261027_01_camaras_fontine_id_indice_duplicado.py
# Ubicación de archivo: db/alembic/versions/20261027_01_camaras_fontine_id_indice_duplicado.py
# Descripción: Borra app.ix_camaras_fontine_id, índice UNIQUE duplicado exacto de la constraint camaras_fontine_id_key

"""Índice duplicado sobre ``app.camaras.fontine_id``

``20251230_01_infra`` creó la columna con ``unique=True`` (constraint ``camaras_fontine_id_key``,
con su índice UNIQUE implícito) y además ``op.create_index("ix_camaras_fontine_id", ...,
unique=True)``: dos índices UNIQUE idénticos sobre la misma columna (544 kB entre los dos en dev
al 2026-10-27). La unicidad la sigue garantizando ``camaras_fontine_id_key``; el modelo
(`db/models/infra.py`) la declara como ``UniqueConstraint`` y ya no declara el índice.

Hallazgo del chequeo de drift modelo↔base (P18, `scripts/check_drift_modelos.py`).

``IF EXISTS`` / ``IF NOT EXISTS`` porque el esquema de prod puede diferir del de dev. El downgrade
recrea el índice tal como estaba; no puede fallar por duplicados porque la constraint los impide.

Revision ID: 20261027_01
Revises: 20261023_01
Create Date: 2026-10-27
"""

from __future__ import annotations

from alembic import op

revision = "20261027_01"
down_revision = "20261023_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS app.ix_camaras_fontine_id")


def downgrade() -> None:
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_camaras_fontine_id ON app.camaras USING btree (fontine_id)")
