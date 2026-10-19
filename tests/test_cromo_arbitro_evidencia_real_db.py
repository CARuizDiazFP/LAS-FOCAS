# Nombre de archivo: test_cromo_arbitro_evidencia_real_db.py
# Ubicación de archivo: tests/test_cromo_arbitro_evidencia_real_db.py
# Descripción: Tests contra Postgres real del upsert de evidencia de caminos del árbitro de Cromo

"""Corren dentro de una transacción que se revierte; si la tabla no existe todavía, el fixture aplica
`upgrade()` de la migración 20261020_01 dentro de esa misma transacción."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from core.services.cromo.arbitro.evidencia import EvidenciaEntrada, registrar_evidencia
from core.services.cromo.tracking_service import ExtremoCamino, ResumenCamino
from db.session import async_engine
from tests.soporte_postgres_real import requiere_postgres_real
from tests.test_cromo_arbitro_migracion_real_db import _correr, _servicio

pytestmark = requiere_postgres_real

_PELO = 999_920_101


@pytest_asyncio.fixture
async def entorno():
    engine = create_async_engine(
        async_engine.url.render_as_string(hide_password=False), poolclass=NullPool
    )
    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
            existe = (await conn.execute(text("SELECT to_regclass('app.cromo_propuesta')"))).scalar()
            if existe is None:
                await conn.run_sync(_correr, "upgrade")
            sesion = AsyncSession(
                bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
            )
            yield sesion, conn
            await sesion.close()
        finally:
            await trans.rollback()
    await engine.dispose()


def _entrada(odf_id: int) -> EvidenciaEntrada:
    fin = ExtremoCamino(
        tipo="CONECTOR_ODF", id_cromo=odf_id + 1, clase=136, odf_id=odf_id, servicio_at62="99992001",
        pelo_conectado=_PELO,
    )
    resumen = ResumenCamino(inicio=ExtremoCamino(tipo="PELO", id_cromo=_PELO, clase=130), fin=fin)
    return EvidenciaEntrada(_PELO, resumen, frozenset({_PELO, _PELO + 1}))


@pytest.mark.asyncio
async def test_registrar_evidencia_upsert_pisa_lo_viejo(entorno):
    sesion, conn = entorno
    sid = await _servicio(conn)
    assert await registrar_evidencia(sesion, sid, [_entrada(111)], completo=False, fuente="WEB") == 1
    assert await registrar_evidencia(sesion, sid, [_entrada(222)], completo=True, fuente="SLACK") == 1
    filas = (
        await conn.execute(
            text(
                "SELECT completo, extremos, pelos_camino, fuente FROM app.cromo_evidencia_camino "
                "WHERE servicio_id = :s"
            ),
            {"s": sid},
        )
    ).all()
    assert len(filas) == 1
    completo, extremos, pelos, fuente = filas[0]
    assert completo is True and fuente == "SLACK"
    assert extremos[1]["odf_id"] == 222 and extremos[1]["pelo_conectado"] == _PELO
    assert sorted(pelos) == [_PELO, _PELO + 1]


@pytest.mark.asyncio
async def test_registrar_evidencia_error_no_lanza(entorno):
    sesion, conn = entorno
    escritas = await registrar_evidencia(
        sesion, 2_000_000_000, [_entrada(1)], completo=True, fuente="WEB"
    )
    assert escritas == 0
    assert (await sesion.execute(text("SELECT 1"))).scalar_one() == 1
