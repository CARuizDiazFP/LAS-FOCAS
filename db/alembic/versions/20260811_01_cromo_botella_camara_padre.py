# Nombre de archivo: 20260811_01_cromo_botella_camara_padre.py
# Ubicación de archivo: db/alembic/versions/20260811_01_cromo_botella_camara_padre.py
# Descripción: Vincula Botellas Cromo a una Cámara padre propia (app.camaras) y les da estado operativo — nuevos valores NO_OPERATIVA/INFERIDO_CROMO

"""Cámara padre + estado para Botellas Cromo

Revision ID: 20260811_01
Revises: 20260810_01
Create Date: 2026-08-11

Cambios:
- Nuevo valor en enum ``app.camara_estado``: NO_OPERATIVA (default seguro,
  fail-closed, para Cámaras/Botellas sin ninguna señal operativa real —
  ``app.cromo_botellas`` no trackea Libre/Ocupada/Baneada en origen).
- Nuevo valor en enum ``app.camara_origen_datos``: INFERIDO_CROMO (Cámara
  padre sintetizada por el backfill de nombre sobre Botellas Cromo — distinto
  de INFERIDO, que es del backfill legado Bot-N sobre ``app.camaras``; permite
  distinguir con una query trivial qué pipeline heurístico sintetizó cada fila).
- Nueva columna ``app.cromo_botellas.camara_id``: FK nullable a
  ``app.camaras.id`` (``ondelete=SET NULL``). Nombre deliberado (no
  ``camara_padre_id``): ese término ya es jerga específica del self-FK
  jerárquico de ``Camara`` — acá es una FK simple hacia "la cámara asociada",
  mismo patrón de nombre que ``camara_alias.camara_id``/``ingresos.camara_id``.
- Nueva columna ``app.cromo_botellas.estado``: reusa el mismo tipo Postgres
  ``camara_estado`` (no un enum paralelo). ``NOT NULL DEFAULT 'NO_OPERATIVA'``
  — en PG11+ es metadata-only, no reescribe las ~11.100 filas existentes.
- CHECK constraint ``ck_cromo_botellas_estado_valido``: Cromo sólo admite
  LIBRE/OCUPADA/BANEADA/NO_OPERATIVA — DETECTADA/PENDIENTE_REVISION son
  workflows exclusivos del dominio legado (ver mapeo de herencia en
  ``scripts/cromo_backfill_camara_padre.py::_MAPEO_ESTADO_CROMO``).

Nota técnica: ``db/alembic/env.py`` corre todas las migraciones dentro de una
única transacción (``context.begin_transaction()``). Postgres prohíbe usar un
valor de enum recién agregado (``ADD VALUE``) dentro de la misma transacción
que lo crea, y esta migración sí necesita usar 'NO_OPERATIVA' en el mismo
archivo (server_default + CHECK) — a diferencia de 20260810_01, que agregó
INFERIDO sin consumirlo. Los dos ``ADD VALUE`` van envueltos en
``op.get_context().autocommit_block()`` para comitearlos de forma
independiente antes de usarlos (primera vez que este repo necesita esta
técnica).

No hay forma de expresar en un CHECK de Postgres el invariante cross-tabla
"``camara_id`` debe apuntar siempre a una fila raíz de ``camaras``, nunca a
una botella legado" (no hay subqueries en CHECK) — se garantiza por
construcción del lado de escritura (todo alta pasa por
``resolver_o_crear_padre_desde_base``) y se audita por log en el script de
backfill, no por constraint de DB.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260811_01"
down_revision = "20260810_01"
branch_labels = None
depends_on = None


camara_estado_enum = postgresql.ENUM(
    "LIBRE",
    "OCUPADA",
    "BANEADA",
    "DETECTADA",
    "PENDIENTE_REVISION",
    "NO_OPERATIVA",
    name="camara_estado",
    schema="app",
    create_type=False,
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE app.camara_estado ADD VALUE IF NOT EXISTS 'NO_OPERATIVA'")
        op.execute("ALTER TYPE app.camara_origen_datos ADD VALUE IF NOT EXISTS 'INFERIDO_CROMO'")

    op.add_column(
        "cromo_botellas",
        sa.Column(
            "camara_id",
            sa.Integer(),
            sa.ForeignKey("app.camaras.id", ondelete="SET NULL"),
            nullable=True,
        ),
        schema="app",
    )
    op.create_index(
        "ix_cromo_botellas_camara_id",
        "cromo_botellas",
        ["camara_id"],
        schema="app",
    )
    op.add_column(
        "cromo_botellas",
        sa.Column(
            "estado",
            camara_estado_enum,
            nullable=False,
            server_default="NO_OPERATIVA",
        ),
        schema="app",
    )
    op.create_check_constraint(
        "ck_cromo_botellas_estado_valido",
        "cromo_botellas",
        "estado IN ('LIBRE', 'OCUPADA', 'BANEADA', 'NO_OPERATIVA')",
        schema="app",
    )


def downgrade() -> None:
    op.drop_constraint("ck_cromo_botellas_estado_valido", "cromo_botellas", schema="app", type_="check")
    op.drop_column("cromo_botellas", "estado", schema="app")
    op.drop_index("ix_cromo_botellas_camara_id", table_name="cromo_botellas", schema="app")
    op.drop_column("cromo_botellas", "camara_id", schema="app")
    # NOTA: no se puede revertir ADD VALUE en PostgreSQL 11+ — NO_OPERATIVA e
    # INFERIDO_CROMO quedan en sus enums tras el downgrade, mismo caso ya
    # documentado para INFERIDO en 20260810_01_camara_padre_botella.py.
