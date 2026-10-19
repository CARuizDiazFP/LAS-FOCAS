# Nombre de archivo: test_cromo_arbitro_acciones_real_db.py
# Ubicación de archivo: tests/test_cromo_arbitro_acciones_real_db.py
# Descripción: Tests contra Postgres real de las acciones aplicables y reversibles del árbitro de Cromo

"""Corren dentro de una transacción que se revierte, con ids sintéticos `999_920_5xx` y un número de
servicio que no existe en la base real. Son las únicas funciones del árbitro que mutan datos reales,
así que cada test verifica en la base lo que quedó, no sólo lo que devuelve la función."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from core.services.cromo.arbitro.acciones import AccionNoAplicable, aplicar, revertir
from core.services.cromo.arbitro.senales import USUARIO_ARBITRO
from core.services.cromo.servicios_sin_odf import listar_servicios_sin_odf
from db.models.cromo import CromoBotella, CromoBotellaAlias, CromoPropuesta
from db.session import async_engine
from tests.soporte_postgres_real import requiere_postgres_real
from tests.test_cromo_arbitro_migracion_real_db import _correr

pytestmark = requiere_postgres_real

_NUMERO = "999920501"
_ODF = 999_920_510
_PELO = 999_920_511
_ORIGEN = 999_920_520
_DESTINO = 999_920_521
_DEPENDIENTE = 999_920_522
_CABLE_DESTINO = 999_920_530
_CABLE_ORIGEN = 999_920_531
_NOMBRE = "QA Arbitro Acciones Zzyzx 999920"

# La propuesta se crea "hace una hora": dentro de la transacción del test `now()` es constante, así
# que sin esto un override "posterior" empataría con la propuesta en `creado_en`.
_HACE_UNA_HORA = datetime.now(timezone.utc) - timedelta(hours=1)


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


async def _servicio(conn) -> int:
    return (
        await conn.execute(
            text(
                "INSERT INTO app.servicios (servicio_id, numero_primer_servicio, nombre_cliente, "
                "categoria, origen_datos, estado_servicio, es_verificable) "
                "VALUES (:n, :n, 'QA Arbitro Acciones', 6, 'INGEST_EXCEL', 'Activo', true) RETURNING id"
            ),
            {"n": _NUMERO},
        )
    ).scalar_one()


async def _odf(conn) -> None:
    await conn.execute(
        text(
            "INSERT INTO app.cromo_odfs (n_id, version_id, vmax, clase, nombre, payload_raw) "
            "VALUES (:n, :n, 1, 69, :nombre, '{}'::jsonb)"
        ),
        {"n": _ODF, "nombre": _NOMBRE},
    )


async def _override_manual(conn, servicio_id: int, creado_en: datetime) -> int:
    return (
        await conn.execute(
            text(
                "INSERT INTO app.cromo_servicio_odf_override "
                "(servicio_id, odf_n_id, categoria_causa, usuario, creado_en) "
                "VALUES (:s, :o, 'OTRO', 'operador-qa', :c) RETURNING id"
            ),
            {"s": servicio_id, "o": _ODF, "c": creado_en},
        )
    ).scalar_one()


async def _botella(conn, n_id: int, *, vigente: bool = True) -> None:
    await conn.execute(
        text(
            "INSERT INTO app.cromo_botellas (n_id, version_id, vmax, clase, nombre, payload_raw, vigente) "
            "VALUES (:n, :n, 1, 68, :nombre, '{}'::jsonb, :v)"
        ),
        {"n": n_id, "nombre": _NOMBRE, "v": vigente},
    )


async def _cable(conn, n_id: int, extremo: int) -> None:
    await conn.execute(
        text(
            "INSERT INTO app.cromo_cables (n_id, version_id, vmax, extremo_a_n_id, payload_raw) "
            "VALUES (:n, :n, 1, :e, '{}'::jsonb)"
        ),
        {"n": n_id, "e": extremo},
    )


async def _alias(conn, origen: int, destino: int, creado_por: str) -> None:
    await conn.execute(
        text(
            "INSERT INTO app.cromo_botella_alias (id_cromo_origen, id_cromo_destino, accion, creado_por) "
            "VALUES (:o, :d, 'fusionar', :c)"
        ),
        {"o": origen, "d": destino, "c": creado_por},
    )


async def _propuesta(sesion, *, regla, objeto_tipo, objeto_id, accion, parametros) -> CromoPropuesta:
    propuesta = CromoPropuesta(
        regla=regla,
        objeto_tipo=objeto_tipo,
        objeto_id=objeto_id,
        accion=accion,
        parametros=parametros,
        confianza=95,
        senales=[],
        evidencia_hash="0" * 64,
        estado="PROPUESTA",
        modo_al_evaluar="AUTO",
        disparo="VIEWER",
        creada_en=_HACE_UNA_HORA,
    )
    sesion.add(propuesta)
    await sesion.flush()
    return propuesta


async def _propuesta_asociar(sesion, servicio_id: int) -> CromoPropuesta:
    return await _propuesta(
        sesion,
        regla="ODF_POR_CAMINO",
        objeto_tipo="SERVICIO",
        objeto_id=servicio_id,
        accion="ASOCIAR_ODF",
        parametros={"odf_n_id": _ODF, "pelo_n_id": _PELO, "odfs_extremo": [_ODF]},
    )


async def _propuesta_fusionar(sesion) -> CromoPropuesta:
    return await _propuesta(
        sesion,
        regla="GEMELO_VACIO",
        objeto_tipo="BOTELLA",
        objeto_id=_ORIGEN,
        accion="FUSIONAR_GEMELO",
        parametros={"origen": _ORIGEN, "destino": _DESTINO},
    )


async def _overrides(conn, servicio_id: int) -> list[tuple]:
    return (
        await conn.execute(
            text(
                "SELECT origen, odf_n_id, pelo_n_id, categoria_causa, usuario, propuesta_id "
                "FROM app.cromo_servicio_odf_override WHERE servicio_id = :s ORDER BY id"
            ),
            {"s": servicio_id},
        )
    ).all()


async def _alias_de(conn, origen: int):
    return (
        await conn.execute(
            text(
                "SELECT id_cromo_destino, accion, creado_por FROM app.cromo_botella_alias "
                "WHERE id_cromo_origen = :o"
            ),
            {"o": origen},
        )
    ).first()


async def _vigente(conn, n_id: int) -> bool:
    return (
        await conn.execute(text("SELECT vigente FROM app.cromo_botellas WHERE n_id = :n"), {"n": n_id})
    ).scalar_one()


# ── ASOCIAR_ODF ──────────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_asociar_odf_crea_override_auto_y_sale_de_sin_odf(entorno):
    sesion, conn = entorno
    sid = await _servicio(conn)
    await _odf(conn)
    assert (await listar_servicios_sin_odf(sesion, q=_NUMERO)).total == 1

    propuesta = await _propuesta_asociar(sesion, sid)
    reversion = await aplicar(sesion, propuesta)

    filas = await _overrides(conn, sid)
    assert len(filas) == 1
    assert tuple(filas[0]) == ("AUTO", _ODF, _PELO, "EVIDENCIA_CAMINO", USUARIO_ARBITRO, propuesta.id)
    override_id = (
        await conn.execute(
            text("SELECT id FROM app.cromo_servicio_odf_override WHERE servicio_id = :s"), {"s": sid}
        )
    ).scalar_one()
    assert reversion == {"override_id": override_id}
    assert (await listar_servicios_sin_odf(sesion, q=_NUMERO)).total == 0


@pytest.mark.asyncio
async def test_revertir_asociar_borra_solo_la_fila_auto(entorno):
    sesion, conn = entorno
    sid = await _servicio(conn)
    await _odf(conn)
    await _override_manual(conn, sid, _HACE_UNA_HORA - timedelta(hours=1))

    propuesta = await _propuesta_asociar(sesion, sid)
    propuesta.reversion = await aplicar(sesion, propuesta)
    assert [f.origen for f in await _overrides(conn, sid)] == ["MANUAL", "AUTO"]

    await revertir(sesion, propuesta)

    filas = await _overrides(conn, sid)
    assert [(f.origen, f.usuario) for f in filas] == [("MANUAL", "operador-qa")]


@pytest.mark.asyncio
async def test_revertir_asociar_no_borra_manual_aunque_apunte_su_id(entorno):
    """Si la reversión trajera el id de una fila MANUAL, el filtro `origen = 'AUTO'` la protege."""
    sesion, conn = entorno
    sid = await _servicio(conn)
    await _odf(conn)
    manual_id = await _override_manual(conn, sid, _HACE_UNA_HORA - timedelta(hours=1))
    propuesta = await _propuesta_asociar(sesion, sid)
    propuesta.reversion = {"override_id": manual_id}

    with pytest.raises(AccionNoAplicable, match="override_ausente"):
        await revertir(sesion, propuesta)

    assert [f.origen for f in await _overrides(conn, sid)] == ["MANUAL"]


@pytest.mark.asyncio
async def test_asociar_con_override_manual_posterior_no_aplica(entorno):
    sesion, conn = entorno
    sid = await _servicio(conn)
    await _odf(conn)
    propuesta = await _propuesta_asociar(sesion, sid)
    # El operador asocia a mano DESPUÉS de que el árbitro propuso.
    await _override_manual(conn, sid, _HACE_UNA_HORA + timedelta(minutes=30))

    with pytest.raises(AccionNoAplicable, match="override_manual"):
        await aplicar(sesion, propuesta)

    assert [f.origen for f in await _overrides(conn, sid)] == ["MANUAL"]


# ── FUSIONAR_GEMELO ──────────────────────────────────────────────────────────────────────────────


async def _par_gemelo(conn) -> None:
    await _botella(conn, _ORIGEN)
    await _botella(conn, _DESTINO)
    await _cable(conn, _CABLE_DESTINO, _DESTINO)


@pytest.mark.asyncio
async def test_fusionar_gemelo_y_revertir_restituye_vigente_y_quita_alias(entorno):
    sesion, conn = entorno
    await _par_gemelo(conn)
    propuesta = await _propuesta_fusionar(sesion)

    propuesta.reversion = await aplicar(sesion, propuesta)

    assert propuesta.reversion == {"alias_origen": _ORIGEN}
    alias = await _alias_de(conn, _ORIGEN)
    assert tuple(alias) == (_DESTINO, "fusionar", USUARIO_ARBITRO)
    assert await _vigente(conn, _ORIGEN) is False
    assert await _vigente(conn, _DESTINO) is True

    await revertir(sesion, propuesta)

    assert await _alias_de(conn, _ORIGEN) is None
    assert await _vigente(conn, _ORIGEN) is True
    assert await _vigente(conn, _DESTINO) is True


@pytest.mark.asyncio
async def test_fusionar_y_revertir_restituye_alias_dependientes(entorno):
    """`consolidar_grupo_botellas` repunta al destino los alias que apuntaban al origen; revertir
    tiene que devolverlos al origen o la reversión no es exacta."""
    sesion, conn = entorno
    await _par_gemelo(conn)
    await _botella(conn, _DEPENDIENTE, vigente=False)
    await _alias(conn, _DEPENDIENTE, _ORIGEN, "operador-qa")
    propuesta = await _propuesta_fusionar(sesion)

    propuesta.reversion = await aplicar(sesion, propuesta)
    assert (await _alias_de(conn, _DEPENDIENTE)).id_cromo_destino == _DESTINO

    await revertir(sesion, propuesta)

    assert tuple(await _alias_de(conn, _DEPENDIENTE)) == (_ORIGEN, "fusionar", "operador-qa")
    assert await _alias_de(conn, _ORIGEN) is None
    assert await _vigente(conn, _ORIGEN) is True


@pytest.mark.asyncio
async def test_fusionar_gemelo_que_gano_cables_no_aplica(entorno):
    sesion, conn = entorno
    await _par_gemelo(conn)
    propuesta = await _propuesta_fusionar(sesion)
    # Entre la propuesta y la aplicación, la botella vacía ganó un cable.
    await _cable(conn, _CABLE_ORIGEN, _ORIGEN)

    with pytest.raises(AccionNoAplicable, match="gemelo_cambio"):
        await aplicar(sesion, propuesta)

    assert await _alias_de(conn, _ORIGEN) is None
    assert await _vigente(conn, _ORIGEN) is True


@pytest.mark.asyncio
async def test_fusionar_gemelo_con_fusion_en_origen_no_aplica(entorno):
    sesion, conn = entorno
    await _par_gemelo(conn)
    await conn.execute(
        text("INSERT INTO app.cromo_fusiones (n_id, botella_n_id) VALUES (:n, :b)"),
        {"n": _CABLE_ORIGEN, "b": _ORIGEN},
    )
    propuesta = await _propuesta_fusionar(sesion)

    with pytest.raises(AccionNoAplicable, match="gemelo_cambio"):
        await aplicar(sesion, propuesta)


@pytest.mark.asyncio
async def test_fusionar_gemelo_con_destino_sin_cables_no_aplica(entorno):
    sesion, conn = entorno
    await _botella(conn, _ORIGEN)
    await _botella(conn, _DESTINO)
    propuesta = await _propuesta_fusionar(sesion)

    with pytest.raises(AccionNoAplicable, match="gemelo_cambio"):
        await aplicar(sesion, propuesta)


@pytest.mark.asyncio
async def test_fusionar_gemelo_con_origen_no_vigente_no_aplica(entorno):
    sesion, conn = entorno
    await _botella(conn, _ORIGEN, vigente=False)
    await _botella(conn, _DESTINO)
    await _cable(conn, _CABLE_DESTINO, _DESTINO)
    propuesta = await _propuesta_fusionar(sesion)

    with pytest.raises(AccionNoAplicable, match="gemelo_cambio"):
        await aplicar(sesion, propuesta)


@pytest.mark.asyncio
async def test_fusionar_gemelo_con_destino_aliasado_no_aplica(entorno):
    """El destino ya fue fusionado hacia otra botella: no puede ser el golden record."""
    sesion, conn = entorno
    await _par_gemelo(conn)
    await _botella(conn, _DEPENDIENTE)
    await _alias(conn, _DESTINO, _DEPENDIENTE, "operador-qa")
    propuesta = await _propuesta_fusionar(sesion)

    with pytest.raises(AccionNoAplicable, match="gemelo_cambio"):
        await aplicar(sesion, propuesta)

    assert await _alias_de(conn, _ORIGEN) is None


@pytest.mark.asyncio
async def test_fusionar_gemelo_con_origen_ya_aliasado_no_aplica(entorno):
    """Consolidar pisaría un alias previo del origen y revertir lo borraría: no se aplica."""
    sesion, conn = entorno
    await _par_gemelo(conn)
    await _alias(conn, _ORIGEN, _DESTINO, "operador-qa")
    propuesta = await _propuesta_fusionar(sesion)

    with pytest.raises(AccionNoAplicable, match="gemelo_cambio"):
        await aplicar(sesion, propuesta)

    assert tuple(await _alias_de(conn, _ORIGEN)) == (_DESTINO, "fusionar", "operador-qa")


@pytest.mark.asyncio
async def test_revertir_fusion_con_alias_cambiado_por_operador_no_toca_nada(entorno):
    sesion, conn = entorno
    await _par_gemelo(conn)
    propuesta = await _propuesta_fusionar(sesion)
    propuesta.reversion = await aplicar(sesion, propuesta)
    await conn.execute(
        text("UPDATE app.cromo_botella_alias SET creado_por = 'operador-qa' WHERE id_cromo_origen = :o"),
        {"o": _ORIGEN},
    )

    with pytest.raises(AccionNoAplicable, match="alias_cambio"):
        await revertir(sesion, propuesta)

    assert (await _alias_de(conn, _ORIGEN)).creado_por == "operador-qa"
    assert await _vigente(conn, _ORIGEN) is False


# ── INFORMAR ─────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_informar_no_aplica(entorno):
    sesion, _ = entorno
    propuesta = await _propuesta(
        sesion,
        regla="ODF_GEMELA_ISLA",
        objeto_tipo="ODF",
        objeto_id=_ODF,
        accion="INFORMAR",
        parametros={"isla": _ODF, "gemela": _ODF + 1},
    )

    with pytest.raises(AccionNoAplicable, match="solo_informativa"):
        await aplicar(sesion, propuesta)
    with pytest.raises(AccionNoAplicable, match="solo_informativa"):
        await revertir(sesion, propuesta)


# ── Fix ronda 1: estado ORM tras revertir y filas ausentes ───────────────────────────────────────


@pytest.mark.asyncio
async def test_aplicar_revertir_aplicar_misma_sesion(entorno):
    """`revertir` usa SQL directo: sin expirar el identity map, el segundo `aplicar` en la misma
    sesión vería el origen todavía `vigente=False` y los dependientes ya repuntados, y saltearía los
    UPDATE (fusión aplicada a medias)."""
    sesion, conn = entorno
    await _par_gemelo(conn)
    await _botella(conn, _DEPENDIENTE, vigente=False)
    await _alias(conn, _DEPENDIENTE, _ORIGEN, "operador-qa")
    propuesta = await _propuesta_fusionar(sesion)

    # El identity map es débil: los objetos quedan stale cuando el llamador los retiene (p. ej. los
    # cargó por ORM antes de aplicar, como un endpoint que muestra la botella). Se reproduce eso.
    retenidos = [
        await sesion.get(CromoBotella, _ORIGEN),
        (
            await sesion.execute(
                select(CromoBotellaAlias).where(CromoBotellaAlias.id_cromo_origen == _DEPENDIENTE)
            )
        ).scalar_one(),
    ]

    propuesta.reversion = await aplicar(sesion, propuesta)
    await revertir(sesion, propuesta)
    assert await _vigente(conn, _ORIGEN) is True
    assert (await _alias_de(conn, _DEPENDIENTE)).id_cromo_destino == _ORIGEN

    propuesta.reversion = await aplicar(sesion, propuesta)
    assert await _vigente(conn, _ORIGEN) is False
    assert (await _alias_de(conn, _DEPENDIENTE)).id_cromo_destino == _DESTINO
    assert tuple(await _alias_de(conn, _ORIGEN)) == (_DESTINO, "fusionar", USUARIO_ARBITRO)

    await revertir(sesion, propuesta)
    assert await _vigente(conn, _ORIGEN) is True
    assert (await _alias_de(conn, _DEPENDIENTE)).id_cromo_destino == _ORIGEN
    assert await _alias_de(conn, _ORIGEN) is None
    assert retenidos


@pytest.mark.asyncio
async def test_revertir_asociar_sin_fila_auto_no_aplica(entorno):
    sesion, conn = entorno
    sid = await _servicio(conn)
    await _odf(conn)
    propuesta = await _propuesta_asociar(sesion, sid)
    propuesta.reversion = await aplicar(sesion, propuesta)
    await conn.execute(
        text("DELETE FROM app.cromo_servicio_odf_override WHERE id = :id"),
        {"id": propuesta.reversion["override_id"]},
    )

    with pytest.raises(AccionNoAplicable, match="override_ausente"):
        await revertir(sesion, propuesta)


@pytest.mark.asyncio
async def test_revertir_no_devuelve_dependiente_repuntado_por_otro(entorno):
    sesion, conn = entorno
    await _par_gemelo(conn)
    await _botella(conn, _DEPENDIENTE, vigente=False)
    await _alias(conn, _DEPENDIENTE, _ORIGEN, "operador-qa")
    otro = 999_920_523
    await _botella(conn, otro)
    propuesta = await _propuesta_fusionar(sesion)
    propuesta.reversion = await aplicar(sesion, propuesta)
    # Un operador repunta el dependiente a otra botella mientras la propuesta está en observación.
    await conn.execute(
        text("UPDATE app.cromo_botella_alias SET id_cromo_destino = :d WHERE id_cromo_origen = :o"),
        {"d": otro, "o": _DEPENDIENTE},
    )

    await revertir(sesion, propuesta)

    assert (await _alias_de(conn, _DEPENDIENTE)).id_cromo_destino == otro
    assert await _alias_de(conn, _ORIGEN) is None
    assert await _vigente(conn, _ORIGEN) is True
