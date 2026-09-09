# Nombre de archivo: test_cromo_servicio_odf_override_service.py
# Ubicación de archivo: tests/test_cromo_servicio_odf_override_service.py
# Descripción: Integración contra Postgres real de la asociación manual Servicio→ODF (crear_override, override_vigente_de_servicio, overrides_vigentes_por_odf) + el touch-point en verificador.py::servicios_por_odf

"""Este archivo es de integración: necesita un Postgres real con el esquema `app.*` poblado. Mismo
motivo y guard que el resto de los tests `*_real_db.py` del módulo Cromo (ver
`tests/test_cromo_servicios_sin_odf_real_db.py` para el mismo patrón).

Por qué no alcanza un mock acá:

- Los 3 `CHECK` de `categoria_causa`/`subcategoria`/`senal_direccion` y la FK dura
  `servicio_id → servicios.id` (`ondelete=CASCADE`) son constraints reales de la migración
  `20260908_01` — sólo Postgres real los hace cumplir.
- `overrides_vigentes_por_odf` usa `Select.distinct(columna)`, que SQLAlchemy sólo traduce a
  `DISTINCT ON` en el dialecto Postgres (ver su docstring) — un mock nunca ejercita esa traducción.
- El test de `servicios_por_odf` confirma que el `UNION` en memoria con los overrides no duplica un
  Servicio que además matchea automático a la misma ODF: necesita datos reales atravesando
  `cromo_pelos`/`cromo_servicio_match`/`cromo_servicio_odf_override` a la vez.

Todos los IDs sintéticos van en el rango `999_940_0xx` (n_ids) / `99999 5x` (números de servicio),
un rango fresco que no pisa ninguno de los ya usados por otros tests `*_real_db.py` de Cromo
(`999_900_0xx` en `test_cromo_odf_conectores_real_db.py`/`test_cromo_odf_inventario_real_db.py`,
`999_920_0xx` en `test_cromo_servicios_sin_odf_real_db.py`). Cada escenario usa su PROPIO n_id de
ODF (nunca comparte uno entre fixtures): el hallazgo real de `test_cromo_servicios_sin_odf_real_db.py`
es que compartir un n_id entre fixtures se rompe con `-p random-order`/xdist. Cleanup siempre en
`finally`.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.services.cromo.direccion_comparacion import SenalDireccion
from core.services.cromo.servicio_odf_override_service import (
    crear_override,
    override_vigente_de_servicio,
    overrides_vigentes_por_odf,
)
from core.services.cromo.verificador import ObjetoNoEncontrado, servicios_por_odf
from db.session import SessionLocal, async_engine

pytestmark = pytest.mark.skipif(
    os.getenv("CI") == "true",
    reason="requiere Postgres real alcanzable; el workflow de CI no tiene ese servicio configurado",
)

# Mismo motivo que el resto de los tests `*_real_db.py` de Cromo: `NullPool` evita reusar una
# conexión pooleada entre event loops distintos (cada test async corre en el suyo).
_engine_test = create_async_engine(
    async_engine.url.render_as_string(hide_password=False), poolclass=NullPool
)
AsyncSessionLocal = async_sessionmaker(_engine_test, expire_on_commit=False)

# ── Rango sintético — ver docstring del módulo ───────────────────────────────

_ODF_FELIZ_N_ID = 999_940_001  # crear_override caso feliz + "fila más reciente"
_ODF_CASCADE_N_ID = 999_940_002  # FK dura con CASCADE
_ODF_CHECK_N_ID = 999_940_003  # CHECK constraints (INSERT crudo, sin FK a esta ODF)
_ODF_INEXISTENTE_N_ID = 999_940_099  # nunca se crea una fila para éste, a propósito

_ODF_DEDUPE_N_ID = 999_940_010  # servicios_por_odf: override + automático a la MISMA odf
_CABLE_DEDUPE_N_ID = 999_940_011
_PELO_DEDUPE_N_ID = 999_940_012

_ODF_REASOCIACION_A_N_ID = 999_940_020  # reasociación cross-ODF (fix Important 1, round 1)
_ODF_REASOCIACION_B_N_ID = 999_940_021

_ODF_SOLO_CONECTOR_N_ID = 999_940_030  # fix Important 2, round 1: ODF SIN fila propia
_CONECTOR_SOLO_N_ID = 999_940_031

_NUM_OVERRIDE_FELIZ = "9999951"
_NUM_CASCADE = "9999952"
_NUM_ODF_INEXISTENTE = "9999953"
_NUM_CHECK = "9999954"
_NUM_AUTOMATICO_Y_OVERRIDE = "9999955"
_NUM_SOLO_OVERRIDE = "9999956"
_NUM_REASOCIACION = "9999957"
_NUM_ODF_SOLO_CONECTOR = "9999958"


_SQL_ALTA_SERVICIO = text(
    """
    INSERT INTO app.servicios
        (servicio_id, numero_primer_servicio, nombre_cliente, categoria, origen_datos, estado_servicio)
    VALUES (:numero, :numero, :cliente, 0, 'INFERIDO_CROMO', 'DESCONOCIDO')
    RETURNING id
    """
)
_SQL_ALTA_ODF = text(
    "INSERT INTO app.cromo_odfs (n_id, version_id, vmax, clase, nombre, payload_raw) "
    "VALUES (:n_id, 1, 1, 69, :nombre, '{}'::jsonb)"
)
_SQL_ALTA_ODF_CON_CABLES = text(
    "INSERT INTO app.cromo_odfs (n_id, version_id, vmax, clase, nombre, cables_asociados, payload_raw) "
    "VALUES (:n_id, 1, 1, 69, :nombre, :cables_asociados, '{}'::jsonb)"
)
_SQL_ALTA_PELO = text(
    "INSERT INTO app.cromo_pelos (n_id, tubo_n_id, cable_n_id, servicio_numero) "
    "VALUES (:n_id, :n_id, :cable_n_id, :servicio_numero)"
)
_SQL_ALTA_MATCH = text(
    "INSERT INTO app.cromo_servicio_match (pelo_n_id, servicio_numero, servicio_id, metodo) "
    "VALUES (:pelo_n_id, :servicio_numero, :servicio_id, 'REGEX_EXACTO')"
)
# ODF conocida SOLO por un conector, sin fila propia en `cromo_odfs` — el escenario que
# `crear_override` debe rechazar (fix Important 2, round 1: antes de la review aceptaba esto con
# el criterio tolerante copiado de `odf_conectores.py`, que acá es INCORRECTO).
_SQL_ALTA_CONECTOR_SOLO = text(
    "INSERT INTO app.cromo_odf_conectores (n_id, odf_n_id, numero_conector, payload_raw) "
    "VALUES (:n_id, :odf_n_id, '1', '{}'::jsonb)"
)
_SQL_INSERT_OVERRIDE_RAW = text(
    """
    INSERT INTO app.cromo_servicio_odf_override
        (servicio_id, odf_n_id, categoria_causa, subcategoria, senal_direccion, usuario)
    VALUES (:servicio_id, :odf_n_id, :categoria_causa, :subcategoria, :senal_direccion, 'qa-real-db')
    """
)


def _alta_servicio(session, numero: str, *, cliente: str = "QA Override") -> int:
    return int(
        session.execute(_SQL_ALTA_SERVICIO, {"numero": numero, "cliente": cliente}).scalar_one()
    )


def _borrar_servicios_y_overrides(numeros: list[str]) -> None:
    """Cleanup idempotente de `servicios` + cualquier override que quede colgado de ellos (la FK
    `ondelete=CASCADE` ya se encarga cuando el servicio se borra primero, pero corre igual como
    salvaguarda para el caso en que el propio test haya borrado el servicio antes)."""
    with SessionLocal() as session:
        session.execute(
            text(
                "DELETE FROM app.cromo_servicio_odf_override WHERE servicio_id IN "
                "(SELECT id FROM app.servicios WHERE servicio_id = ANY(:numeros))"
            ),
            {"numeros": numeros},
        )
        session.execute(
            text("DELETE FROM app.servicios WHERE servicio_id = ANY(:numeros)"), {"numeros": numeros}
        )
        session.commit()


# ─────────────────────────────────────────────────────────────────────────────
# crear_override — caso feliz + "fila más reciente"
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def servicio_override_feliz():
    _borrar_servicios_y_overrides([_NUM_OVERRIDE_FELIZ])
    with SessionLocal() as session:
        session.execute(_SQL_ALTA_ODF, {"n_id": _ODF_FELIZ_N_ID, "nombre": "ODF QA Override Feliz"})
        servicio_id = _alta_servicio(session, _NUM_OVERRIDE_FELIZ)
        session.commit()
    try:
        yield servicio_id
    finally:
        with SessionLocal() as session:
            session.execute(text("DELETE FROM app.cromo_odfs WHERE n_id = :n_id"), {"n_id": _ODF_FELIZ_N_ID})
            session.commit()
        _borrar_servicios_y_overrides([_NUM_OVERRIDE_FELIZ])


@pytest.mark.asyncio
async def test_crear_override_caso_feliz_inserta_y_devuelve_la_fila(servicio_override_feliz):
    servicio_id = servicio_override_feliz
    async with AsyncSessionLocal() as sesion:
        override = await crear_override(
            sesion,
            servicio_id=servicio_id,
            odf_n_id=_ODF_FELIZ_N_ID,
            pelo_n_id=123456,
            categoria_causa="OLT_PON_COMPARTIDO",
            subcategoria=None,
            usuario="qa-real-db",
            notas="primero",
            senal_direccion=SenalDireccion.COINCIDE,
        )

    assert override.id is not None
    assert override.servicio_id == servicio_id
    assert override.odf_n_id == _ODF_FELIZ_N_ID
    assert override.pelo_n_id == 123456
    assert override.categoria_causa == "OLT_PON_COMPARTIDO"
    # Persiste el `.value` del enum (mismo literal que el CHECK), no el enum en sí.
    assert override.senal_direccion == "coincide"
    assert override.usuario == "qa-real-db"
    assert override.notas == "primero"
    assert override.creado_en is not None

    # Confirma contra la fila real en DB, no sólo contra el objeto que devolvió el ORM.
    with SessionLocal() as session:
        fila = session.execute(
            text(
                "SELECT categoria_causa, senal_direccion, pelo_n_id "
                "FROM app.cromo_servicio_odf_override WHERE id = :id"
            ),
            {"id": override.id},
        ).first()
    assert fila is not None
    assert fila.categoria_causa == "OLT_PON_COMPARTIDO"
    assert fila.senal_direccion == "coincide"
    assert fila.pelo_n_id == 123456


@pytest.mark.asyncio
async def test_override_vigente_de_servicio_devuelve_la_fila_mas_reciente(servicio_override_feliz):
    """Dos overrides para el MISMO servicio_id (reasociación sin perder historial, Task 1): la
    vigente es siempre la segunda — nunca la primera, aunque `crear_override` sea un INSERT puro que
    deja las dos filas en la tabla."""
    servicio_id = servicio_override_feliz
    async with AsyncSessionLocal() as sesion:
        primero = await crear_override(
            sesion,
            servicio_id=servicio_id,
            odf_n_id=_ODF_FELIZ_N_ID,
            categoria_causa="OLT_PON_COMPARTIDO",
            usuario="qa-real-db",
            notas="primero",
        )
        segundo = await crear_override(
            sesion,
            servicio_id=servicio_id,
            odf_n_id=_ODF_FELIZ_N_ID,
            categoria_causa="SIN_SENAL_PROV",
            usuario="qa-real-db",
            notas="segundo",
        )

    # Dos filas reales, no un upsert que pisó la primera.
    assert segundo.id > primero.id
    with SessionLocal() as session:
        total = session.execute(
            text("SELECT count(*) FROM app.cromo_servicio_odf_override WHERE servicio_id = :sid"),
            {"sid": servicio_id},
        ).scalar_one()
    assert total == 2

    async with AsyncSessionLocal() as sesion:
        vigente = await override_vigente_de_servicio(sesion, servicio_id)

    assert vigente is not None
    assert vigente.id == segundo.id
    assert vigente.notas == "segundo"
    assert vigente.categoria_causa == "SIN_SENAL_PROV"


@pytest.mark.asyncio
async def test_override_vigente_de_servicio_none_si_nunca_se_asocio():
    async with AsyncSessionLocal() as sesion:
        vigente = await override_vigente_de_servicio(sesion, -1)
    assert vigente is None


# ─────────────────────────────────────────────────────────────────────────────
# crear_override — odf_n_id inexistente falla explícito
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def servicio_para_odf_inexistente():
    _borrar_servicios_y_overrides([_NUM_ODF_INEXISTENTE])
    with SessionLocal() as session:
        servicio_id = _alta_servicio(session, _NUM_ODF_INEXISTENTE)
        session.commit()
    try:
        yield servicio_id
    finally:
        _borrar_servicios_y_overrides([_NUM_ODF_INEXISTENTE])


@pytest.mark.asyncio
async def test_crear_override_con_odf_inexistente_falla_explicito(servicio_para_odf_inexistente):
    servicio_id = servicio_para_odf_inexistente
    async with AsyncSessionLocal() as sesion:
        with pytest.raises(ObjetoNoEncontrado):
            await crear_override(
                sesion,
                servicio_id=servicio_id,
                odf_n_id=_ODF_INEXISTENTE_N_ID,
                categoria_causa="OTRO",
                usuario="qa-real-db",
            )

    # Ningún override colgado: el chequeo de existencia corre ANTES del INSERT.
    with SessionLocal() as session:
        fila = session.execute(
            text("SELECT 1 FROM app.cromo_servicio_odf_override WHERE servicio_id = :sid"),
            {"sid": servicio_id},
        ).first()
    assert fila is None


# ─────────────────────────────────────────────────────────────────────────────
# FK dura servicio_id → servicios.id (ondelete=CASCADE)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def escenario_cascade():
    _borrar_servicios_y_overrides([_NUM_CASCADE])
    with SessionLocal() as session:
        session.execute(_SQL_ALTA_ODF, {"n_id": _ODF_CASCADE_N_ID, "nombre": "ODF QA Cascade"})
        servicio_id = _alta_servicio(session, _NUM_CASCADE)
        session.commit()
    try:
        yield servicio_id
    finally:
        with SessionLocal() as session:
            session.execute(text("DELETE FROM app.cromo_odfs WHERE n_id = :n_id"), {"n_id": _ODF_CASCADE_N_ID})
            session.commit()
        # El test borra el Servicio directo por SQL para probar el CASCADE — este cleanup es
        # idempotente si ya no queda nada.
        _borrar_servicios_y_overrides([_NUM_CASCADE])


@pytest.mark.asyncio
async def test_fk_cascade_borra_el_override_al_borrar_el_servicio(escenario_cascade):
    servicio_id = escenario_cascade
    async with AsyncSessionLocal() as sesion:
        override = await crear_override(
            sesion,
            servicio_id=servicio_id,
            odf_n_id=_ODF_CASCADE_N_ID,
            categoria_causa="OTRO",
            usuario="qa-real-db",
        )
    assert override.id is not None

    with SessionLocal() as session:
        antes = session.execute(
            text("SELECT 1 FROM app.cromo_servicio_odf_override WHERE servicio_id = :sid"),
            {"sid": servicio_id},
        ).first()
        assert antes is not None

        session.execute(text("DELETE FROM app.servicios WHERE id = :sid"), {"sid": servicio_id})
        session.commit()

        despues = session.execute(
            text("SELECT 1 FROM app.cromo_servicio_odf_override WHERE servicio_id = :sid"),
            {"sid": servicio_id},
        ).first()
        assert despues is None


# ─────────────────────────────────────────────────────────────────────────────
# Los 3 CHECK constraints reales (INSERT crudo, sin pasar por crear_override: el objetivo es
# confirmar que la DB los hace cumplir, no revalidar la capa Python)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def servicio_para_checks():
    """Servicio real para que la FK de `servicio_id` nunca sea la causa del error — cada test aísla
    específicamente el CHECK que le toca probar."""
    _borrar_servicios_y_overrides([_NUM_CHECK])
    with SessionLocal() as session:
        servicio_id = _alta_servicio(session, _NUM_CHECK)
        session.commit()
    try:
        yield servicio_id
    finally:
        _borrar_servicios_y_overrides([_NUM_CHECK])


def test_check_categoria_causa_invalida_falla(servicio_para_checks):
    servicio_id = servicio_para_checks
    with pytest.raises(IntegrityError):
        with SessionLocal() as session:
            session.execute(
                _SQL_INSERT_OVERRIDE_RAW,
                {
                    "servicio_id": servicio_id,
                    "odf_n_id": _ODF_CHECK_N_ID,
                    "categoria_causa": "CATEGORIA_QUE_NO_EXISTE",
                    "subcategoria": None,
                    "senal_direccion": None,
                },
            )
            session.commit()

    with SessionLocal() as session:
        fila = session.execute(
            text("SELECT 1 FROM app.cromo_servicio_odf_override WHERE servicio_id = :sid"),
            {"sid": servicio_id},
        ).first()
    assert fila is None


def test_check_subcategoria_invalida_falla(servicio_para_checks):
    servicio_id = servicio_para_checks
    with pytest.raises(IntegrityError):
        with SessionLocal() as session:
            session.execute(
                _SQL_INSERT_OVERRIDE_RAW,
                {
                    "servicio_id": servicio_id,
                    "odf_n_id": _ODF_CHECK_N_ID,
                    "categoria_causa": "OTRO",
                    "subcategoria": "SUBCATEGORIA_QUE_NO_EXISTE",
                    "senal_direccion": None,
                },
            )
            session.commit()

    with SessionLocal() as session:
        fila = session.execute(
            text("SELECT 1 FROM app.cromo_servicio_odf_override WHERE servicio_id = :sid"),
            {"sid": servicio_id},
        ).first()
    assert fila is None


def test_check_senal_direccion_invalida_falla(servicio_para_checks):
    servicio_id = servicio_para_checks
    with pytest.raises(IntegrityError):
        with SessionLocal() as session:
            session.execute(
                _SQL_INSERT_OVERRIDE_RAW,
                {
                    "servicio_id": servicio_id,
                    "odf_n_id": _ODF_CHECK_N_ID,
                    "categoria_causa": "OTRO",
                    "subcategoria": None,
                    "senal_direccion": "SENAL_QUE_NO_EXISTE",
                },
            )
            session.commit()

    with SessionLocal() as session:
        fila = session.execute(
            text("SELECT 1 FROM app.cromo_servicio_odf_override WHERE servicio_id = :sid"),
            {"sid": servicio_id},
        ).first()
    assert fila is None


def test_check_valores_validos_de_los_tres_campos_no_falla(servicio_para_checks):
    """Contraparte de los tres tests anteriores: los valores reales del vocabulario (mismos
    literales que `servicios_sin_odf.py`/`direccion_comparacion.py`) sí pasan el CHECK."""
    servicio_id = servicio_para_checks
    with SessionLocal() as session:
        session.execute(
            _SQL_INSERT_OVERRIDE_RAW,
            {
                "servicio_id": servicio_id,
                "odf_n_id": _ODF_CHECK_N_ID,
                "categoria_causa": "SIN_SENAL_PROV",
                "subcategoria": "PELO_SIN_CONECTOR_ODF",
                "senal_direccion": "no_se_pudo_comparar",
            },
        )
        session.commit()

    with SessionLocal() as session:
        fila = session.execute(
            text("SELECT 1 FROM app.cromo_servicio_odf_override WHERE servicio_id = :sid"),
            {"sid": servicio_id},
        ).first()
    assert fila is not None


# ─────────────────────────────────────────────────────────────────────────────
# servicios_por_odf — suma el override manual sin duplicar el matching automático
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def escenario_dedupe_odf():
    """Un ODF con dos Servicios:

    - `automatico_id`: alcanzado por matching automático (pelo→match, vía `cables_asociados`) Y con
      un override manual vigente a la MISMA odf — no debe duplicarse en el resultado.
    - `solo_override_id`: sin ningún pelo/match, alcanzado ÚNICAMENTE por el override manual — debe
      aparecer con `origen="override_manual"`.

    Sin fila propia de `cromo_cables`: `_SQL_SERVICIOS_POR_ODF` sólo necesita que
    `cromo_pelos.cable_n_id` aparezca en `cromo_odfs.cables_asociados`, no una fila real en
    `cromo_cables` (mismo hallazgo ya documentado por `test_cromo_odf_inventario_real_db.py`).
    """
    numeros = [_NUM_AUTOMATICO_Y_OVERRIDE, _NUM_SOLO_OVERRIDE]
    _borrar_servicios_y_overrides(numeros)
    with SessionLocal() as session:
        session.execute(text("DELETE FROM app.cromo_servicio_match WHERE pelo_n_id = :pelo"), {"pelo": _PELO_DEDUPE_N_ID})
        session.execute(text("DELETE FROM app.cromo_pelos WHERE n_id = :pelo"), {"pelo": _PELO_DEDUPE_N_ID})
        session.execute(text("DELETE FROM app.cromo_odfs WHERE n_id = :n_id"), {"n_id": _ODF_DEDUPE_N_ID})

        session.execute(
            _SQL_ALTA_ODF_CON_CABLES,
            {
                "n_id": _ODF_DEDUPE_N_ID,
                "nombre": "ODF QA Dedupe Override",
                "cables_asociados": "[%d]" % _CABLE_DEDUPE_N_ID,
            },
        )
        automatico_id = _alta_servicio(session, _NUM_AUTOMATICO_Y_OVERRIDE, cliente="QA Automatico")
        solo_override_id = _alta_servicio(session, _NUM_SOLO_OVERRIDE, cliente="QA Solo Override")
        session.execute(
            _SQL_ALTA_PELO,
            {
                "n_id": _PELO_DEDUPE_N_ID,
                "cable_n_id": _CABLE_DEDUPE_N_ID,
                "servicio_numero": _NUM_AUTOMATICO_Y_OVERRIDE,
            },
        )
        session.execute(
            _SQL_ALTA_MATCH,
            {
                "pelo_n_id": _PELO_DEDUPE_N_ID,
                "servicio_numero": _NUM_AUTOMATICO_Y_OVERRIDE,
                "servicio_id": automatico_id,
            },
        )
        session.commit()

    try:
        yield {"automatico_id": automatico_id, "solo_override_id": solo_override_id}
    finally:
        with SessionLocal() as session:
            session.execute(text("DELETE FROM app.cromo_servicio_match WHERE pelo_n_id = :pelo"), {"pelo": _PELO_DEDUPE_N_ID})
            session.execute(text("DELETE FROM app.cromo_pelos WHERE n_id = :pelo"), {"pelo": _PELO_DEDUPE_N_ID})
            session.execute(text("DELETE FROM app.cromo_odfs WHERE n_id = :n_id"), {"n_id": _ODF_DEDUPE_N_ID})
            session.commit()
        _borrar_servicios_y_overrides(numeros)


@pytest.mark.asyncio
async def test_servicios_por_odf_suma_override_manual_sin_duplicar_el_automatico(escenario_dedupe_odf):
    automatico_id = escenario_dedupe_odf["automatico_id"]
    solo_override_id = escenario_dedupe_odf["solo_override_id"]

    async with AsyncSessionLocal() as sesion:
        # El Servicio automático ADEMÁS tiene un override confirmando la MISMA odf — no debe
        # duplicarse en el resultado.
        await crear_override(
            sesion,
            servicio_id=automatico_id,
            odf_n_id=_ODF_DEDUPE_N_ID,
            categoria_causa="OTRO",
            usuario="qa-real-db",
        )
        # Este Servicio sólo tiene override, sin ningún pelo/match automático.
        await crear_override(
            sesion,
            servicio_id=solo_override_id,
            odf_n_id=_ODF_DEDUPE_N_ID,
            categoria_causa="OTRO",
            usuario="qa-real-db",
        )

    async with AsyncSessionLocal() as sesion:
        resultado = await servicios_por_odf(sesion, _ODF_DEDUPE_N_ID)

    por_id = {s.servicio_id: s for s in resultado.servicios}
    # Ni duplicado (el automático no aparece dos veces) ni faltante (el sólo-override aparece).
    assert len(resultado.servicios) == 2
    assert set(por_id.keys()) == {automatico_id, solo_override_id}

    automatico = por_id[automatico_id]
    assert automatico.origen == "automatico"
    # Gana la fila automática: trae el pelo/método REALES de la resolución por texto, no los del
    # override (que en este caso ni siquiera tiene pelo_n_id pineado).
    assert automatico.pelo_n_id == _PELO_DEDUPE_N_ID
    assert automatico.metodo == "REGEX_EXACTO"
    assert automatico.servicio_numero_match == _NUM_AUTOMATICO_Y_OVERRIDE

    solo_override = por_id[solo_override_id]
    assert solo_override.origen == "override_manual"
    assert solo_override.servicio_id_externo == _NUM_SOLO_OVERRIDE
    assert solo_override.pelo_n_id is None  # el override de este test no pineó ningún pelo
    assert solo_override.metodo == "OVERRIDE_MANUAL"


@pytest.mark.asyncio
async def test_servicios_por_odf_sin_overrides_se_comporta_igual_que_antes(escenario_dedupe_odf):
    """Sin overrides todavía creados, `servicios_por_odf` sigue devolviendo sólo el Servicio
    automático — confirma que sumar la Tarea 4 no le agrega nada quien no tiene overrides."""
    automatico_id = escenario_dedupe_odf["automatico_id"]

    async with AsyncSessionLocal() as sesion:
        resultado = await servicios_por_odf(sesion, _ODF_DEDUPE_N_ID)

    assert [s.servicio_id for s in resultado.servicios] == [automatico_id]
    assert resultado.servicios[0].origen == "automatico"


# ─────────────────────────────────────────────────────────────────────────────
# overrides_vigentes_por_odf — una fila por servicio_id, la más reciente de cada uno
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_overrides_vigentes_por_odf_una_fila_por_servicio_la_mas_reciente(servicio_override_feliz):
    servicio_id = servicio_override_feliz
    async with AsyncSessionLocal() as sesion:
        await crear_override(
            sesion,
            servicio_id=servicio_id,
            odf_n_id=_ODF_FELIZ_N_ID,
            categoria_causa="OLT_PON_COMPARTIDO",
            usuario="qa-real-db",
            notas="viejo",
        )
        segundo = await crear_override(
            sesion,
            servicio_id=servicio_id,
            odf_n_id=_ODF_FELIZ_N_ID,
            categoria_causa="SIN_SENAL_PROV",
            usuario="qa-real-db",
            notas="vigente",
        )

    async with AsyncSessionLocal() as sesion:
        vigentes = await overrides_vigentes_por_odf(sesion, _ODF_FELIZ_N_ID)

    assert [o.servicio_id for o in vigentes] == [servicio_id]
    assert vigentes[0].id == segundo.id
    assert vigentes[0].notas == "vigente"


@pytest.mark.asyncio
async def test_overrides_vigentes_por_odf_vacio_sin_overrides():
    async with AsyncSessionLocal() as sesion:
        vigentes = await overrides_vigentes_por_odf(sesion, _ODF_INEXISTENTE_N_ID)
    assert vigentes == []


# ─────────────────────────────────────────────────────────────────────────────
# Reasociación cross-ODF — bug real (Important 1, round 1 de review): el `DISTINCT ON` no puede
# filtrar por `odf_n_id` ANTES de deduplicar, o un Servicio reasociado de una ODF a otra queda
# duplicado entre las dos vistas de detalle en vez de aparecer sólo bajo la más nueva.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def servicio_para_reasociacion():
    _borrar_servicios_y_overrides([_NUM_REASOCIACION])
    with SessionLocal() as session:
        session.execute(_SQL_ALTA_ODF, {"n_id": _ODF_REASOCIACION_A_N_ID, "nombre": "ODF QA Reasociacion A"})
        session.execute(_SQL_ALTA_ODF, {"n_id": _ODF_REASOCIACION_B_N_ID, "nombre": "ODF QA Reasociacion B"})
        servicio_id = _alta_servicio(session, _NUM_REASOCIACION, cliente="QA Reasociacion")
        session.commit()
    try:
        yield servicio_id
    finally:
        with SessionLocal() as session:
            session.execute(
                text("DELETE FROM app.cromo_odfs WHERE n_id = ANY(:ids)"),
                {"ids": [_ODF_REASOCIACION_A_N_ID, _ODF_REASOCIACION_B_N_ID]},
            )
            session.commit()
        _borrar_servicios_y_overrides([_NUM_REASOCIACION])


@pytest.mark.asyncio
async def test_reasociacion_a_otra_odf_no_deja_al_servicio_duplicado_entre_las_dos(
    servicio_para_reasociacion,
):
    """Repro exacto del bug que encontró la review: override a la ODF A en t1, reasociación (INSERT
    nuevo, sin UPDATE) a la ODF B en t2 > t1. El Servicio debe aparecer SÓLO bajo B — nunca bajo
    las dos, y nunca "olvidado" de las dos."""
    servicio_id = servicio_para_reasociacion
    async with AsyncSessionLocal() as sesion:
        viejo = await crear_override(
            sesion,
            servicio_id=servicio_id,
            odf_n_id=_ODF_REASOCIACION_A_N_ID,
            categoria_causa="OTRO",
            usuario="qa-real-db",
            notas="odf-a-vieja",
        )
        nuevo = await crear_override(
            sesion,
            servicio_id=servicio_id,
            odf_n_id=_ODF_REASOCIACION_B_N_ID,
            categoria_causa="OTRO",
            usuario="qa-real-db",
            notas="odf-b-nueva",
        )
    assert nuevo.id > viejo.id

    async with AsyncSessionLocal() as sesion:
        vigente = await override_vigente_de_servicio(sesion, servicio_id)
        vigentes_a = await overrides_vigentes_por_odf(sesion, _ODF_REASOCIACION_A_N_ID)
        vigentes_b = await overrides_vigentes_por_odf(sesion, _ODF_REASOCIACION_B_N_ID)

    assert vigente is not None
    assert vigente.id == nuevo.id
    # El corazón del bug: la ODF vieja NO debe seguir viendo a este Servicio como vigente.
    assert vigentes_a == []
    assert [o.id for o in vigentes_b] == [nuevo.id]

    async with AsyncSessionLocal() as sesion:
        resultado_a = await servicios_por_odf(sesion, _ODF_REASOCIACION_A_N_ID)
        resultado_b = await servicios_por_odf(sesion, _ODF_REASOCIACION_B_N_ID)

    # Sin match automático a ninguna de las dos: sólo el override manda, y sólo bajo la ODF nueva.
    assert resultado_a.servicios == []
    assert [s.servicio_id for s in resultado_b.servicios] == [servicio_id]
    assert resultado_b.servicios[0].origen == "override_manual"


# ─────────────────────────────────────────────────────────────────────────────
# crear_override rechaza una ODF conocida SOLO por sus conectores (Important 2, round 1 de review)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def servicio_para_odf_solo_conector():
    """Una ODF sin fila propia en `cromo_odfs`, conocida únicamente por un conector real en
    `cromo_odf_conectores` — el mismo tipo de "referencia colgada" que `odf_conectores.py::
    conectores_de_odf` SÍ tolera para lectura, pero que `servicios_por_odf`/`obtener_detalle_odf`
    (y, desde el fix de esta review, `crear_override`) tratan como "no existe"."""
    _borrar_servicios_y_overrides([_NUM_ODF_SOLO_CONECTOR])
    with SessionLocal() as session:
        session.execute(
            _SQL_ALTA_CONECTOR_SOLO,
            {"n_id": _CONECTOR_SOLO_N_ID, "odf_n_id": _ODF_SOLO_CONECTOR_N_ID},
        )
        servicio_id = _alta_servicio(session, _NUM_ODF_SOLO_CONECTOR)
        session.commit()
    try:
        yield servicio_id
    finally:
        with SessionLocal() as session:
            session.execute(
                text("DELETE FROM app.cromo_odf_conectores WHERE n_id = :n_id"),
                {"n_id": _CONECTOR_SOLO_N_ID},
            )
            session.commit()
        _borrar_servicios_y_overrides([_NUM_ODF_SOLO_CONECTOR])


@pytest.mark.asyncio
async def test_crear_override_rechaza_odf_conocida_solo_por_conectores_sin_fila_propia(
    servicio_para_odf_solo_conector,
):
    servicio_id = servicio_para_odf_solo_conector
    async with AsyncSessionLocal() as sesion:
        with pytest.raises(ObjetoNoEncontrado):
            await crear_override(
                sesion,
                servicio_id=servicio_id,
                odf_n_id=_ODF_SOLO_CONECTOR_N_ID,
                categoria_causa="OTRO",
                usuario="qa-real-db",
            )

    with SessionLocal() as session:
        fila = session.execute(
            text("SELECT 1 FROM app.cromo_servicio_odf_override WHERE servicio_id = :sid"),
            {"sid": servicio_id},
        ).first()
    assert fila is None
