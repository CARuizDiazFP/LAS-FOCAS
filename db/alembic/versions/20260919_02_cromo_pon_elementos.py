# Nombre de archivo: 20260919_02_cromo_pon_elementos.py
# Ubicación de archivo: db/alembic/versions/20260919_02_cromo_pon_elementos.py
# Descripción: Crea app.cromo_pon_elementos, la tabla única de cajas PON y rosetas de la red de
# acceso, discriminadas por clase

"""Tabla cromo_pon_elementos

Revision ID: 20260919_02
Revises: 20260919_01
Create Date: 2026-09-19

Una sola tabla para las ocho clases raíz de la red de acceso PON: 84, 126, 127, 137, 138, 139 y
140 (caja PON) más 85 (roseta). El esquema medido contra Cromo real es idéntico en las ocho —todas
raíz, con ``ll``/``pts``/``vmax`` y los mismos ``at``— así que ocho tablas serían ocho copias del
mismo DDL. Lo que las distingue es ``cromo_clases.entidad``, de donde el camino óptico ya saca la
etiqueta del nodo; ver el docstring de ``CromoPonElemento`` para el razonamiento completo.

Volumen esperado (conteos reales de `20260919_01`): 13.432 cajas PON + 17.348 rosetas ≈ 30.800
filas.

La FK de ``clase`` contra ``app.cromo_clases`` exige que las 5 clases nuevas ya estén catalogadas,
por eso esta migración va después de `20260919_01` y no puede adelantarse.

Columnas con semántica medida, no inferida: ``capacidad_puertos`` (``at.46``: sobre 81 objetos
reales tomó sólo 8, 16 y 4), ``tipo_conector`` (``at.40``: "Fast connect", "Easy Connect",
"Conector de campo", "Con casquillo") y ``propietario`` (``at.47``). Los ``at`` 45 y 203 **no**
tienen columna: el primero fue constante ("SI" en los 81) y el segundo devolvió valores
incoherentes entre sí; quedan en ``payload_raw`` hasta que alguien los entienda.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260919_02"
down_revision = "20260919_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cromo_pon_elementos",
        sa.Column("n_id", sa.BigInteger(), primary_key=True),
        sa.Column("version_id", sa.BigInteger(), nullable=False),
        sa.Column("vmax", sa.Integer(), nullable=False),
        sa.Column(
            "clase",
            sa.SmallInteger(),
            sa.ForeignKey("app.cromo_clases.clase"),
            nullable=False,
        ),
        sa.Column("nombre", sa.Text(), nullable=True),
        sa.Column("codigo_modelo", sa.Text(), nullable=True),
        sa.Column("id_legacy", sa.Text(), nullable=True),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column("calle", sa.Text(), nullable=True),
        sa.Column("altura", sa.Text(), nullable=True),
        sa.Column("localidad", sa.Text(), nullable=True),
        sa.Column("provincia", sa.Text(), nullable=True),
        sa.Column("ubicacion_fisica", sa.Text(), nullable=True),
        sa.Column("tendido", sa.Text(), nullable=True),
        sa.Column("propietario", sa.Text(), nullable=True),
        sa.Column("tipo_conector", sa.Text(), nullable=True),
        sa.Column("capacidad_puertos", sa.SmallInteger(), nullable=True),
        sa.Column("latitud", sa.Float(), nullable=True),
        sa.Column("longitud", sa.Float(), nullable=True),
        sa.Column("pts_raw", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("payload_raw", JSONB(astext_type=sa.Text()), nullable=False),
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
        sa.Column("ultima_modificacion", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )
    op.create_index(
        "ix_cromo_pon_elementos_nombre_btree",
        "cromo_pon_elementos",
        ["nombre"],
        schema="app",
    )
    op.create_index(
        "ix_cromo_pon_elementos_clase", "cromo_pon_elementos", ["clase"], schema="app"
    )
    op.create_index(
        "ix_cromo_pon_elementos_localidad",
        "cromo_pon_elementos",
        ["localidad"],
        schema="app",
    )


def downgrade() -> None:
    op.drop_index("ix_cromo_pon_elementos_localidad", table_name="cromo_pon_elementos", schema="app")
    op.drop_index("ix_cromo_pon_elementos_clase", table_name="cromo_pon_elementos", schema="app")
    op.drop_index("ix_cromo_pon_elementos_nombre_btree", table_name="cromo_pon_elementos", schema="app")
    op.drop_table("cromo_pon_elementos", schema="app")
