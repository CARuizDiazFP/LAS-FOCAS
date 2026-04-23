# Nombre de archivo: 20260423_01_config_servicios_hora_inicio.py
# Ubicación de archivo: db/alembic/versions/20260423_01_config_servicios_hora_inicio.py
# Descripción: Agrega columna hora_inicio a app.config_servicios para programar inicio del ciclo en GMT-3

"""Agregar hora_inicio a config_servicios

Revision ID: 20260423_01
Revises: 20260420_01
Create Date: 2026-04-23

"""

from alembic import op
import sqlalchemy as sa

revision = "20260423_01"
down_revision = "20260420_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Agrega columna hora_inicio (0-23, GMT-3) a app.config_servicios."""
    op.add_column(
        "config_servicios",
        sa.Column(
            "hora_inicio",
            sa.SmallInteger(),
            nullable=True,
            comment="Hora del día (0-23) en GMT-3 en que se ancla el primer ciclo; NULL = arrancar de inmediato",
        ),
        schema="app",
    )


def downgrade() -> None:
    """Elimina columna hora_inicio de app.config_servicios."""
    op.drop_column("config_servicios", "hora_inicio", schema="app")
