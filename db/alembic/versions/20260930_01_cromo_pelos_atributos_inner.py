# Nombre de archivo: 20260930_01_cromo_pelos_atributos_inner.py
# Ubicación de archivo: db/alembic/versions/20260930_01_cromo_pelos_atributos_inner.py
# Descripción: Atributos at.62/at.63 del pelo (sólo vía /inner del cable) y config del barrido semanal
# SOLO_PELOS_INNER, sembrada deshabilitada.

"""cromo_pelos: servicio_atributo, estado_cromo, atributos_leidos_at + cromo_ingesta_config.modo

Revision ID: 20260930_01
Revises: 20260929_03
Create Date: 2026-09-30

Cambios:
- ``app.cromo_pelos``: ``servicio_atributo`` (at.62, id de servicio que Cromo asigna al pelo),
  ``estado_cromo`` (at.63: Utilizado/Libre/Dañado) y ``atributos_leidos_at`` (cuándo se leyeron por
  ``GET /db/objects/{cable}/inner``). ``NULL`` en ``atributos_leidos_at`` = nunca se preguntó: el
  barrido de botellas no trae esos atributos, así que tampoco los escribe (quedan fuera de
  ``PELO_CAMPOS``).
- ``app.cromo_ingesta_config.modo`` (default ``COMPLETA``, la fila existente) + fila ``id=2`` para
  el barrido semanal ``SOLO_PELOS_INNER`` (168 h), **deshabilitada**: el worker programa un job por
  fila pero sólo corre si ``habilitado``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260930_01"
down_revision = "20260929_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cromo_pelos", sa.Column("servicio_atributo", sa.Text(), nullable=True), schema="app")
    op.add_column("cromo_pelos", sa.Column("estado_cromo", sa.Text(), nullable=True), schema="app")
    op.add_column(
        "cromo_pelos", sa.Column("atributos_leidos_at", sa.DateTime(timezone=True), nullable=True), schema="app"
    )
    op.add_column(
        "cromo_ingesta_config",
        sa.Column("modo", sa.Text(), nullable=False, server_default=sa.text("'COMPLETA'")),
        schema="app",
    )
    op.execute(
        "INSERT INTO app.cromo_ingesta_config (id, habilitado, intervalo_horas, psize, clases, modo) "
        "VALUES (2, false, 168, 5, '[51]'::jsonb, 'SOLO_PELOS_INNER') ON CONFLICT (id) DO NOTHING"
    )
    # La fila 2 se inserta con id explícito: se alinea la secuencia para que un INSERT futuro sin id
    # no choque con ella.
    op.execute(
        "SELECT setval(pg_get_serial_sequence('app.cromo_ingesta_config', 'id'), "
        "(SELECT max(id) FROM app.cromo_ingesta_config))"
    )


def downgrade() -> None:
    op.execute("DELETE FROM app.cromo_ingesta_config WHERE modo = 'SOLO_PELOS_INNER'")
    op.drop_column("cromo_ingesta_config", "modo", schema="app")
    op.drop_column("cromo_pelos", "atributos_leidos_at", schema="app")
    op.drop_column("cromo_pelos", "estado_cromo", schema="app")
    op.drop_column("cromo_pelos", "servicio_atributo", schema="app")
