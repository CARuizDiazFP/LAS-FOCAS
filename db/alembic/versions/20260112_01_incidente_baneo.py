# Nombre de archivo: 20260112_01_incidente_baneo.py
# Ubicación de archivo: db/alembic/versions/20260112_01_incidente_baneo.py
# Descripción: Migración para crear tabla incidentes_baneo (Protocolo de Protección)

"""Crear tabla incidentes_baneo para Protocolo de Protección

Revision ID: 20260112_01
Revises: 20260110_01
Create Date: 2026-01-12

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260112_01'
down_revision = '20260110_01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Crear tabla incidentes_baneo para el Protocolo de Protección."""
    
    # Crear tabla incidentes_baneo
    op.create_table(
        'incidentes_baneo',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('ticket_asociado', sa.String(64), nullable=True, index=True),
        sa.Column('servicio_afectado_id', sa.String(64), nullable=False, index=True),
        sa.Column('servicio_protegido_id', sa.String(64), nullable=False, index=True),
        sa.Column('ruta_protegida_id', sa.Integer(), 
                  sa.ForeignKey('app.rutas_servicio.id', ondelete='SET NULL'), 
                  nullable=True, index=True),
        sa.Column('usuario_ejecutor', sa.String(128), nullable=True),
        sa.Column('motivo', sa.String(512), nullable=True),
        sa.Column('fecha_inicio', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('fecha_fin', sa.DateTime(timezone=True), nullable=True),
        sa.Column('activo', sa.Boolean(), nullable=False, default=True, index=True),
        schema='app',
    )
    
    # Crear índice compuesto para búsquedas frecuentes
    op.create_index(
        'ix_incidentes_baneo_servicio_activo',
        'incidentes_baneo',
        ['servicio_protegido_id', 'activo'],
        schema='app',
    )


def downgrade() -> None:
    """Eliminar tabla incidentes_baneo."""
    
    # Eliminar índice compuesto
    op.drop_index(
        'ix_incidentes_baneo_servicio_activo',
        table_name='incidentes_baneo',
        schema='app',
    )
    
    # Eliminar tabla
    op.drop_table('incidentes_baneo', schema='app')
