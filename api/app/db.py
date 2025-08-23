# Nombre de archivo: db.py
# Ubicación de archivo: api/app/db.py
# Descripción: Conexión básica a PostgreSQL usando SQLAlchemy + Psycopg 3
from os import getenv
import logging
from sqlalchemy import create_engine, text
from core import get_secret


logger = logging.getLogger(__name__)

DB_HOST = getenv("POSTGRES_HOST", "postgres")
DB_PORT = getenv("POSTGRES_PORT", "5432")
DB_NAME = getenv("POSTGRES_DB", "lasfocas")
DB_USER = getenv("POSTGRES_USER", "lasfocas")
DB_PASS = get_secret("POSTGRES_PASSWORD", "cambiar-este-password")

DSN = f"postgresql+psycopg://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_engine(DSN, pool_pre_ping=True, pool_recycle=1800)

def db_health() -> dict:
    """Realiza un SELECT 1 y devuelve info básica."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            server_version = conn.exec_driver_sql("SHOW server_version").scalar()
    except Exception as exc:  # noqa: BLE001
        logger.warning("db_health_fallo", extra={"error": str(exc)})
        return {"db": "error", "detail": str(exc)}
    return {"db": "ok", "server_version": server_version}

