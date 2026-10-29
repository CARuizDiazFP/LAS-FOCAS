# Nombre de archivo: test_cromo_arbitro_evaluaciones_listado_real_db.py
# Ubicación de archivo: tests/test_cromo_arbitro_evaluaciones_listado_real_db.py
# Descripción: Tests contra Postgres real de listar_evaluaciones y del alta del análisis retroactivo (vigencia de 6 h), en transacción revertida

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from core.services.cromo.arbitro import evaluaciones
from db.session import async_engine
from tests.soporte_postgres_real import requiere_postgres_real, sesion_async_revertida

pytestmark = requiere_postgres_real


@pytest_asyncio.fixture
async def sesion():
    async with sesion_async_revertida() as s:
        # Aísla el test de filas reales de la DB dev: todo dentro de la transacción revertida.
        await s.execute(text("DELETE FROM app.cromo_arbitro_evaluacion"))
        yield s


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


@pytest.mark.asyncio
async def test_alcances_de_propuestas_agrupa_por_tipo(sesion):
    ids = []
    for tipo, objeto in (("SERVICIO", 999_920_101), ("BOTELLA", 999_920_102), ("BOTELLA", 999_920_103)):
        ids.append(
            (
                await sesion.execute(
                    text(
                        "INSERT INTO app.cromo_propuesta (regla, objeto_tipo, objeto_id, accion, confianza, "
                        "evidencia_hash, estado, modo_al_evaluar, disparo) "
                        "VALUES ('GEMELO_VACIO', :t, :o, 'INFORMAR', 90, 'h', 'PROPUESTA', 'SOMBRA', 'INGESTA') "
                        "RETURNING id"
                    ),
                    {"t": tipo, "o": objeto},
                )
            ).scalar_one()
        )
    r = await evaluaciones.alcances_de_propuestas(sesion, ids)
    assert {k: sorted(v) for k, v in r.items()} == {
        "SERVICIOS": [999_920_101], "BOTELLAS": [999_920_102, 999_920_103]
    }
    assert await evaluaciones.alcances_de_propuestas(sesion, []) == {}


@pytest.mark.asyncio
async def test_crear_normalizador_concurrente_deja_una_sola_fila():
    """Dos sesiones reales: la segunda espera el lock y, tras el commit de la primera, ve la fila."""
    engine = create_async_engine(
        async_engine.url.render_as_string(hide_password=False), poolclass=NullPool
    )
    marca = "test-concurrencia-t13"
    try:
        async with AsyncSession(engine) as limpia:
            await limpia.execute(text("DELETE FROM app.cromo_arbitro_evaluacion WHERE solicitada_por = :m"), {"m": marca})
            hay = (
                await limpia.execute(
                    text("SELECT count(*) FROM app.cromo_arbitro_evaluacion WHERE disparo='NORMALIZADOR' "
                         "AND estado IN ('EN_COLA','EN_CURSO') AND encolada_en > now() - interval '6 hours'")
                )
            ).scalar_one()
            await limpia.commit()
        if hay:
            pytest.skip("hay un análisis retroactivo real en curso en la DB dev")
        a = AsyncSession(engine)
        b = AsyncSession(engine)
        try:
            id_a, previa_a = await evaluaciones.crear_evaluacion_normalizador(a, marca, None)
            tarea = asyncio.create_task(evaluaciones.crear_evaluacion_normalizador(b, marca, None))
            await asyncio.sleep(0.5)
            assert not tarea.done()  # bloqueada por el advisory lock de A
            await a.commit()
            id_b, previa_b = await asyncio.wait_for(tarea, 10)
            await b.rollback()
            assert id_a is not None and previa_a is None
            assert id_b is None and previa_b == id_a
            async with AsyncSession(engine) as chequeo:
                n = (
                    await chequeo.execute(
                        text("SELECT count(*) FROM app.cromo_arbitro_evaluacion WHERE solicitada_por = :m AND estado = 'EN_COLA'"),
                        {"m": marca},
                    )
                ).scalar_one()
            assert n == 1
        finally:
            await a.close()
            await b.close()
    finally:
        async with AsyncSession(engine) as limpia:
            await limpia.execute(text("DELETE FROM app.cromo_arbitro_evaluacion WHERE solicitada_por = :m"), {"m": marca})
            await limpia.commit()
        await engine.dispose()
