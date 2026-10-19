# Nombre de archivo: test_cromo_arbitro_migracion_real_db.py
# Ubicación de archivo: tests/test_cromo_arbitro_migracion_real_db.py
# Descripción: Tests contra Postgres real del esquema del árbitro de Cromo (reglas, propuestas, evidencia, evaluaciones, origen del override)

"""Valida la migración 20261020_01: seed de reglas, índice único parcial de propuestas abiertas, CHECKs,
default/valor nuevo del override y cascada de la evidencia. Corre dentro de una transacción que se
revierte; si las tablas todavía no existen en la DB, aplica `upgrade()` dentro de esa misma transacción."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from db.session import async_engine
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real

_MIGRACION = (
    Path(__file__).resolve().parents[1] / "db" / "alembic" / "versions" / "20261020_01_cromo_arbitro.py"
)
_REGLAS = {"ODF_POR_CAMINO", "CONTRADICCION_SERVICIO", "GEMELO_VACIO", "GEMELO_OPERATIVO", "ODF_GEMELA_ISLA"}
_OBJETO = 999_920_001


def _correr(sync_conn, funcion: str) -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    spec = importlib.util.spec_from_file_location("mig_20261020_01", _MIGRACION)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    with Operations.context(MigrationContext.configure(sync_conn)):
        getattr(modulo, funcion)()


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


async def _propuesta(conn, estado: str = "PROPUESTA", accion: str = "INFORMAR", confianza: int = 90):
    async with conn.begin_nested():
        await conn.execute(
            text(
                "INSERT INTO app.cromo_propuesta (regla, objeto_tipo, objeto_id, accion, confianza, "
                "evidencia_hash, estado, modo_al_evaluar, disparo) "
                "VALUES ('GEMELO_VACIO', 'BOTELLA', :o, :a, :c, 'h', :e, 'SOMBRA', 'INGESTA')"
            ),
            {"o": _OBJETO, "a": accion, "c": confianza, "e": estado},
        )


@pytest.mark.asyncio
async def test_regla_seed_en_sombra(entorno):
    _, conn = entorno
    filas = (
        await conn.execute(text("SELECT codigo, modo, umbral, descripcion FROM app.cromo_regla_correccion"))
    ).all()
    por_codigo = {f[0]: f for f in filas}
    assert _REGLAS <= set(por_codigo)
    for codigo in _REGLAS:
        assert por_codigo[codigo][1] == "SOMBRA"
        assert por_codigo[codigo][2] == 90
        assert por_codigo[codigo][3]


@pytest.mark.asyncio
async def test_propuesta_abierta_unica(entorno):
    _, conn = entorno
    await _propuesta(conn)
    with pytest.raises(IntegrityError):
        await _propuesta(conn, estado="EN_OBSERVACION")
    await conn.execute(
        text("UPDATE app.cromo_propuesta SET estado='RECHAZADA' WHERE objeto_id = :o"), {"o": _OBJETO}
    )
    await _propuesta(conn)  # con la primera cerrada, entra


@pytest.mark.asyncio
async def test_checks_propuesta(entorno):
    _, conn = entorno
    for kwargs in ({"estado": "X"}, {"accion": "X"}, {"confianza": 101}):
        with pytest.raises(IntegrityError):
            await _propuesta(conn, **kwargs)


@pytest.mark.asyncio
async def test_evaluacion_checks(entorno):
    _, conn = entorno
    with pytest.raises(IntegrityError):
        async with conn.begin_nested():
            await conn.execute(
                text(
                    "INSERT INTO app.cromo_arbitro_evaluacion (disparo, alcance, estado) "
                    "VALUES ('VIEWER', '{}'::jsonb, 'X')"
                )
            )
    async with conn.begin_nested():
        await conn.execute(
            text(
                "INSERT INTO app.cromo_arbitro_evaluacion (disparo, alcance, estado) "
                "VALUES ('VIEWER', '{}'::jsonb, 'EN_COLA')"
            )
        )


async def _servicio(conn) -> int:
    return (
        await conn.execute(
            text(
                "INSERT INTO app.servicios (servicio_id, numero_primer_servicio, nombre_cliente, "
                "categoria, origen_datos, estado_servicio, es_verificable) "
                "VALUES ('99992001', '99992001', 'QA Arbitro', 6, 'INGEST_EXCEL', 'Activo', true) RETURNING id"
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_override_origen_default_manual_y_categoria_evidencia(entorno):
    _, conn = entorno
    sid = await _servicio(conn)
    for categoria in ("OTRO", "EVIDENCIA_CAMINO"):
        await conn.execute(
            text(
                "INSERT INTO app.cromo_servicio_odf_override (servicio_id, odf_n_id, categoria_causa, usuario) "
                "VALUES (:s, :o, :c, 'qa')"
            ),
            {"s": sid, "o": _OBJETO, "c": categoria},
        )
    origenes = (
        await conn.execute(
            text("SELECT origen FROM app.cromo_servicio_odf_override WHERE servicio_id = :s"), {"s": sid}
        )
    ).scalars().all()
    assert origenes == ["MANUAL", "MANUAL"]
    with pytest.raises(IntegrityError):
        async with conn.begin_nested():
            await conn.execute(
                text(
                    "INSERT INTO app.cromo_servicio_odf_override "
                    "(servicio_id, odf_n_id, categoria_causa, usuario, origen) "
                    "VALUES (:s, :o, 'OTRO', 'qa', 'X')"
                ),
                {"s": sid, "o": _OBJETO},
            )


@pytest.mark.asyncio
async def test_evidencia_cascade_servicio(entorno):
    _, conn = entorno
    sid = await _servicio(conn)
    await conn.execute(
        text(
            "INSERT INTO app.cromo_evidencia_camino (servicio_id, pelo_n_id, completo, fuente) "
            "VALUES (:s, :p, true, 'SLACK')"
        ),
        {"s": sid, "p": _OBJETO},
    )
    await conn.execute(text("DELETE FROM app.servicios WHERE id = :s"), {"s": sid})
    cuenta = (
        await conn.execute(
            text("SELECT count(*) FROM app.cromo_evidencia_camino WHERE servicio_id = :s"), {"s": sid}
        )
    ).scalar_one()
    assert cuenta == 0
