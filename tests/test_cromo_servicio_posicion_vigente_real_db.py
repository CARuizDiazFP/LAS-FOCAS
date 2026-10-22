# Nombre de archivo: test_cromo_servicio_posicion_vigente_real_db.py
# Ubicación de archivo: tests/test_cromo_servicio_posicion_vigente_real_db.py
# Descripción: Pruebas contra Postgres real de la posición vigente por conector: posiciones posibles con sus filtros (93150, 42352, 93153), par sugerido, declarar/retirar, estados reales de pelo y camino ajeno por etiqueta dominante (93150/61972, 42351/42352)

"""Casos reales de dev (2026-10-21) que una sesión fake no puede cubrir: lo que se prueba es el SQL
de `posiciones_posibles` (UNION por identidad, filtro de pelo de otro servicio Activo, pelos
excluidos a mano) contra los datos que motivaron cada regla.

- **93150** (`servicios.id=4`): el camino vigente va por O-1252871-1:1/2 (conectores 8604882/83),
  cuyos pelos 7028862/63 llevan la etiqueta `44649` de un servicio de Baja. Tienen que ser
  posiciones posibles con `etiqueta_ajena`.
- **42352** (id 568): sus 11 conectores dicen `servicio_resuelto=42352`, pero los pelos son del
  42351 (id 567, Activo). No tiene que tomar ninguno.
- **93153** (id 16): 8 pelos excluidos a mano están en conectores resueltos al mismo 93153. No
  tienen que volver como posición.

Todo es lectura, salvo declarar/retirar, que corren dentro de una transacción revertida (sesión con
`join_transaction_mode="create_savepoint"`: el commit de adentro sólo libera un savepoint). No se
escribe nunca sobre tablas de datos de Cromo: los estados de pelo y los cables "Sin Uso" se leen.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from core.services.cromo import servicio_posicion_vigente as pv
from core.services.cromo.tracking_service import ResumenCamino, TrackingGenerado
from db.session import async_engine
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real

_SERVICIO_93150 = 4
_SERVICIO_42351 = 567
_SERVICIO_42352 = 568
_SERVICIO_93153 = 16
_CONECTOR_1 = 8604882  # O-1252871-1:1
_CONECTOR_2 = 8604883  # O-1252871-1:2
_PELO_1 = 7028862
_PELO_2 = 7028863


@pytest_asyncio.fixture
async def sesion():
    engine = create_async_engine(
        async_engine.url.render_as_string(hide_password=False), poolclass=NullPool
    )
    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
            s = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
            yield s
            await s.close()
        finally:
            await trans.rollback()
    await engine.dispose()


async def _escalares(sesion, sql: str, **params) -> list:
    return list((await sesion.execute(text(sql), params)).scalars().all())


# ── Posiciones posibles ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_93150_incluye_o_1252871_1_con_la_etiqueta_ajena_del_44649(sesion):
    posibles = {p.conector_n_id: p for p in await pv.posiciones_posibles(sesion, _SERVICIO_93150)}

    # 14 conectores en dev (2026-10-21): 8 de pelos 44649 resueltos a 93150 y 6 de pelos 93150.
    assert len(posibles) == 14
    assert {_CONECTOR_1, _CONECTOR_2} <= set(posibles)
    p = posibles[_CONECTOR_1]
    assert p.posicion == "O-1252871-1:1"
    assert p.pelo_n_id == _PELO_1
    assert p.etiqueta_pelo == "44649" and p.etiqueta_ajena is True
    assert p.por_resuelto is True
    assert _PELO_1 in p.pelos_candidatos
    assert posibles[_CONECTOR_2].pelo_n_id == _PELO_2
    # Las semillas de posiciones incluyen los dos hilos del camino vigente, sin repetir.
    pelos = pv.pelos_de_posiciones(list(posibles.values()))
    assert {_PELO_1, _PELO_2} <= set(pelos) and len(pelos) == len(set(pelos))
    assert await pv.tiene_posiciones(sesion, _SERVICIO_93150) is True
    assert await pv.pelo_es_de_posicion(sesion, _SERVICIO_93150, _PELO_1) is True


@pytest.mark.asyncio
async def test_conector_de_dos_pelos_guarda_los_dos_candidatos(sesion):
    """O-1239922-1:5 (8546318) une 7028862 y 6799284 en `tp[]`: los dos son candidatos."""
    posibles = {p.conector_n_id: p for p in await pv.posiciones_posibles(sesion, _SERVICIO_93150)}

    assert 8546318 in posibles
    assert {_PELO_1, 6799284} <= set(posibles[8546318].pelos_candidatos)


@pytest.mark.asyncio
async def test_par_sugerido_de_o_1252871_1_1_es_el_2(sesion):
    posibles = await pv.posiciones_posibles(sesion, _SERVICIO_93150)
    por_id = {p.conector_n_id: p for p in posibles}

    assert pv.par_sugerido(por_id[_CONECTOR_1], posibles) == _CONECTOR_2
    assert pv.par_sugerido(por_id[_CONECTOR_2], posibles) == _CONECTOR_1


@pytest.mark.asyncio
async def test_42352_no_toma_los_pelos_del_42351(sesion):
    pelos_42351 = set(
        await _escalares(
            sesion,
            "SELECT pelo_n_id FROM app.v_cromo_servicio_match_vigente WHERE servicio_id = :sid",
            sid=_SERVICIO_42351,
        )
    )
    en_conectores_del_42352 = await _escalares(
        sesion,
        "SELECT pelo_n_id FROM app.cromo_odf_conectores "
        "WHERE vigente AND servicio_resuelto = '42352' AND pelo_n_id = ANY(:pelos)",
        pelos=sorted(pelos_42351),
    )
    # Precondición: el escenario real sigue existiendo (si no, el test no prueba nada).
    assert en_conectores_del_42352, "ya no hay conectores 42352 con pelos del 42351 en dev"

    posibles = await pv.posiciones_posibles(sesion, _SERVICIO_42352)

    assert not [p for p in posibles if p.pelo_n_id in pelos_42351]
    assert pv.pelos_de_posiciones(posibles) == []
    assert await pv.tiene_posiciones(sesion, _SERVICIO_42352) is False
    # La guarda del `.txt` usa el mismo filtro.
    assert await pv.pelo_es_de_posicion(sesion, _SERVICIO_42352, en_conectores_del_42352[0]) is False


@pytest.mark.asyncio
async def test_exclusiones_del_93153_no_vuelven_por_posicion(sesion):
    excluidos_en_sus_conectores = await _escalares(
        sesion,
        "SELECT x.pelo_n_id FROM app.cromo_servicio_pelo_excluido x "
        "JOIN app.cromo_odf_conectores c ON c.pelo_n_id = x.pelo_n_id AND c.vigente "
        "JOIN app.servicios s ON s.id = x.servicio_id "
        "WHERE x.servicio_id = :sid "
        "AND (c.servicio_resuelto = s.servicio_id OR c.servicio_resuelto = ANY(s.alias_ids))",
        sid=_SERVICIO_93153,
    )
    assert excluidos_en_sus_conectores, "ya no hay pelos excluidos del 93153 en sus conectores"

    posibles = await pv.posiciones_posibles(sesion, _SERVICIO_93153)

    assert not set(excluidos_en_sus_conectores) & set(pv.pelos_de_posiciones(posibles))
    for pelo in excluidos_en_sus_conectores:
        assert await pv.pelo_es_de_posicion(sesion, _SERVICIO_93153, pelo) is False


# ── Declarar y retirar (transacción revertida) ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_declarar_y_retirar_condicionado_por_pelo(sesion):
    await sesion.execute(
        text("DELETE FROM app.servicio_posicion_vigente WHERE servicio_id = :sid"),
        {"sid": _SERVICIO_93150},
    )

    declaradas = await pv.declarar(sesion, _SERVICIO_93150, [_CONECTOR_1, _CONECTOR_2], usuario="test")

    assert [(d.conector_n_id, d.pelo_declarado) for d in declaradas] == [
        (_CONECTOR_1, _PELO_1),
        (_CONECTOR_2, _PELO_2),
    ]
    assert all(d.conector_existe and d.pelo_actual == d.pelo_declarado for d in declaradas)
    assert _PELO_1 in declaradas[0].pelos_candidatos
    assert pv.validar_en_db(declaradas) == []
    assert pv.etiqueta_posiciones(
        (d.bandeja_nombre, d.numero_conector) for d in declaradas
    ) == "O-1252871-1:1,2"

    # Re-declarar es upsert: conserva el id (el índice único parcial no deja duplicar).
    otra_vez = await pv.declarar(sesion, _SERVICIO_93150, [_CONECTOR_1], usuario="test2")
    assert {d.id for d in otra_vez} == {d.id for d in declaradas}

    primera = declaradas[0]
    # Retiro calculado con un pelo viejo: no pisa la declaración vigente.
    assert await pv.retirar(sesion, primera.id, pelo_leido=1, motivo=pv.MOTIVO_PELO_CAMBIO) is False
    assert await pv.retirar(
        sesion, primera.id, pelo_leido=_PELO_1, motivo=pv.MOTIVO_PELO_CAMBIO, detalle={"actual": 1}
    ) is True
    assert await pv.retirar(sesion, primera.id, pelo_leido=_PELO_1, motivo=pv.MOTIVO_MANUAL) is False

    fila = (
        await sesion.execute(
            text(
                "SELECT vigente, retirado_por, motivo_retiro, detalle_retiro "
                "FROM app.servicio_posicion_vigente WHERE id = :id"
            ),
            {"id": primera.id},
        )
    ).one()
    assert fila.vigente is False and fila.retirado_por == "auto"
    assert fila.motivo_retiro == "PELO_CAMBIO" and fila.detalle_retiro == {"actual": 1}
    assert [d.conector_n_id for d in await pv.listar_declaradas(sesion, _SERVICIO_93150)] == [_CONECTOR_2]


@pytest.mark.asyncio
async def test_declarar_conector_del_42351_desde_el_42352_no_escribe(sesion):
    antes = await _escalares(
        sesion, "SELECT count(*) FROM app.servicio_posicion_vigente WHERE servicio_id = :sid",
        sid=_SERVICIO_42352,
    )

    with pytest.raises(pv.PosicionNoValida):
        await pv.declarar(sesion, _SERVICIO_42352, [8600662], usuario="test")

    despues = await _escalares(
        sesion, "SELECT count(*) FROM app.servicio_posicion_vigente WHERE servicio_id = :sid",
        sid=_SERVICIO_42352,
    )
    assert despues == antes


# ── Estados reales de pelo y cables "Sin Uso" (sólo lectura) ─────────────────────────────────

# Las 12 variantes reales de Cortado/Dañado en `cromo_pelos.estado_cromo` (dev, 2026-10-21).
_VARIANTES_DANADO = (
    "Cortado",
    "Dañado",
    "CORTADO",
    "CORTADO AL RAS",
    "CORTADO AL RAZ",
    "BUFFER 6 CORTADO AL RAS",
    "CORTADO LADO BOT",
    "Cortado dentro del BUFFER",
    "buffer cortado al ras",
    "Cortado en Cra. Ramal Pilar Km 50.400 Calle Magnolias",
    "Fibra Dañada",
    "Fibra dañana",
)
_ESTADOS_SANOS = ("Utilizado", "Libre", "Reservado", "Cedidos")


@pytest.mark.asyncio
async def test_normalizacion_de_los_estados_reales(sesion):
    reales = set(
        await _escalares(
            sesion,
            "SELECT DISTINCT estado_cromo FROM app.cromo_pelos WHERE vigente AND estado_cromo IS NOT NULL",
        )
    )
    assert set(_VARIANTES_DANADO) <= reales
    assert set(_ESTADOS_SANOS) <= reales

    assert all(pv.es_estado_pelo_danado(e) for e in _VARIANTES_DANADO)
    assert not any(pv.es_estado_pelo_danado(e) for e in (*_ESTADOS_SANOS, None))
    # Ningún otro valor real se clasifica como dañado.
    assert {e for e in reales if pv.es_estado_pelo_danado(e)} == set(_VARIANTES_DANADO)


def _tracking(pelo: int, pelos=(), cables=()) -> TrackingGenerado:
    from datetime import datetime, timezone

    return TrackingGenerado(
        pelo_n_id=pelo, nombre_archivo=f"{pelo}.txt", contenido="", desde_cache=True,
        generado_at=datetime(2026, 10, 21, tzinfo=timezone.utc), duracion_ms=None,
        pelos_camino=frozenset({pelo, *pelos}), extremos=ResumenCamino(cables=tuple(cables)),
    )


def _declarada_93150() -> pv.PosicionDeclarada:
    return pv.PosicionDeclarada(
        id=0, conector_n_id=_CONECTOR_1, odf_n_id=6644560, odf_nombre=None, bandeja_n_id=8604881,
        bandeja_nombre="O-1252871-1", numero_conector="1", pelo_declarado=_PELO_1,
        pelos_candidatos=(_PELO_1,), pelo_actual=_PELO_1, conector_existe=True,
        declarado_por="test", declarado_en=None,
    )


@pytest.mark.asyncio
async def test_validar_camino_detecta_pelo_danado_real(sesion):
    danado = (
        await sesion.execute(
            text(
                "SELECT n_id, estado_cromo FROM app.cromo_pelos "
                "WHERE vigente AND estado_cromo = 'Dañado' ORDER BY n_id LIMIT 1"
            )
        )
    ).one()

    aviso = await pv.validar_camino(
        sesion, _declarada_93150(), _tracking(_PELO_1, pelos=(danado.n_id,))
    )

    assert aviso is not None and aviso.codigo == pv.MOTIVO_PELO_DANADO
    assert aviso.retirada is False
    assert aviso.detalle["pelo"] == danado.n_id and aviso.detalle["estado"] == "Dañado"


@pytest.mark.asyncio
async def test_validar_camino_detecta_cable_sin_uso_real(sesion):
    cable = (
        await sesion.execute(
            text(
                "SELECT c.n_id, c.nombre FROM app.cromo_cables c "
                "WHERE c.tendido = 'Sin Uso' ORDER BY c.n_id LIMIT 1"
            )
        )
    ).one()
    sanos = await _escalares(
        sesion,
        "SELECT n_id FROM app.cromo_pelos WHERE n_id = ANY(:p) "
        "AND (estado_cromo IS NULL OR estado_cromo = 'Utilizado')",
        p=[_PELO_1, _PELO_2],
    )
    assert sanos, "los pelos del 93150 ya no están sanos en dev"

    aviso = await pv.validar_camino(
        sesion, _declarada_93150(), _tracking(sanos[0], cables=(cable.n_id,))
    )

    assert aviso is not None and aviso.codigo == pv.MOTIVO_CABLE_SIN_USO
    assert aviso.detalle == {"cable": cable.n_id, "nombre": cable.nombre}
    assert "con tendido «Sin Uso»" in pv.texto_aviso(aviso)


# ── Hallazgos de revisión (transacción revertida) ───────────────────────────────────────────

_PELO_FALSO = -910_000_077  # no existe en Cromo: sólo vive en esta transacción
_PELO_FALSO_2 = -910_000_078


async def _insertar_declarada(sesion, conector: int, pelo: int, candidatos=None) -> int:
    return (
        await sesion.execute(
            text(
                "INSERT INTO app.servicio_posicion_vigente "
                "(servicio_id, conector_n_id, odf_n_id, pelo_n_id, pelos_candidatos, declarado_por) "
                "VALUES (:sid, :c, -78, :p, CAST(:cand AS bigint[]), 'test') RETURNING id"
            ),
            {"sid": _SERVICIO_93150, "c": conector, "p": pelo, "cand": candidatos or [pelo]},
        )
    ).scalar_one()


async def _atribucion(sesion, pelo: int):
    return (
        await sesion.execute(
            text("SELECT servicio_id FROM app.cromo_tracking_cache WHERE pelo_n_id = :p"), {"p": pelo}
        )
    ).scalar_one()


async def _cachear(sesion, pelo: int, servicio_id):
    from core.services.cromo import tracking_cache

    await tracking_cache.guardar(
        sesion, pelo_n_id=pelo, servicio_id=servicio_id, nombre_archivo="x.txt", contenido="v"
    )


@pytest.mark.asyncio
async def test_retirar_saca_del_servicio_el_cache_del_pelo_retirado(sesion):
    """Paso a paso del hallazgo: la fase 1 cachea el pelo declarado con el Servicio; se retira;
    la fase 3 vuelve a sembrarlo con `servicio_id=None`. Antes el COALESCE conservaba el Servicio
    y la traza (`_SQL_TRACKINGS_DEL_SERVICIO`) seguía mostrando el camino retirado."""
    from core.services.servicio_traza import _SQL_TRACKINGS_DEL_SERVICIO

    await sesion.execute(
        text("DELETE FROM app.servicio_posicion_vigente WHERE servicio_id = :sid"),
        {"sid": _SERVICIO_93150},
    )
    await _insertar_declarada(sesion, -77, _PELO_FALSO)
    await _cachear(sesion, _PELO_FALSO, _SERVICIO_93150)

    assert await pv.retirar_manual(sesion, _SERVICIO_93150, -77, usuario="test") is True

    assert await _atribucion(sesion, _PELO_FALSO) is None
    await _cachear(sesion, _PELO_FALSO, None)  # fase 3: posición no declarada
    assert await _atribucion(sesion, _PELO_FALSO) is None
    traza = (await sesion.execute(_SQL_TRACKINGS_DEL_SERVICIO, {"sid": _SERVICIO_93150})).all()
    assert _PELO_FALSO not in [fila[0] for fila in traza]


@pytest.mark.asyncio
async def test_retiro_automatico_tambien_limpia_y_respeta_etiquetados_y_otras_declaradas(sesion):
    """`aplicar_retiros` pasa por el mismo `retirar`. No pierde la atribución: un pelo etiquetado
    al Servicio, un pelo que sostiene otra declarada vigente ni la fila de otro servicio."""
    await sesion.execute(
        text("DELETE FROM app.servicio_posicion_vigente WHERE servicio_id = :sid"),
        {"sid": _SERVICIO_93150},
    )
    etiquetado = (
        await sesion.execute(
            text(
                "SELECT pelo_n_id FROM app.v_cromo_servicio_match_vigente "
                "WHERE servicio_id = :sid ORDER BY pelo_n_id LIMIT 1"
            ),
            {"sid": _SERVICIO_93150},
        )
    ).scalar_one()
    id_falso = await _insertar_declarada(sesion, -77, _PELO_FALSO)
    id_etiquetado = await _insertar_declarada(sesion, -79, etiquetado)
    id_compartido = await _insertar_declarada(sesion, -80, _PELO_FALSO_2)
    await _insertar_declarada(sesion, -81, _PELO_FALSO_2)  # sigue vigente: sostiene el pelo
    await _cachear(sesion, _PELO_FALSO, _SERVICIO_93150)
    await _cachear(sesion, etiquetado, _SERVICIO_93150)
    await _cachear(sesion, _PELO_FALSO_2, _SERVICIO_93150)

    avisos = [
        pv.AvisoPosicion(-77, "A:1", pv.MOTIVO_SIN_PELO, True, id_falso, _PELO_FALSO),
        pv.AvisoPosicion(-79, "A:2", pv.MOTIVO_SIN_PELO, True, id_etiquetado, etiquetado),
        pv.AvisoPosicion(-80, "A:3", pv.MOTIVO_SIN_PELO, True, id_compartido, _PELO_FALSO_2),
    ]
    assert await pv.aplicar_retiros(sesion, avisos) == 3

    assert await _atribucion(sesion, _PELO_FALSO) is None
    assert await _atribucion(sesion, etiquetado) == _SERVICIO_93150
    assert await _atribucion(sesion, _PELO_FALSO_2) == _SERVICIO_93150

    # La fila de otro servicio con el mismo pelo no se toca (sólo se limpia la del retirado).
    await _cachear(sesion, _PELO_FALSO, _SERVICIO_42351)
    id_otra = await _insertar_declarada(sesion, -82, _PELO_FALSO)
    assert await pv.retirar(sesion, id_otra, pelo_leido=_PELO_FALSO, motivo=pv.MOTIVO_MANUAL) is True
    assert await _atribucion(sesion, _PELO_FALSO) == _SERVICIO_42351


@pytest.mark.asyncio
async def test_guarda_del_txt_y_declaradas_validas_ignoran_declaradas_invalidas(sesion):
    """Una declarada que `validar_en_db` ya invalidó (pendiente de retiro) no habilita su pelo en
    la guarda del `.txt`; una con el pelo actual entre sus candidatos sí."""
    await sesion.execute(
        text("DELETE FROM app.servicio_posicion_vigente WHERE servicio_id = :sid"),
        {"sid": _SERVICIO_93150},
    )
    inexistente = await _insertar_declarada(sesion, -77, _PELO_FALSO)  # CONECTOR_INEXISTENTE
    # El conector real sigue con 7028862: un pelo declarado que ya no es candidato es PELO_CAMBIO.
    cambiado = await _insertar_declarada(sesion, _CONECTOR_1, _PELO_FALSO_2)
    # El conector real (8604883, pelo 7028863) entre los candidatos: válida aunque el declarado difiera.
    valida = await _insertar_declarada(sesion, _CONECTOR_2, -910_000_079, [-910_000_079, _PELO_2])

    assert await pv.pelo_es_de_posicion(sesion, _SERVICIO_93150, _PELO_FALSO) is False
    assert await pv.pelo_es_de_posicion(sesion, _SERVICIO_93150, _PELO_FALSO_2) is False
    assert await pv.pelo_es_de_posicion(sesion, _SERVICIO_93150, -910_000_079) is True

    todas = {d.id for d in await pv.listar_declaradas(sesion, _SERVICIO_93150)}
    assert todas == {inexistente, cambiado, valida}
    assert [d.id for d in await pv.declaradas_validas(sesion, _SERVICIO_93150)] == [valida]


_SERVICIO_44649 = 24547  # Baja
_SERVICIO_61972 = 34651  # BBVA, Activo
# Pelos etiquetados 61972 (sueltos, mal cargados en Cromo) que recorre el hilo 2 del camino viejo
# del 93150 (semilla 6822051, O-1252871-1:2 ↔ O-1252734-1:12, 49 pelos), medidos en dev 2026-10-22.
_PELOS_61972_DEL_93150 = (6801908, 7477077, 7487940, 7500336)


@pytest.mark.asyncio
async def test_matches_de_pelos_reales_del_hilo_2_del_93150(sesion):
    matches = await pv._matches_de_pelos(sesion, _SERVICIO_93150, [*_PELOS_61972_DEL_93150, _PELO_1])

    for pelo in _PELOS_61972_DEL_93150:
        assert matches[pelo] == pv.MatchDePelo(f"servicio:{_SERVICIO_61972}", propio=False, activo=True)
    assert matches[_PELO_1] == pv.MatchDePelo(f"servicio:{_SERVICIO_44649}", propio=False, activo=False)


@pytest.mark.asyncio
async def test_hilo_del_93150_con_4_pelos_de_otro_activo_no_es_ajeno(sesion):
    """Bug real (2026-10-22): el hilo 2 del camino viejo del 93150 recorre 4 pelos de 61972
    (Activo) entre 42 de 44649 (Baja). Domina 44649: no es ajeno. Con más pelos de 61972 que de
    44649 sí lo es."""
    pelos_44649 = await _escalares(
        sesion,
        "SELECT pelo_n_id FROM app.v_cromo_servicio_match_vigente WHERE servicio_id = :sid "
        "ORDER BY pelo_n_id LIMIT 42",
        sid=_SERVICIO_44649,
    )
    assert len(pelos_44649) == 42, "el 44649 ya no tiene sus pelos etiquetados en dev"

    hilo_2 = [*pelos_44649, *_PELOS_61972_DEL_93150]
    mayormente_61972 = [*pelos_44649[:3], *_PELOS_61972_DEL_93150]
    ajenos = await pv.caminos_de_otro_servicio_activo(
        sesion, _SERVICIO_93150, {6822051: hilo_2, 1: mayormente_61972}
    )
    assert ajenos == frozenset({1})


@pytest.mark.asyncio
async def test_camino_cacheado_del_hilo_2_del_93150_no_es_ajeno(sesion):
    """Con el camino real que dejó el E2E en el caché (si sigue ahí)."""
    pelos = await _escalares(
        sesion,
        "SELECT unnest(pelos_camino) FROM app.cromo_tracking_cache WHERE pelo_n_id = 6822051",
    )
    if not pelos or not set(_PELOS_61972_DEL_93150) <= set(pelos):
        pytest.skip("el camino del hilo 2 del 93150 ya no está en el caché de dev")
    assert await pv.caminos_de_otro_servicio_activo(sesion, _SERVICIO_93150, {6822051: pelos}) == frozenset()


@pytest.mark.asyncio
async def test_camino_del_42351_es_ajeno_desde_el_42352_y_no_desde_el_42351(sesion):
    """El camino del 42351 (Activo) pedido desde el 42352 lleva su etiqueta: es ajeno. Desde el
    propio 42351 no."""
    pelos_42351 = await _escalares(
        sesion,
        "SELECT pelo_n_id FROM app.v_cromo_servicio_match_vigente WHERE servicio_id = :sid "
        "ORDER BY pelo_n_id LIMIT 40",
        sid=_SERVICIO_42351,
    )
    assert pelos_42351, "el 42351 ya no tiene pelos etiquetados en dev"
    camino = {pelos_42351[0]: [*pelos_42351, _PELO_1, _PELO_2]}

    assert await pv.caminos_de_otro_servicio_activo(sesion, _SERVICIO_42352, camino) == frozenset(
        {pelos_42351[0]}
    )
    assert await pv.caminos_de_otro_servicio_activo(sesion, _SERVICIO_42351, camino) == frozenset()
