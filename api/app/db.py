# Nombre de archivo: db.py
# Ubicación de archivo: api/app/db.py
# Descripción: Health check de la conexión a PostgreSQL usando el motor asíncrono (asyncpg)
import logging
from sqlalchemy import text

from db.session import async_engine

logger = logging.getLogger(__name__)


async def db_health() -> dict:
    """Realiza un SELECT 1 usando el engine asíncrono y devuelve info básica."""
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            server_version = (
                await conn.exec_driver_sql("SHOW server_version")
            ).scalar()
    except Exception as exc:  # noqa: BLE001
        logger.warning("db_health_fallo", extra={"error": str(exc)})
        return {"db": "error", "detail": str(exc)}
    return {"db": "ok", "server_version": server_version}

