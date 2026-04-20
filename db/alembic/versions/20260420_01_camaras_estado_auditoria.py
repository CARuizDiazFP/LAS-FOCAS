# Nombre de archivo: 20260420_01_camaras_estado_auditoria.py
# Ubicación de archivo: db/alembic/versions/20260420_01_camaras_estado_auditoria.py
# Descripción: Crea tabla de auditoría para cambios manuales del estado de cámaras

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260420_01"
down_revision = "20260417_01"
branch_labels = None
depends_on = None


camara_estado_enum = postgresql.ENUM(
    "LIBRE",
    "OCUPADA",
    "BANEADA",
    "DETECTADA",
    name="camara_estado",
    schema="app",
    create_type=False,
)


def upgrade() -> None:
    op.create_table(
        "camaras_estado_auditoria",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "camara_id",
            sa.Integer(),
            sa.ForeignKey("app.camaras.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("usuario", sa.String(length=128), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("estado_anterior", camara_estado_enum, nullable=False),
        sa.Column("estado_nuevo", camara_estado_enum, nullable=False),
        sa.Column("estado_sugerido", camara_estado_enum, nullable=True),
        sa.Column("incidentes_activos", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        schema="app",
    )
    op.create_index(
        "ix_camaras_estado_auditoria_camara_id",
        "camaras_estado_auditoria",
        ["camara_id"],
        schema="app",
    )
    op.create_index(
        "ix_camaras_estado_auditoria_created_at",
        "camaras_estado_auditoria",
        ["created_at"],
        schema="app",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_camaras_estado_auditoria_created_at",
        table_name="camaras_estado_auditoria",
        schema="app",
    )
    op.drop_index(
        "ix_camaras_estado_auditoria_camara_id",
        table_name="camaras_estado_auditoria",
        schema="app",
    )
    op.drop_table("camaras_estado_auditoria", schema="app")