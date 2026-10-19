# Nombre de archivo: test_cromo_arbitro_regla_gemelos_real_db.py
# Ubicación de archivo: tests/test_cromo_arbitro_regla_gemelos_real_db.py
# Descripción: Tests contra Postgres real de la carga de las reglas de gemelos del árbitro

"""Corren dentro de una transacción que se revierte, con ids sintéticos `999_920_4xx` y un nombre que
no existe en la base real, para que el grupo homónimo sea sólo el del test."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from core.services.cromo.arbitro.reglas.gemelos import (
    REGLA_GEMELO_VACIO,
    ReglaGemeloVacio,
    ReglaOdfGemelaIsla,
)
from core.services.cromo.arbitro.senales import USUARIO_ARBITRO, Alcance
from db.session import async_engine
from tests.soporte_postgres_real import requiere_postgres_real
from tests.test_cromo_arbitro_migracion_real_db import _correr

pytestmark = requiere_postgres_real

_OPERATIVA = 999_920_401
_VACIA = 999_920_402
_CABLE = 999_920_410
_ODF_ISLA = 999_920_420
_ODF_GEMELA = 999_920_421
_NOMBRE = "QA Arbitro Gemelo Zzyzx 999920"


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


async def _botella(
    conn, n_id: int, *, nombre: str = _NOMBRE, vigente: bool = True, clase: int = 68
) -> None:
    await conn.execute(
        text(
            "INSERT INTO app.cromo_botellas (n_id, version_id, vmax, clase, nombre, payload_raw, vigente) "
            "VALUES (:n, :n, 1, :clase, :nombre, '{}'::jsonb, :v)"
        ),
        {"n": n_id, "nombre": nombre, "v": vigente, "clase": clase},
    )


async def _cable(conn, extremo: int) -> None:
    await conn.execute(
        text(
            "INSERT INTO app.cromo_cables (n_id, version_id, vmax, extremo_a_n_id, payload_raw) "
            "VALUES (:n, :n, 1, :e, '{}'::jsonb)"
        ),
        {"n": _CABLE, "e": extremo},
    )


async def _alias(conn, origen: int, destino: int, creado_por: str | None) -> None:
    await conn.execute(
        text(
            "INSERT INTO app.cromo_botella_alias (id_cromo_origen, id_cromo_destino, accion, creado_por) "
            "VALUES (:o, :d, 'fusionar', :c)"
        ),
        {"o": origen, "d": destino, "c": creado_por},
    )


async def _vacias(sesion, propios: frozenset[int] = frozenset()):
    return await ReglaGemeloVacio().evaluar(
        sesion, Alcance("BOTELLAS", (_VACIA,)), propios=propios, contexto={}
    )


@pytest.mark.asyncio
async def test_carga_agrupa_por_nombre_extendido_sin_camara(entorno):
    sesion, conn = entorno
    await _botella(conn, _OPERATIVA, nombre=_NOMBRE)
    # Misma clave extendida: mayúsculas, puntuación y espacios distintos.
    await _botella(conn, _VACIA, nombre="  qa arbitro, gemelo ZZYZX 999920 ")
    await _cable(conn, _OPERATIVA)

    evs = await _vacias(sesion)

    assert len(evs) == 1
    ev = evs[0]
    assert (ev.regla, ev.objeto_id, ev.accion) == (REGLA_GEMELO_VACIO, _VACIA, "FUSIONAR_GEMELO")
    assert dict(ev.parametros) == {"origen": _VACIA, "destino": _OPERATIVA}
    assert not any(s.veto for s in ev.senales)


@pytest.mark.asyncio
async def test_no_mezcla_clases_en_grupo(entorno):
    sesion, conn = entorno
    await _botella(conn, _OPERATIVA, clase=68)
    await _botella(conn, _VACIA, clase=121)  # caja PON homónima
    await _cable(conn, _OPERATIVA)

    assert await _vacias(sesion) == []


@pytest.mark.asyncio
async def test_propia_fusionada_se_reevalua(entorno):
    sesion, conn = entorno
    await _botella(conn, _OPERATIVA)
    await _botella(conn, _VACIA, vigente=False)
    await _cable(conn, _OPERATIVA)
    await _alias(conn, _VACIA, _OPERATIVA, USUARIO_ARBITRO)

    assert await _vacias(sesion) == []

    evs = await _vacias(sesion, frozenset({_VACIA}))
    assert len(evs) == 1
    assert evs[0].objeto_id == _VACIA
    assert "ALIAS_PREVIO" not in {s.codigo for s in evs[0].senales}


@pytest.mark.asyncio
async def test_alias_de_un_operador_veta(entorno):
    sesion, conn = entorno
    await _botella(conn, _OPERATIVA)
    await _botella(conn, _VACIA)
    await _cable(conn, _OPERATIVA)
    await _alias(conn, _VACIA, _OPERATIVA, "operador-qa")

    (ev,) = await _vacias(sesion, frozenset({_VACIA}))
    assert any(s.codigo == "ALIAS_PREVIO" and s.veto for s in ev.senales)


@pytest.mark.asyncio
async def test_alias_sin_creador_de_una_propia_veta(entorno):
    """`creado_por` NULL no es del árbitro: con lógica trivalente (`=`) el alias se perdía."""
    sesion, conn = entorno
    await _botella(conn, _OPERATIVA)
    await _botella(conn, _VACIA)
    await _cable(conn, _OPERATIVA)
    await _alias(conn, _VACIA, _OPERATIVA, None)

    (ev,) = await _vacias(sesion, frozenset({_VACIA}))
    assert any(s.codigo == "ALIAS_PREVIO" and s.veto for s in ev.senales)


@pytest.mark.asyncio
async def test_odf_isla_con_gemela_homonima(entorno):
    sesion, conn = entorno
    for n_id, (lat, lon) in ((_ODF_ISLA, (-34.6, -58.4)), (_ODF_GEMELA, (-34.6001, -58.4))):
        await conn.execute(
            text(
                "INSERT INTO app.cromo_odfs (n_id, version_id, vmax, clase, nombre, localidad, "
                "latitud, longitud, payload_raw) "
                "VALUES (:n, :n, 1, 69, :nombre, 'QA', :lat, :lon, '{}'::jsonb)"
            ),
            {"n": n_id, "nombre": _NOMBRE if n_id == _ODF_GEMELA else f" {_NOMBRE.upper()} ", "lat": lat, "lon": lon},
        )
    await conn.execute(
        text(
            "INSERT INTO app.cromo_inconsistencia (tipo, objeto_n_id, objeto_clase, nombre, revision, estado) "
            "VALUES ('ELEMENTO_ISLA', :n, 69, :nombre, 'AUTO', 'PENDIENTE')"
        ),
        {"n": _ODF_ISLA, "nombre": _NOMBRE},
    )

    evs = await ReglaOdfGemelaIsla().evaluar(
        sesion, Alcance("ODFS", (_ODF_ISLA,)), propios=frozenset(), contexto={}
    )

    assert len(evs) == 1
    ev = evs[0]
    assert (ev.objeto_tipo, ev.objeto_id, ev.accion) == ("ODF", _ODF_ISLA, "INFORMAR")
    assert dict(ev.parametros) == {"isla": _ODF_ISLA, "gemela": _ODF_GEMELA}
    assert {s.codigo for s in ev.senales} == {"MISMA_LOCALIDAD", "CERCA_50M"}
