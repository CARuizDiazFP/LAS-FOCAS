# Nombre de archivo: 20260113_01_puntos_terminales.py
# Ubicación de archivo: db/alembic/versions/20260113_01_puntos_terminales.py
# Descripción: Agregar puntos terminales, alias_ids a servicios, es_transito a empalmes, cantidad_pelos a rutas

"""Agregar puntos terminales y campos de tránsito

Revision ID: 20260113_01
Revises: 20260112_02
Create Date: 2026-01-13

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY


# revision identifiers, used by Alembic.
revision = '20260113_01'
down_revision = '20260112_02'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Agregar nuevas columnas y tabla puntos_terminales."""
    
    # 1. Crear enum para tipo de punto terminal (idempotente)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE punto_terminal_tipo AS ENUM ('A', 'B');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # 2. Agregar alias_ids a servicios (array de strings para IDs alternativos)
    op.add_column(
        'servicios',
        sa.Column('alias_ids', ARRAY(sa.String(64)), nullable=True),
        schema='app',
    )
    
    # 3. Agregar cantidad_pelos a rutas_servicio
    op.add_column(
        'rutas_servicio',
        sa.Column('cantidad_pelos', sa.Integer(), nullable=True),
        schema='app',
    )
    
    # 4. Agregar es_transito a empalmes
    op.add_column(
        'empalmes',
        sa.Column('es_transito', sa.Boolean(), nullable=False, server_default='false'),
        schema='app',
    )
    
    # 5. Crear tabla puntos_terminales (usando SQL puro para evitar que SQLAlchemy intente crear el enum)
    op.execute("""
        CREATE TABLE IF NOT EXISTS app.puntos_terminales (
            id SERIAL PRIMARY KEY,
            ruta_id INTEGER NOT NULL REFERENCES app.rutas_servicio(id) ON DELETE CASCADE,
            tipo punto_terminal_tipo NOT NULL,
            sitio_descripcion VARCHAR(255),
            identificador_fisico VARCHAR(255),
            pelo_conector VARCHAR(64),
            CONSTRAINT uq_punto_terminal_ruta_tipo UNIQUE (ruta_id, tipo)
        )
    """)
    
    # 6. Crear índice en ruta_id para puntos_terminales
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_app_puntos_terminales_ruta_id 
        ON app.puntos_terminales (ruta_id)
    """)


def downgrade() -> None:
    """Eliminar cambios de puntos terminales."""
    
    # Eliminar índice
    op.execute("DROP INDEX IF EXISTS app.ix_app_puntos_terminales_ruta_id")
    
    # Eliminar tabla puntos_terminales
    op.execute("DROP TABLE IF EXISTS app.puntos_terminales")
    
    # Eliminar columna es_transito de empalmes
    op.drop_column('empalmes', 'es_transito', schema='app')
    
    # Eliminar columna cantidad_pelos de rutas_servicio
    op.drop_column('rutas_servicio', 'cantidad_pelos', schema='app')
    
    # Eliminar columna alias_ids de servicios
    op.drop_column('servicios', 'alias_ids', schema='app')
    
    # Eliminar enum
    op.execute("DROP TYPE punto_terminal_tipo")
