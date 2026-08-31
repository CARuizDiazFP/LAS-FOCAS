# Nombre de archivo: test_cromo_odf_conectores_ingesta_real_db.py
# Ubicación de archivo: tests/test_cromo_odf_conectores_ingesta_real_db.py
# Descripción: Prueba de integración contra Postgres real — resolver_servicio_conectores necesita el driver real para el `= ANY(:pelo_n_ids)` sobre bigint[]

"""Este archivo es de integración: necesita un Postgres real con el esquema `app.*` poblado
(`cromo_pelos`, `cromo_odf_conectores`). Mismo motivo y mismo guard que
`test_cromo_odf_inventario_real_db.py`: el workflow de CI corre `pytest -q tests` sin un servicio
Postgres, así que acá fallaría por conexión, no por regresión.

El caso central que justifica este archivo: `resolver_servicio_conectores` arma
`WHERE n_id = ANY(:pelo_n_ids)` sobre una columna `bigint` real — un mock nunca ejercita el binding
real de un array de Python contra `bigint[]` vía asyncpg, ni el JOIN contra filas de `cromo_pelos`
ya ingeridas por otra fase."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from db.session import SessionLocal, async_engine

pytestmark = pytest.mark.skipif(
    os.getenv("CI") == "true",
    reason="requiere Postgres real alcanzable; el workflow de CI no tiene ese servicio configurado",
)

_engine_test = create_async_engine(async_engine.url.render_as_string(hide_password=False), poolclass=NullPool)
AsyncSessionLocal = async_sessionmaker(_engine_test, expire_on_commit=False)

# Rango sintético fuera de lo que Cromo real puede asignar, mismo criterio que el resto de los
# tests real_db — nunca pisa datos reales de dev.
_ODF_N_ID = 999_900_030
_CABLE_N_ID = 999_900_031
_TUBO_N_ID = 999_900_032
_PELO_N_ID = 999_900_033


@pytest.fixture
def pelo_con_servicio_numero():
    """Un pelo real (mínimo: cable/tubo sin fila propia, mismo criterio "sin FK dura" del resto de
    Cromo) con `servicio_numero` ya parseado por regex, para que
    `resolver_servicio_conectores` lo encuentre vía JOIN real."""
    with SessionLocal() as session:
        session.execute(
            text(
                "INSERT INTO app.cromo_pelos (n_id, tubo_n_id, cable_n_id, servicio_numero) "
                "VALUES (:pelo, :tubo, :cable, '61943')"
            ),
            {"pelo": _PELO_N_ID, "tubo": _TUBO_N_ID, "cable": _CABLE_N_ID},
        )
        session.commit()

    try:
        yield {"pelo_n_id": _PELO_N_ID}
    finally:
        with SessionLocal() as session:
            session.execute(text("DELETE FROM app.cromo_pelos WHERE n_id = :pelo"), {"pelo": _PELO_N_ID})
            session.commit()


@pytest.mark.asyncio
async def test_resolver_servicio_conectores_join_real_contra_cromo_pelos(pelo_con_servicio_numero):
    from core.services.cromo.ingesta import resolver_servicio_conectores
    from core.services.cromo.modelos import ConectorOdf

    conector = ConectorOdf(
        n_id=1,
        odf_n_id=_ODF_N_ID,
        bandeja_n_id=None,
        bandeja_nombre=None,
        bandeja_modelo=None,
        numero_conector="15",
        pelo_n_id=_PELO_N_ID,
        servicio_numero_atributo="41140",
    )

    async with AsyncSessionLocal() as sesion:
        await resolver_servicio_conectores(sesion, [conector])

    assert conector.servicio_resuelto == "61943"
    assert conector.servicio_id_historico == "41140"


@pytest.mark.asyncio
async def test_resolver_servicio_conectores_pelo_inexistente_no_revienta():
    from core.services.cromo.ingesta import resolver_servicio_conectores
    from core.services.cromo.modelos import ConectorOdf

    conector = ConectorOdf(
        n_id=1,
        odf_n_id=_ODF_N_ID,
        bandeja_n_id=None,
        bandeja_nombre=None,
        bandeja_modelo=None,
        numero_conector="99",
        pelo_n_id=-999,
        servicio_numero_atributo="12345",
    )

    async with AsyncSessionLocal() as sesion:
        await resolver_servicio_conectores(sesion, [conector])

    assert conector.servicio_resuelto == "12345"
    assert conector.servicio_id_historico is None
