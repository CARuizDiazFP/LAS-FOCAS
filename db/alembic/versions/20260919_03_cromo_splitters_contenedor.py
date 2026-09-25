# Nombre de archivo: 20260919_03_cromo_splitters_contenedor.py
# Ubicación de archivo: db/alembic/versions/20260919_03_cromo_splitters_contenedor.py
# Descripción: Agrega contenedor_n_id/contenedor_clase a app.cromo_splitters, porque el 88% de los
# splitters no cuelga de una Botella sino de una caja PON

"""Contenedor real del splitter

Revision ID: 20260919_03
Revises: 20260919_02
Create Date: 2026-09-19

``cromo_splitters`` nació con una sola columna de vínculo, ``botella_n_id``, porque los splitters se
ingerían embebidos en el árbol de Botella. La medición del 2026-09-19 sobre **800 splitters reales**
muestra que esa premisa cubre apenas el 12%: el reparto por clase del contenedor es 137→435,
139→176, 68→84, 138→35, 84→32, 140→21, 122→8, 126→4, 125→2, y 123/121/127→1. El 88% cuelga de una
caja PON.

Con el barrido directo de la clase 133 (el modo ``SOLO_SPLITTERS``) esos objetos entran al
inventario, y sin estas dos columnas quedarían sin vínculo a nada.

``botella_n_id`` **se conserva y no se toca**: es por donde consulta ``empalmes.py`` para el panel
de empalmes del Verificador. Pasa a poblarse sólo cuando el contenedor es de una clase Botella, que
es lo que esa consulta siempre quiso decir.

El backfill afecta **1 fila** (el único splitter ingerido hasta hoy, de la botella de verificación
8941541): copia ``botella_n_id`` a ``contenedor_n_id`` y resuelve la clase por join contra
``cromo_botellas``. No se pone FK dura sobre ``contenedor_n_id``: apunta a dos tablas distintas
según la clase, igual criterio que el resto de las referencias cruzadas del módulo, que se auditan
con la fase de reconciliación en vez de con una constraint.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260919_03"
down_revision = "20260919_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cromo_splitters",
        sa.Column("contenedor_n_id", sa.BigInteger(), nullable=True),
        schema="app",
    )
    op.add_column(
        "cromo_splitters",
        sa.Column("contenedor_clase", sa.SmallInteger(), nullable=True),
        schema="app",
    )
    op.create_index(
        "ix_cromo_splitters_contenedor_n_id",
        "cromo_splitters",
        ["contenedor_n_id"],
        schema="app",
    )
    op.execute(
        """
        UPDATE app.cromo_splitters AS s
           SET contenedor_n_id = s.botella_n_id,
               contenedor_clase = b.clase
          FROM app.cromo_botellas AS b
         WHERE s.botella_n_id IS NOT NULL
           AND b.n_id = s.botella_n_id
           AND s.contenedor_n_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_cromo_splitters_contenedor_n_id", table_name="cromo_splitters", schema="app"
    )
    op.drop_column("cromo_splitters", "contenedor_clase", schema="app")
    op.drop_column("cromo_splitters", "contenedor_n_id", schema="app")
