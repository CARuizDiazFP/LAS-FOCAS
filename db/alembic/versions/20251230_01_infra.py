"""
# Nombre de archivo: 20251230_01_infra.py
# Ubicación de archivo: db/alembic/versions/20251230_01_infra.py
# Descripción: Crea tablas de infraestructura (cámaras, cables, empalmes, servicios, ingresos y asociación)
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20251230_01"
down_revision = "20251014_01"
branch_labels = None
depends_on = None


camara_estado_enum = postgresql.ENUM(
    "LIBRE",
    "OCUPADA",
    "BANEADA",
    name="camara_estado",
    schema="app",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    camara_estado_enum.create(bind, checkfirst=True)

    op.create_table(
        "camaras",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fontine_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("nombre", sa.String(length=128), nullable=True),
        sa.Column("latitud", sa.Float(), nullable=True),
        sa.Column("longitud", sa.Float(), nullable=True),
        sa.Column("direccion", sa.String(length=255), nullable=True),
        sa.Column("estado", camara_estado_enum, nullable=False, server_default="LIBRE"),
        sa.Column("last_update", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )
    op.create_index("ix_camaras_fontine_id", "camaras", ["fontine_id"], schema="app", unique=True)

    op.create_table(
        "cables",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nombre", sa.String(length=128), nullable=True),
        sa.Column("origen_camara_id", sa.Integer(), sa.ForeignKey("app.camaras.id", ondelete="SET NULL"), nullable=True),
        sa.Column("destino_camara_id", sa.Integer(), sa.ForeignKey("app.camaras.id", ondelete="SET NULL"), nullable=True),
        schema="app",
    )

    op.create_table(
        "empalmes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tracking_empalme_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("camara_id", sa.Integer(), sa.ForeignKey("app.camaras.id"), nullable=True),
        sa.Column("tipo", sa.String(length=64), nullable=True),
        schema="app",
    )
    op.create_index("ix_empalmes_camara_id", "empalmes", ["camara_id"], schema="app")
    op.create_index("ix_empalmes_tracking_empalme_id", "empalmes", ["tracking_empalme_id"], schema="app")

    op.create_table(
        "servicios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cliente", sa.String(length=255), nullable=True),
        sa.Column("categoria", sa.Integer(), nullable=True),
        sa.Column("raw_tracking_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="app",
    )

    op.create_table(
        "servicio_empalme_association",
        sa.Column("servicio_id", sa.Integer(), sa.ForeignKey("app.servicios.id"), primary_key=True),
        sa.Column("empalme_id", sa.Integer(), sa.ForeignKey("app.empalmes.id"), primary_key=True),
        schema="app",
    )

    op.create_table(
        "ingresos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("camara_id", sa.Integer(), sa.ForeignKey("app.camaras.id"), nullable=False),
        sa.Column("tecnico_id", sa.String(length=128), nullable=True),
        sa.Column("fecha_inicio", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fecha_fin", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )
    op.create_index("ix_ingresos_camara_id", "ingresos", ["camara_id"], schema="app")


def downgrade() -> None:
    op.drop_index("ix_camaras_fontine_id", table_name="camaras", schema="app")
    op.drop_index("ix_ingresos_camara_id", table_name="ingresos", schema="app")
    op.drop_table("ingresos", schema="app")

    op.drop_table("servicio_empalme_association", schema="app")

    op.drop_table("servicios", schema="app")

    op.drop_index("ix_empalmes_tracking_empalme_id", table_name="empalmes", schema="app")
    op.drop_index("ix_empalmes_camara_id", table_name="empalmes", schema="app")
    op.drop_table("empalmes", schema="app")

    op.drop_table("cables", schema="app")

    op.drop_table("camaras", schema="app")

    camara_estado_enum.drop(op.get_bind(), checkfirst=True)
