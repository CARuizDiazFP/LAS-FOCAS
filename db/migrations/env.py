# Nombre de archivo: env.py
# Ubicación de archivo: db/migrations/env.py
# Descripción: Configuración del contexto de migraciones de Alembic

from logging.config import fileConfig
import os
from sqlalchemy import engine_from_config, pool
from alembic import context

# Objeto de configuración de Alembic
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Construir la URL de conexión desde variables de entorno
_db_user = os.getenv("POSTGRES_USER", "lasfocas")
_db_password = os.getenv("POSTGRES_PASSWORD", "lasfocas")
_db_host = os.getenv("POSTGRES_HOST", "localhost")
_db_port = os.getenv("POSTGRES_PORT", "5432")
_db_name = os.getenv("POSTGRES_DB", "lasfocas")

config.set_main_option(
    "sqlalchemy.url",
    f"postgresql+psycopg://{_db_user}:{_db_password}@{_db_host}:{_db_port}/{_db_name}",
)

# Metadatos objetivo para autogeneración
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
# Al no contar con modelos ORM se deja en None


# pylint: disable=unused-argument
# Alembic requiere estas funciones con firmas específicas

def run_migrations_offline() -> None:
    """Ejecutar migraciones en modo offline."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, literal_binds=True, dialect_opts={"paramstyle": "named"})

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Ejecutar migraciones en modo online."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
