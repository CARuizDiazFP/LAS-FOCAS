# Nombre de archivo: 20260427_01_unaccent_extension.py
# Ubicación de archivo: db/alembic/versions/20260427_01_unaccent_extension.py
# Descripción: Instala la extensión unaccent de PostgreSQL requerida por las búsquedas de cámaras

"""Instalar extensión unaccent en PostgreSQL

Revision ID: 20260427_01
Revises: 20260423_01
Create Date: 2026-04-27

La extensión 'unaccent' es requerida por `camara_search._buscar_ilike` y
`_buscar_tokens` para normalizar acentos en consultas ILIKE sobre nombres de
cámaras.  Sin ella el worker lanza `UndefinedFunction: function unaccent(text)
does not exist`.
"""

from __future__ import annotations

from alembic import op


revision = "20260427_01"
down_revision = "20260423_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Instala la extensión unaccent (idempotente)."""
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")


def downgrade() -> None:
    """Elimina la extensión unaccent.

    ADVERTENCIA: solo ejecutar si ningún otro objeto depende de unaccent.
    """
    op.execute("DROP EXTENSION IF EXISTS unaccent;")
