# Nombre de archivo: 20260917_03_cromo_splitters.py
# Ubicación de archivo: db/alembic/versions/20260917_03_cromo_splitters.py
# Descripción: Tablas app.cromo_splitters y app.cromo_splitter_puertos — el ratio del splitter y
# sus puertos vienen publicados por Cromo y hasta ahora se descartaban en cada corrida

"""Tablas cromo_splitters y cromo_splitter_puertos

Revision ID: 20260917_03
Revises: 20260917_02
Create Date: 2026-09-17

Cambios:
- Nueva tabla ``app.cromo_splitters`` (clase 133) y ``app.cromo_splitter_puertos`` (clase 134).
  Las dos cuelgan del ``inner[]`` de la Botella, igual que las fusiones, y **ya venían en cada
  barrido**: ``parse_arbol_botella`` las descartaba como "clase inesperada".
- Motivo, medido real contra Cromo el 2026-09-17 sobre **30 botellas**: la heurística de
  ``core/services/cromo/empalmes.py``, que deduce el splitter por fan-out de fusiones, acertó en 18
  y falló en 12 — 1 falso positivo (inventó un splitter donde Cromo no tiene ninguno), 5 falsos
  negativos y 6 casos con la cantidad equivocada. En **ninguno** de los casos con splitter real
  devolvió un ratio: siempre ``None``. Cromo lo publica en ``at.83`` ("1x8", "1x4", "1x2").
- ``salidas`` guarda el ``N`` de "1xN" ya parseado; ``ratio`` conserva el texto crudo porque es lo
  que el operador reconoce. Un ratio que no matchea ``1xN`` deja ``salidas`` en NULL en vez de
  normalizarse a un número inventado.
- ``servicios_atributo`` (JSONB) es el ``at.62`` del puerto: **NULL significa "no se preguntó"** y
  ``[]`` significa "se preguntó y el puerto está libre". La distinción importa porque el barrido de
  colección **no** trae ese atributo —sólo la respuesta de ``/db/objects/{id}/inner``—, misma
  asimetría ya documentada para los conectores de ODF.
- Sin FK duras hacia ``n_id`` de Cromo (mismo criterio que el resto del namespace); ``sentido`` es
  Text + CHECK y no un enum nativo, igual que ``cromo_odfs.tipo_elemento``.
- Bajas lógicas con ``vigente``, nunca ``DELETE``.
- Columna ``app.cromo_botellas.splitters_relevados`` (default ``false``): distingue "esta botella
  **no tiene** splitters" de "esta botella **todavía no se barrió** con el código que los lee".
  Sin ese marcador, cero filas en ``cromo_splitters`` sería ambiguo y ``empalmes.py`` no podría
  saber cuándo dejar de aplicar su heurística — que es justamente la que inventa splitters donde no
  hay (falso positivo real: botella 6636551, 2 detectados contra 0 reales).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260917_03"
down_revision = "20260917_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cromo_splitters",
        sa.Column("n_id", sa.BigInteger(), primary_key=True),
        sa.Column("botella_n_id", sa.BigInteger(), nullable=True),
        sa.Column("nombre", sa.Text(), nullable=True),
        sa.Column("ratio", sa.Text(), nullable=True),
        sa.Column("salidas", sa.Integer(), nullable=True),
        sa.Column("vigente", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "ultima_ingesta",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        schema="app",
    )
    op.create_index(
        "ix_cromo_splitters_botella_n_id", "cromo_splitters", ["botella_n_id"], schema="app"
    )

    op.create_table(
        "cromo_splitter_puertos",
        sa.Column("n_id", sa.BigInteger(), primary_key=True),
        sa.Column("splitter_n_id", sa.BigInteger(), nullable=True),
        sa.Column("botella_n_id", sa.BigInteger(), nullable=True),
        sa.Column("nombre", sa.Text(), nullable=True),
        sa.Column("sentido", sa.Text(), nullable=True),
        sa.Column(
            "servicios_atributo",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("vigente", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "ultima_ingesta",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        schema="app",
    )
    op.create_index(
        "ix_cromo_splitter_puertos_splitter_n_id",
        "cromo_splitter_puertos",
        ["splitter_n_id"],
        schema="app",
    )
    op.create_index(
        "ix_cromo_splitter_puertos_botella_n_id",
        "cromo_splitter_puertos",
        ["botella_n_id"],
        schema="app",
    )
    op.create_check_constraint(
        "ck_cromo_splitter_puertos_sentido_valido",
        "cromo_splitter_puertos",
        "sentido IS NULL OR sentido IN ('ENTRADA', 'SALIDA')",
        schema="app",
    )

    op.add_column(
        "cromo_botellas",
        sa.Column(
            "splitters_relevados",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("cromo_botellas", "splitters_relevados", schema="app")
    op.drop_constraint(
        "ck_cromo_splitter_puertos_sentido_valido",
        "cromo_splitter_puertos",
        schema="app",
        type_="check",
    )
    op.drop_index(
        "ix_cromo_splitter_puertos_botella_n_id", table_name="cromo_splitter_puertos", schema="app"
    )
    op.drop_index(
        "ix_cromo_splitter_puertos_splitter_n_id", table_name="cromo_splitter_puertos", schema="app"
    )
    op.drop_table("cromo_splitter_puertos", schema="app")
    op.drop_index("ix_cromo_splitters_botella_n_id", table_name="cromo_splitters", schema="app")
    op.drop_table("cromo_splitters", schema="app")
