# Nombre de archivo: db.py
# Ubicación de archivo: api/app/db.py
# Descripción: Conexión básica a PostgreSQL usando SQLAlchemy + Psycopg 3
from os import getenv
from sqlalchemy import create_engine, text
import logging

logger = logging.getLogger(__name__)

DB_HOST = getenv("POSTGRES_HOST", "postgres")
DB_PORT = getenv("POSTGRES_PORT", "5432")
DB_NAME = getenv("POSTGRES_DB", "lasfocas")
DB_USER = getenv("POSTGRES_USER", "lasfocas")
DB_PASS = getenv("POSTGRES_PASSWORD", "cambiar-este-password")

DSN = f"postgresql+psycopg://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_engine(DSN, pool_pre_ping=True, pool_recycle=1800)


def db_health() -> dict:
    """Realiza un SELECT 1 y devuelve info básica."""
    logger.debug("Ejecutando verificación de salud de la base de datos")
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        server_version = conn.exec_driver_sql("SHOW server_version").scalar()
    logger.debug("Verificación completada con versión %s", server_version)
    return {"db": "ok", "server_version": server_version}
