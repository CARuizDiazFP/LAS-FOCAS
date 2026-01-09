# Nombre de archivo: 20260110_01_ruta_servicio.py
# Ubicación de archivo: db/alembic/versions/20260110_01_ruta_servicio.py
# Descripción: Crea tabla rutas_servicio y asociativa ruta_empalme para versionado de rutas
"""
Migración: Versionado de rutas de servicio

- Crea enum ruta_tipo (PRINCIPAL, BACKUP, ALTERNATIVA)
- Crea tabla rutas_servicio para versionar caminos de FO
- Crea tabla asociativa ruta_empalme_association con columna orden
- Mantiene retrocompatibilidad con servicio_empalme_association

Revision ID: 20260110_01
Revises: 20260108_01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260110_01"
down_revision = "20260108_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Crear enum ruta_tipo
    bind.execute(sa.text("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'ruta_tipo' AND typnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'app')) THEN
                CREATE TYPE app.ruta_tipo AS ENUM ('PRINCIPAL', 'BACKUP', 'ALTERNATIVA');
            END IF;
        END
        $$;
    """))

    # 2. Crear tabla rutas_servicio
    op.create_table(
        "rutas_servicio",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "servicio_id",
            sa.Integer(),
            sa.ForeignKey("app.servicios.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("nombre", sa.String(255), nullable=False, server_default="Principal"),
        sa.Column(
            "tipo",
            postgresql.ENUM(
                "PRINCIPAL",
                "BACKUP",
                "ALTERNATIVA",
                name="ruta_tipo",
                schema="app",
                create_type=False,
            ),
            nullable=False,
            server_default="PRINCIPAL",
        ),
        sa.Column("hash_contenido", sa.String(64), nullable=True, comment="SHA256 del contenido del tracking"),
        sa.Column("activa", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("nombre_archivo_origen", sa.String(255), nullable=True),
        sa.Column("contenido_original", sa.Text(), nullable=True, comment="Contenido raw del tracking para debugging"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), onupdate=sa.text("now()")),
        schema="app",
    )

    # 3. Crear tabla asociativa ruta_empalme_association
    op.create_table(
        "ruta_empalme_association",
        sa.Column(
            "ruta_id",
            sa.Integer(),
            sa.ForeignKey("app.rutas_servicio.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "empalme_id",
            sa.Integer(),
            sa.ForeignKey("app.empalmes.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("orden", sa.Integer(), nullable=True, comment="Orden del empalme en la secuencia de la ruta"),
        schema="app",
    )

    # 4. Crear índice para búsqueda rápida por hash
    op.create_index(
        "ix_rutas_servicio_hash_contenido",
        "rutas_servicio",
        ["hash_contenido"],
        schema="app",
    )

    # 5. Crear índice compuesto para servicio + tipo + activa
    op.create_index(
        "ix_rutas_servicio_servicio_tipo_activa",
        "rutas_servicio",
        ["servicio_id", "tipo", "activa"],
        schema="app",
    )


def downgrade() -> None:
    # Eliminar índices
    op.drop_index(
        "ix_rutas_servicio_servicio_tipo_activa",
        table_name="rutas_servicio",
        schema="app",
    )
    op.drop_index(
        "ix_rutas_servicio_hash_contenido",
        table_name="rutas_servicio",
        schema="app",
    )

    # Eliminar tablas
    op.drop_table("ruta_empalme_association", schema="app")
    op.drop_table("rutas_servicio", schema="app")

    # Eliminar enum
    bind = op.get_bind()
    bind.execute(sa.text("DROP TYPE IF EXISTS app.ruta_tipo;"))
