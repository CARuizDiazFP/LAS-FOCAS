# Nombre de archivo: 20260814_01_servicios_categoria_check.py
# Ubicación de archivo: db/alembic/versions/20260814_01_servicios_categoria_check.py
# Descripción: CHECK + DEFAULT + NOT NULL sobre app.servicios.categoria (0-6), backfill de las ~1488 filas existentes (100% NULL hoy) a 6 ("sin categorizar")

"""CHECK + DEFAULT + NOT NULL sobre servicios.categoria

Revision ID: 20260814_01
Revises: 20260813_01
Create Date: 2026-08-14

Cambios:
- Backfill: las ~1488 filas existentes de `app.servicios` (100% con `categoria IS NULL` hoy,
  verificado contra `lasfocasdev-postgres`) pasan a `categoria = 6` — "sin categorizar todavía".
  `6` es un sentinela distinto de `0`, reservado para los placeholders sintetizados por el
  matching de Cromo (ver `20260814_02_servicios_origen_datos.py` y
  `core/services/cromo/ingesta.py::fase_servicios`) — así "sin categorizar" (servicio real, falta
  triage admin) y "ni siquiera es un servicio real todavía" quedan en valores distintos y
  filtrables por separado.
- `ALTER COLUMN categoria SET DEFAULT 6`: cualquier alta nueva que no fije `categoria`
  explícitamente (ingest SLA por Excel, alta por tracking legado) nace "sin categorizar" en vez
  de NULL.
- `ALTER COLUMN categoria SET NOT NULL`.
- `CHECK ck_servicios_categoria_valida (categoria BETWEEN 0 AND 6)`.

Orden de operaciones (obligatorio): el backfill de datos corre ANTES de `SET NOT NULL`/`CHECK` —
si se invierte el orden, las 1488 filas con `categoria IS NULL` violan `NOT NULL` de inmediato y
la migración aborta a mitad de camino.

Se evaluó `ADD CONSTRAINT ... NOT VALID` + `VALIDATE CONSTRAINT` (evita el lock `ACCESS EXCLUSIVE`
mientras Postgres escanea la tabla completa para validar el CHECK) — descartado: a 1488 filas el
`UPDATE` + `ALTER COLUMN` corre en milisegundos: la sofisticación de `NOT VALID` sólo se justifica
en una tabla caliente de alta escritura concurrente donde ese lock breve importa, y no es el caso
de `app.servicios` (1488 filas, escritura esporádica vía ingest SLA/admin).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260814_01"
down_revision = "20260813_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Backfill ANTES de aplicar NOT NULL/CHECK — hoy el 100% de las filas tiene categoria NULL.
    bind.execute(sa.text("UPDATE app.servicios SET categoria = 6 WHERE categoria IS NULL"))

    # 2. Default para altas futuras que no fijen categoria explícitamente.
    op.alter_column(
        "servicios",
        "categoria",
        existing_type=sa.Integer(),
        server_default=sa.text("6"),
        schema="app",
    )

    # 3. NOT NULL — seguro recién ahora que el backfill ya corrió.
    op.alter_column(
        "servicios",
        "categoria",
        existing_type=sa.Integer(),
        nullable=False,
        schema="app",
    )

    # 4. CHECK de rango válido.
    op.create_check_constraint(
        "ck_servicios_categoria_valida",
        "servicios",
        "categoria BETWEEN 0 AND 6",
        schema="app",
    )


def downgrade() -> None:
    op.drop_constraint("ck_servicios_categoria_valida", "servicios", schema="app", type_="check")
    op.alter_column("servicios", "categoria", existing_type=sa.Integer(), nullable=True, schema="app")
    op.alter_column("servicios", "categoria", existing_type=sa.Integer(), server_default=None, schema="app")
    # No se revierte el backfill (6 -> NULL): sería indistinguible de un 6 real asignado después de
    # esta migración por un admin o por el propio backfill de placeholders. Mismo criterio que el
    # resto de las migraciones de este repo para datos ya escritos (ver DETECTADA/INFERIDO: quedan,
    # no son reversibles a nivel dato).
