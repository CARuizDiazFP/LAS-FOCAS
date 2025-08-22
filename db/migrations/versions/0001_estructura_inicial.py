# Nombre de archivo: 0001_estructura_inicial.py
# Ubicación de archivo: db/migrations/versions/0001_estructura_inicial.py
# Descripción: Migración inicial que aplica el esquema base

"""estructura inicial

Revision ID: 0001
Revises:
Create Date: 2025-08-22 19:10:47.732795

"""
from typing import Sequence, Union
from alembic import op
import pathlib

# Identificadores de revisión de Alembic
revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Crear esquema inicial desde db/init.sql."""
    sql_path = pathlib.Path(__file__).resolve().parents[2] / "db" / "init.sql"
    with open(sql_path, "r", encoding="utf-8") as sql_file:
        op.execute(sql_file.read())


def downgrade() -> None:
    """Eliminar esquema y usuario creados en la migración."""
    op.execute("DROP SCHEMA IF EXISTS app CASCADE;")
    op.execute("DROP USER IF EXISTS lasfocas_readonly;")
