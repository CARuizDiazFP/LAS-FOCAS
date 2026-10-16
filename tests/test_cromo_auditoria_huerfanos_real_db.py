# Nombre de archivo: test_cromo_auditoria_huerfanos_real_db.py
# Ubicación de archivo: tests/test_cromo_auditoria_huerfanos_real_db.py
# Descripción: Integración contra Postgres real de la auditoría de huérfanos — migración 20261016_04,
# upsert idempotente, normalizar (sólo CABLE_DESUSO, nunca protegido), descartar y restaurar

"""Todo corre dentro de UNA transacción que se revierte al final, migración incluida.

Por qué real: lo que importa es SQL — `unnest` de arrays con `ON CONFLICT ... WHERE estado =
'PENDIENTE'`, `RETURNING (xmax = 0)`, el `FOR UPDATE`, los CHECK de la migración, el
`DELETE ... RETURNING` de restaurar. Una sesión fake devolvería lo que uno le dicta.

Si la tabla todavía no existe (la DB de dev no tiene la migración aplicada), el fixture corre el
`upgrade()` real de `20261016_04` sobre la conexión, dentro de la transacción: valida la migración
y no deja nada. El `downgrade()` se prueba en un test propio, también revertido.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from db.session import async_engine
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real

_MIGRACION = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "alembic"
    / "versions"
    / "20261016_04_cromo_auditoria_huerfanos.py"
)

# Rango sintético propio (999_915_xxx): no lo usa ningún otro `*_real_db`.
_SERVICIO_NUMERO = "99991501"
_CABLE_SIN_USO = 999_915_001
_CABLE_TRAMO = 999_915_002
_PELO_DESUSO = 999_915_101
_PELO_DESUSO_2 = 999_915_102
_PELO_DANADO = 999_915_103
_PELO_PROTEGIDO = 999_915_104
_PELO_TRAMO = 999_915_105
_PELO_AJENO = 999_915_106  # recorrido por un residual pero sin la etiqueta del Servicio
AHORA = datetime(2026, 10, 16, tzinfo=timezone.utc)


def _cargar_migracion():
    spec = importlib.util.spec_from_file_location("mig_20261016_04", _MIGRACION)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _correr(sync_conn, funcion: str) -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    contexto = MigrationContext.configure(sync_conn)
    with Operations.context(contexto):
        getattr(_cargar_migracion(), funcion)()


async def _insertar_datos(conn) -> int:
    servicio_id = (
        await conn.execute(
            text(
                "INSERT INTO app.servicios (servicio_id, estado_servicio) "
                "VALUES (:n, 'Activo') RETURNING id"
            ),
            {"n": _SERVICIO_NUMERO},
        )
    ).scalar_one()
    for n_id, tendido in ((_CABLE_SIN_USO, "Sin Uso"), (_CABLE_TRAMO, "Canalizado")):
        await conn.execute(
            text(
                "INSERT INTO app.cromo_cables (n_id, version_id, vmax, nombre, tendido, payload_raw) "
                "VALUES (:n, :n, 1, :nombre, :tendido, '{}'::jsonb)"
            ),
            {"n": n_id, "nombre": f"F-TEST-{n_id}", "tendido": tendido},
        )
    pelos = {
        _PELO_DESUSO: _CABLE_SIN_USO,
        _PELO_DESUSO_2: _CABLE_SIN_USO,
        _PELO_DANADO: _CABLE_TRAMO,
        _PELO_PROTEGIDO: _CABLE_SIN_USO,
        _PELO_TRAMO: _CABLE_TRAMO,
        _PELO_AJENO: _CABLE_SIN_USO,
    }
    for pelo, cable in pelos.items():
        await conn.execute(
            text(
                "INSERT INTO app.cromo_pelos (n_id, tubo_n_id, cable_n_id, numero_pelo) "
                "VALUES (:p, 1, :c, '1')"
            ),
            {"p": pelo, "c": cable},
        )
        if pelo != _PELO_AJENO:
            await conn.execute(
                text(
                    "INSERT INTO app.cromo_servicio_match (pelo_n_id, servicio_numero, servicio_id, metodo) "
                    "VALUES (:p, :n, :s, 'REGEX_EXACTO')"
                ),
                {"p": pelo, "n": _SERVICIO_NUMERO, "s": servicio_id},
            )
    return servicio_id


@pytest_asyncio.fixture
async def entorno():
    engine = create_async_engine(
        async_engine.url.render_as_string(hide_password=False), poolclass=NullPool
    )
    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
            existe = (
                await conn.execute(text("SELECT to_regclass('app.cromo_auditoria_huerfanos')"))
            ).scalar()
            if existe is None:
                await conn.run_sync(_correr, "upgrade")
            servicio_id = await _insertar_datos(conn)
            sesion = AsyncSession(
                bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
            )
            yield sesion, servicio_id, conn
            await sesion.close()
        finally:
            await trans.rollback()
    await engine.dispose()


def _tracking(semilla: int, pelos: set[int], resumen):
    from core.services.cromo.tracking_service import TrackingGenerado

    return TrackingGenerado(
        pelo_n_id=semilla,
        nombre_archivo="x.txt",
        contenido="",
        desde_cache=True,
        generado_at=AHORA,
        duracion_ms=None,
        pelos_camino=frozenset(pelos),
        extremos=resumen,
    )


def _escenario():
    """Un tramo ODF↔ODF por el cable de tramo; tres residuales: uno por el cable 'Sin Uso' (con un
    pelo ajeno), uno que comparte el cable del tramo y uno 'Sin Uso' que termina en ODF Nodo."""
    from core.services.cromo.tracking_service import ExtremoCamino, ResumenCamino

    odf = lambda i: ExtremoCamino(tipo="CONECTOR_ODF", id_cromo=i, odf_id=i, odf_clase=69)  # noqa: E731
    pelo = lambda i: ExtremoCamino(tipo="PELO", id_cromo=i, clase=130)  # noqa: E731
    tramo = _tracking(
        _PELO_TRAMO,
        {_PELO_TRAMO},
        ResumenCamino(inicio=odf(1), fin=odf(2), odfs=(1, 2), cables=(_CABLE_TRAMO,)),
    )
    desuso = _tracking(
        _PELO_DESUSO,
        {_PELO_DESUSO, _PELO_DESUSO_2, _PELO_AJENO},
        ResumenCamino(inicio=pelo(_PELO_DESUSO), fin=pelo(_PELO_DESUSO_2), cables=(_CABLE_SIN_USO,)),
    )
    danado = _tracking(
        _PELO_DANADO,
        {_PELO_DANADO},
        ResumenCamino(inicio=pelo(_PELO_DANADO), fin=pelo(_PELO_DANADO), cables=(_CABLE_TRAMO,)),
    )
    protegido = _tracking(
        _PELO_PROTEGIDO,
        {_PELO_PROTEGIDO},
        ResumenCamino(
            inicio=pelo(_PELO_PROTEGIDO),
            fin=ExtremoCamino(tipo="CONECTOR_ODF", id_cromo=9, odf_id=9, odf_clase=86),
            odfs=(9,),
            cables=(_CABLE_SIN_USO,),
        ),
    )
    return [tramo], [desuso, danado, protegido]


_SEMILLAS = frozenset({_PELO_DESUSO, _PELO_DESUSO_2, _PELO_DANADO, _PELO_PROTEGIDO, _PELO_TRAMO})


async def _filas(conn, servicio_id):
    filas = (
        await conn.execute(
            text(
                "SELECT pelo_n_id, causa, estado, camino_semilla, "
                "(evidencia->>'protegido')::boolean AS protegido, id "
                "FROM app.cromo_auditoria_huerfanos WHERE servicio_id = :s ORDER BY pelo_n_id"
            ),
            {"s": servicio_id},
        )
    ).mappings().all()
    return {f["pelo_n_id"]: dict(f) for f in filas}


async def _auditar(sesion, servicio_id, tramos, residuales, **kw):
    from core.services.cromo import auditoria_huerfanos

    return await auditoria_huerfanos.auditar_sin_romper(
        sesion, servicio_id, tramos=tramos, residuales=residuales, semillas=_SEMILLAS, **kw
    )


@pytest.mark.asyncio
async def test_upsert_idempotente_solo_pelos_del_servicio(entorno):
    sesion, servicio_id, conn = entorno
    tramos, residuales = _escenario()

    primero = await _auditar(sesion, servicio_id, tramos, residuales)
    assert (primero.nuevos, primero.actualizados) == (4, 0)
    filas = await _filas(conn, servicio_id)
    assert set(filas) == {_PELO_DESUSO, _PELO_DESUSO_2, _PELO_DANADO, _PELO_PROTEGIDO}
    assert filas[_PELO_DESUSO]["causa"] == "CABLE_DESUSO"
    assert filas[_PELO_DESUSO_2]["camino_semilla"] == _PELO_DESUSO
    assert filas[_PELO_DANADO]["causa"] == "PELO_DANADO"
    assert filas[_PELO_PROTEGIDO]["protegido"] is True
    assert all(f["estado"] == "PENDIENTE" for f in filas.values())

    segundo = await _auditar(sesion, servicio_id, tramos, residuales)
    assert (segundo.nuevos, segundo.actualizados) == (0, 4)
    assert len(await _filas(conn, servicio_id)) == 4


@pytest.mark.asyncio
async def test_reauditar_no_pisa_decididos_y_retira_pendientes_que_ahora_son_tramo(entorno):
    from core.services.cromo import auditoria_huerfanos

    sesion, servicio_id, conn = entorno
    tramos, residuales = _escenario()
    await _auditar(sesion, servicio_id, tramos, residuales)
    filas = await _filas(conn, servicio_id)
    await auditoria_huerfanos.descartar(sesion, [filas[_PELO_PROTEGIDO]["id"]], usuario="admin")

    # El dañado ahora está en un tramo; el protegido sigue residual pero ya está DESCARTADO.
    tramo_nuevo = _tracking(_PELO_DANADO, {_PELO_DANADO}, residuales[1].extremos)
    resumen = await _auditar(sesion, servicio_id, [*tramos, tramo_nuevo], [residuales[0], residuales[2]])

    filas = await _filas(conn, servicio_id)
    assert _PELO_DANADO not in filas
    assert resumen.retirados == 1
    assert filas[_PELO_PROTEGIDO]["estado"] == "DESCARTADO"


@pytest.mark.asyncio
async def test_normalizar_solo_cable_desuso_no_protegido_y_restaurar_vuelve_a_pendiente(entorno):
    from core.services.cromo import auditoria_huerfanos, pelos_excluidos

    sesion, servicio_id, conn = entorno
    tramos, residuales = _escenario()
    await _auditar(sesion, servicio_id, tramos, residuales)
    filas = await _filas(conn, servicio_id)
    ids = {p: f["id"] for p, f in filas.items()}

    resultado = await auditoria_huerfanos.normalizar(sesion, list(ids.values()) + [-1], usuario="admin")

    assert sorted(resultado.aplicados) == sorted([ids[_PELO_DESUSO], ids[_PELO_DESUSO_2]])
    rechazados = {r["id"]: r["motivo"] for r in resultado.rechazados}
    assert "PELO_DANADO" in rechazados[ids[_PELO_DANADO]]
    assert "Protegido" in rechazados[ids[_PELO_PROTEGIDO]]
    assert rechazados[-1] == "No existe."

    excluidos = (
        await conn.execute(
            text(
                "SELECT pelo_n_id, origen, auditoria_id, motivo, excluido_por "
                "FROM app.cromo_servicio_pelo_excluido WHERE servicio_id = :s ORDER BY pelo_n_id"
            ),
            {"s": servicio_id},
        )
    ).mappings().all()
    assert [dict(x) for x in excluidos] == [
        {"pelo_n_id": _PELO_DESUSO, "origen": "AUDITORIA", "auditoria_id": ids[_PELO_DESUSO],
         "motivo": "CABLE_DESUSO", "excluido_por": "admin"},
        {"pelo_n_id": _PELO_DESUSO_2, "origen": "AUDITORIA", "auditoria_id": ids[_PELO_DESUSO_2],
         "motivo": "CABLE_DESUSO", "excluido_por": "admin"},
    ]
    filas = await _filas(conn, servicio_id)
    assert filas[_PELO_DESUSO]["estado"] == "NORMALIZADO"
    assert filas[_PELO_DANADO]["estado"] == "PENDIENTE"

    # Normalizar otra vez lo ya normalizado se rechaza, no duplica.
    otra = await auditoria_huerfanos.normalizar(sesion, [ids[_PELO_DESUSO]], usuario="admin")
    assert otra.aplicados == [] and "NORMALIZADO" in otra.rechazados[0]["motivo"]

    assert await pelos_excluidos.restaurar_pelo(sesion, servicio_id, _PELO_DESUSO, usuario="admin2")
    filas = await _filas(conn, servicio_id)
    assert filas[_PELO_DESUSO]["estado"] == "PENDIENTE"
    assert filas[_PELO_DESUSO_2]["estado"] == "NORMALIZADO"


@pytest.mark.asyncio
async def test_restaurar_exclusion_manual_no_toca_la_auditoria(entorno):
    from core.services.cromo import auditoria_huerfanos, pelos_excluidos

    sesion, servicio_id, conn = entorno
    tramos, residuales = _escenario()
    await _auditar(sesion, servicio_id, tramos, residuales)
    filas = await _filas(conn, servicio_id)
    await auditoria_huerfanos.descartar(sesion, [filas[_PELO_DANADO]["id"]], usuario="admin")
    await pelos_excluidos.excluir_pelos(sesion, servicio_id, [_PELO_DANADO], usuario="admin")
    origen = (
        await conn.execute(
            text(
                "SELECT origen FROM app.cromo_servicio_pelo_excluido "
                "WHERE servicio_id = :s AND pelo_n_id = :p"
            ),
            {"s": servicio_id, "p": _PELO_DANADO},
        )
    ).scalar_one()
    assert origen == "MANUAL"
    assert await pelos_excluidos.restaurar_pelo(sesion, servicio_id, _PELO_DANADO, usuario="admin")
    assert (await _filas(conn, servicio_id))[_PELO_DANADO]["estado"] == "DESCARTADO"


@pytest.mark.asyncio
async def test_normalizar_pelo_ya_excluido_a_mano_se_rechaza_y_queda_pendiente(entorno):
    from core.services.cromo import auditoria_huerfanos, pelos_excluidos

    sesion, servicio_id, conn = entorno
    tramos, residuales = _escenario()
    await _auditar(sesion, servicio_id, tramos, residuales)
    filas = await _filas(conn, servicio_id)
    await pelos_excluidos.excluir_pelos(sesion, servicio_id, [_PELO_DESUSO], usuario="admin")

    resultado = await auditoria_huerfanos.normalizar(
        sesion, [filas[_PELO_DESUSO]["id"], filas[_PELO_DESUSO_2]["id"]], usuario="admin"
    )
    assert resultado.aplicados == [filas[_PELO_DESUSO_2]["id"]]
    assert (await _filas(conn, servicio_id))[_PELO_DESUSO]["estado"] == "PENDIENTE"


@pytest.mark.asyncio
async def test_listar_filtra_y_cuenta_por_causa(entorno):
    from core.services.cromo import auditoria_huerfanos

    sesion, servicio_id, _conn = entorno
    tramos, residuales = _escenario()
    await _auditar(sesion, servicio_id, tramos, residuales)

    pagina = await auditoria_huerfanos.listar_huerfanos(
        sesion, servicio_id=servicio_id, causa="CABLE_DESUSO", estado="PENDIENTE"
    )
    assert pagina["total"] == 3
    assert pagina["conteos_por_causa"]["CABLE_DESUSO"] == 3
    assert pagina["conteos_por_causa"]["PELO_DANADO"] == 1
    por_pelo = {i["pelo_n_id"]: i for i in pagina["items"]}
    assert por_pelo[_PELO_DESUSO]["normalizable"] is True
    assert por_pelo[_PELO_DESUSO]["cable_nombre"] == f"F-TEST-{_CABLE_SIN_USO}"
    assert por_pelo[_PELO_DESUSO]["servicio_numero"] == _SERVICIO_NUMERO
    assert por_pelo[_PELO_PROTEGIDO]["normalizable"] is False


@pytest.mark.asyncio
async def test_check_constraints_de_la_migracion(entorno):
    sesion, servicio_id, conn = entorno
    for columna, valor in (("estado", "OTRO"), ("causa", "OTRA")):
        with pytest.raises(Exception):
            async with conn.begin_nested():
                await conn.execute(
                    text(
                        f"INSERT INTO app.cromo_auditoria_huerfanos (servicio_id, pelo_n_id, {columna}) "
                        "VALUES (:s, 1, :v)"
                    ),
                    {"s": servicio_id, "v": valor},
                )
    with pytest.raises(Exception):
        async with conn.begin_nested():
            await conn.execute(
                text(
                    "INSERT INTO app.cromo_servicio_pelo_excluido (servicio_id, pelo_n_id, origen) "
                    "VALUES (:s, 1, 'OTRO')"
                ),
                {"s": servicio_id},
            )


@pytest.mark.asyncio
async def test_downgrade_quita_tabla_y_columnas(entorno):
    _sesion, _servicio_id, conn = entorno
    await conn.run_sync(_correr, "downgrade")
    assert (
        await conn.execute(text("SELECT to_regclass('app.cromo_auditoria_huerfanos')"))
    ).scalar() is None
    columnas = (
        await conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'app' AND table_name = 'cromo_servicio_pelo_excluido'"
            )
        )
    ).scalars().all()
    assert "origen" not in columnas and "auditoria_id" not in columnas


@pytest.mark.asyncio
async def test_servicios_por_pelos_ordena_por_pelos_y_descuenta_excluidos(entorno):
    """La query de la corrida global (arms de igualdad en vez del OR) sobre la DB real: un Servicio
    sintético con 2000 pelos —por alias— queda primero, y un pelo excluido no cuenta."""
    from core.services.cromo.auditoria_huerfanos_global import servicios_por_pelos

    sesion, _servicio_id, conn = entorno
    grande = (
        await conn.execute(
            text(
                "INSERT INTO app.servicios (servicio_id, estado_servicio, alias_ids) "
                "VALUES ('99991502', 'Activo', ARRAY['99991503']) RETURNING id"
            )
        )
    ).scalar_one()
    await conn.execute(
        text(
            "INSERT INTO app.cromo_pelos (n_id, tubo_n_id, cable_n_id) "
            "SELECT g, 1, :c FROM generate_series(999916000, 999917999) g"
        ),
        {"c": _CABLE_TRAMO},
    )
    await conn.execute(
        text(
            "INSERT INTO app.cromo_servicio_match (pelo_n_id, servicio_numero, metodo) "
            "SELECT g, '99991503', 'REGEX_EXACTO' FROM generate_series(999916000, 999917999) g"
        )
    )
    await conn.execute(
        text(
            "INSERT INTO app.cromo_servicio_pelo_excluido (servicio_id, pelo_n_id) "
            "VALUES (:s, 999916000)"
        ),
        {"s": grande},
    )

    primeros = await servicios_por_pelos(sesion, 3)

    assert primeros[0] == (grande, 1999)
    assert [p for _s, p in primeros] == sorted((p for _s, p in primeros), reverse=True)
