# Nombre de archivo: 20260929_01_api_clients.py
# Ubicación de archivo: db/alembic/versions/20260929_01_api_clients.py
# Descripción: Tabla app.api_clients para OAuth2 client_credentials (M2M) de la API v1

"""Tabla api_clients (OAuth2 client_credentials)

Revision ID: 20260929_01
Revises: 20260928_01
Create Date: 2026-09-29

Otras áreas de Metrotel consultan la API por sistema (`GET /api/v1/servicios/{id}/botellas`). La
API key compartida (`api_key_v1`) no sirve para eso: es una sola, la usa la web internamente, y no
permite identificar ni revocar a un área sin cortar a todas. Esta tabla guarda un cliente por área:

- ``client_id`` único e indexado (lookup del token endpoint).
- ``client_secret_hash``: hash SHA-256 + bcrypt de ``core/password.py``; el secreto en claro nunca
  toca la base.
- ``scopes``: ``VARCHAR(64)[]`` con default ``'{}'`` (un cliente sin scopes no puede hacer nada).
- ``activo``: se consulta en cada request, no sólo al emitir el token (JWT de 7 días + revocación
  inmediata).
- ``ultimo_uso_at``: auditoría de qué integraciones siguen vivas.

Tabla nueva sin datos previos: el ``downgrade()`` la elimina sin pérdida de información existente
(sólo se pierden los clientes dados de alta después de aplicarla).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260929_01"
down_revision = "20260928_01"
branch_labels = None
depends_on = None

_TABLA = "api_clients"
_SCHEMA = "app"


def upgrade() -> None:
    op.create_table(
        _TABLA,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("client_secret_hash", sa.String(length=255), nullable=False),
        sa.Column("nombre_area", sa.String(length=128), nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "scopes",
            postgresql.ARRAY(sa.String(length=64)),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("ultimo_uso_at", sa.DateTime(timezone=True), nullable=True),
        schema=_SCHEMA,
    )
    op.create_index("ix_api_clients_client_id", _TABLA, ["client_id"], unique=True, schema=_SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_api_clients_client_id", table_name=_TABLA, schema=_SCHEMA)
    op.drop_table(_TABLA, schema=_SCHEMA)
