# Nombre de archivo: 20260112_02_raw_file_content.py
# Ubicación de archivo: db/alembic/versions/20260112_02_raw_file_content.py
# Descripción: Agrega columna raw_file_content a rutas_servicio para guardar TXT original

"""Agregar raw_file_content a rutas_servicio

Revision ID: 20260112_02
Revises: 20260112_01
Create Date: 2026-01-12

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260112_02'
down_revision = '20260112_01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Agregar columna raw_file_content para guardar el TXT original."""
    
    # Agregar columna raw_file_content
    op.add_column(
        'rutas_servicio',
        sa.Column('raw_file_content', sa.Text(), nullable=True),
        schema='app',
    )


def downgrade() -> None:
    """Eliminar columna raw_file_content."""
    op.drop_column('rutas_servicio', 'raw_file_content', schema='app')
