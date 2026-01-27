# Nombre de archivo: 20260127_01_incidente_baneo_email_fields.py
# Ubicación de archivo: db/alembic/versions/20260127_01_incidente_baneo_email_fields.py
# Descripción: Agrega campos de asunto y cuerpo de correo a incidentes de baneo

"""Agregar email_subject y email_body a incidentes_baneo

Revision ID: 20260127_01
Revises: 20260113_01
Create Date: 2026-01-27

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260127_01"
down_revision = "20260113_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Agregar columnas para persistir asunto y cuerpo de email en incidentes de baneo."""
    op.add_column(
        "incidentes_baneo",
        sa.Column("email_subject", sa.String(length=512), nullable=True),
        schema="app",
    )
    op.add_column(
        "incidentes_baneo",
        sa.Column("email_body", sa.Text(), nullable=True),
        schema="app",
    )


def downgrade() -> None:
    """Revertir columnas de asunto y cuerpo de email en incidentes de baneo."""
    op.drop_column("incidentes_baneo", "email_body", schema="app")
    op.drop_column("incidentes_baneo", "email_subject", schema="app")
