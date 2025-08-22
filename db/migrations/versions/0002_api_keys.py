# Nombre de archivo: 0002_api_keys.py
# Ubicación de archivo: db/migrations/versions/0002_api_keys.py
# Descripción: Crea la tabla api_keys para gestión de claves de API
"""tabla api_keys

Revision ID: 0002
Revises: 0001
Create Date: 2025-08-22 19:10:47.732795

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Crear tabla api_keys."""
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("api_key", sa.Text, nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.text("NOW()"),
        ),
        schema="app",
    )


def downgrade() -> None:
    """Eliminar tabla api_keys."""
    op.drop_table("api_keys", schema="app")
