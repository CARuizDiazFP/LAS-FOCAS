# Nombre de archivo: 20260919_04_cromo_cables_clase.py
# Ubicación de archivo: db/alembic/versions/20260919_04_cromo_cables_clase.py
# Descripción: Agrega clase a app.cromo_cables para poder alojar cables de bajada (66) junto a los
# de FO (51) sin que se confundan

"""Clase del cable en cromo_cables

Revision ID: 20260919_04
Revises: 20260919_03
Create Date: 2026-09-19

``app.cromo_cables`` nunca tuvo columna de clase: era implícitamente la 51. Con el modo
``SOLO_CABLES_BAJADA`` entran además 19.030 cables de la clase 66, que comparten esquema y parser
—medido: publican exactamente los mismos ``at``— pero **no** son lo mismo.

Sin esta columna sólo se distinguirían por ``jerarquia``, que es texto libre que llega de Cromo, y
de eso depende un guardrail que no puede apoyarse en una heurística: la fase de reconciliación
marca como "referencia colgada" todo cable cuyo extremo no sea una botella, y **los extremos de un
cable de bajada son una caja PON y una roseta, nunca una botella**. Sin el filtro por clase, cada
corrida completa reportaría ~38.000 referencias colgadas inventadas.

Las 32.790 filas existentes se backfillean a 51 por el ``server_default``. Postgres no reescribe la
tabla para un ``ADD COLUMN`` con default constante, así que es barato aun con la tabla poblada.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260919_04"
down_revision = "20260919_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cromo_cables",
        sa.Column(
            "clase",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("51"),
        ),
        schema="app",
    )
    op.create_foreign_key(
        "cromo_cables_clase_fkey",
        "cromo_cables",
        "cromo_clases",
        ["clase"],
        ["clase"],
        source_schema="app",
        referent_schema="app",
    )
    op.create_index("ix_cromo_cables_clase", "cromo_cables", ["clase"], schema="app")


def downgrade() -> None:
    op.drop_index("ix_cromo_cables_clase", table_name="cromo_cables", schema="app")
    op.drop_constraint("cromo_cables_clase_fkey", "cromo_cables", schema="app", type_="foreignkey")
    op.drop_column("cromo_cables", "clase", schema="app")
