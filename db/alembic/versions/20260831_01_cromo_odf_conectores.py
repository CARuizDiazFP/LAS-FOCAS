# Nombre de archivo: 20260831_01_cromo_odf_conectores.py
# Ubicación de archivo: db/alembic/versions/20260831_01_cromo_odf_conectores.py
# Descripción: Nueva tabla app.cromo_odf_conectores — inventario de conectores/posiciones de
# patchera de una ODF (Cromo Red clases 135/136), con el servicio resuelto vía atributo directo
# + regex de pelo, combinados por criterio MAX-based ID final.

"""Tabla cromo_odf_conectores (conectores de ODF, Cromo Red clases 135/136)

Revision ID: 20260831_01
Revises: 20260828_01
Create Date: 2026-08-31

Cambios:
- Nueva tabla ``app.cromo_odf_conectores``: cada fila es una "Posición Patchera" (clase 136,
  n_id real de Cromo como PK de linaje). La "Patchera"/bandeja padre (clase 135, ej.
  "O-1238223-1") se denormaliza directo en la fila (``bandeja_n_id``/``bandeja_nombre``/
  ``bandeja_modelo``) en vez de una tabla propia — nunca se navega "a" una bandeja sola, sólo
  agrupa visualmente sus conectores.
- ``pelo_n_id`` es el mismo ``n_id`` ya ingerido en ``app.cromo_pelos`` (confirmado real contra
  `lasfocasdev-postgres`: `tp[].id_to` de un conector coincide 1:1 con `cromo_pelos.n_id` — a
  diferencia del "ID dual" ya conocido en extremos de cable, acá `id_to` sí es directamente
  utilizable). Sin FK dura, mismo criterio que el resto de Cromo.
- ``servicio_numero_atributo``: valor crudo del atributo id=62 de Cromo (sólo presente si el
  conector está en uso) — vínculo directo y confiable, sin necesidad de regex, pero con
  inconsistencias propias de Cromo (puede no coincidir con el regex ya resuelto sobre la
  descripción del pelo). ``servicio_resuelto``/``servicio_id_historico`` combinan ese atributo
  con ``cromo_pelos.servicio_numero`` (ya parseado por regex) tomando el mayor como vigente y el
  menor como posible ID histórico — mismo criterio "MAX-based ID final" ya usado en la
  consolidación de identidad de Servicios SLA. Se calculan en la fase de ingesta, no en cada
  lectura.
- Índice sobre ``odf_n_id`` (acceso principal: "conectores de esta ODF") y sobre ``pelo_n_id``
  (acceso secundario: "en qué conector termina este pelo").
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260831_01"
down_revision = "20260828_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cromo_odf_conectores",
        sa.Column("n_id", sa.BigInteger(), primary_key=True),
        sa.Column("odf_n_id", sa.BigInteger(), nullable=False),
        sa.Column("bandeja_n_id", sa.BigInteger(), nullable=True),
        sa.Column("bandeja_nombre", sa.Text(), nullable=True),
        sa.Column("bandeja_modelo", sa.Text(), nullable=True),
        sa.Column("numero_conector", sa.Text(), nullable=True),
        sa.Column("pelo_n_id", sa.BigInteger(), nullable=True),
        sa.Column("servicio_numero_atributo", sa.Text(), nullable=True),
        sa.Column("servicio_resuelto", sa.Text(), nullable=True),
        sa.Column("servicio_id_historico", sa.Text(), nullable=True),
        sa.Column("payload_raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("vigente", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "primera_ingesta",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "ultima_ingesta",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        schema="app",
    )
    op.create_index(
        "ix_cromo_odf_conectores_odf_n_id",
        "cromo_odf_conectores",
        ["odf_n_id"],
        schema="app",
    )
    op.create_index(
        "ix_cromo_odf_conectores_pelo_n_id",
        "cromo_odf_conectores",
        ["pelo_n_id"],
        schema="app",
    )


def downgrade() -> None:
    op.drop_index("ix_cromo_odf_conectores_pelo_n_id", table_name="cromo_odf_conectores", schema="app")
    op.drop_index("ix_cromo_odf_conectores_odf_n_id", table_name="cromo_odf_conectores", schema="app")
    op.drop_table("cromo_odf_conectores", schema="app")
