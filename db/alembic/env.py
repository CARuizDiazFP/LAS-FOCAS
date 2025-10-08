# Nombre de archivo: env.py
# Ubicación de archivo: db/alembic/env.py
# Descripción: Script de arranque para ejecutar migraciones Alembic en LAS-FOCAS

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

section = config.get_section(config.config_ini_section)
if section is None:
    section = {}
url_override = os.getenv("DATABASE_URL")
if url_override:
    section["sqlalchemy.url"] = url_override
elif "sqlalchemy.url" not in section:
    section["sqlalchemy.url"] = os.getenv(
        "ALEMBIC_URL",
        "postgresql+psycopg://lasfocas:superseguro@postgres:5432/lasfocas",
    )

config.set_section_option(config.config_ini_section, "sqlalchemy.url", section["sqlalchemy.url"])

target_metadata = None


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
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
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
