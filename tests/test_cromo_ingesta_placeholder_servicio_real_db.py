# Nombre de archivo: test_cromo_ingesta_placeholder_servicio_real_db.py
# Ubicación de archivo: tests/test_cromo_ingesta_placeholder_servicio_real_db.py
# Descripción: Regresión contra Postgres real — _SQL_CREAR_PLACEHOLDER_SERVICIO debe insertar sin error de sintaxis (bug real 2026-09-07, catch-up de fase_servicios)

"""Bug real (2026-09-07, catch-up puntual de FASE 6 · SERVICIOS tras 944 pelos sin match): el INSERT
de `_SQL_CREAR_PLACEHOLDER_SERVICIO` (`core/services/cromo/ingesta.py`) usa
`:origen::app.servicio_origen_datos` — el cast `::tipo` pegado sin espacio al bind param rompe el
parser de binds de SQLAlchemy (no reconoce `:origen` como parámetro, lo manda literal al driver) y
Postgres/asyncpg responde `syntax error at or near ":"`. Mismo patrón ya documentado para psycopg3
sync (`docs/decisiones.md`, `:nombre::tipo` vs `:nombre ::tipo`), confirmado acá también bajo el
dialecto asyncpg async. Corrida real contra `lasfocasdev-postgres`: 199/944 pelos pendientes (todos
los que necesitaban CREAR un placeholder nuevo, no sólo resolver contra un Servicio ya existente)
fallaron con este error; los otros 745 (match directo, sin creación) resolvieron bien porque nunca
pasan por este INSERT.

Mismo motivo/guard que `test_cromo_ingesta_ambiguedad_servicio_real_db.py`: necesita Postgres real; un
mock nunca ejercita la compilación real del bind + cast contra el driver.
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

# Número sintético plausible (4-6 dígitos) fuera de lo que Cromo/SLA real puede asignar — nunca pisa
# datos reales de dev, mismo criterio que el resto de los tests real_db.
_NUMERO_PLACEHOLDER = "999911"


@pytest.fixture
def limpiar_placeholder():
    try:
        yield
    finally:
        with SessionLocal() as session:
            session.execute(
                text("DELETE FROM app.servicios WHERE servicio_id = :numero"),
                {"numero": _NUMERO_PLACEHOLDER},
            )
            session.commit()


@pytest.mark.asyncio
async def test_resolver_o_crear_servicio_crea_placeholder_sin_error_de_sintaxis(limpiar_placeholder):
    from core.services.cromo.ingesta import _resolver_o_crear_servicio

    async with AsyncSessionLocal() as sesion:
        servicio_id, fue_creado = await _resolver_o_crear_servicio(sesion, _NUMERO_PLACEHOLDER, {})
        await sesion.commit()

    assert fue_creado is True
    assert servicio_id is not None

    with SessionLocal() as session:
        fila = session.execute(
            text("SELECT origen_datos, estado_servicio FROM app.servicios WHERE id = :id"),
            {"id": servicio_id},
        ).first()
    assert fila is not None
    assert fila[0] == "INFERIDO_CROMO"
    assert fila[1] == "DESCONOCIDO"
