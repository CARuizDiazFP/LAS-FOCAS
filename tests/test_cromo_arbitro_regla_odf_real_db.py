# Nombre de archivo: test_cromo_arbitro_regla_odf_real_db.py
# Ubicación de archivo: tests/test_cromo_arbitro_regla_odf_real_db.py
# Descripción: Tests contra Postgres real de la carga de las reglas ODF_POR_CAMINO y CONTRADICCION_SERVICIO

"""Corren dentro de una transacción que se revierte. Usan alcance `SERVICIOS`, así que sólo cuenta la
evidencia en vivo (`cromo_evidencia_camino`); el BFS local corre únicamente con alcance `TODO`."""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from core.services.cromo.arbitro.evidencia import EvidenciaEntrada, registrar_evidencia
from core.services.cromo.arbitro.reglas.odf_por_camino import (
    REGLA_ODF,
    ReglaContradiccionServicio,
    ReglaOdfPorCamino,
)
from core.services.cromo.arbitro.senales import Alcance
from core.services.cromo.camino_optico_service import TIPO_CONECTOR_ODF
from core.services.cromo.tracking_service import ExtremoCamino, ResumenCamino
from db.session import async_engine
from tests.soporte_postgres_real import requiere_postgres_real
from tests.test_cromo_arbitro_migracion_real_db import _correr, _servicio

pytestmark = requiere_postgres_real

_PELO = 999_920_301
_ODF_A = 999_920_310
_ODF_B = 999_920_320
_VERSION_B = 999_920_321


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
            for n_id, version in ((_ODF_A, _ODF_A), (_ODF_B, _VERSION_B)):
                await conn.execute(
                    text(
                        "INSERT INTO app.cromo_odfs (n_id, version_id, vmax, clase, nombre, payload_raw) "
                        "VALUES (:n, :v, 1, 69, 'ODF QA Arbitro', '{}'::jsonb)"
                    ),
                    {"n": n_id, "v": version},
                )
            yield sesion, conn
            await sesion.close()
        finally:
            await trans.rollback()
    await engine.dispose()


def _extremos(odf_id: int) -> list[dict]:
    inicio = ExtremoCamino(tipo="PELO", id_cromo=_PELO, clase=130)
    fin = ExtremoCamino(
        tipo=TIPO_CONECTOR_ODF, id_cromo=odf_id + 5, clase=136, odf_id=odf_id,
        servicio_at62="99992001", pelo_conectado=_PELO,
    )
    return [asdict(inicio), asdict(fin)]


async def _evidencia(conn, sid: int, odf_id: int, *, dias: int = 0) -> None:
    await conn.execute(
        text(
            "INSERT INTO app.cromo_evidencia_camino "
            "(servicio_id, pelo_n_id, completo, extremos, pelos_camino, fuente, generado_at) "
            "VALUES (:s, :p, true, CAST(:e AS jsonb), ARRAY[:p ::bigint], 'WEB', "
            "now() - make_interval(days => :d))"
        ),
        {"s": sid, "p": _PELO, "e": json.dumps(_extremos(odf_id)), "d": dias},
    )


async def _override(conn, sid: int, origen: str) -> None:
    await conn.execute(
        text(
            "INSERT INTO app.cromo_servicio_odf_override "
            "(servicio_id, odf_n_id, categoria_causa, usuario, origen) "
            "VALUES (:s, :o, 'EVIDENCIA_CAMINO', 'qa', :origen)"
        ),
        {"s": sid, "o": _ODF_A, "origen": origen},
    )


async def _evaluar(sesion, sid: int, propios: frozenset[int] = frozenset()):
    return await ReglaOdfPorCamino().evaluar(
        sesion, Alcance("SERVICIOS", (sid,)), propios=propios, contexto={}
    )


@pytest.mark.asyncio
async def test_evidencia_fresca_propone_odf(entorno):
    sesion, conn = entorno
    sid = await _servicio(conn)
    await _evidencia(conn, sid, _ODF_A)
    (ev,) = await _evaluar(sesion, sid)
    assert ev.regla == REGLA_ODF and ev.objeto_id == sid
    assert ev.parametros["odf_n_id"] == _ODF_A and ev.parametros["pelo_n_id"] == _PELO
    codigos = {s.codigo for s in ev.senales}
    assert {"CAMINO_VIVO_COMPLETO", "AT62_COINCIDE", "CONECTOR_LIBRE"} <= codigos
    assert ev.tope == 100


@pytest.mark.asyncio
async def test_evidencia_vencida_no_cuenta(entorno):
    sesion, conn = entorno
    sid = await _servicio(conn)
    await _evidencia(conn, sid, _ODF_A, dias=31)
    assert await _evaluar(sesion, sid) == []


@pytest.mark.asyncio
async def test_override_manual_saca_del_universo(entorno):
    sesion, conn = entorno
    sid = await _servicio(conn)
    await _evidencia(conn, sid, _ODF_A)
    await _override(conn, sid, "MANUAL")
    assert await _evaluar(sesion, sid) == []
    assert await _evaluar(sesion, sid, frozenset({sid})) == []


@pytest.mark.asyncio
async def test_override_auto_propio_sigue_en_universo(entorno):
    sesion, conn = entorno
    sid = await _servicio(conn)
    await _evidencia(conn, sid, _ODF_A)
    await _override(conn, sid, "AUTO")
    (ev,) = await _evaluar(sesion, sid, frozenset({sid}))
    assert ev.parametros["odf_n_id"] == _ODF_A
    # Un AUTO que no está en observación de esta regla ya salió del listado "sin ODF".
    assert await _evaluar(sesion, sid) == []


@pytest.mark.asyncio
async def test_odf_por_version_id_se_resuelve_a_n_id(entorno):
    sesion, conn = entorno
    sid = await _servicio(conn)
    await _evidencia(conn, sid, _VERSION_B)
    (ev,) = await _evaluar(sesion, sid)
    assert ev.parametros["odf_n_id"] == _ODF_B
    assert "ODF_SIN_FILA" not in {s.codigo for s in ev.senales}


@pytest.mark.asyncio
async def test_odf_inexistente_veta(entorno):
    sesion, conn = entorno
    sid = await _servicio(conn)
    await _evidencia(conn, sid, 999_920_399)
    (ev,) = await _evaluar(sesion, sid)
    assert any(s.codigo == "ODF_SIN_FILA" and s.veto for s in ev.senales)


@pytest.mark.asyncio
async def test_evidencia_actualizada_cambia_parametros(entorno):
    sesion, conn = entorno
    sid = await _servicio(conn)

    def entrada(odf_id: int) -> EvidenciaEntrada:
        inicio, fin = (ExtremoCamino(**e) for e in _extremos(odf_id))
        return EvidenciaEntrada(_PELO, ResumenCamino(inicio=inicio, fin=fin), frozenset({_PELO}))

    assert await registrar_evidencia(sesion, sid, [entrada(_ODF_A)], completo=True, fuente="WEB") == 1
    (antes,) = await _evaluar(sesion, sid)
    assert antes.parametros["odf_n_id"] == _ODF_A
    assert await registrar_evidencia(sesion, sid, [entrada(_ODF_B)], completo=True, fuente="SLACK") == 1
    (despues,) = await _evaluar(sesion, sid)
    assert despues.parametros["odf_n_id"] == _ODF_B


@pytest.mark.asyncio
async def test_conector_de_otro_servicio_emite_contradiccion(entorno):
    sesion, conn = entorno
    sid = await _servicio(conn)
    await _evidencia(conn, sid, _ODF_A)
    await conn.execute(
        text(
            "INSERT INTO app.cromo_odf_conectores (n_id, odf_n_id, servicio_resuelto, payload_raw) "
            "VALUES (:c, :o, '99992999', '{}'::jsonb)"
        ),
        {"c": _ODF_A + 5, "o": _ODF_A},
    )
    contexto: dict = {}
    alcance = Alcance("SERVICIOS", (sid,))
    (contra,) = await ReglaContradiccionServicio().evaluar(
        sesion, alcance, propios=frozenset(), contexto=contexto
    )
    assert dict(contra.parametros) == {
        "conector_n_id": _ODF_A + 5,
        "odf_n_id": _ODF_A,
        "servicio_conector": "99992999",
    }
    # El único conector es de otro servicio: no hay ODF válida que proponer.
    assert await ReglaOdfPorCamino().evaluar(
        sesion, alcance, propios=frozenset(), contexto=contexto
    ) == []
    # Las dos reglas comparten una sola carga.
    assert len(contexto["odf_por_camino"]["cargas"]) == 1
