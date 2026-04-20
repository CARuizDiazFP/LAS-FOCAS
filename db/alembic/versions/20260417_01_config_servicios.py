# Nombre de archivo: 20260417_01_config_servicios.py
# Ubicación de archivo: db/alembic/versions/20260417_01_config_servicios.py
# Descripción: Crea tabla config_servicios para configuración de workers automatizados

"""Crear tabla config_servicios

Revision ID: 20260417_01
Revises: 20260127_01
Create Date: 2026-04-17

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260417_01"
down_revision = "20260127_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Crear tabla app.config_servicios con fila por defecto para slack_baneo_notifier."""
    op.create_table(
        "config_servicios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "nombre_servicio",
            sa.String(length=128),
            nullable=False,
            unique=True,
            index=True,
            comment="Identificador único del servicio",
        ),
        sa.Column(
            "intervalo_horas",
            sa.Integer(),
            nullable=False,
            server_default="4",
            comment="Intervalo de ejecución en horas",
        ),
        sa.Column(
            "slack_channels",
            sa.String(length=512),
            nullable=False,
            server_default="",
            comment="Canales Slack separados por coma",
        ),
        sa.Column(
            "ultima_ejecucion",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp de la última ejecución exitosa",
        ),
        sa.Column(
            "activo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="Si el servicio está habilitado",
        ),
        sa.Column(
            "ultimo_error",
            sa.Text(),
            nullable=True,
            comment="Último error registrado",
        ),
        schema="app",
    )

    # Insertar configuración por defecto para el notificador de baneos
    op.execute(
        "INSERT INTO app.config_servicios (nombre_servicio, intervalo_horas, slack_channels, activo) "
        "VALUES ('slack_baneo_notifier', 4, '#baneo-de-camaras-prueba,#ingresos_nodos_camaras', true)"
    )


def downgrade() -> None:
    """Eliminar tabla app.config_servicios."""
    op.drop_table("config_servicios", schema="app")
