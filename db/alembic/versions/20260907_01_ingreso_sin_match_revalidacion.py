# Nombre de archivo: 20260907_01_ingreso_sin_match_revalidacion.py
# Ubicación de archivo: db/alembic/versions/20260907_01_ingreso_sin_match_revalidacion.py
# Descripción: Columnas de revalidación en IngresoSinMatch (texto_mensaje, resuelto_via_revalidacion, ingreso_id)

"""Revalidación de ingresos sin match/ambiguos

Revision ID: 20260907_01
Revises: 20260904_01
Create Date: 2026-09-07

Cambios (mecanismo "Revalidar ingreso" — respuesta en el hilo de Slack de un caso pendiente):

- Nueva columna ``app.ingresos_sin_match.texto_mensaje`` (``TEXT NULL``): mensaje completo del
  evento de Slack (no sólo el nombre ya recortado en ``texto_original``) — necesario para poder
  re-extraer nombre/tipo/persona con el código ACTUAL al revalidar, sin depender de que esos otros
  campos también se hayan guardado por separado. ``NULL`` en filas creadas antes de esta migración
  — esos casos históricos no son revalidables automáticamente (no hay forma de recuperar el mensaje
  original).
- Nueva columna ``resuelto_via_revalidacion BOOLEAN NOT NULL DEFAULT false`` — evita reprocesar el
  mismo caso dos veces (mismo patrón que ``resuelto_via_empalme``, migración ``20260823_01``).
- Nueva columna ``ingreso_id INTEGER NULL`` con FK a ``app.ingresos.id`` (``ON DELETE SET NULL``) —
  trazabilidad: al revalidar con éxito, enlaza el caso con el ``Ingreso`` real que terminó
  creando/cerrando.

Motivación: hasta esta fecha, el caso "ambiguo/genérico" (``AmbiguousSearchError``) no persistía
absolutamente nada — a diferencia del caso "sin match", que sí crea una fila en
``ingresos_sin_match``. Desde el cambio de código acompañante (``modules/slack_baneo_notifier/
listener.py``), el caso ambiguo también crea esta fila, y ambos casos quedan revalidables.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260907_01"
down_revision = "20260904_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingresos_sin_match",
        sa.Column("texto_mensaje", sa.Text(), nullable=True),
        schema="app",
    )
    op.add_column(
        "ingresos_sin_match",
        sa.Column("resuelto_via_revalidacion", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="app",
    )
    op.add_column(
        "ingresos_sin_match",
        sa.Column("ingreso_id", sa.Integer(), nullable=True),
        schema="app",
    )
    op.create_foreign_key(
        "fk_ingresos_sin_match_ingreso_id",
        "ingresos_sin_match",
        "ingresos",
        ["ingreso_id"],
        ["id"],
        source_schema="app",
        referent_schema="app",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_ingresos_sin_match_ingreso_id", "ingresos_sin_match", schema="app", type_="foreignkey"
    )
    op.drop_column("ingresos_sin_match", "ingreso_id", schema="app")
    op.drop_column("ingresos_sin_match", "resuelto_via_revalidacion", schema="app")
    op.drop_column("ingresos_sin_match", "texto_mensaje", schema="app")
