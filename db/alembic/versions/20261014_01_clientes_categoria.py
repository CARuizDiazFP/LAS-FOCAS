# Nombre de archivo: 20261014_01_clientes_categoria.py
# Ubicación de archivo: db/alembic/versions/20261014_01_clientes_categoria.py
# Descripción: Tablas app.clientes y app.clientes_alias, enum cliente_origen_categoria y categoría SLA/excepción en app.servicios (categoria pasa a nullable sin default)

"""clientes_categoria

Revision ID: 20261014_01
Revises: 20261005_02
Create Date: 2026-10-14

Cambios:
- Nuevo enum ``app.cliente_origen_categoria``: LISTA, MANUAL, SLA, AUTO. Se crea de cero
  (``CREATE TYPE``), así que se puede usar en la misma transacción — mismo caso que
  ``20260814_02_servicios_origen_datos.py``. ``categoria NULL`` con ``AUTO`` = "sin datos".
- ``app.clientes``: un cliente por ``clave`` normalizada, con su categoría (0–6 o NULL) y el origen
  de esa categoría.
- ``app.clientes_alias``: variantes del nombre de cliente que apuntan a un ``clientes.id``
  (``ON DELETE CASCADE``).
- ``app.servicios``:
  - ``categoria_sla smallint NULL`` (CHECK 0–6): la categoría que trajo la planilla SLA.
  - ``categoria_excepcion bool NOT NULL DEFAULT false``: el servicio no sigue a su cliente.
  - ``categoria`` deja de ser ``NOT NULL DEFAULT 6``. ``NULL`` pasa a significar "sin
    categorizar"; 6 queda sólo para C6 real. ``ck_servicios_categoria_valida`` sigue vigente
    (Postgres deja pasar NULL en un CHECK).

Backfill estructural (no carga clientes; eso lo hace el script de la Tarea 3):
- ``categoria_sla = categoria`` donde ``nombre_cliente IS NOT NULL AND categoria BETWEEN 1 AND 6``.
  Hoy ese valor sólo puede venir de la planilla: PROV no escribe categoría.
- ``categoria = NULL`` donde ``categoria = 6 AND nombre_cliente IS NULL``: era el default.

``downgrade()`` vuelve los NULL a 6, restaura ``NOT NULL``/``DEFAULT 6`` y borra columnas, tablas y
enum. El paso NULL→6 es con pérdida: no distingue un NULL que antes era 6 de uno nuevo.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261014_01"
down_revision = "20261005_02"
branch_labels = None
depends_on = None


_VALORES_ORIGEN = ("LISTA", "MANUAL", "SLA", "AUTO")


def _enum_origen() -> postgresql.ENUM:
    return postgresql.ENUM(*_VALORES_ORIGEN, name="cliente_origen_categoria", schema="app", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    _enum_origen().create(bind, checkfirst=True)

    op.create_table(
        "clientes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nombre", sa.String(255), nullable=False),
        sa.Column("clave", sa.String(255), nullable=False, unique=True),
        sa.Column("categoria", sa.SmallInteger(), nullable=True),
        sa.Column("origen_categoria", _enum_origen(), nullable=False, server_default="AUTO"),
        sa.Column("a_revisar", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_por", sa.String(120), nullable=True),
        sa.CheckConstraint("categoria BETWEEN 0 AND 6", name="ck_clientes_categoria_valida"),
        schema="app",
    )

    op.create_table(
        "clientes_alias",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clave", sa.String(255), nullable=False, unique=True),
        sa.Column("nombre_original", sa.String(255), nullable=False),
        sa.Column(
            "cliente_id",
            sa.Integer(),
            sa.ForeignKey("app.clientes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("origen", sa.String(10), nullable=False, server_default="AUTO"),
        sa.CheckConstraint("origen IN ('AUTO', 'MANUAL')", name="ck_clientes_alias_origen_valido"),
        schema="app",
    )
    op.create_index("ix_clientes_alias_cliente_id", "clientes_alias", ["cliente_id"], schema="app")

    op.add_column("servicios", sa.Column("categoria_sla", sa.SmallInteger(), nullable=True), schema="app")
    op.create_check_constraint(
        "ck_servicios_categoria_sla_valida",
        "servicios",
        "categoria_sla BETWEEN 0 AND 6",
        schema="app",
    )
    op.add_column(
        "servicios",
        sa.Column("categoria_excepcion", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema="app",
    )

    op.alter_column(
        "servicios",
        "categoria",
        existing_type=sa.Integer(),
        nullable=True,
        server_default=None,
        schema="app",
    )

    op.execute(
        "UPDATE app.servicios SET categoria_sla = categoria "
        "WHERE nombre_cliente IS NOT NULL AND categoria BETWEEN 1 AND 6"
    )
    op.execute("UPDATE app.servicios SET categoria = NULL WHERE categoria = 6 AND nombre_cliente IS NULL")


def downgrade() -> None:
    op.execute("UPDATE app.servicios SET categoria = 6 WHERE categoria IS NULL")
    op.alter_column(
        "servicios",
        "categoria",
        existing_type=sa.Integer(),
        nullable=False,
        server_default=sa.text("6"),
        schema="app",
    )

    op.drop_column("servicios", "categoria_excepcion", schema="app")
    op.drop_constraint("ck_servicios_categoria_sla_valida", "servicios", schema="app", type_="check")
    op.drop_column("servicios", "categoria_sla", schema="app")

    op.drop_index("ix_clientes_alias_cliente_id", table_name="clientes_alias", schema="app")
    op.drop_table("clientes_alias", schema="app")
    op.drop_table("clientes", schema="app")
    _enum_origen().drop(bind=op.get_bind(), checkfirst=True)
