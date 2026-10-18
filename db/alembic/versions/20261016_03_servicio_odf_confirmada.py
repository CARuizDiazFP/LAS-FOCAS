# Nombre de archivo: 20261016_03_servicio_odf_confirmada.py
# Ubicación de archivo: db/alembic/versions/20261016_03_servicio_odf_confirmada.py
# Descripción: Tabla app.servicio_odf_confirmada (ODF confirmadas por servicio, con rol EXTREMO o
# TRANSITO) y columna app.servicios.trackings_esperados (cantidad de trackings que declara el operador).

"""servicio_odf_confirmada + servicios.trackings_esperados

Revision ID: 20261016_03
Revises: 20261016_02
Create Date: 2026-10-16

Cambios:
- Nueva tabla ``app.servicio_odf_confirmada``: las ODF que un operador confirma como parte del
  recorrido de un Servicio, con su rol (``EXTREMO`` o ``TRANSITO``). Un camino que toca una ODF
  confirmada es siempre ``TRAMO`` (``tracking_service.clasificar_caminos``). ``odf_n_id`` es
  referencia blanda a ``cromo_odfs.n_id`` (Cromo puede reingerir). Des-confirmar es
  ``vigente=false``, no se borra la fila: queda el historial. ``UNIQUE(servicio_id, odf_n_id)``
  vale sólo entre las filas vigentes (índice único parcial).
- Nueva columna ``servicios.trackings_esperados SMALLINT NULL`` con ``CHECK (> 0)``: cuántos
  trackings declara el operador para el Servicio. ``NULL`` = sin declarar.
- No reemplaza ``cromo_servicio_odf_override``, que sigue siendo el escudo de "servicios sin ODF":
  la tabla nueva admite varias ODF por servicio.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261016_03"
down_revision = "20261016_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "servicio_odf_confirmada",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "servicio_id",
            sa.Integer(),
            sa.ForeignKey("app.servicios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("odf_n_id", sa.BigInteger(), nullable=False),
        sa.Column("rol", sa.Text(), nullable=False),
        sa.Column("confirmado_por", sa.String(length=128), nullable=False),
        sa.Column(
            "confirmado_en",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("vigente", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.CheckConstraint(
            "rol IN ('EXTREMO', 'TRANSITO')", name="ck_servicio_odf_confirmada_rol_valido"
        ),
        schema="app",
    )
    op.create_index(
        "ux_servicio_odf_confirmada_vigente",
        "servicio_odf_confirmada",
        ["servicio_id", "odf_n_id"],
        unique=True,
        schema="app",
        postgresql_where=sa.text("vigente"),
    )
    op.create_index(
        "ix_servicio_odf_confirmada_servicio",
        "servicio_odf_confirmada",
        ["servicio_id"],
        schema="app",
    )
    op.add_column(
        "servicios", sa.Column("trackings_esperados", sa.SmallInteger(), nullable=True), schema="app"
    )
    op.create_check_constraint(
        "ck_servicios_trackings_esperados_positivo",
        "servicios",
        "trackings_esperados IS NULL OR trackings_esperados > 0",
        schema="app",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_servicios_trackings_esperados_positivo", "servicios", schema="app", type_="check"
    )
    op.drop_column("servicios", "trackings_esperados", schema="app")
    op.drop_index("ix_servicio_odf_confirmada_servicio", table_name="servicio_odf_confirmada", schema="app")
    op.drop_index("ux_servicio_odf_confirmada_vigente", table_name="servicio_odf_confirmada", schema="app")
    op.drop_table("servicio_odf_confirmada", schema="app")
