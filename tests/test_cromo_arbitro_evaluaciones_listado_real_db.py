# Nombre de archivo: test_cromo_arbitro_evaluaciones_listado_real_db.py
# Ubicación de archivo: tests/test_cromo_arbitro_evaluaciones_listado_real_db.py
# Descripción: Tests contra Postgres real de listar_evaluaciones y del alta del análisis retroactivo (vigencia de 6 h), en transacción revertida

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from core.services.cromo.arbitro import evaluaciones
from db.session import async_engine
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real


@pytest_asyncio.fixture
async def sesion():
    engine = create_async_engine(
        async_engine.url.render_as_string(hide_password=False), poolclass=NullPool
    )
    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
            s = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
            # Aísla el test de filas reales de la DB dev: todo dentro de la transacción revertida.
            await s.execute(text("DELETE FROM app.cromo_arbitro_evaluacion"))
            yield s
            await s.close()
        finally:
            await trans.rollback()
    await engine.dispose()


async def _insertar(sesion, estado: str, horas: int, disparo: str = "NORMALIZADOR") -> int:
    return (
        await sesion.execute(
            text(
                "INSERT INTO app.cromo_arbitro_evaluacion (disparo, alcance, estado, encolada_en) "
                "VALUES (:d, CAST('{\"tipo\":\"TODO\"}' AS jsonb), :e, now() - make_interval(hours => :h)) "
                "RETURNING id"
            ),
            {"d": disparo, "e": estado, "h": horas},
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_en_curso_ignora_viejas_y_terminadas(sesion):
    vieja = await _insertar(sesion, "EN_CURSO", 7)
    await _insertar(sesion, "OK", 0)
    r = await evaluaciones.listar_evaluaciones(sesion, 10)
    assert r["en_curso"] is None
    assert vieja in [i["id"] for i in r["items"]]

    reciente = await _insertar(sesion, "EN_COLA", 5)
    r = await evaluaciones.listar_evaluaciones(sesion, 10)
    assert r["en_curso"] == reciente
    assert r["items"][0]["id"] == reciente
    assert isinstance(r["items"][0]["encolada_en"], str)
    assert len((await evaluaciones.listar_evaluaciones(sesion, 1))["items"]) == 1


@pytest.mark.asyncio
async def test_crear_normalizador_respeta_en_curso_y_vigencia(sesion):
    await _insertar(sesion, "EN_CURSO", 7)  # trabada: no bloquea
    nuevo, previa = await evaluaciones.crear_evaluacion_normalizador(sesion, "admin", ["GEMELO_VACIO"])
    assert nuevo is not None and previa is None
    fila = (
        await sesion.execute(
            text("SELECT estado, disparo, alcance, reglas, solicitada_por FROM app.cromo_arbitro_evaluacion WHERE id = :i"),
            {"i": nuevo},
        )
    ).one()
    assert (fila.estado, fila.disparo, fila.alcance, fila.reglas, fila.solicitada_por) == (
        "EN_COLA", "NORMALIZADOR", {"tipo": "TODO"}, ["GEMELO_VACIO"], "admin"
    )
    nuevo2, previa2 = await evaluaciones.crear_evaluacion_normalizador(sesion, "admin", None)
    assert nuevo2 is None and previa2 == nuevo


@pytest.mark.asyncio
async def test_viewer_en_curso_no_bloquea_normalizador(sesion):
    await _insertar(sesion, "EN_CURSO", 0, disparo="VIEWER")
    nuevo, previa = await evaluaciones.crear_evaluacion_normalizador(sesion, "admin", None)
    assert nuevo is not None and previa is None
