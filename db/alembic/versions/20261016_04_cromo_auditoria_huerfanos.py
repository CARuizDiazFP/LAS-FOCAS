# Nombre de archivo: 20261016_04_cromo_auditoria_huerfanos.py
# Ubicación de archivo: db/alembic/versions/20261016_04_cromo_auditoria_huerfanos.py
# Descripción: Tabla app.cromo_auditoria_huerfanos (pelos de caminos residuales con causa sugerida) y
# traza de origen (MANUAL / AUDITORIA) en app.cromo_servicio_pelo_excluido.

"""cromo_auditoria_huerfanos + origen/auditoria_id en cromo_servicio_pelo_excluido

Revision ID: 20261016_04
Revises: 20261016_03
Create Date: 2026-10-16

Cambios:
- Nueva tabla ``app.cromo_auditoria_huerfanos``: una fila por pelo de un camino RESIDUAL de un
  Servicio (los "huérfanos"). Guarda la corrida que lo detectó (``corrida_id``, nula en la
  auditoría por servicio que corre al resolver los caminos), el camino semilla, la causa sugerida,
  la evidencia (JSONB) y el estado de revisión. ``UNIQUE(servicio_id, pelo_n_id)``: re-auditar es
  idempotente. ``pelo_n_id`` es referencia blanda (n_id de linaje de Cromo, como en el caché).
- ``estado``: ``PENDIENTE`` | ``NORMALIZADO`` | ``DESCARTADO`` (Text + CHECK, no ENUM).
- ``causa``: ``PELO_DANADO`` | ``CAMBIO_CABLE_DANO`` | ``CABLE_DESUSO`` | ``MIGRACION_SITIO`` |
  ``SIN_CLASIFICAR``.
- ``app.cromo_servicio_pelo_excluido`` suma ``origen`` (``MANUAL`` default, o ``AUDITORIA``) y
  ``auditoria_id`` (FK a la tabla nueva, ``ON DELETE SET NULL``) para dejar la traza de qué
  exclusión salió de la auditoría.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261016_04"
down_revision = "20261016_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cromo_auditoria_huerfanos",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "corrida_id",
            sa.BigInteger(),
            sa.ForeignKey("app.cromo_ingesta_corridas.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "servicio_id",
            sa.Integer(),
            sa.ForeignKey("app.servicios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pelo_n_id", sa.BigInteger(), nullable=False),
        sa.Column("camino_semilla", sa.BigInteger(), nullable=True),
        sa.Column("causa", sa.Text(), nullable=False, server_default=sa.text("'SIN_CLASIFICAR'")),
        sa.Column("evidencia", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("estado", sa.Text(), nullable=False, server_default=sa.text("'PENDIENTE'")),
        sa.Column("revisado_por", sa.String(length=128), nullable=True),
        sa.Column(
            "detectado_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "actualizado_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "estado IN ('PENDIENTE', 'NORMALIZADO', 'DESCARTADO')",
            name="ck_cromo_auditoria_huerfanos_estado_valido",
        ),
        sa.CheckConstraint(
            "causa IN ('PELO_DANADO', 'CAMBIO_CABLE_DANO', 'CABLE_DESUSO', 'MIGRACION_SITIO', "
            "'SIN_CLASIFICAR')",
            name="ck_cromo_auditoria_huerfanos_causa_valida",
        ),
        sa.UniqueConstraint(
            "servicio_id", "pelo_n_id", name="uq_cromo_auditoria_huerfanos_servicio_pelo"
        ),
        schema="app",
    )
    op.create_index(
        "ix_cromo_auditoria_huerfanos_estado_causa",
        "cromo_auditoria_huerfanos",
        ["estado", "causa"],
        schema="app",
    )
    op.add_column(
        "cromo_servicio_pelo_excluido",
        sa.Column("origen", sa.Text(), nullable=False, server_default=sa.text("'MANUAL'")),
        schema="app",
    )
    op.create_check_constraint(
        "ck_cromo_servicio_pelo_excluido_origen_valido",
        "cromo_servicio_pelo_excluido",
        "origen IN ('MANUAL', 'AUDITORIA')",
        schema="app",
    )
    op.add_column(
        "cromo_servicio_pelo_excluido",
        sa.Column(
            "auditoria_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "app.cromo_auditoria_huerfanos.id",
                ondelete="SET NULL",
                name="fk_cromo_servicio_pelo_excluido_auditoria",
            ),
            nullable=True,
        ),
        schema="app",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_cromo_servicio_pelo_excluido_auditoria",
        "cromo_servicio_pelo_excluido",
        schema="app",
        type_="foreignkey",
    )
    op.drop_column("cromo_servicio_pelo_excluido", "auditoria_id", schema="app")
    op.drop_constraint(
        "ck_cromo_servicio_pelo_excluido_origen_valido",
        "cromo_servicio_pelo_excluido",
        schema="app",
        type_="check",
    )
    op.drop_column("cromo_servicio_pelo_excluido", "origen", schema="app")
    op.drop_index(
        "ix_cromo_auditoria_huerfanos_estado_causa",
        table_name="cromo_auditoria_huerfanos",
        schema="app",
    )
    op.drop_table("cromo_auditoria_huerfanos", schema="app")
