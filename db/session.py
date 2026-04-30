# Nombre de archivo: session.py
# Ubicación de archivo: db/session.py
# Descripción: Configuración de engines (síncrono y asíncrono) y sesiones SQLAlchemy compartidas

from __future__ import annotations

from os import getenv
from typing import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker


def _engine_url() -> str:
    return getenv(
        "ALEMBIC_URL",
        getenv(
            "DATABASE_URL",
            f"postgresql+psycopg://{getenv('POSTGRES_USER', 'lasfocas')}:{getenv('POSTGRES_PASSWORD', 'superseguro')}@{getenv('POSTGRES_HOST', 'postgres')}:{getenv('POSTGRES_PORT', '5432')}/{getenv('POSTGRES_DB', 'lasfocas')}",
        ),
    )


def _async_engine_url() -> str:
    """Deriva la URL para asyncpg reemplazando el prefijo del driver automáticamente.

    Soporta los prefijos postgresql+psycopg://, postgresql+psycopg2://, postgresql://.
    La variable DATABASE_URL (o ALEMBIC_URL) puede seguir usando el prefijo síncrono;
    este método construye la variante asyncpg sin requerir una variable separada.
    """
    url = _engine_url()
    for prefijo_sync in (
        "postgresql+psycopg://",
        "postgresql+psycopg2://",
        "postgresql://",
    ):
        if url.startswith(prefijo_sync):
            return "postgresql+asyncpg://" + url[len(prefijo_sync):]
    return url  # ya tiene prefijo asyncpg u otro driver


# ── Motor síncrono (usado por workers, Alembic y servicios no-async) ──────────
engine = create_engine(_engine_url(), pool_pre_ping=True, pool_recycle=1800)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# ── Motor asíncrono (usado por la API FastAPI) ────────────────────────────────
async_engine = create_async_engine(
    _async_engine_url(),
    pool_pre_ping=True,
    pool_recycle=1800,
)
AsyncSessionLocal = async_sessionmaker(
    async_engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependencia FastAPI: inyecta una AsyncSession por request."""
    async with AsyncSessionLocal() as session:
        yield session