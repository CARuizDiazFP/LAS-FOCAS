# Nombre de archivo: test_cromo_tracking_cache_real_db.py
# Ubicación de archivo: tests/test_cromo_tracking_cache_real_db.py
# Descripción: Prueba contra Postgres real del upsert del caché de trackings: guardar sin servicio conserva la atribución de la fila

"""`servicio_traza._SQL_TRACKINGS_DEL_SERVICIO` arma la traza de un Servicio (que expone la API v1)
con las filas del caché cuyo `servicio_id` es el del Servicio. Un `track odf` o una posición no
declarada cachean el pelo con `servicio_id=None`; sin el `COALESCE` del upsert esa fila salía de la
traza del 93150 (su camino vigente va por pelos con etiqueta 44649).

Corre en una transacción revertida, con un `pelo_n_id` negativo que no existe, y con `ahora` en el
año 2000: la purga de vencidos de `guardar` borra lo anterior a 1999, o sea nada.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from core.services.cromo import tracking_cache
from db.session import async_engine
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real

_PELO_FALSO = -910_000_001
_SERVICIO_93150 = 4
_HACE_MUCHO = datetime(2000, 1, 1, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def sesion():
    engine = create_async_engine(
        async_engine.url.render_as_string(hide_password=False), poolclass=NullPool
    )
    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
            yield AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
        finally:
            await trans.rollback()
    await engine.dispose()


async def _servicio_de_la_fila(sesion) -> object:
    return (
        await sesion.execute(
            text("SELECT servicio_id FROM app.cromo_tracking_cache WHERE pelo_n_id = :p"),
            {"p": _PELO_FALSO},
        )
    ).scalar_one()


async def _guardar(sesion, servicio_id, contenido):
    await tracking_cache.guardar(
        sesion,
        pelo_n_id=_PELO_FALSO,
        servicio_id=servicio_id,
        nombre_archivo="93150 CROMO.txt",
        contenido=contenido,
        ahora=_HACE_MUCHO,
    )


@pytest.mark.asyncio
async def test_guardar_con_servicio_none_no_borra_la_atribucion(sesion):
    await _guardar(sesion, _SERVICIO_93150, "v1")
    await _guardar(sesion, None, "v2")

    assert await _servicio_de_la_fila(sesion) == _SERVICIO_93150
    contenido = (
        await sesion.execute(
            text("SELECT contenido FROM app.cromo_tracking_cache WHERE pelo_n_id = :p"),
            {"p": _PELO_FALSO},
        )
    ).scalar_one()
    assert contenido == "v2"


@pytest.mark.asyncio
async def test_guardar_con_otro_servicio_si_lo_pisa(sesion):
    await _guardar(sesion, None, "v1")
    assert await _servicio_de_la_fila(sesion) is None
    await _guardar(sesion, _SERVICIO_93150, "v2")
    assert await _servicio_de_la_fila(sesion) == _SERVICIO_93150
