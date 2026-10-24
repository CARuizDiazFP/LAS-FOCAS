# Nombre de archivo: test_cromo_servicio_posicion_vigente_migracion_real_db.py
# Ubicación de archivo: tests/test_cromo_servicio_posicion_vigente_migracion_real_db.py
# Descripción: Tests contra Postgres real del esquema app.servicio_posicion_vigente (migración 20261021_01)

"""Valida la migración 20261021_01: índice único parcial de posiciones vigentes, CHECKs de motivo y de
coherencia del retiro, `pelos_candidatos` como `bigint[]` y cascada al borrar el Servicio. Corre dentro
de una transacción que se revierte; si la tabla todavía no existe en la DB, aplica `upgrade()` dentro
de esa misma transacción."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from db.session import async_engine
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real

_MIGRACION = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "alembic"
    / "versions"
    / "20261021_01_servicio_posicion_vigente.py"
)
_AHORA = datetime(2026, 10, 21, tzinfo=timezone.utc)
_CONECTOR = 999_921_001  # referencia blanda: no hace falta que exista en cromo_odf_conectores


def _correr(sync_conn, funcion: str) -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    spec = importlib.util.spec_from_file_location("mig_20261021_01", _MIGRACION)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    with Operations.context(MigrationContext.configure(sync_conn)):
        getattr(modulo, funcion)()


def test_migracion_encadena_sobre_el_arbitro():
    spec = importlib.util.spec_from_file_location("mig_20261021_01_meta", _MIGRACION)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    assert modulo.revision == "20261021_01"
    assert modulo.down_revision == "20261020_01"


@pytest_asyncio.fixture
async def conn():
    engine = create_async_engine(
        async_engine.url.render_as_string(hide_password=False), poolclass=NullPool
    )
    async with engine.connect() as conexion:
        trans = await conexion.begin()
        try:
            existe = (
                await conexion.execute(text("SELECT to_regclass('app.servicio_posicion_vigente')"))
            ).scalar()
            if existe is None:
                await conexion.run_sync(_correr, "upgrade")
            yield conexion
        finally:
            await trans.rollback()
    await engine.dispose()


async def _servicio(conexion) -> int:
    return (
        await conexion.execute(
            text(
                "INSERT INTO app.servicios (servicio_id, numero_primer_servicio, nombre_cliente, "
                "categoria, origen_datos, estado_servicio, es_verificable) "
                "VALUES ('99992101', '99992101', 'QA Posicion', 6, 'INGEST_EXCEL', 'Activo', true) RETURNING id"
            )
        )
    ).scalar_one()


async def _declarar(conexion, sid: int, **extra) -> None:
    columnas = {
        "servicio_id": sid,
        "conector_n_id": _CONECTOR,
        "odf_n_id": 1,
        "pelo_n_id": 7028862,
        "declarado_por": "qa",
        **extra,
    }
    nombres = ", ".join(columnas)
    valores = ", ".join(
        f"CAST(:{k} AS bigint[])" if k == "pelos_candidatos" else f":{k}" for k in columnas
    )
    async with conexion.begin_nested():
        await conexion.execute(
            text(f"INSERT INTO app.servicio_posicion_vigente ({nombres}) VALUES ({valores})"),
            columnas,
        )


@pytest.mark.asyncio
async def test_una_sola_vigente_por_servicio_y_conector(conn):
    sid = await _servicio(conn)
    await _declarar(conn, sid, pelos_candidatos=[7028862, 6799284])
    with pytest.raises(IntegrityError):
        await _declarar(conn, sid)
    await conn.execute(
        text(
            "UPDATE app.servicio_posicion_vigente SET vigente = false, retirado_en = now(), "
            "retirado_por = 'qa', motivo_retiro = 'MANUAL' WHERE servicio_id = :s"
        ),
        {"s": sid},
    )
    await _declarar(conn, sid)  # con la primera retirada, entra

    filas = (
        await conn.execute(
            text(
                "SELECT vigente, pelos_candidatos FROM app.servicio_posicion_vigente "
                "WHERE servicio_id = :s ORDER BY id"
            ),
            {"s": sid},
        )
    ).all()
    assert [f[0] for f in filas] == [False, True]
    assert filas[0][1] == [7028862, 6799284]


@pytest.mark.asyncio
async def test_check_motivo_rechaza_valores_fuera_de_la_lista(conn):
    sid = await _servicio(conn)
    with pytest.raises(IntegrityError):
        await _declarar(
            conn, sid, vigente=False, retirado_en=_AHORA, motivo_retiro="OTRO"
        )
    for motivo in (
        "MANUAL",
        "SIN_PELO",
        "PELO_CAMBIO",
        "PELO_DANADO",
        "CABLE_SIN_USO",
        "CONECTOR_INEXISTENTE",
    ):
        await _declarar(
            conn, sid, vigente=False, retirado_en=_AHORA, motivo_retiro=motivo
        )


@pytest.mark.asyncio
async def test_check_retiro_coherente(conn):
    sid = await _servicio(conn)
    with pytest.raises(IntegrityError):
        await _declarar(conn, sid, vigente=False)  # retirada sin fecha ni motivo
    with pytest.raises(IntegrityError):
        await _declarar(conn, sid, vigente=False, motivo_retiro="MANUAL")  # sin fecha


@pytest.mark.asyncio
async def test_defaults_y_cascada_al_borrar_el_servicio(conn):
    sid = await _servicio(conn)
    await _declarar(conn, sid)
    fila = (
        await conn.execute(
            text(
                "SELECT vigente, declarado_en IS NOT NULL, pelos_candidatos, detalle_retiro "
                "FROM app.servicio_posicion_vigente WHERE servicio_id = :s"
            ),
            {"s": sid},
        )
    ).one()
    assert fila[0] is True and fila[1] is True
    assert fila[2] is None and fila[3] is None

    await conn.execute(text("DELETE FROM app.servicios WHERE id = :s"), {"s": sid})
    cuenta = (
        await conn.execute(
            text("SELECT count(*) FROM app.servicio_posicion_vigente WHERE servicio_id = :s"),
            {"s": sid},
        )
    ).scalar_one()
    assert cuenta == 0


@pytest.mark.asyncio
async def test_indices_con_los_nombres_del_modelo(conn):
    nombres = set(
        (
            await conn.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = 'app' AND tablename = 'servicio_posicion_vigente'"
                )
            )
        ).scalars()
    )
    assert {"ux_servicio_posicion_vigente_vigente", "ix_servicio_posicion_vigente_servicio"} <= nombres


@pytest.mark.asyncio
async def test_downgrade_y_upgrade_son_reversibles(conn):
    """DDL transaccional: dentro de la transacción revertida, `downgrade()` borra la tabla y
    `upgrade()` la vuelve a crear con sus índices."""
    await conn.run_sync(_correr, "downgrade")
    assert (await conn.execute(text("SELECT to_regclass('app.servicio_posicion_vigente')"))).scalar() is None
    await conn.run_sync(_correr, "upgrade")
    assert (await conn.execute(text("SELECT to_regclass('app.servicio_posicion_vigente')"))).scalar() is not None
