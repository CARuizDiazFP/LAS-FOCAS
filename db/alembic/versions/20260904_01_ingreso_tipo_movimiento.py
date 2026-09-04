# Nombre de archivo: 20260904_01_ingreso_tipo_movimiento.py
# Ubicación de archivo: db/alembic/versions/20260904_01_ingreso_tipo_movimiento.py
# Descripción: Nuevo enum app.ingreso_tipo + columna app.ingresos.tipo — distingue INGRESO/EGRESO real de un INTENTO_BLOQUEADO por baneo

"""Enum ingreso_tipo + columna ingresos.tipo

Revision ID: 20260904_01
Revises: 20260902_01
Create Date: 2026-09-04

Cambios:
- Nuevo enum Postgres ``app.ingreso_tipo``: INGRESO, EGRESO, INTENTO_BLOQUEADO — mismo patrón que
  ``app.servicio_origen_datos`` (migración ``20260814_02``).
- Nueva columna ``app.ingresos.tipo``: ``NOT NULL DEFAULT 'INGRESO'`` — todas las filas existentes
  hasta esta fecha representan movimientos reales creados como "Ingreso" (nunca hubo un camino de
  escritura de Intento bloqueado antes de esta migración), así que el default es exacto para el
  histórico, no una aproximación.

Motivación: antes de esta columna, un Ingreso real "en curso" (`fecha_fin IS NULL`) era
indistinguible de un futuro Intento bloqueado con la misma condición — `tiene_ingreso_activo`
(``core/services/camara_estado_service.py``) y el cierre de Egreso NULL-safe
(``core/services/ingreso_service.py``) necesitan filtrar explícitamente por
``tipo == 'INGRESO'`` para no confundir ambos casos.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260904_01"
down_revision = "20260902_01"
branch_labels = None
depends_on = None


_VALORES = ("INGRESO", "EGRESO", "INTENTO_BLOQUEADO")


def upgrade() -> None:
    bind = op.get_bind()

    ingreso_tipo_enum = postgresql.ENUM(*_VALORES, name="ingreso_tipo", schema="app", create_type=False)
    ingreso_tipo_enum.create(bind, checkfirst=True)

    op.add_column(
        "ingresos",
        sa.Column(
            "tipo",
            postgresql.ENUM(*_VALORES, name="ingreso_tipo", schema="app", create_type=False),
            nullable=False,
            server_default="INGRESO",
        ),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("ingresos", "tipo", schema="app")
    ingreso_tipo_enum = postgresql.ENUM(*_VALORES, name="ingreso_tipo", schema="app", create_type=False)
    ingreso_tipo_enum.drop(bind=op.get_bind(), checkfirst=True)
