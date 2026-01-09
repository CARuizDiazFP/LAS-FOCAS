# Nombre de archivo: 20260108_01_infra_updates.py
# Ubicación de archivo: db/alembic/versions/20260108_01_infra_updates.py
# Descripción: Actualiza tablas de infraestructura: nuevo estado DETECTADA, enum origen_datos, campos servicio_id
"""
Migración: Actualización de tablas de infraestructura

- Agrega valor DETECTADA al enum camara_estado
- Crea nuevo enum camara_origen_datos (MANUAL, TRACKING, SHEET)
- Agrega columna origen_datos a camaras
- Modifica fontine_id a nullable en camaras
- Amplía columna nombre en camaras a 255 chars
- Agrega columna servicio_id a servicios (unique, indexed)
- Agrega columna nombre_archivo_origen a servicios
- Quita constraint unique de tracking_empalme_id en empalmes (puede repetirse entre servicios)

Revision ID: 20260108_01
Revises: 20251230_01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260108_01"
down_revision = "20251230_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Agregar valor DETECTADA al enum camara_estado
    # ALTER TYPE no soporta IF NOT EXISTS, así que verificamos primero
    bind.execute(sa.text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_enum
                WHERE enumlabel = 'DETECTADA'
                AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'camara_estado')
            ) THEN
                ALTER TYPE app.camara_estado ADD VALUE 'DETECTADA';
            END IF;
        END
        $$;
    """))

    # 2. Crear enum camara_origen_datos
    camara_origen_enum = postgresql.ENUM(
        "MANUAL",
        "TRACKING",
        "SHEET",
        name="camara_origen_datos",
        schema="app",
        create_type=False,
    )
    camara_origen_enum.create(bind, checkfirst=True)

    # 3. Agregar columna origen_datos a camaras
    op.add_column(
        "camaras",
        sa.Column(
            "origen_datos",
            postgresql.ENUM("MANUAL", "TRACKING", "SHEET", name="camara_origen_datos", schema="app", create_type=False),
            nullable=False,
            server_default="MANUAL",
        ),
        schema="app",
    )

    # 4. Modificar fontine_id a nullable (para cámaras detectadas sin ID Fontine)
    op.alter_column(
        "camaras",
        "fontine_id",
        existing_type=sa.String(length=64),
        nullable=True,
        schema="app",
    )

    # 5. Ampliar columna nombre de camaras a 255 caracteres
    op.alter_column(
        "camaras",
        "nombre",
        existing_type=sa.String(length=128),
        type_=sa.String(length=255),
        existing_nullable=True,
        nullable=False,  # nombre ahora es requerido
        schema="app",
    )

    # 6. Crear índice en nombre de camaras
    op.create_index("ix_camaras_nombre", "camaras", ["nombre"], schema="app")

    # 7. Agregar columna servicio_id a servicios
    op.add_column(
        "servicios",
        sa.Column("servicio_id", sa.String(length=64), nullable=True),
        schema="app",
    )

    # Actualizar registros existentes con un valor por defecto basado en ID
    bind.execute(sa.text("""
        UPDATE app.servicios
        SET servicio_id = CONCAT('legacy-', id::text)
        WHERE servicio_id IS NULL;
    """))

    # Ahora hacer la columna NOT NULL y agregar constraint unique + index
    op.alter_column(
        "servicios",
        "servicio_id",
        existing_type=sa.String(length=64),
        nullable=False,
        schema="app",
    )
    op.create_index("ix_servicios_servicio_id", "servicios", ["servicio_id"], schema="app", unique=True)

    # 8. Agregar columna nombre_archivo_origen a servicios
    op.add_column(
        "servicios",
        sa.Column("nombre_archivo_origen", sa.String(length=255), nullable=True),
        schema="app",
    )

    # 9. Quitar constraint unique de tracking_empalme_id en empalmes
    # El mismo tracking_empalme_id puede existir en múltiples servicios
    op.drop_index("ix_empalmes_tracking_empalme_id", table_name="empalmes", schema="app")
    op.drop_constraint("empalmes_tracking_empalme_id_key", "empalmes", schema="app", type_="unique")
    op.create_index("ix_empalmes_tracking_empalme_id", "empalmes", ["tracking_empalme_id"], schema="app", unique=False)


def downgrade() -> None:
    bind = op.get_bind()

    # 9. Restaurar constraint unique en tracking_empalme_id
    op.drop_index("ix_empalmes_tracking_empalme_id", table_name="empalmes", schema="app")
    # Eliminar duplicados antes de crear unique constraint
    bind.execute(sa.text("""
        DELETE FROM app.empalmes a
        USING app.empalmes b
        WHERE a.id > b.id AND a.tracking_empalme_id = b.tracking_empalme_id;
    """))
    op.create_index("ix_empalmes_tracking_empalme_id", "empalmes", ["tracking_empalme_id"], schema="app", unique=True)

    # 8. Quitar nombre_archivo_origen
    op.drop_column("servicios", "nombre_archivo_origen", schema="app")

    # 7. Quitar servicio_id
    op.drop_index("ix_servicios_servicio_id", table_name="servicios", schema="app")
    op.drop_column("servicios", "servicio_id", schema="app")

    # 6. Quitar índice de nombre
    op.drop_index("ix_camaras_nombre", table_name="camaras", schema="app")

    # 5. Restaurar tamaño de nombre
    op.alter_column(
        "camaras",
        "nombre",
        existing_type=sa.String(length=255),
        type_=sa.String(length=128),
        nullable=True,
        schema="app",
    )

    # 4. Restaurar fontine_id a NOT NULL (puede fallar si hay NULLs)
    bind.execute(sa.text("""
        UPDATE app.camaras
        SET fontine_id = CONCAT('migrated-', id::text)
        WHERE fontine_id IS NULL;
    """))
    op.alter_column(
        "camaras",
        "fontine_id",
        existing_type=sa.String(length=64),
        nullable=False,
        schema="app",
    )

    # 3. Quitar columna origen_datos
    op.drop_column("camaras", "origen_datos", schema="app")

    # 2. Eliminar enum camara_origen_datos
    camara_origen_enum = postgresql.ENUM(
        "MANUAL",
        "TRACKING",
        "SHEET",
        name="camara_origen_datos",
        schema="app",
        create_type=False,
    )
    camara_origen_enum.drop(bind, checkfirst=True)

    # 1. No se puede quitar valor de enum en PostgreSQL fácilmente
    # Se deja DETECTADA en el enum (operación no reversible sin recrear el tipo)
