# Nombre de archivo: env.py
# Ubicación de archivo: db/alembic/env.py
# Descripción: Script de arranque para ejecutar migraciones Alembic en LAS-FOCAS

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# `alembic -c db/alembic.ini` corre desde la raíz del repo; en el contenedor la raíz también es el cwd.
# Se agrega por las dudas para que `db.models` sea importable desde cualquier cwd.
_RAIZ = Path(__file__).resolve().parents[2]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from db.models.autogenerate import OPCIONES_COMPARACION, target_metadata  # noqa: E402


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

section = config.get_section(config.config_ini_section)
if section is None:
    section = {}

# Precedencia: DATABASE_URL > ALEMBIC_URL > valor del ini > default seguro
db_url = os.getenv("DATABASE_URL") or os.getenv("ALEMBIC_URL")
if db_url:
    section["sqlalchemy.url"] = db_url
elif "sqlalchemy.url" not in section:
    section["sqlalchemy.url"] = "postgresql+psycopg://lasfocas:cambiar_por_password_seguro@postgres:5432/lasfocas"

config.set_section_option(
    config.config_ini_section,
    "sqlalchemy.url",
    section["sqlalchemy.url"].replace("%", "%%"),
)

# Autogenerate encendido desde 2026-10-27 (P18): los modelos quedaron alineados con la base y el
# alcance (sólo `app`, sin las tablas que no se modelan) vive en db/models/autogenerate.py, que
# comparte con scripts/check_drift_modelos.py.


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        dialect_opts={"paramstyle": "named"},
        **OPCIONES_COMPARACION,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, **OPCIONES_COMPARACION)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
