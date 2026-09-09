# Nombre de archivo: test_cromo_servicios_sin_odf_real_db.py
# Ubicación de archivo: tests/test_cromo_servicios_sin_odf_real_db.py
# Descripción: Integración contra Postgres real del detector "Servicios sin ODF" — anti-join con ANY(text[]) y contención @>, exclusión por override, filtros q/categoría, sugerencia OLT, identidades del Servicio en la cascada de subcategoría y regresión del plan de índices

"""Este archivo es de integración: necesita un Postgres real con el esquema `app.*` poblado.
Mismo motivo y guard que el resto de los tests `*_real_db.py` del módulo Cromo.

Por qué no alcanza un mock acá:

- El anti-join del listado usa `= ANY(text[])` y `alias_ids @> ARRAY[...]` — nada de eso se
  ejercita sin el driver y el planner reales.
- La exclusión por `app.cromo_servicio_odf_override` es el guardrail crítico del gestor (sin
  ella un Servicio recién asociado a mano seguiría apareciendo tras confirmarlo) y sólo se
  puede probar insertando la fila de verdad.
- `test_el_universo_es_identico_al_de_la_forma_original_sin_optimizar` compara el universo de la
  query optimizada contra el de la forma ORIGINAL del plan (la del brief de la Tarea 1: `= ANY(...)`
  en el self-join y un único `NOT EXISTS` sobre la CTE `resueltos AS MATERIALIZED`). La query pasó
  por TRES rewrites de performance (~23.9s → ~0.15s) y este test es el que garantiza que ninguno
  cambió la semántica de detección. Compara las dos formas entre sí, no contra un número fijo, así
  que no se desactualiza cuando cambian los datos de dev.
- El test del plan (`EXPLAIN (FORMAT JSON)`) es la regresión automática de los DOS índices y del
  rewrite: si alguien dropea `ix_cromo_odf_conectores_servicio_resuelto` (migración `20260908_01`)
  o `ix_servicios_alias_ids_gin` (`20260908_02`), o revierte cualquiera de los dos rewrites, la
  query vuelve a tardar 12-24s en silencio y este test lo detecta.

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
    CATEGORIA_SWITCH_COMPARTIDO_REVISAR,
    CATEGORIAS_POR_PRIORIDAD,
    SUBCATEGORIA_AUSENTE_RED_CROMO,
    SUBCATEGORIA_BAJA_LOGICA_HEREDADA,
    SUBCATEGORIA_PELO_SIN_CONECTOR_ODF,
    _SQL_LISTADO_SIN_ODF,
    _SQL_LISTADO_SIN_ODF_CON_BUSQUEDA,
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
# Cada fixture crea y limpia SU PROPIA ODF: compartir un `n_id` entre fixtures funcionaba sólo
# porque `cromo_odf_conectores.odf_n_id` no tiene FK dura, y se rompía con `-p random-order`/xdist
# (una fixture borraba la ODF que la otra estaba usando).
_ODF_SUBCATEGORIAS_N_ID = 999_920_021
# Referencia BLANDA: `cromo_servicio_odf_override.odf_n_id` es NOT NULL pero sin FK a `cromo_odfs`
# (criterio ya establecido para todo lo que apunta a Cromo), así que este test no necesita que
# exista la fila — sólo que el número no colisione con nada real.
_ODF_OVERRIDE_N_ID = 999_920_022
_PELO_IDENT_NPS_N_ID = 999_920_011
_PELO_IDENT_ALIAS_N_ID = 999_920_012
_PELO_IDENT_FK_N_ID = 999_920_013

# Ranking de sugerencia con VARIAS candidatas (fix de review: `_SQL_SUGERENCIA_ODF` tenía `LIMIT 1`
# sin `ORDER BY`). La ODF MENOS corroborada tiene el `n_id` MÁS BAJO a propósito: así, si el orden
# fuera sólo por `odf_n_id` (o el que devuelva el plan), ganaría la equivocada — el test distingue
# "ordena por corroboración" de "ordena por id".
_ODF_RANKING_MENOS_N_ID = 999_920_031  # 1 hermano resuelto, n_id más bajo
_ODF_RANKING_MAS_N_ID = 999_920_032  # 2 hermanos resueltos, n_id más alto → tiene que ganar
_CONECTOR_RANKING_MENOS_N_ID = 999_920_033
_CONECTOR_RANKING_MAS_A_N_ID = 999_920_034
_CONECTOR_RANKING_MAS_B_N_ID = 999_920_035

_NUM_SIN_ODF = "9999921"
_NUM_HERMANO_RESUELTO = "9999922"
_NUM_CON_OVERRIDE = "9999923"
_NUM_PELO_SIN_CONECTOR = "9999924"
_NUM_AUSENTE_CROMO = "9999925"
_NUM_CON_HERMANO_BAJA = "9999926"
_NUM_HERMANO_BAJA = "9999927"
_NUM_SIN_HERMANO_BAJA = "9999928"
# Servicios con las TRES identidades distintas entre sí, para probar que la cascada de subcategoría
# las resuelve todas y no sólo `servicio_id`.
_NUM_IDENT_SERVICIO_ID = "9999931"
_NUM_IDENT_NPS = "9999932"  # `numero_primer_servicio` del mismo Servicio, distinto del anterior
_NUM_IDENT_CON_ALIAS = "9999933"
_NUM_IDENT_ALIAS = "9999934"  # sólo en `alias_ids`
_NUM_IDENT_SOLO_FK = "9999935"
_NUM_IDENT_AJENO = "9999936"  # no es identidad de ningún Servicio del escenario
# Grupo del escenario de ranking de sugerencia: 1 Servicio sin ODF + 3 hermanos resueltos.
_NUM_RANKING_SIN_ODF = "9999941"
_NUM_RANKING_HERMANO_MENOS = "9999942"  # resuelto a la ODF con menos corroboración
_NUM_RANKING_HERMANO_MAS_A = "9999943"  # los dos siguientes, a la ODF más corroborada
_NUM_RANKING_HERMANO_MAS_B = "9999944"

# Grupo OLT sintético, calcado del real `ElRincon842_Pilar` / `OLT2_Pilar`.
_NODO_GRUPO = "QA_ElRincon842_Pilar"
_EQUIPO_OLT = "OLT9_QA_Pilar"
_EQUIPO_SWITCH = "SW_9_QA_ElRincon842_Pilar"

# Grupo aparte para el escenario de ranking: no puede compartir (nodo, equipo) con el de arriba o
# las dos fixtures se verían como hermanas entre sí.
_NODO_RANKING = "QA_Ranking_Pilar"
_EQUIPO_RANKING_OLT = "OLT9_QA_Ranking"

# La página tiene que abarcar el universo entero (2891 filas reales en dev al escribir esto) para
# poder buscar la fila sintética por id. No cuesta más que `LIMIT 50`: `listar_servicios_sin_odf`
# trae siempre todos los candidatos y corta en Python (la categoría se calcula acá, no en SQL — ver
# su docstring), así que el `limit` no cambia lo que se ejecuta en el motor.
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


_SQL_ALTA_ODF = text(
    """
    INSERT INTO app.cromo_odfs (n_id, version_id, vmax, clase, nombre, calle, altura, payload_raw)
    VALUES (:n_id, 1, 1, 69, :nombre, :calle, :altura, '{}'::jsonb)
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
            _SQL_ALTA_ODF,
            {
                "n_id": _ODF_N_ID,
                "nombre": "ODF QA Pilar",
                "calle": "CALLE QA SINODF",
                "altura": "100",
            },
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
def escenario_ranking_sugerencia():
    """Un Servicio sin ODF con DOS ODFs candidatas en su grupo (nodo, equipo), corroboradas de
    forma distinta: `_ODF_RANKING_MAS_N_ID` tiene 2 hermanos resueltos y `_ODF_RANKING_MENOS_N_ID`
    uno solo.

    Es el escenario que la forma vieja de `_SQL_SUGERENCIA_ODF` (`SELECT DISTINCT ... LIMIT 1` sin
    `ORDER BY`) no podía resolver de forma definida: devolvía la que el plan alcanzaba primero, sin
    garantía de estabilidad y sin decirle al operador que había más de una. Medido real 2026-09-09:
    88 de los 1057 Servicios `OLT_PON_COMPARTIDO` con sugerencia tienen entre 2 y 4 candidatas.
    """
    numeros = [
        _NUM_RANKING_SIN_ODF,
        _NUM_RANKING_HERMANO_MENOS,
        _NUM_RANKING_HERMANO_MAS_A,
        _NUM_RANKING_HERMANO_MAS_B,
    ]
    conectores = [
        _CONECTOR_RANKING_MENOS_N_ID,
        _CONECTOR_RANKING_MAS_A_N_ID,
        _CONECTOR_RANKING_MAS_B_N_ID,
    ]
    odfs = [_ODF_RANKING_MENOS_N_ID, _ODF_RANKING_MAS_N_ID]
    _borrar_todo(numeros, conectores=conectores, odfs=odfs)
    with SessionLocal() as session:
        sin_odf_id = _alta_servicio(
            session, _NUM_RANKING_SIN_ODF, cliente="QA Ranking Actual", direccion="CALLE QA RANK 1"
        )
        hermanos = {
            _NUM_RANKING_HERMANO_MENOS: _alta_servicio(
                session, _NUM_RANKING_HERMANO_MENOS, cliente="QA Ranking Hermano Menos"
            ),
            _NUM_RANKING_HERMANO_MAS_A: _alta_servicio(
                session, _NUM_RANKING_HERMANO_MAS_A, cliente="QA Ranking Hermano Mas A"
            ),
            _NUM_RANKING_HERMANO_MAS_B: _alta_servicio(
                session, _NUM_RANKING_HERMANO_MAS_B, cliente="QA Ranking Hermano Mas B"
            ),
        }
        for servicio_id in (sin_odf_id, *hermanos.values()):
            session.execute(
                _SQL_ALTA_EQUIPO,
                {
                    "servicio_id": servicio_id,
                    "extremo": 1,
                    "nodo": _NODO_RANKING,
                    "equipo": _EQUIPO_RANKING_OLT,
                },
            )
        for n_id, nombre in (
            (_ODF_RANKING_MENOS_N_ID, "ODF QA Ranking Menos"),
            (_ODF_RANKING_MAS_N_ID, "ODF QA Ranking Mas"),
        ):
            session.execute(
                _SQL_ALTA_ODF,
                {"n_id": n_id, "nombre": nombre, "calle": "CALLE QA RANK", "altura": "1"},
            )
        for conector_n_id, odf_n_id, numero in (
            (_CONECTOR_RANKING_MENOS_N_ID, _ODF_RANKING_MENOS_N_ID, _NUM_RANKING_HERMANO_MENOS),
            (_CONECTOR_RANKING_MAS_A_N_ID, _ODF_RANKING_MAS_N_ID, _NUM_RANKING_HERMANO_MAS_A),
            (_CONECTOR_RANKING_MAS_B_N_ID, _ODF_RANKING_MAS_N_ID, _NUM_RANKING_HERMANO_MAS_B),
        ):
            session.execute(
                _SQL_ALTA_CONECTOR,
                {
                    "n_id": conector_n_id,
                    "odf_n_id": odf_n_id,
                    "conector": "1",
                    "pelo_n_id": None,
                    "servicio_resuelto": numero,
                },
            )
        session.commit()

    try:
        yield {"sin_odf_id": sin_odf_id}
    finally:
        _borrar_todo(numeros, conectores=conectores, odfs=odfs)


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
    _borrar_todo(numeros, pelos=pelos, conectores=conectores, odfs=[_ODF_SUBCATEGORIAS_N_ID])
    with SessionLocal() as session:
        ids = {}
        # ODF propia de ESTA fixture (ver el comentario de `_ODF_SUBCATEGORIAS_N_ID`).
        session.execute(
            _SQL_ALTA_ODF,
            {
                "n_id": _ODF_SUBCATEGORIAS_N_ID,
                "nombre": "ODF QA Subcategorias",
                "calle": "CALLE QA SUB",
                "altura": "10",
            },
        )
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
                "odf_n_id": _ODF_SUBCATEGORIAS_N_ID,
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
                "odf_n_id": _ODF_SUBCATEGORIAS_N_ID,
                "conector": "21",
                "pelo_n_id": _PELO_SIN_BAJA_N_ID,
                "servicio_resuelto": None,
            },
        )
        session.commit()

    try:
        yield ids
    finally:
        _borrar_todo(numeros, pelos=pelos, conectores=conectores, odfs=[_ODF_SUBCATEGORIAS_N_ID])


@pytest.fixture
def escenario_identidades_cromo():
    """Tres Servicios cuyos pelos están en Cromo bajo una identidad **distinta** de su
    `servicio_id`: uno bajo su `numero_primer_servicio`, uno bajo un `alias_ids`, y uno vinculado
    sólo por la FK `cromo_servicio_match.servicio_id` (con un `servicio_numero` que no es identidad
    de nadie, como pasa cuando la numeración cambió después de que se registró el match).

    Ninguno tiene conector, así que la respuesta correcta para los tres es
    `PELO_SIN_CONECTOR_ODF`. Con la versión anterior de la cascada — que keyeaba por UN número
    recibido del llamador — los tres daban `AUSENTE_RED_CROMO`, un diagnóstico falso.
    """
    numeros = [_NUM_IDENT_SERVICIO_ID, _NUM_IDENT_CON_ALIAS, _NUM_IDENT_SOLO_FK]
    pelos = [_PELO_IDENT_NPS_N_ID, _PELO_IDENT_ALIAS_N_ID, _PELO_IDENT_FK_N_ID]
    _borrar_todo(numeros, pelos=pelos)
    with SessionLocal() as session:
        ids = {}

        # 1. `servicio_id` != `numero_primer_servicio`, pelo registrado bajo el segundo.
        ids["bajo_numero_primer_servicio"] = int(
            session.execute(
                text(
                    "INSERT INTO app.servicios (servicio_id, numero_primer_servicio, "
                    " nombre_cliente, categoria, origen_datos, estado_servicio, es_verificable) "
                    "VALUES (:sid, :nps, 'QA Ident NPS', 6, 'INGEST_EXCEL', 'Activo', true) "
                    "RETURNING id"
                ),
                {"sid": _NUM_IDENT_SERVICIO_ID, "nps": _NUM_IDENT_NPS},
            ).scalar_one()
        )
        session.execute(_SQL_ALTA_PELO, {"n_id": _PELO_IDENT_NPS_N_ID, "servicio_numero": _NUM_IDENT_NPS})
        session.execute(
            text(
                "INSERT INTO app.cromo_servicio_match (pelo_n_id, servicio_numero, servicio_id, metodo) "
                "VALUES (:pelo_n_id, :servicio_numero, NULL, 'REGEX_EXACTO')"
            ),
            {"pelo_n_id": _PELO_IDENT_NPS_N_ID, "servicio_numero": _NUM_IDENT_NPS},
        )

        # 2. Pelo registrado bajo un `alias_ids`.
        ids["bajo_alias"] = int(
            session.execute(
                text(
                    "INSERT INTO app.servicios (servicio_id, numero_primer_servicio, alias_ids, "
                    " nombre_cliente, categoria, origen_datos, estado_servicio, es_verificable) "
                    "VALUES (:sid, :sid, ARRAY[:alias], 'QA Ident Alias', 6, 'INGEST_EXCEL', "
                    " 'Activo', true) RETURNING id"
                ),
                {"sid": _NUM_IDENT_CON_ALIAS, "alias": _NUM_IDENT_ALIAS},
            ).scalar_one()
        )
        session.execute(
            _SQL_ALTA_PELO, {"n_id": _PELO_IDENT_ALIAS_N_ID, "servicio_numero": _NUM_IDENT_ALIAS}
        )
        session.execute(
            text(
                "INSERT INTO app.cromo_servicio_match (pelo_n_id, servicio_numero, servicio_id, metodo) "
                "VALUES (:pelo_n_id, :servicio_numero, NULL, 'REGEX_EXACTO')"
            ),
            {"pelo_n_id": _PELO_IDENT_ALIAS_N_ID, "servicio_numero": _NUM_IDENT_ALIAS},
        )

        # 3. Vinculado SÓLO por la FK: `servicio_numero` no es identidad de este Servicio.
        ids["solo_por_fk"] = _alta_servicio(
            session, _NUM_IDENT_SOLO_FK, cliente="QA Ident Solo FK"
        )
        session.execute(
            _SQL_ALTA_PELO, {"n_id": _PELO_IDENT_FK_N_ID, "servicio_numero": _NUM_IDENT_AJENO}
        )
        session.execute(
            _SQL_ALTA_MATCH,
            {
                "pelo_n_id": _PELO_IDENT_FK_N_ID,
                "servicio_numero": _NUM_IDENT_AJENO,
                "servicio_id": ids["solo_por_fk"],
            },
        )
        session.commit()

    try:
        yield ids
    finally:
        _borrar_todo(numeros, pelos=pelos)


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

    # La prioridad de categorización NO oculta información: los DOS extremos se exponen enteros,
    # en orden de `extremo`, aunque sólo el 2 haya ganado la categoría.
    assert [(e.extremo, e.nodo, e.equipo) for e in fila.extremos] == [
        (1, _NODO_GRUPO, _EQUIPO_SWITCH),
        (2, _NODO_GRUPO, _EQUIPO_OLT),
    ]
    # Y se dice CUÁL ganó, sin que la UI tenga que deducirlo comparando valores.
    assert fila.indice_extremo_categorizado == 1
    assert fila.extremos[fila.indice_extremo_categorizado].equipo == _EQUIPO_OLT

    # El hermano tiene ODF resuelta en `cromo_odf_conectores`: está fuera del universo.
    assert escenario_grupo_olt["hermano_id"] not in por_id

    # `total` es el universo completo y la página lo cubre entero con este LIMIT.
    assert resultado.total == len(resultado.items)
    assert resultado.limit == _LIMIT_UNIVERSO
    assert resultado.offset == 0


@pytest.mark.asyncio
async def test_listado_pagina_con_limit_y_offset_sin_cambiar_el_total(escenario_grupo_olt):
    """DEPENDE DEL VOLUMEN DE DATOS DE DEV: exige que el universo "sin ODF" tenga **más de 5**
    filas para que las dos páginas de 5 estén llenas y sean disjuntas (2891 al escribir esto). La
    fixture sólo garantiza 1 fila propia, no las 10. Si este test falla con páginas cortas, mirá
    primero el tamaño del universo (`listar_servicios_sin_odf(limit=0).total`) antes de sospechar
    de la paginación."""
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
    fila = antes.items[[i.id for i in antes.items].index(servicio_para_override)]
    assert fila.categoria_causa == CATEGORIA_SIN_SENAL_PROV
    # Sin fila PROV: `extremos` vacía (no `None`), y `nodo`/`equipo`/índice en `None`.
    assert fila.extremos == []
    assert fila.nodo is None and fila.equipo is None
    assert fila.indice_extremo_categorizado is None

    with SessionLocal() as session:
        session.execute(
            text(
                "INSERT INTO app.cromo_servicio_odf_override "
                "(servicio_id, odf_n_id, categoria_causa, usuario) "
                "VALUES (:servicio_id, :odf_n_id, :categoria, 'qa-real-db')"
            ),
            {
                "servicio_id": servicio_para_override,
                "odf_n_id": _ODF_OVERRIDE_N_ID,
                "categoria": CATEGORIA_SIN_SENAL_PROV,
            },
        )
        session.commit()

    async with AsyncSessionLocal() as sesion:
        despues = await listar_servicios_sin_odf(sesion, limit=_LIMIT_UNIVERSO, offset=0)

    assert servicio_para_override not in {i.id for i in despues.items}
    assert despues.total == antes.total - 1


# ─────────────────────────────────────────────────────────────────────────────
# Equivalencia semántica: la query optimizada vs. la forma original del plan
# ─────────────────────────────────────────────────────────────────────────────

# Forma ORIGINAL, tal cual la especificó el brief de la Tarea 1, ANTES de los tres rewrites de
# performance: `= ANY(v2.alias_ids)` en el self-join anti-ambigüedad y UN solo `NOT EXISTS` con tres
# `OR` adentro sobre la CTE `resueltos AS MATERIALIZED`. Es la referencia semántica de "qué es un
# Servicio sin ODF", no una query que se use en producción — acá vive sólo para compararle el
# resultado a la optimizada. Tarda ~24s a propósito: es exactamente el costo que los rewrites
# eliminaron.
_SQL_UNIVERSO_FORMA_ORIGINAL = text(
    """
    WITH verificables AS (
      SELECT s.id, s.servicio_id, s.numero_primer_servicio, s.alias_ids
      FROM app.servicios s
      WHERE s.estado_servicio ILIKE 'activo' AND s.es_verificable = true
        AND s.numero_primer_servicio IS NOT NULL
        AND NOT EXISTS (
          SELECT 1 FROM app.servicios v2
          WHERE v2.id <> s.id
            AND (s.servicio_id = ANY(v2.alias_ids) OR s.numero_primer_servicio = ANY(v2.alias_ids))
        )
    ),
    resueltos AS MATERIALIZED (
      SELECT servicio_resuelto FROM app.cromo_odf_conectores WHERE servicio_resuelto IS NOT NULL
    ),
    con_override AS (
      SELECT DISTINCT servicio_id FROM app.cromo_servicio_odf_override
    )
    SELECT v.id FROM verificables v
    WHERE NOT EXISTS (
      SELECT 1 FROM resueltos c
      WHERE c.servicio_resuelto = v.servicio_id
         OR c.servicio_resuelto = v.numero_primer_servicio
         OR c.servicio_resuelto = ANY(v.alias_ids)
    )
    AND v.id NOT IN (SELECT servicio_id FROM con_override)
    """
)


@pytest.mark.asyncio
async def test_el_universo_es_identico_al_de_la_forma_original_sin_optimizar(escenario_grupo_olt):
    """La query pasó por TRES rewrites de performance (~23.9s → ~0.15s):

    1. índice btree parcial sobre `cromo_odf_conectores.servicio_resuelto` (migración `20260908_01`);
    2. `= ANY(v2.alias_ids)` → `v2.alias_ids @> ARRAY[...]` + índice GIN (`20260908_02`);
    3. la CTE `resueltos AS MATERIALIZED` + un `NOT EXISTS` con tres `OR` → tres `NOT EXISTS`
       independientes por De Morgan.

    Ninguno de los tres debe cambiar QUÉ servicios se consideran "sin ODF". Este test lo verifica
    comparando los dos conjuntos de ids entre sí sobre los datos reales de dev (incluido el
    escenario sintético del fixture, que aporta un Servicio que SÍ debe estar y un hermano resuelto
    que NO), en vez de contra un número fijo — así no se desactualiza cuando cambian los datos.
    """
    async with AsyncSessionLocal() as sesion:
        optimizada = await listar_servicios_sin_odf(sesion, limit=_LIMIT_UNIVERSO, offset=0)
        referencia = (await sesion.execute(_SQL_UNIVERSO_FORMA_ORIGINAL)).all()

    ids_optimizada = {i.id for i in optimizada.items}
    ids_referencia = {fila.id for fila in referencia}

    assert ids_optimizada == ids_referencia, (
        f"la optimización cambió el universo: {len(ids_optimizada - ids_referencia)} de más, "
        f"{len(ids_referencia - ids_optimizada)} de menos"
    )
    assert optimizada.total == len(ids_referencia)
    # Sanity: el fixture garantiza que el conjunto no está vacío ni degenerado.
    assert escenario_grupo_olt["sin_odf_id"] in ids_referencia
    assert escenario_grupo_olt["hermano_id"] not in ids_referencia


# ─────────────────────────────────────────────────────────────────────────────
# Filtros `q` (SQL) y `categoria` (Python)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_filtro_q_busca_por_servicio_id_y_por_nombre_cliente(escenario_grupo_olt):
    async with AsyncSessionLocal() as sesion:
        por_numero = await listar_servicios_sin_odf(sesion, limit=_LIMIT_UNIVERSO, q=_NUM_SIN_ODF)
        por_cliente = await listar_servicios_sin_odf(
            sesion, limit=_LIMIT_UNIVERSO, q="QA SinOdf Actual"
        )
        parcial = await listar_servicios_sin_odf(sesion, limit=_LIMIT_UNIVERSO, q="QA SinOdf")
        sin_matches = await listar_servicios_sin_odf(
            sesion, limit=_LIMIT_UNIVERSO, q="zzz-no-existe-en-dev-zzz"
        )

    # Por número exacto: sólo el sintético (los números `99999 2x` no existen en datos reales).
    assert [i.id for i in por_numero.items] == [escenario_grupo_olt["sin_odf_id"]]
    assert por_numero.total == 1
    # Por nombre de cliente.
    assert [i.id for i in por_cliente.items] == [escenario_grupo_olt["sin_odf_id"]]
    # Substring (ILIKE '%...%'): matchea el sin-ODF; el hermano igual queda fuera del universo.
    assert escenario_grupo_olt["sin_odf_id"] in {i.id for i in parcial.items}
    assert escenario_grupo_olt["hermano_id"] not in {i.id for i in parcial.items}
    # Sin matches: total 0 y lista vacía, no el universo entero.
    assert sin_matches.total == 0
    assert sin_matches.items == []


@pytest.mark.asyncio
async def test_filtro_q_es_case_insensitive(escenario_grupo_olt):
    async with AsyncSessionLocal() as sesion:
        minusculas = await listar_servicios_sin_odf(
            sesion, limit=_LIMIT_UNIVERSO, q="qa sinodf actual"
        )
    assert [i.id for i in minusculas.items] == [escenario_grupo_olt["sin_odf_id"]]


@pytest.mark.asyncio
async def test_filtro_categoria_particiona_el_universo_sin_perder_ni_duplicar(escenario_grupo_olt):
    """Las 4 categorías tienen que sumar exactamente el universo sin filtrar: si sumaran menos hay
    filas sin categorizar, y si sumaran más hay filas contadas dos veces."""
    async with AsyncSessionLocal() as sesion:
        universo = await listar_servicios_sin_odf(sesion, limit=_LIMIT_UNIVERSO)
        por_categoria = {
            categoria: await listar_servicios_sin_odf(
                sesion, limit=_LIMIT_UNIVERSO, categoria=categoria
            )
            for categoria in CATEGORIAS_POR_PRIORIDAD
        }

    for categoria, resultado in por_categoria.items():
        assert all(i.categoria_causa == categoria for i in resultado.items), categoria
        assert resultado.total == len(resultado.items), categoria

    assert sum(r.total for r in por_categoria.values()) == universo.total
    ids_por_categoria = [{i.id for i in r.items} for r in por_categoria.values()]
    assert set().union(*ids_por_categoria) == {i.id for i in universo.items}

    # El sintético con OLT en el extremo 2 tiene que caer en OLT, no en el bucket de switch.
    assert escenario_grupo_olt["sin_odf_id"] in {
        i.id for i in por_categoria[CATEGORIA_OLT_PON_COMPARTIDO].items
    }
    assert escenario_grupo_olt["sin_odf_id"] not in {
        i.id for i in por_categoria[CATEGORIA_SWITCH_COMPARTIDO_REVISAR].items
    }


@pytest.mark.asyncio
async def test_paginacion_se_aplica_despues_de_filtrar_y_el_total_es_el_del_set_filtrado():
    """El bug que este test previene: cortar por `LIMIT`/`OFFSET` ANTES de filtrar por categoría
    daría páginas con menos filas de las pedidas y un `total` del universo sin filtrar, así que el
    paginador de la UI prometería páginas que no existen.

    DEPENDE DEL VOLUMEN DE DATOS DE DEV: exige **≥14** filas en la categoría `OLT_PON_COMPARTIDO`
    (dos páginas de 7 llenas; 1537 al escribir esto) y **≥1** fila fuera de esa categoría (para que
    el set filtrado sea estrictamente menor que el universo; 1354 al escribir esto). Ninguna fixture
    garantiza esos volúmenes. Si falla, chequeá primero la distribución por categoría antes de
    sospechar de la paginación."""
    async with AsyncSessionLocal() as sesion:
        completo = await listar_servicios_sin_odf(
            sesion, limit=_LIMIT_UNIVERSO, categoria=CATEGORIA_OLT_PON_COMPARTIDO
        )
        universo = await listar_servicios_sin_odf(sesion, limit=_LIMIT_UNIVERSO)
        pagina_1 = await listar_servicios_sin_odf(
            sesion, limit=7, offset=0, categoria=CATEGORIA_OLT_PON_COMPARTIDO
        )
        pagina_2 = await listar_servicios_sin_odf(
            sesion, limit=7, offset=7, categoria=CATEGORIA_OLT_PON_COMPARTIDO
        )

    # `total` es el del set FILTRADO, estrictamente menor que el universo.
    assert pagina_1.total == pagina_2.total == completo.total < universo.total
    # Páginas llenas y del tamaño pedido: se cortó después de filtrar.
    assert len(pagina_1.items) == len(pagina_2.items) == 7
    assert all(i.categoria_causa == CATEGORIA_OLT_PON_COMPARTIDO for i in pagina_1.items)
    # Y son exactamente las dos primeras tajadas del set filtrado, en el mismo orden.
    assert [i.id for i in pagina_1.items] == [i.id for i in completo.items[:7]]
    assert [i.id for i in pagina_2.items] == [i.id for i in completo.items[7:14]]
    assert pagina_1.limit == 7 and pagina_2.offset == 7


@pytest.mark.asyncio
async def test_filtros_q_y_categoria_se_combinan(escenario_grupo_olt):
    async with AsyncSessionLocal() as sesion:
        acierto = await listar_servicios_sin_odf(
            sesion,
            limit=_LIMIT_UNIVERSO,
            q="QA SinOdf",
            categoria=CATEGORIA_OLT_PON_COMPARTIDO,
        )
        # Misma búsqueda, categoría que no le corresponde: 0 resultados, no el set de `q` entero.
        categoria_que_no_aplica = await listar_servicios_sin_odf(
            sesion,
            limit=_LIMIT_UNIVERSO,
            q="QA SinOdf",
            categoria=CATEGORIA_SIN_SENAL_PROV,
        )

    assert [i.id for i in acierto.items] == [escenario_grupo_olt["sin_odf_id"]]
    assert acierto.total == 1
    assert categoria_que_no_aplica.total == 0
    assert categoria_que_no_aplica.items == []


@pytest.mark.asyncio
async def test_categoria_desconocida_levanta_value_error():
    """Explícito antes que silencioso: un listado vacío parecería "no hay servicios de esta
    categoría" en vez de "escribiste mal el nombre de la categoría"."""
    async with AsyncSessionLocal() as sesion:
        with pytest.raises(ValueError, match="categoria desconocida"):
            await listar_servicios_sin_odf(sesion, categoria="OLT")  # prefijo, no la categoría


@pytest.mark.asyncio
async def test_filtro_q_trata_los_metacaracteres_de_like_como_literales(escenario_grupo_olt):
    """Sin escapar, `q="_"` matchearía TODO y `q="100%"` sería el prefijo "100" — resultados
    plausibles pero equivocados, y la Task 5 va a exponer esto a un buscador de UI."""
    async with AsyncSessionLocal() as sesion:
        universo = await listar_servicios_sin_odf(sesion, limit=_LIMIT_UNIVERSO)
        guion_bajo = await listar_servicios_sin_odf(sesion, limit=_LIMIT_UNIVERSO, q="_")
        porcentaje = await listar_servicios_sin_odf(sesion, limit=_LIMIT_UNIVERSO, q="%")
        # El número sintético existe; con `%` de wildcard este patrón matchearía, literal no.
        con_porcentaje = await listar_servicios_sin_odf(
            sesion, limit=_LIMIT_UNIVERSO, q=f"{_NUM_SIN_ODF[:4]}%{_NUM_SIN_ODF[5:]}"
        )
        barra = await listar_servicios_sin_odf(sesion, limit=_LIMIT_UNIVERSO, q="\\")

    assert universo.total > 0
    # `_` como comodín de UN carácter traería casi todo el universo; literal, ninguno de estos
    # `servicio_id`/`nombre_cliente` sintéticos ni reales lo contiene como texto.
    assert guion_bajo.total < universo.total
    assert porcentaje.total < universo.total
    assert con_porcentaje.total == 0
    # Una barra sola no debe romper la query (sin `ESCAPE` bien armado, Postgres tira error).
    assert barra.total >= 0


@pytest.mark.asyncio
async def test_offset_y_limit_negativos_levantan_value_error():
    """`items[-3:-1]` devolvería una página del FINAL en silencio: plausible y equivocada, el peor
    tipo de bug para un paginador. Misma convención explícita que `categoria`."""
    async with AsyncSessionLocal() as sesion:
        with pytest.raises(ValueError, match="offset no puede ser negativo"):
            await listar_servicios_sin_odf(sesion, limit=2, offset=-3)
        with pytest.raises(ValueError, match="limit no puede ser negativo"):
            await listar_servicios_sin_odf(sesion, limit=-1)


@pytest.mark.asyncio
async def test_limit_cero_devuelve_lista_vacia_con_el_total_real():
    """`limit=0` es válido y significa "sólo quiero el conteo" — la UI lo usa para los chips de
    categoría sin traer filas."""
    async with AsyncSessionLocal() as sesion:
        universo = await listar_servicios_sin_odf(sesion, limit=_LIMIT_UNIVERSO)
        solo_total = await listar_servicios_sin_odf(sesion, limit=0)

    assert solo_total.items == []
    assert solo_total.limit == 0
    assert solo_total.total == universo.total > 0


@pytest.mark.asyncio
async def test_offset_mas_alla_del_total_devuelve_pagina_vacia_sin_error():
    async with AsyncSessionLocal() as sesion:
        pagina = await listar_servicios_sin_odf(sesion, limit=10, offset=10_000_000)
    assert pagina.items == []
    assert pagina.total > 0  # el total sigue siendo el del set completo


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
    assert sugerencia.cantidad_candidatas == 1, "una sola ODF candidata en este grupo"


@pytest.mark.asyncio
async def test_sugerencia_gana_la_odf_mas_corroborada_no_la_de_id_mas_bajo(
    escenario_ranking_sugerencia,
):
    """Con varias candidatas gana la que MÁS hermanos ya resolvieron, no la del `odf_n_id` más
    bajo: `_ODF_RANKING_MAS_N_ID` tiene 2 hermanos resueltos y el `n_id` más ALTO, así que si el
    orden fuera por id (o el que devolviera el plan sin `ORDER BY`) ganaría la equivocada."""
    async with AsyncSessionLocal() as sesion:
        sugerencia = await sugerencia_odf_para_servicio(
            sesion, escenario_ranking_sugerencia["sin_odf_id"]
        )

    assert sugerencia is not None
    assert sugerencia.odf_n_id == _ODF_RANKING_MAS_N_ID
    assert sugerencia.nombre == "ODF QA Ranking Mas"
    assert sugerencia.cantidad_candidatas == 2, (
        "la UI necesita saber que había MÁS de una candidata para no presentar la sugerencia como "
        "la única ODF posible"
    )


@pytest.mark.asyncio
async def test_sugerencia_es_estable_entre_ejecuciones_repetidas(escenario_ranking_sugerencia):
    """La misma pregunta tiene que dar la misma respuesta, incluso forzando planes distintos.

    Es la regresión del `LIMIT 1` sin `ORDER BY`: sin orden explícito, Postgres devuelve la fila
    que el plan alcanza primero y nada garantiza que sea la misma tras un cambio de plan, una
    ingesta que reordena el heap o un scan paralelo. Se fuerzan planes distintos (deshabilitando
    hash join / hash agg / nested loop y forzando paralelismo) para que el test no dependa de que
    el planner elija hoy lo mismo que mañana.
    """
    planes = (
        [],
        ["SET LOCAL enable_hashjoin = off"],
        ["SET LOCAL enable_hashagg = off"],
        ["SET LOCAL enable_nestloop = off"],
        [
            "SET LOCAL max_parallel_workers_per_gather = 4",
            "SET LOCAL parallel_setup_cost = 0",
            "SET LOCAL parallel_tuple_cost = 0",
            "SET LOCAL min_parallel_table_scan_size = 0",
        ],
    )
    vistos = set()
    for ajustes in planes:
        async with AsyncSessionLocal() as sesion:
            for ajuste in ajustes:
                await sesion.execute(text(ajuste))
            sugerencia = await sugerencia_odf_para_servicio(
                sesion, escenario_ranking_sugerencia["sin_odf_id"]
            )
            await sesion.rollback()
        assert sugerencia is not None
        vistos.add((sugerencia.odf_n_id, sugerencia.cantidad_candidatas))

    assert vistos == {(_ODF_RANKING_MAS_N_ID, 2)}, f"sugerencia inestable entre planes: {vistos}"


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
            sesion, escenario_subcategorias["pelo_sin_conector"]
        )
    assert sub == SUBCATEGORIA_PELO_SIN_CONECTOR_ODF


@pytest.mark.asyncio
async def test_subcategoria_ausente_red_cromo(escenario_subcategorias):
    async with AsyncSessionLocal() as sesion:
        sub = await subcategoria_sin_senal_prov(sesion, escenario_subcategorias["ausente"])
    assert sub == SUBCATEGORIA_AUSENTE_RED_CROMO


@pytest.mark.asyncio
async def test_subcategoria_es_none_para_un_servicio_inexistente():
    """Sin fila no hay evidencia de nada. Preferido a una excepción para la carrera "el Servicio se
    borró entre el 404 del endpoint y esta consulta"."""
    async with AsyncSessionLocal() as sesion:
        assert await subcategoria_sin_senal_prov(sesion, 999_929_999) is None


@pytest.mark.asyncio
async def test_subcategoria_baja_logica_heredada(escenario_subcategorias):
    """El Servicio tiene pelo Y ese pelo llega a un conector (así los pasos 1 y 2 no aplican), y
    existe un hermano mismo-cliente/misma-dirección dado de Baja que también tiene pelo."""
    async with AsyncSessionLocal() as sesion:
        sub = await subcategoria_sin_senal_prov(
            sesion, escenario_subcategorias["con_hermano_baja"]
        )
    assert sub == SUBCATEGORIA_BAJA_LOGICA_HEREDADA


@pytest.mark.asyncio
async def test_subcategoria_none_cuando_ninguna_cascada_aplica(escenario_subcategorias):
    async with AsyncSessionLocal() as sesion:
        sub = await subcategoria_sin_senal_prov(
            sesion, escenario_subcategorias["sin_hermano_baja"]
        )
    assert sub is None


@pytest.mark.parametrize(
    "clave",
    ["bajo_numero_primer_servicio", "bajo_alias", "solo_por_fk"],
)
@pytest.mark.asyncio
async def test_subcategoria_resuelve_las_tres_identidades_no_solo_una(
    escenario_identidades_cromo, clave
):
    """Bug real encontrado en la review de la Tarea 3.

    `cromo_servicio_match.servicio_numero` sale del regex sobre la descripción del pelo, así que
    puede ser CUALQUIERA de las identidades del Servicio (`servicio_id`, `numero_primer_servicio`,
    o un `alias_ids`) — es exactamente el motivo por el que el listado y `conectores_de_odf`
    matchean por las tres. La versión anterior de esta cascada keyeaba por UN solo número recibido
    del llamador: los tres Servicios de este test tienen su pelo en Cromo registrado bajo una
    identidad distinta de su `servicio_id`, así que devolvía `AUSENTE_RED_CROMO` ("Cromo no conoce
    este Servicio") — un diagnóstico FALSO mostrado al operador.

    Los tres deben dar `PELO_SIN_CONECTOR_ODF`: Cromo sí los conoce, lo que falta es el conector.
    """
    async with AsyncSessionLocal() as sesion:
        sub = await subcategoria_sin_senal_prov(sesion, escenario_identidades_cromo[clave])
    assert sub == SUBCATEGORIA_PELO_SIN_CONECTOR_ODF


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


async def _nodos_del_plan(sql, params=None):
    """Nodos del plan de `EXPLAIN (FORMAT JSON)`. Sin `ANALYZE`: pide el plan, no ejecuta."""
    async with AsyncSessionLocal() as sesion:
        crudo = (
            await sesion.execute(text("EXPLAIN (FORMAT JSON) " + str(sql)), params or {})
        ).scalar_one()
    plan_json = json.loads(crudo) if isinstance(crudo, str) else crudo
    return _aplanar_plan(plan_json[0]["Plan"])


def _verificar_plan_optimo(nodos):
    """Las 4 aserciones de performance del plan, comunes a la query con y sin filtro `q`."""
    # 1. `ix_cromo_odf_conectores_servicio_resuelto` (migración 20260908_01) usado al menos 3
    #    veces: el `NOT EXISTS` de "no tiene ODF resuelta" está desarmado por De Morgan en tres
    #    subqueries independientes, y cada una tiene que sondear por índice. Con la forma vieja (un
    #    único `NOT EXISTS` con tres `OR` sobre la CTE materializada) el índice aparecía UNA sola
    #    vez, para construir la CTE — y la query tardaba ~11.4s en vez de ~0.15s.
    por_indice = [
        n
        for n in nodos
        if n.get("Index Name") == "ix_cromo_odf_conectores_servicio_resuelto"
        and n.get("Node Type") in _NODOS_INDEXADOS
    ]
    nodos_conectores = [
        (n.get("Node Type"), n.get("Index Name"))
        for n in nodos
        if n.get("Relation Name") == "cromo_odf_conectores"
    ]
    assert len(por_indice) >= 3, (
        "se esperaban >=3 sondeos por ix_cromo_odf_conectores_servicio_resuelto (uno por cada "
        "NOT EXISTS de De Morgan) y hay "
        f"{len(por_indice)}; nodos sobre cromo_odf_conectores: {nodos_conectores}"
    )

    # 2. Cero `Seq Scan` sobre `cromo_odf_conectores` (~205k filas).
    assert not [
        n
        for n in nodos
        if n.get("Relation Name") == "cromo_odf_conectores" and n.get("Node Type") == "Seq Scan"
    ], f"Seq Scan sobre cromo_odf_conectores: el índice parcial no se usó ({nodos_conectores})"

    # 3. Cero `CTE Scan`: la CTE `resueltos AS MATERIALIZED` tiene que seguir FUERA de la query.
    #    Materializarla obliga a re-escanearla completa por cada fila candidata (~46M filas
    #    descartadas por Join Filter) y el índice del punto 1 sólo acelera construirla, no
    #    recorrerla. `con_override` no aparece como CTE Scan: el planner la aplana a un SubPlan.
    assert not [n for n in nodos if n.get("Node Type") == "CTE Scan"], (
        "volvió un CTE Scan al plan (¿reapareció `resueltos AS MATERIALIZED`?): "
        f"{[(n.get('Node Type'), n.get('CTE Name')) for n in nodos if n.get('Node Type') == 'CTE Scan']}"
    )

    # 4. `ix_servicios_alias_ids_gin` (migración 20260908_02): el self-join anti-ambigüedad (alias
    #    `v2`) tiene que resolverse por el GIN. Ojo: `Seq Scan on servicios s` (el barrido de
    #    candidatos) SÍ es esperado y correcto — la aserción es específica del alias `v2`.
    nodos_servicios = [
        (n.get("Node Type"), n.get("Alias"), n.get("Index Name"))
        for n in nodos
        if n.get("Relation Name") == "servicios"
    ]
    assert [
        n
        for n in nodos
        if n.get("Index Name") == "ix_servicios_alias_ids_gin"
        and n.get("Node Type") in _NODOS_INDEXADOS
    ], f"el plan no usa ix_servicios_alias_ids_gin; nodos sobre servicios: {nodos_servicios}"
    assert not [
        n
        for n in nodos
        if n.get("Relation Name") == "servicios"
        and n.get("Alias") == "v2"
        and n.get("Node Type") == "Seq Scan"
    ], (
        "Seq Scan sobre servicios v2: el GIN no se usó (¿volvió el `= ANY(v2.alias_ids)` en vez "
        f"del `v2.alias_ids @> ARRAY[...]`?); nodos sobre servicios: {nodos_servicios}"
    )


@pytest.mark.asyncio
async def test_plan_del_listado_usa_los_dos_indices_sin_seq_scan_ni_cte():
    """Regresión automática de performance de la query final. Números reales medidos en dev sobre
    el mismo universo (2891 filas), con `EXPLAIN (ANALYZE, TIMING OFF)`:

    | forma                                                     | Execution Time |
    |-----------------------------------------------------------|----------------|
    | original del plan (`= ANY` + CTE MATERIALIZED)            | ~23.9 s        |
    | + GIN y rewrite a `@>`                                    | ~11.6 s        |
    | + De Morgan sin CTE (la actual)                           | **~0.15 s**    |

    Si alguien dropea cualquiera de los dos índices, revierte el `@>` a `= ANY(...)` o reintroduce
    la CTE materializada, la query vuelve a tardar 12-24s **en silencio** — nada falla, sólo se
    pone lenta. Estas aserciones son lo que convierte esa regresión en un test rojo.
    """
    _verificar_plan_optimo(await _nodos_del_plan(_SQL_LISTADO_SIN_ODF))


@pytest.mark.asyncio
async def test_plan_del_listado_con_filtro_q_mantiene_los_mismos_indices():
    """El filtro `q` se inyecta en la CTE `verificables` como una cláusula extra; no debe hacer
    que el planner abandone ninguno de los dos índices."""
    _verificar_plan_optimo(
        await _nodos_del_plan(_SQL_LISTADO_SIN_ODF_CON_BUSQUEDA, {"patron": "%SA%"})
    )
