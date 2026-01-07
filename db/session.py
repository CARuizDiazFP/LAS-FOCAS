# Nombre de archivo: session.py
# Ubicación de archivo: db/session.py
# Descripción: Configuración de engine y sesión SQLAlchemy compartida para servicios internos

from __future__ import annotations

from os import getenv

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _engine_url() -> str:
    return getenv(
        "ALEMBIC_URL",
        getenv(
            "DATABASE_URL",
            f"postgresql+psycopg://{getenv('POSTGRES_USER', 'lasfocas')}:{getenv('POSTGRES_PASSWORD', 'superseguro')}@{getenv('POSTGRES_HOST', 'postgres')}:{getenv('POSTGRES_PORT', '5432')}/{getenv('POSTGRES_DB', 'lasfocas')}",
        ),
    )


engine = create_engine(_engine_url(), pool_pre_ping=True, pool_recycle=1800)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)