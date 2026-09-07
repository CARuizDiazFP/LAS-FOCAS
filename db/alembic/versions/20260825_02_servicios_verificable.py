# Nombre de archivo: 20260825_02_servicios_verificable.py
# Ubicación de archivo: db/alembic/versions/20260825_02_servicios_verificable.py
# Descripción: Agrega es_verificable (calculado por tipo_servicio, con backfill) y es_verificable_override (corrección manual) a app.servicios

"""es_verificable + es_verificable_override en servicios

Revision ID: 20260825_02
Revises: 20260825_01
Create Date: 2026-08-25

Cambios:
- `es_verificable` (Boolean NOT NULL): True si `tipo_servicio` está en {INT, RPV, ISI, ISIS, TLS,
  EWS} (ver `core/services/servicios_consolidacion_service.py::TIPOS_SERVICIO_VERIFICABLES`).
  Backfill con la misma regla para las filas existentes ANTES de fijar NOT NULL — mismo orden que
  `20260814_01_servicios_categoria_check.py` (backfill antes de SET NOT NULL/CHECK).
- `es_verificable_override` (Boolean, nullable, default NULL): corrección manual de admin. Cuando
  no es NULL, la ingesta de Excel no recalcula `es_verificable` para esa fila — mismo criterio ya
  usado para no auditar `categoria`, sin tabla de auditoría dedicada.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260825_02"
down_revision = "20260825_01"
branch_labels = None
depends_on = None

_TIPOS_VERIFICABLES = ("INT", "RPV", "ISI", "ISIS", "TLS", "EWS")


def upgrade() -> None:
    bind = op.get_bind()

    op.add_column(
        "servicios",
        sa.Column("es_verificable", sa.Boolean(), nullable=True),
        schema="app",
    )
    op.add_column(
        "servicios",
        sa.Column("es_verificable_override", sa.Boolean(), nullable=True),
        schema="app",
    )

    # Backfill ANTES de SET NOT NULL — calcula desde tipo_servicio para las filas existentes.
    # _TIPOS_VERIFICABLES es una constante fija del código (no dato de usuario): el f-string es un
    # literal IN (...), no una concatenación de datos externos.
    # COALESCE(tipo_servicio IN (...), false) para manejar tipos_servicio NULL → false.
    tipos_sql = ", ".join(f"'{tipo}'" for tipo in _TIPOS_VERIFICABLES)
    bind.execute(
        sa.text(
            f"UPDATE app.servicios SET es_verificable = COALESCE(tipo_servicio IN ({tipos_sql}), false) "
            "WHERE es_verificable IS NULL"
        )
    )

    op.alter_column(
        "servicios",
        "es_verificable",
        existing_type=sa.Boolean(),
        nullable=False,
        server_default=sa.text("false"),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("servicios", "es_verificable_override", schema="app")
    op.drop_column("servicios", "es_verificable", schema="app")
