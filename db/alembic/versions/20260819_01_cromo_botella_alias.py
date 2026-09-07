# Nombre de archivo: 20260819_01_cromo_botella_alias.py
# Ubicación de archivo: db/alembic/versions/20260819_01_cromo_botella_alias.py
# Descripción: Tabla de aliasing manual de botellas Cromo — permite marcar un n_id junk/duplicado
# como fusionado a un n_id "golden" o directamente ignorado, y que la ingesta lo honre.

"""Alias manual de Botellas Cromo (fusionar/ignorar)

Revision ID: 20260819_01
Revises: 20260814_02
Create Date: 2026-08-19

Cambios:
- Nueva tabla ``app.cromo_botella_alias``: cada fila decide, para un ``id_cromo_origen`` (n_id de
  Cromo, sin FK dura — mismo criterio que el resto de las referencias cruzadas Cromo, ver
  ``db/models/cromo.py``), si ese n_id es basura a ignorar (``accion='ignorar'``) o debe
  considerarse fusionado dentro de un registro "golden" (``accion='fusionar'``,
  ``id_cromo_destino`` obligatorio). La ingesta (``core/services/cromo/alias_service.py`` +
  ``core/services/cromo/ingesta.py``) la usa para no crear la fila junk y para reescribir
  cualquier referencia blanda (extremo de cable, parent de fusión) que apunte al origen.
- Sin CRUD/API todavía (fuera de alcance de este cambio): las filas se cargan a mano o por script
  puntual. ``motivo``/``creado_por`` quedan como la única traza de auditoría mientras eso sea así.
- Riesgo a documentar, no a resolver acá: si ``id_cromo_destino`` corresponde a una clase que este
  repo nunca ingiere como ``CromoBotella`` (ODF, o cualquier clase fuera de ``CLASES_BOTELLA``),
  esa fila queda como ``REF_COLGADA`` permanente en ``fase_reconciliacion`` — comportamiento
  esperado: el destino de una fusión debe ser un n_id de botella real e ingerible.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260819_01"
down_revision = "20260814_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cromo_botella_alias",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("id_cromo_origen", sa.BigInteger(), nullable=False),
        sa.Column("id_cromo_destino", sa.BigInteger(), nullable=True),
        sa.Column("accion", sa.String(length=20), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column("creado_por", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )
    op.create_index(
        "uq_cromo_botella_alias_id_cromo_origen",
        "cromo_botella_alias",
        ["id_cromo_origen"],
        unique=True,
        schema="app",
    )
    op.create_index(
        "ix_cromo_botella_alias_id_cromo_destino",
        "cromo_botella_alias",
        ["id_cromo_destino"],
        schema="app",
    )
    op.create_check_constraint(
        "ck_cromo_botella_alias_accion_valida",
        "cromo_botella_alias",
        "accion IN ('fusionar', 'ignorar')",
        schema="app",
    )
    op.create_check_constraint(
        "ck_cromo_botella_alias_destino_coherente",
        "cromo_botella_alias",
        "(accion = 'fusionar' AND id_cromo_destino IS NOT NULL) "
        "OR (accion = 'ignorar' AND id_cromo_destino IS NULL)",
        schema="app",
    )
    op.create_check_constraint(
        "ck_cromo_botella_alias_no_autoreferencia",
        "cromo_botella_alias",
        # En Postgres, `<> NULL` evalúa a NULL (no a FALSE) y un CHECK sólo falla ante FALSE
        # explícito, así que esta única condición cubre 'fusionar' (chequeo real) e 'ignorar'
        # (destino NULL, la condición es un no-op) sin necesitar una cláusula OR aparte.
        "id_cromo_origen <> id_cromo_destino",
        schema="app",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_cromo_botella_alias_no_autoreferencia", "cromo_botella_alias", schema="app", type_="check"
    )
    op.drop_constraint(
        "ck_cromo_botella_alias_destino_coherente", "cromo_botella_alias", schema="app", type_="check"
    )
    op.drop_constraint(
        "ck_cromo_botella_alias_accion_valida", "cromo_botella_alias", schema="app", type_="check"
    )
    op.drop_index("ix_cromo_botella_alias_id_cromo_destino", table_name="cromo_botella_alias", schema="app")
    op.drop_index("uq_cromo_botella_alias_id_cromo_origen", table_name="cromo_botella_alias", schema="app")
    op.drop_table("cromo_botella_alias", schema="app")
