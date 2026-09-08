# Nombre de archivo: test_cromo_servicios_sin_odf_real_db.py
# Ubicación de archivo: tests/test_cromo_servicios_sin_odf_real_db.py
# Descripción: Integración contra Postgres real del detector "Servicios sin ODF" — anti-join con ANY(text[]), CTE MATERIALIZED, exclusión por override, sugerencia OLT y regresión del plan de índices

"""Este archivo es de integración: necesita un Postgres real con el esquema `app.*` poblado.
Mismo motivo y guard que el resto de los tests `*_real_db.py` del módulo Cromo.

Por qué no alcanza un mock acá:

- El anti-join del listado usa `= ANY(text[])`, `alias_ids @> ARRAY[...]` y una CTE
  `AS MATERIALIZED` — nada de eso se ejercita sin el driver y el planner reales.
- La exclusión por `app.cromo_servicio_odf_override` es el guardrail crítico del gestor (sin
  ella un Servicio recién asociado a mano seguiría apareciendo tras confirmarlo) y sólo se
  puede probar insertando la fila de verdad.
- El test del plan (`EXPLAIN (FORMAT JSON)`) es una regresión automática de los DOS índices de
  performance de este gestor: si alguien dropea `ix_cromo_odf_conectores_servicio_resuelto`
  (migración `20260908_01`) o `ix_servicios_alias_ids_gin` (`20260908_02`), la query vuelve a
  tardar ~24s en silencio y este test lo detecta.

El escenario sintético reproduce el patrón REAL 618/1 de dev: el grupo
`ElRincon842_Pilar`/`OLT2_Pilar` tiene 618 servicios y sólo 1 con ODF ya resuelta — que es
justamente el dato que hace útil la sugerencia para los otros 617.

Todos los IDs sintéticos van en el rango `999_92x_xxx` / números `99999 2x`, fuera de todo rango
real de Cromo (`n_id` real observado: 6.6M–10.3M) y sin colisionar con el `999_900_04x` que ya usa
`tests/test_cromo_odf_conectores_real_db.py`. Cleanup siempre en `finally`.
"""

from __future__ import annotations

import json
import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.services.cromo.servicios_sin_odf import (
    CATEGORIA_OLT_PON_COMPARTIDO,
    CATEGORIA_SIN_SENAL_PROV,
    SUBCATEGORIA_AUSENTE_RED_CROMO,
    SUBCATEGORIA_BAJA_LOGICA_HEREDADA,
    SUBCATEGORIA_PELO_SIN_CONECTOR_ODF,
    _SQL_LISTADO_SIN_ODF,
    listar_servicios_sin_odf,
    subcategoria_sin_senal_prov,
    sugerencia_odf_para_servicio,
)
from db.session import SessionLocal, async_engine

pytestmark = pytest.mark.skipif(
    os.getenv("CI") == "true",
    reason="requiere Postgres real alcanzable; el workflow de CI no tiene ese servicio configurado",
)

_engine_test = create_async_engine(
    async_engine.url.render_as_string(hide_password=False), poolclass=NullPool
)
AsyncSessionLocal = async_sessionmaker(_engine_test, expire_on_commit=False)

# Rango sintético — ver docstring del módulo.
_ODF_N_ID = 999_920_001
_CONECTOR_HERMANO_N_ID = 999_920_002
_PELO_SIN_CONECTOR_N_ID = 999_920_003
_PELO_CON_CONECTOR_N_ID = 999_920_004
_CONECTOR_DEL_PELO_N_ID = 999_920_005
_PELO_HERMANO_BAJA_N_ID = 999_920_006
_PELO_SIN_BAJA_N_ID = 999_920_007
_CONECTOR_SIN_BAJA_N_ID = 999_920_008

_NUM_SIN_ODF = "9999921"
_NUM_HERMANO_RESUELTO = "9999922"
_NUM_CON_OVERRIDE = "9999923"
_NUM_PELO_SIN_CONECTOR = "9999924"
_NUM_AUSENTE_CROMO = "9999925"
_NUM_CON_HERMANO_BAJA = "9999926"
_NUM_HERMANO_BAJA = "9999927"
_NUM_SIN_HERMANO_BAJA = "9999928"

# Grupo OLT sintético, calcado del real `ElRincon842_Pilar` / `OLT2_Pilar`.
_NODO_GRUPO = "QA_ElRincon842_Pilar"
_EQUIPO_OLT = "OLT9_QA_Pilar"
_EQUIPO_SWITCH = "SW_9_QA_ElRincon842_Pilar"

# La página tiene que abarcar el universo entero (2891 filas reales en dev al escribir esto) para
# poder buscar la fila sintética por id. No cuesta más que `LIMIT 50`: el `COUNT(*) OVER ()` obliga
# a evaluar el anti-join completo igual, así que el LIMIT no ahorra tiempo.
_LIMIT_UNIVERSO = 20_000

_SQL_ALTA_SERVICIO = text(
    """
    INSERT INTO app.servicios
        (servicio_id, numero_primer_servicio, nombre_cliente, direccion, categoria,
         origen_datos, estado_servicio, es_verificable)
    VALUES (:numero, :numero, :cliente, :direccion, 6, 'INGEST_EXCEL', :estado, :verificable)
    RETURNING id
    """
)
_SQL_ALTA_EQUIPO = text(
    """
    INSERT INTO app.servicios_equipos_ultima_milla (servicio_id, extremo, nodo, equipo)
    VALUES (:servicio_id, :extremo, :nodo, :equipo)
    """
)
_SQL_ALTA_CONECTOR = text(
    """
    INSERT INTO app.cromo_odf_conectores
        (n_id, odf_n_id, numero_conector, pelo_n_id, servicio_resuelto, payload_raw)
    VALUES (:n_id, :odf_n_id, :conector, :pelo_n_id, :servicio_resuelto, '{}'::jsonb)
    """
)
_SQL_ALTA_PELO = text(
    """
    INSERT INTO app.cromo_pelos (n_id, tubo_n_id, cable_n_id, numero_pelo, servicio_numero)
    VALUES (:n_id, :n_id, :n_id, '1', :servicio_numero)
    """
)
_SQL_ALTA_MATCH = text(
    """
    INSERT INTO app.cromo_servicio_match (pelo_n_id, servicio_numero, servicio_id, metodo)
    VALUES (:pelo_n_id, :servicio_numero, :servicio_id, 'REGEX_EXACTO')
    """
)


def _alta_servicio(session, numero, *, cliente, direccion=None, estado="Activo", verificable=True):
    return int(
        session.execute(
            _SQL_ALTA_SERVICIO,
            {
                "numero": numero,
                "cliente": cliente,
                "direccion": direccion,
                "estado": estado,
                "verificable": verificable,
            },
        ).scalar_one()
    )


def _borrar_todo(numeros, *, pelos=(), conectores=(), odfs=()):
    """Cleanup idempotente. Los pelos van antes que nada porque
    `cromo_servicio_match.pelo_n_id` es FK con `ON DELETE CASCADE` a `cromo_pelos`; los
    `servicios` van al final por la FK de `cromo_servicio_match.servicio_id` (sin CASCADE)."""
    with SessionLocal() as session:
        if conectores:
            session.execute(
                text("DELETE FROM app.cromo_odf_conectores WHERE n_id = ANY(:ids)"),
                {"ids": list(conectores)},
            )
        if pelos:
            session.execute(
                text("DELETE FROM app.cromo_servicio_match WHERE pelo_n_id = ANY(:ids)"),
                {"ids": list(pelos)},
            )
            session.execute(
                text("DELETE FROM app.cromo_pelos WHERE n_id = ANY(:ids)"), {"ids": list(pelos)}
            )
        if odfs:
            session.execute(
                text("DELETE FROM app.cromo_odfs WHERE n_id = ANY(:ids)"), {"ids": list(odfs)}
            )
        session.execute(
            text(
                "DELETE FROM app.cromo_servicio_odf_override WHERE servicio_id IN "
                "(SELECT id FROM app.servicios WHERE servicio_id = ANY(:numeros))"
            ),
            {"numeros": list(numeros)},
        )
        session.execute(
            text(
                "DELETE FROM app.servicios_equipos_ultima_milla WHERE servicio_id IN "
                "(SELECT id FROM app.servicios WHERE servicio_id = ANY(:numeros))"
            ),
            {"numeros": list(numeros)},
        )
        session.execute(
            text("DELETE FROM app.servicios WHERE servicio_id = ANY(:numeros)"),
            {"numeros": list(numeros)},
        )
        session.commit()


@pytest.fixture
def escenario_grupo_olt():
    """Patrón real 618/1: dos Servicios Activos verificables en el MISMO (nodo, equipo) OLT — uno
    sin ODF resuelta y su "hermano" con ODF ya resuelta vía `cromo_odf_conectores`.

    El Servicio sin ODF tiene última milla DOBLE a propósito: extremo 1 en un switch genérico y
    extremo 2 en el OLT. Es el caso real de 206 servicios de dev en los que los dos extremos caen
    en categorías distintas — si el listado se quedara con el extremo 1, quedaría como
    `SWITCH_COMPARTIDO_REVISAR` y nunca se le ofrecería la sugerencia del grupo OLT.
    """
    numeros = [_NUM_SIN_ODF, _NUM_HERMANO_RESUELTO]
    _borrar_todo(numeros, conectores=[_CONECTOR_HERMANO_N_ID], odfs=[_ODF_N_ID])
    with SessionLocal() as session:
        sin_odf_id = _alta_servicio(
            session, _NUM_SIN_ODF, cliente="QA SinOdf Actual", direccion="CALLE QA SINODF 100"
        )
        hermano_id = _alta_servicio(
            session, _NUM_HERMANO_RESUELTO, cliente="QA SinOdf Hermano Resuelto"
        )
        for extremo, equipo in ((1, _EQUIPO_SWITCH), (2, _EQUIPO_OLT)):
            session.execute(
                _SQL_ALTA_EQUIPO,
                {
                    "servicio_id": sin_odf_id,
                    "extremo": extremo,
                    "nodo": _NODO_GRUPO,
                    "equipo": equipo,
                },
            )
        session.execute(
            _SQL_ALTA_EQUIPO,
            {"servicio_id": hermano_id, "extremo": 1, "nodo": _NODO_GRUPO, "equipo": _EQUIPO_OLT},
        )
        session.execute(
            text(
                "INSERT INTO app.cromo_odfs (n_id, version_id, vmax, clase, nombre, calle, altura, "
                " payload_raw) "
                "VALUES (:n_id, 1, 1, 69, 'ODF QA Pilar', 'CALLE QA SINODF', '100', '{}'::jsonb)"
            ),
            {"n_id": _ODF_N_ID},
        )
        # El hermano SÍ está resuelto: por eso queda fuera del universo "sin ODF" y por eso su ODF
        # sirve como sugerencia para el otro.
        session.execute(
            _SQL_ALTA_CONECTOR,
            {
                "n_id": _CONECTOR_HERMANO_N_ID,
                "odf_n_id": _ODF_N_ID,
                "conector": "9",
                "pelo_n_id": None,
                "servicio_resuelto": _NUM_HERMANO_RESUELTO,
            },
        )
        session.commit()

    try:
        yield {"sin_odf_id": sin_odf_id, "hermano_id": hermano_id}
    finally:
        _borrar_todo(numeros, conectores=[_CONECTOR_HERMANO_N_ID], odfs=[_ODF_N_ID])


@pytest.fixture
def servicio_para_override():
    """Un Servicio Activo verificable sin ODF y sin última milla PROV (→ `SIN_SENAL_PROV`), listo
    para que el test le agregue el override en el medio."""
    _borrar_todo([_NUM_CON_OVERRIDE])
    with SessionLocal() as session:
        servicio_id = _alta_servicio(session, _NUM_CON_OVERRIDE, cliente="QA SinOdf Override")
        session.commit()
    try:
        yield servicio_id
    finally:
        _borrar_todo([_NUM_CON_OVERRIDE])


@pytest.fixture
def escenario_subcategorias():
    """Los 4 desenlaces de la cascada de `SIN_SENAL_PROV`, cada uno con sus filas Cromo reales."""
    numeros = [
        _NUM_PELO_SIN_CONECTOR,
        _NUM_AUSENTE_CROMO,
        _NUM_CON_HERMANO_BAJA,
        _NUM_HERMANO_BAJA,
        _NUM_SIN_HERMANO_BAJA,
    ]
    pelos = [_PELO_SIN_CONECTOR_N_ID, _PELO_CON_CONECTOR_N_ID, _PELO_HERMANO_BAJA_N_ID, _PELO_SIN_BAJA_N_ID]
    conectores = [_CONECTOR_DEL_PELO_N_ID, _CONECTOR_SIN_BAJA_N_ID]
    _borrar_todo(numeros, pelos=pelos, conectores=conectores)
    with SessionLocal() as session:
        ids = {}
        # 1. Cromo conoce el número, pero el pelo no llega a ninguna patchera.
        ids["pelo_sin_conector"] = _alta_servicio(
            session, _NUM_PELO_SIN_CONECTOR, cliente="QA Sub PeloSinConector"
        )
        session.execute(
            _SQL_ALTA_PELO,
            {"n_id": _PELO_SIN_CONECTOR_N_ID, "servicio_numero": _NUM_PELO_SIN_CONECTOR},
        )
        session.execute(
            _SQL_ALTA_MATCH,
            {
                "pelo_n_id": _PELO_SIN_CONECTOR_N_ID,
                "servicio_numero": _NUM_PELO_SIN_CONECTOR,
                "servicio_id": ids["pelo_sin_conector"],
            },
        )
        # 2. Cromo no conoce el número en absoluto: ninguna fila en `cromo_servicio_match`.
        ids["ausente"] = _alta_servicio(session, _NUM_AUSENTE_CROMO, cliente="QA Sub Ausente")
        # 3. Fibra en Cromo bajo la identidad de un hermano dado de Baja (mismo cliente+dirección).
        ids["con_hermano_baja"] = _alta_servicio(
            session,
            _NUM_CON_HERMANO_BAJA,
            cliente="QA Sub HermanosBaja",
            direccion="CALLE QA BAJA 200",
        )
        ids["hermano_baja"] = _alta_servicio(
            session,
            _NUM_HERMANO_BAJA,
            cliente="QA Sub HermanosBaja",
            direccion="CALLE QA BAJA 200",
            estado="Baja",
            verificable=False,
        )
        session.execute(
            _SQL_ALTA_PELO,
            {"n_id": _PELO_CON_CONECTOR_N_ID, "servicio_numero": _NUM_CON_HERMANO_BAJA},
        )
        session.execute(
            _SQL_ALTA_MATCH,
            {
                "pelo_n_id": _PELO_CON_CONECTOR_N_ID,
                "servicio_numero": _NUM_CON_HERMANO_BAJA,
                "servicio_id": ids["con_hermano_baja"],
            },
        )
        # Con conector: así los pasos 1 y 2 de la cascada NO aplican y se llega al paso 3.
        session.execute(
            _SQL_ALTA_CONECTOR,
            {
                "n_id": _CONECTOR_DEL_PELO_N_ID,
                "odf_n_id": _ODF_N_ID,
                "conector": "20",
                "pelo_n_id": _PELO_CON_CONECTOR_N_ID,
                "servicio_resuelto": None,
            },
        )
        session.execute(
            _SQL_ALTA_PELO,
            {"n_id": _PELO_HERMANO_BAJA_N_ID, "servicio_numero": _NUM_HERMANO_BAJA},
        )
        session.execute(
            _SQL_ALTA_MATCH,
            {
                "pelo_n_id": _PELO_HERMANO_BAJA_N_ID,
                "servicio_numero": _NUM_HERMANO_BAJA,
                "servicio_id": ids["hermano_baja"],
            },
        )
        # 4. Mismo patrón que el 3 pero SIN hermano de Baja: ninguna cascada aplica → None.
        ids["sin_hermano_baja"] = _alta_servicio(
            session,
            _NUM_SIN_HERMANO_BAJA,
            cliente="QA Sub SinHermanoBaja",
            direccion="CALLE QA SOLO 300",
        )
        session.execute(
            _SQL_ALTA_PELO,
            {"n_id": _PELO_SIN_BAJA_N_ID, "servicio_numero": _NUM_SIN_HERMANO_BAJA},
        )
        session.execute(
            _SQL_ALTA_MATCH,
            {
                "pelo_n_id": _PELO_SIN_BAJA_N_ID,
                "servicio_numero": _NUM_SIN_HERMANO_BAJA,
                "servicio_id": ids["sin_hermano_baja"],
            },
        )
        session.execute(
            _SQL_ALTA_CONECTOR,
            {
                "n_id": _CONECTOR_SIN_BAJA_N_ID,
                "odf_n_id": _ODF_N_ID,
                "conector": "21",
                "pelo_n_id": _PELO_SIN_BAJA_N_ID,
                "servicio_resuelto": None,
            },
        )
        session.commit()

    try:
        yield ids
    finally:
        _borrar_todo(numeros, pelos=pelos, conectores=conectores)


# ─────────────────────────────────────────────────────────────────────────────
# Listado: universo, categorización por extremo real y exclusión de los resueltos
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_listado_incluye_el_sin_odf_categorizado_y_excluye_al_hermano_resuelto(
    escenario_grupo_olt,
):
    async with AsyncSessionLocal() as sesion:
        resultado = await listar_servicios_sin_odf(sesion, limit=_LIMIT_UNIVERSO, offset=0)

    por_id = {item.id: item for item in resultado.items}

    # El Servicio sin ODF está, con la categoría del extremo OLT (el 2), no la del switch (el 1).
    assert escenario_grupo_olt["sin_odf_id"] in por_id
    fila = por_id[escenario_grupo_olt["sin_odf_id"]]
    assert fila.categoria_causa == CATEGORIA_OLT_PON_COMPARTIDO
    assert fila.equipo == _EQUIPO_OLT
    assert fila.nodo == _NODO_GRUPO
    assert fila.servicio_id == _NUM_SIN_ODF
    assert fila.numero_primer_servicio == _NUM_SIN_ODF
    assert fila.nombre_cliente == "QA SinOdf Actual"
    # `subcategoria` NUNCA se calcula en el listado paginado (evita N+1).
    assert fila.subcategoria is None

    # El hermano tiene ODF resuelta en `cromo_odf_conectores`: está fuera del universo.
    assert escenario_grupo_olt["hermano_id"] not in por_id

    # `total` es el universo completo y la página lo cubre entero con este LIMIT.
    assert resultado.total == len(resultado.items)
    assert resultado.limit == _LIMIT_UNIVERSO
    assert resultado.offset == 0


@pytest.mark.asyncio
async def test_listado_pagina_con_limit_y_offset_sin_cambiar_el_total(escenario_grupo_olt):
    async with AsyncSessionLocal() as sesion:
        pagina_1 = await listar_servicios_sin_odf(sesion, limit=5, offset=0)
        pagina_2 = await listar_servicios_sin_odf(sesion, limit=5, offset=5)

    assert len(pagina_1.items) == 5
    assert len(pagina_2.items) == 5
    # `total` es el universo, no el largo de la página, y no se mueve entre páginas.
    assert pagina_1.total == pagina_2.total > 5
    # Páginas disjuntas y con el orden estable de la query (`nombre_cliente NULLS LAST, id`).
    assert {i.id for i in pagina_1.items}.isdisjoint({i.id for i in pagina_2.items})


@pytest.mark.asyncio
async def test_override_saca_al_servicio_del_listado(servicio_para_override):
    """Guardrail CRÍTICO del gestor: sin la CTE `con_override`, un Servicio recién asociado a mano
    seguiría apareciendo en el listado después de que el operador lo confirmó."""
    async with AsyncSessionLocal() as sesion:
        antes = await listar_servicios_sin_odf(sesion, limit=_LIMIT_UNIVERSO, offset=0)
    assert servicio_para_override in {i.id for i in antes.items}
    assert antes.items[
        [i.id for i in antes.items].index(servicio_para_override)
    ].categoria_causa == CATEGORIA_SIN_SENAL_PROV

    with SessionLocal() as session:
        session.execute(
            text(
                "INSERT INTO app.cromo_servicio_odf_override "
                "(servicio_id, odf_n_id, categoria_causa, usuario) "
                "VALUES (:servicio_id, :odf_n_id, :categoria, 'qa-real-db')"
            ),
            {
                "servicio_id": servicio_para_override,
                "odf_n_id": _ODF_N_ID,
                "categoria": CATEGORIA_SIN_SENAL_PROV,
            },
        )
        session.commit()

    async with AsyncSessionLocal() as sesion:
        despues = await listar_servicios_sin_odf(sesion, limit=_LIMIT_UNIVERSO, offset=0)

    assert servicio_para_override not in {i.id for i in despues.items}
    assert despues.total == antes.total - 1


# ─────────────────────────────────────────────────────────────────────────────
# Sugerencia de ODF por grupo OLT/PON — patrón real 618/1
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sugerencia_encuentra_la_odf_del_hermano_del_mismo_grupo_olt(escenario_grupo_olt):
    async with AsyncSessionLocal() as sesion:
        sugerencia = await sugerencia_odf_para_servicio(sesion, escenario_grupo_olt["sin_odf_id"])

    assert sugerencia is not None
    assert sugerencia.odf_n_id == _ODF_N_ID
    assert sugerencia.nombre == "ODF QA Pilar"


@pytest.mark.asyncio
async def test_sugerencia_es_none_cuando_ningun_hermano_tiene_odf_resuelta(escenario_grupo_olt):
    """El hermano resuelto es el único con ODF: pedirle la sugerencia A ÉL no debe devolver la de
    sí mismo (`e_hermano.servicio_id <> e_actual.servicio_id`), y sin otro hermano resuelto en el
    grupo la respuesta correcta es `None`, no una sugerencia inventada."""
    async with AsyncSessionLocal() as sesion:
        sugerencia = await sugerencia_odf_para_servicio(sesion, escenario_grupo_olt["hermano_id"])

    assert sugerencia is None


@pytest.mark.asyncio
async def test_sugerencia_es_none_para_un_servicio_sin_ultima_milla(servicio_para_override):
    async with AsyncSessionLocal() as sesion:
        assert await sugerencia_odf_para_servicio(sesion, servicio_para_override) is None


# ─────────────────────────────────────────────────────────────────────────────
# Cascada de subcategoría de SIN_SENAL_PROV
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_subcategoria_pelo_sin_conector_odf(escenario_subcategorias):
    async with AsyncSessionLocal() as sesion:
        sub = await subcategoria_sin_senal_prov(
            sesion, escenario_subcategorias["pelo_sin_conector"], _NUM_PELO_SIN_CONECTOR
        )
    assert sub == SUBCATEGORIA_PELO_SIN_CONECTOR_ODF


@pytest.mark.asyncio
async def test_subcategoria_ausente_red_cromo(escenario_subcategorias):
    async with AsyncSessionLocal() as sesion:
        sub = await subcategoria_sin_senal_prov(
            sesion, escenario_subcategorias["ausente"], _NUM_AUSENTE_CROMO
        )
    assert sub == SUBCATEGORIA_AUSENTE_RED_CROMO


@pytest.mark.asyncio
async def test_subcategoria_ausente_red_cromo_cuando_no_hay_numero(escenario_subcategorias):
    async with AsyncSessionLocal() as sesion:
        assert (
            await subcategoria_sin_senal_prov(sesion, escenario_subcategorias["ausente"], None)
            == SUBCATEGORIA_AUSENTE_RED_CROMO
        )
        assert (
            await subcategoria_sin_senal_prov(sesion, escenario_subcategorias["ausente"], "   ")
            == SUBCATEGORIA_AUSENTE_RED_CROMO
        )


@pytest.mark.asyncio
async def test_subcategoria_baja_logica_heredada(escenario_subcategorias):
    """El Servicio tiene pelo Y ese pelo llega a un conector (así los pasos 1 y 2 no aplican), y
    existe un hermano mismo-cliente/misma-dirección dado de Baja que también tiene pelo."""
    async with AsyncSessionLocal() as sesion:
        sub = await subcategoria_sin_senal_prov(
            sesion, escenario_subcategorias["con_hermano_baja"], _NUM_CON_HERMANO_BAJA
        )
    assert sub == SUBCATEGORIA_BAJA_LOGICA_HEREDADA


@pytest.mark.asyncio
async def test_subcategoria_none_cuando_ninguna_cascada_aplica(escenario_subcategorias):
    async with AsyncSessionLocal() as sesion:
        sub = await subcategoria_sin_senal_prov(
            sesion, escenario_subcategorias["sin_hermano_baja"], _NUM_SIN_HERMANO_BAJA
        )
    assert sub is None


# ─────────────────────────────────────────────────────────────────────────────
# Regresión del plan: los dos índices de performance del gestor
# ─────────────────────────────────────────────────────────────────────────────

_NODOS_INDEXADOS = {"Index Scan", "Index Only Scan", "Bitmap Index Scan"}


def _aplanar_plan(nodo, acumulador=None):
    """Todos los nodos del plan de `EXPLAIN (FORMAT JSON)`, recursivo por `Plans`."""
    acumulador = [] if acumulador is None else acumulador
    acumulador.append(nodo)
    for hijo in nodo.get("Plans", []):
        _aplanar_plan(hijo, acumulador)
    return acumulador


@pytest.mark.asyncio
async def test_plan_del_listado_usa_los_dos_indices_y_no_seq_scan():
    """Regresión automática de performance: si alguien dropea alguno de los dos índices, o
    reescribe la subquery anti-ambigüedad de `@>` a `= ANY(...)`, la query vuelve a tardar ~24s en
    silencio. Números reales medidos en dev: ~23.9s sin los dos fixes, ~11.6s con los dos.

    `EXPLAIN` sin `ANALYZE`: pide el plan, no ejecuta la query.
    """
    async with AsyncSessionLocal() as sesion:
        crudo = (
            await sesion.execute(
                text("EXPLAIN (FORMAT JSON) " + str(_SQL_LISTADO_SIN_ODF)),
                {"limit": 50, "offset": 0},
            )
        ).scalar_one()

    plan_json = json.loads(crudo) if isinstance(crudo, str) else crudo
    nodos = _aplanar_plan(plan_json[0]["Plan"])

    # 1. `ix_cromo_odf_conectores_servicio_resuelto` (migración 20260908_01): la CTE `resueltos`
    #    tiene que leerse por índice, no con un Seq Scan sobre las ~205k filas de la tabla.
    por_indice = [
        n
        for n in nodos
        if n.get("Index Name") == "ix_cromo_odf_conectores_servicio_resuelto"
        and n.get("Node Type") in _NODOS_INDEXADOS
    ]
    assert por_indice, (
        "el plan no usa ix_cromo_odf_conectores_servicio_resuelto; nodos sobre "
        f"cromo_odf_conectores: {[(n.get('Node Type'), n.get('Index Name')) for n in nodos if n.get('Relation Name') == 'cromo_odf_conectores']}"
    )
    seq_conectores = [
        n
        for n in nodos
        if n.get("Relation Name") == "cromo_odf_conectores" and n.get("Node Type") == "Seq Scan"
    ]
    assert not seq_conectores, "Seq Scan sobre cromo_odf_conectores: el índice parcial no se usó"

    # 2. `ix_servicios_alias_ids_gin` (migración 20260908_02): el self-join anti-ambigüedad (alias
    #    `v2`) tiene que resolverse por el GIN. Ojo: `Seq Scan on servicios s` (el barrido de
    #    candidatos) SÍ es esperado y correcto — la aserción es específica del alias `v2`.
    por_gin = [
        n
        for n in nodos
        if n.get("Index Name") == "ix_servicios_alias_ids_gin"
        and n.get("Node Type") in _NODOS_INDEXADOS
    ]
    assert por_gin, (
        "el plan no usa ix_servicios_alias_ids_gin; nodos sobre servicios: "
        f"{[(n.get('Node Type'), n.get('Alias'), n.get('Index Name')) for n in nodos if n.get('Relation Name') == 'servicios']}"
    )
    seq_v2 = [
        n
        for n in nodos
        if n.get("Relation Name") == "servicios"
        and n.get("Alias") == "v2"
        and n.get("Node Type") == "Seq Scan"
    ]
    assert not seq_v2, (
        "Seq Scan sobre servicios v2: el GIN no se usó (¿volvió el `= ANY(v2.alias_ids)` en vez "
        "del `v2.alias_ids @> ARRAY[...]`?)"
    )
