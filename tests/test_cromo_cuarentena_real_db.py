# Nombre de archivo: test_cromo_cuarentena_real_db.py
# Ubicación de archivo: tests/test_cromo_cuarentena_real_db.py
# Descripción: Integración contra Postgres real de la cuarentena de inconsistencias de Cromo — vista
# app.v_cromo_servicio_match_vigente (migración 20261017_03) y sus consumidores principales

"""Un pelo de un caso en `CUARENTENA` deja de contar como uso en todos los consumidores.

Todo corre dentro de UNA transacción que se revierte al final, migraciones incluidas: si la base
todavía no tiene `20261017_02`/`20261017_03`, el fixture corre sus `upgrade()` reales sobre la
conexión y no deja nada.

Escenario sintético (rango propio 999_918_xxx, no lo usa ningún otro `*_real_db`): un Servicio con
tres pelos matcheados.
- `_PELO_SANO` y `_PELO_CUARENTENA` en el cable `_CABLE_MIXTO` (mismo tubo).
- `_PELO_SOLO` en el cable `_CABLE_SOLO`: si su pelo queda en cuarentena, el cable no tiene uso.
- `_PELO_CUARENTENA` llega a un conector de la ODF `_ODF` (vía "pelo" de `odfs_por_servicio`).
- Un caso de inconsistencia con `_PELO_CUARENTENA` y `_PELO_SOLO`. Cada test mide primero con el
  caso en `PENDIENTE` (todo cuenta) y después en `CUARENTENA` (sólo cuenta `_PELO_SANO`): así se
  prueba que lo que filtra es el estado y no la mera existencia del caso.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from core.services import servicio_traza
from core.services.cromo import camino_optico_service, detalle, servicios_sin_odf, verificador
from core.services.fo_monitor import consultas_web
from db.session import async_engine, engine
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real

_VERSIONES = Path(__file__).resolve().parents[1] / "db" / "alembic" / "versions"
_MIGRACIONES = (
    ("app.cromo_inconsistencia", "20261017_02_cromo_inconsistencias.py"),
    ("app.v_cromo_servicio_match_vigente", "20261017_03_cromo_servicio_match_vigente.py"),
)

_SERVICIO = "99991801"
_CABLE_MIXTO = 999_918_011
_CABLE_SOLO = 999_918_012
_TUBO_MIXTO = 999_918_021
_TUBO_SOLO = 999_918_022
_PELO_SANO = 999_918_101
_PELO_CUARENTENA = 999_918_102
_PELO_SOLO = 999_918_103
_ODF = 999_918_001
_CONECTOR = 999_918_201
_CASO_OBJETO = 999_918_301


def _correr(sync_conn, archivo: str, funcion: str) -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    spec = importlib.util.spec_from_file_location(f"mig_{archivo}", _VERSIONES / archivo)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    with Operations.context(MigrationContext.configure(sync_conn)):
        getattr(modulo, funcion)()


def _migrar(sync_conn) -> None:
    for objeto, archivo in _MIGRACIONES:
        if sync_conn.execute(text("SELECT to_regclass(:o)"), {"o": objeto}).scalar() is None:
            _correr(sync_conn, archivo, "upgrade")


def _sembrar(sync_conn) -> int:
    """Inserta el escenario y devuelve la PK del Servicio. El caso arranca en `PENDIENTE`."""
    ejecutar = sync_conn.execute
    servicio_pk = ejecutar(
        text(
            "INSERT INTO app.servicios (servicio_id, numero_primer_servicio, categoria, origen_datos, "
            "estado_servicio) VALUES (:s, :s, 0, 'MANUAL', 'Activo') RETURNING id"
        ),
        {"s": _SERVICIO},
    ).scalar_one()
    ejecutar(
        text(
            "INSERT INTO app.cromo_odfs (n_id, version_id, vmax, clase, nombre, localidad, payload_raw) "
            "VALUES (:n, :n, 1, 69, 'ODF TEST cuarentena', 'Localidad Test', '{}'::jsonb)"
        ),
        {"n": _ODF},
    )
    for cable, tubo in ((_CABLE_MIXTO, _TUBO_MIXTO), (_CABLE_SOLO, _TUBO_SOLO)):
        ejecutar(
            text(
                "INSERT INTO app.cromo_cables (n_id, version_id, vmax, clase, nombre, payload_raw) "
                "VALUES (:n, :n, 1, 51, :nombre, '{}'::jsonb)"
            ),
            {"n": cable, "nombre": f"F-TEST-CUARENTENA-{cable}"},
        )
        ejecutar(
            text("INSERT INTO app.cromo_tubos (n_id, cable_n_id, orden, nombre_color) VALUES (:t, :c, 0, 'AZUL')"),
            {"t": tubo, "c": cable},
        )
    for orden, (pelo, cable, tubo) in enumerate(
        (
            (_PELO_SANO, _CABLE_MIXTO, _TUBO_MIXTO),
            (_PELO_CUARENTENA, _CABLE_MIXTO, _TUBO_MIXTO),
            (_PELO_SOLO, _CABLE_SOLO, _TUBO_SOLO),
        )
    ):
        ejecutar(
            text(
                "INSERT INTO app.cromo_pelos (n_id, tubo_n_id, cable_n_id, numero_pelo, orden, "
                "servicio_raw, servicio_numero, tipo_asociacion) "
                "VALUES (:p, :t, :c, :num, :orden, :raw, :s, 'CLIENTE')"
            ),
            {"p": pelo, "t": tubo, "c": cable, "num": str(orden + 1), "orden": orden,
             "raw": f"FO {_SERVICIO} - CLIENTE TEST", "s": _SERVICIO},
        )
        ejecutar(
            text(
                "INSERT INTO app.cromo_servicio_match (pelo_n_id, servicio_numero, servicio_id, metodo, confianza) "
                "VALUES (:p, :s, :sid, 'REGEX_EXACTO', 100)"
            ),
            {"p": pelo, "s": _SERVICIO, "sid": servicio_pk},
        )
    ejecutar(
        text(
            "INSERT INTO app.cromo_odf_conectores (n_id, odf_n_id, numero_conector, pelo_n_id, payload_raw) "
            "VALUES (:n, :odf, '1', :p, '{}'::jsonb)"
        ),
        {"n": _CONECTOR, "odf": _ODF, "p": _PELO_CUARENTENA},
    )
    caso = ejecutar(
        text(
            "INSERT INTO app.cromo_inconsistencia (tipo, objeto_n_id, revision, estado) "
            "VALUES ('ISLA_FUSION', :o, 'AUTO', 'PENDIENTE') RETURNING id"
        ),
        {"o": _CASO_OBJETO},
    ).scalar_one()
    for pelo in (_PELO_CUARENTENA, _PELO_SOLO):
        ejecutar(
            text("INSERT INTO app.cromo_inconsistencia_pelo (inconsistencia_id, pelo_n_id) VALUES (:i, :p)"),
            {"i": caso, "p": pelo},
        )
    return int(servicio_pk)


_SQL_ESTADO = text("UPDATE app.cromo_inconsistencia SET estado = :e WHERE objeto_n_id = :o")


@pytest_asyncio.fixture
async def entorno():
    """`(sesion_async, conn_async, servicio_pk)` dentro de una transacción revertida."""
    motor = create_async_engine(async_engine.url.render_as_string(hide_password=False), poolclass=NullPool)
    async with motor.connect() as conn:
        trans = await conn.begin()
        try:
            await conn.run_sync(_migrar)
            servicio_pk = await conn.run_sync(_sembrar)
            sesion = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
            yield sesion, conn, servicio_pk
            await sesion.close()
        finally:
            await trans.rollback()
    await motor.dispose()


@pytest.fixture
def entorno_sync():
    """`(session_sync, conn_sync, servicio_pk)` para los consumidores síncronos (Slack, FO Monitor)."""
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            _migrar(conn)
            servicio_pk = _sembrar(conn)
            session = Session(bind=conn, join_transaction_mode="create_savepoint")
            yield session, conn, servicio_pk
            session.close()
        finally:
            trans.rollback()


async def _cuarentena(conn) -> None:
    await conn.execute(_SQL_ESTADO, {"e": "CUARENTENA", "o": _CASO_OBJETO})


# ── La vista ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_vista_excluye_solo_los_pelos_de_casos_en_cuarentena(entorno):
    _sesion, conn, _pk = entorno
    sql = text(
        "SELECT pelo_n_id FROM app.v_cromo_servicio_match_vigente "
        "WHERE pelo_n_id BETWEEN 999918000 AND 999918999 ORDER BY pelo_n_id"
    )
    todos = [_PELO_SANO, _PELO_CUARENTENA, _PELO_SOLO]
    for estado in ("PENDIENTE", "REPORTADA", "CORREGIDA", "ACEPTADA"):
        await conn.execute(_SQL_ESTADO, {"e": estado, "o": _CASO_OBJETO})
        assert list((await conn.execute(sql)).scalars()) == todos, estado
    await _cuarentena(conn)
    assert list((await conn.execute(sql)).scalars()) == [_PELO_SANO]
    # Los datos de Cromo no se tocan: la tabla conserva los tres matches.
    crudos = (
        await conn.execute(
            text("SELECT count(*) FROM app.cromo_servicio_match WHERE pelo_n_id BETWEEN 999918000 AND 999918999")
        )
    ).scalar_one()
    assert crudos == 3


@pytest.mark.asyncio
async def test_downgrade_quita_la_vista(entorno):
    _sesion, conn, _pk = entorno
    await conn.run_sync(_correr, _MIGRACIONES[1][1], "downgrade")
    assert (await conn.execute(text("SELECT to_regclass('app.v_cromo_servicio_match_vigente')"))).scalar() is None


# ── Verificador (Slack Verificar cable, web, FO Monitor, API v1 cables, protección) ──


@pytest.mark.asyncio
async def test_verificador_deja_de_contar_el_pelo_en_cuarentena(entorno):
    sesion, conn, pk = entorno

    unicos = await verificador.servicios_unicos_por_cable(sesion, _CABLE_MIXTO)
    assert [(s.servicio_id, s.cantidad_pelos) for s in unicos.servicios] == [(pk, 2)]
    assert len((await verificador.servicios_por_cable(sesion, _CABLE_SOLO)).servicios) == 1
    odfs = await verificador.odfs_por_servicio(sesion, pk)
    assert [o.odf_n_id for o in odfs] == [_ODF]

    await _cuarentena(conn)

    unicos = await verificador.servicios_unicos_por_cable(sesion, _CABLE_MIXTO)
    assert [(s.servicio_id, s.cantidad_pelos, s.pelos_n_ids) for s in unicos.servicios] == [(pk, 1, [_PELO_SANO])]
    assert (await verificador.servicios_por_cable(sesion, _CABLE_SOLO)).servicios == []
    assert (await verificador.servicios_por_tubo(sesion, _TUBO_SOLO)).servicios == []
    assert await verificador.odfs_por_servicio(sesion, pk) == []


# ── servicio_traza (API v1 servicios) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_servicio_traza_deja_de_listar_el_cable_en_cuarentena(entorno):
    sesion, conn, pk = entorno
    nombre_solo = f"F-TEST-CUARENTENA-{_CABLE_SOLO}"
    assert nombre_solo in await servicio_traza._cables_inventario(sesion, pk)

    await _cuarentena(conn)

    assert await servicio_traza._cables_inventario(sesion, pk) == [f"F-TEST-CUARENTENA-{_CABLE_MIXTO}"]


@pytest.mark.asyncio
async def test_servicio_traza_no_sirve_trackings_cacheados_de_pelos_en_cuarentena(entorno):
    """La rama `tc.servicio_id = :sid` del caché no debe saltear la cuarentena de su pelo semilla."""
    from datetime import datetime, timezone

    sesion, conn, pk = entorno
    await conn.execute(
        text(
            "INSERT INTO app.cromo_tracking_cache (pelo_n_id, servicio_id, nombre_archivo, contenido) "
            "VALUES (:p, :sid, 'x.txt', 'contenido')"
        ),
        {"p": _PELO_CUARENTENA, "sid": pk},
    )
    ahora = datetime.now(timezone.utc)
    assert await servicio_traza._trackings_frescos(sesion, pk, ahora=ahora) == ["contenido"]

    await _cuarentena(conn)

    assert await servicio_traza._trackings_frescos(sesion, pk, ahora=ahora) == []


@pytest.mark.asyncio
async def test_resumen_y_listado_por_servicio_matchean_por_todas_las_identidades(entorno):
    """El match se hizo bajo otra numeración (servicio_id NULL): igual debe contar para el Servicio."""
    from core.services.cromo import inconsistencias_cromo

    sesion, conn, pk = entorno
    await conn.execute(text("UPDATE app.cromo_servicio_match SET servicio_id = NULL WHERE pelo_n_id BETWEEN 999918000 AND 999918999"))

    assert (await inconsistencias_cromo.resumen_de_servicio(sesion, pk))["en_revision"] == 1
    listado = await inconsistencias_cromo.listar(sesion, servicio_id=pk)
    assert listado["total"] == 1


# ── Servicios sin ODF ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_servicios_sin_odf_no_cuenta_pelos_ni_conectores_en_cuarentena(entorno):
    sesion, conn, pk = entorno
    consulta = servicios_sin_odf._SQL_PELOS_Y_CONECTORES
    assert tuple((await sesion.execute(consulta, {"servicio_id": pk})).one()) == (3, 1)

    await _cuarentena(conn)

    assert tuple((await sesion.execute(consulta, {"servicio_id": pk})).one()) == (1, 0)


# ── Camino óptico (semillas, conteos, moda) ──────────────────────────────────


@pytest.mark.asyncio
async def test_camino_optico_no_usa_pelos_en_cuarentena_como_semilla(entorno):
    sesion, conn, pk = entorno
    assert await camino_optico_service.contar_semillas(sesion, pk) == (3, 1)
    assert await camino_optico_service.pelo_pertenece_al_servicio(sesion, pk, _PELO_SOLO)

    await _cuarentena(conn)

    assert await camino_optico_service.contar_semillas(sesion, pk) == (1, 0)
    semillas = await camino_optico_service.listar_pelos_semilla(sesion, pk, limite=None)
    assert [s.pelo_n_id for s in semillas] == [_PELO_SANO]
    assert not await camino_optico_service.pelo_pertenece_al_servicio(sesion, pk, _PELO_SOLO)
    assert await camino_optico_service.caminos_esperados(sesion, pk) == 1


# ── FO Monitor (consultas web, síncronas) ────────────────────────────────────


def test_fo_monitor_busqueda_por_servicio_ignora_cables_en_cuarentena(entorno_sync):
    session, conn, _pk = entorno_sync
    antes = consultas_web.buscar_en_mapa(session, tipo="servicio", q=_SERVICIO)
    assert antes["meta"]["encontrados"] == 2

    conn.execute(_SQL_ESTADO, {"e": "CUARENTENA", "o": _CASO_OBJETO})

    despues = consultas_web.buscar_en_mapa(session, tipo="servicio", q=_SERVICIO)
    assert despues["meta"]["encontrados"] == 1


def test_verificador_sync_deja_de_contar_el_pelo_en_cuarentena(entorno_sync):
    session, conn, _pk = entorno_sync
    conn.execute(_SQL_ESTADO, {"e": "CUARENTENA", "o": _CASO_OBJETO})
    assert verificador.servicios_unicos_por_cable_sync(session, _CABLE_SOLO).servicios == []
    assert verificador.servicios_por_tubo_sync(session, _TUBO_SOLO).servicios == []


# ── Marca visible: detalle de cable (web) y pelos de un buffer (Slack) ───────


@pytest.mark.asyncio
async def test_detalle_de_cable_marca_el_pelo_en_cuarentena(entorno):
    sesion, conn, _pk = entorno
    pelos = {p.n_id: p for t in (await detalle.obtener_detalle_cable(sesion, _CABLE_MIXTO)).tubos for p in t.pelos}
    assert not pelos[_PELO_CUARENTENA].en_cuarentena and pelos[_PELO_CUARENTENA].servicios

    await _cuarentena(conn)

    pelos = {p.n_id: p for t in (await detalle.obtener_detalle_cable(sesion, _CABLE_MIXTO)).tubos for p in t.pelos}
    assert pelos[_PELO_CUARENTENA].en_cuarentena is True
    assert pelos[_PELO_CUARENTENA].servicios == []
    assert pelos[_PELO_SANO].en_cuarentena is False
    assert len(pelos[_PELO_SANO].servicios) == 1


def test_pelos_de_tubo_sync_marca_el_pelo_en_cuarentena(entorno_sync):
    session, conn, _pk = entorno_sync
    conn.execute(_SQL_ESTADO, {"e": "CUARENTENA", "o": _CASO_OBJETO})
    pelos = detalle.pelos_de_tubo_sync(session, _TUBO_SOLO)
    assert [(p.n_id, p.en_cuarentena, p.servicios) for p in pelos] == [(_PELO_SOLO, True, [])]
