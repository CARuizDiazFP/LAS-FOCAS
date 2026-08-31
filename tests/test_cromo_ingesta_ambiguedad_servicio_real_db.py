# Nombre de archivo: test_cromo_ingesta_ambiguedad_servicio_real_db.py
# Ubicación de archivo: tests/test_cromo_ingesta_ambiguedad_servicio_real_db.py
# Descripción: Regresión contra Postgres real — _SQL_BUSCAR_SERVICIO debe resolver a la fila vigente, no a la fila superada, cuando dos filas de app.servicios matchean el mismo número

"""Bug real (2026-08-31, ticket duplicidad Buscador/ODFs), caso concreto en dev: servicio
"41140->61943" de Banco Comafi SA (fila vigente id=557, `alias_ids={61943}`) tenía una fila `MANUAL`
huérfana (id=49, `servicio_id='61943'` literal, creada por una subida de tracking físico anterior a
la renumeración SLA) — `_SQL_BUSCAR_SERVICIO` sin `ORDER BY` resolvía consistentemente contra la fila
49 para cualquier pelo con `servicio_numero='61943'`, dejando el match sin cliente/estado real. 642
pares de este tipo encontrados en dev, ~11.000 pelos ya afectados (remediados aparte con un script de
fusión uno-a-uno); este test cubre la prevención hacia adelante: nuevas ambigüedades del mismo tipo
deben resolver a la fila que absorbió el número como alias, no a la fila superada.

Mismo motivo/guard que `test_cromo_odf_inventario_real_db.py`: necesita Postgres real; un mock nunca
ejercita el `NOT EXISTS` de la query en sí.
"""

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

# Números sintéticos fuera de lo que Cromo/SLA real puede asignar, mismo criterio que el resto de los
# tests real_db — nunca pisan datos reales de dev.
_NUMERO_AMBIGUO = "9999801"
_NUMERO_ORIGEN_VIGENTE = "9999802"


@pytest.fixture
def servicios_en_conflicto():
    """Dos filas reales que matchean `_NUMERO_AMBIGUO` a la vez: la "superada" (su propio
    `servicio_id`/`numero_primer_servicio` es el número ambiguo, como la vieja fila MANUAL id=49 del
    caso real) y la "vigente" (absorbió ese número como alias tras una renumeración, como la fila SLA
    id=557 del caso real)."""
    with SessionLocal() as session:
        superada_id = int(
            session.execute(
                text(
                    "INSERT INTO app.servicios "
                    "(servicio_id, numero_primer_servicio, categoria, origen_datos, estado_servicio) "
                    "VALUES (:numero, :numero, 0, 'MANUAL', 'DESCONOCIDO') RETURNING id"
                ),
                {"numero": _NUMERO_AMBIGUO},
            ).scalar_one()
        )
        vigente_id = int(
            session.execute(
                text(
                    "INSERT INTO app.servicios "
                    "(servicio_id, numero_primer_servicio, alias_ids, nombre_cliente, categoria, "
                    " origen_datos, estado_servicio) "
                    "VALUES (:numero_origen, :numero_origen, ARRAY[:alias], 'Cliente Vigente Test', 6, "
                    " 'INGEST_EXCEL', 'Activo') RETURNING id"
                ),
                {"numero_origen": _NUMERO_ORIGEN_VIGENTE, "alias": _NUMERO_AMBIGUO},
            ).scalar_one()
        )
        session.commit()

    try:
        yield {"superada_id": superada_id, "vigente_id": vigente_id}
    finally:
        with SessionLocal() as session:
            session.execute(
                text("DELETE FROM app.servicios WHERE id = ANY(:ids)"),
                {"ids": [superada_id, vigente_id]},
            )
            session.commit()


@pytest.mark.asyncio
async def test_buscar_servicio_resuelve_a_la_fila_vigente_no_a_la_superada(servicios_en_conflicto):
    from core.services.cromo.ingesta import _SQL_BUSCAR_SERVICIO

    async with AsyncSessionLocal() as sesion:
        fila = (await sesion.execute(_SQL_BUSCAR_SERVICIO, {"numero": _NUMERO_AMBIGUO})).first()

    assert fila is not None
    assert fila[0] == servicios_en_conflicto["vigente_id"]
    assert fila[0] != servicios_en_conflicto["superada_id"]


@pytest.mark.asyncio
async def test_resolver_o_crear_servicio_resuelve_a_la_fila_vigente(servicios_en_conflicto):
    from core.services.cromo.ingesta import _resolver_o_crear_servicio

    async with AsyncSessionLocal() as sesion:
        servicio_id, fue_creado = await _resolver_o_crear_servicio(sesion, _NUMERO_AMBIGUO, {})

    assert fue_creado is False
    assert servicio_id == servicios_en_conflicto["vigente_id"]


@pytest.mark.asyncio
async def test_buscar_servicio_sin_ambiguedad_sigue_matcheando_directo():
    """Caso sin conflicto (ninguna fila absorbió el número como alias de otra): debe seguir
    resolviendo con normalidad, sin que el `NOT EXISTS` nuevo excluya de más."""
    from core.services.cromo.ingesta import _SQL_BUSCAR_SERVICIO

    numero = "9999803"
    with SessionLocal() as session:
        servicio_id = int(
            session.execute(
                text(
                    "INSERT INTO app.servicios "
                    "(servicio_id, numero_primer_servicio, categoria, origen_datos, estado_servicio) "
                    "VALUES (:numero, :numero, 0, 'INFERIDO_CROMO', 'DESCONOCIDO') RETURNING id"
                ),
                {"numero": numero},
            ).scalar_one()
        )
        session.commit()

    try:
        async with AsyncSessionLocal() as sesion:
            fila = (await sesion.execute(_SQL_BUSCAR_SERVICIO, {"numero": numero})).first()
        assert fila is not None
        assert fila[0] == servicio_id
    finally:
        with SessionLocal() as session:
            session.execute(text("DELETE FROM app.servicios WHERE id = :id"), {"id": servicio_id})
            session.commit()
