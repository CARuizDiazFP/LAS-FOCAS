# Nombre de archivo: test_cromo_odfs_por_servicio_real_db.py
# Ubicación de archivo: tests/test_cromo_odfs_por_servicio_real_db.py
# Descripción: Pruebas de integración contra Postgres real de `odfs_por_servicio` — las tres vías de resolución Cromo, su precedencia y el dedupe por ODF

"""Integración contra un Postgres real con el esquema `app.*` (mismo guard y mismo motivo que
`tests/test_cromo_odf_inventario_real_db.py`).

Por qué real y no sesión fake: lo que se prueba acá es SQL — una unión de tres vías con dedupe por
`odf_n_id`, `COUNT(DISTINCT ...)` sobre esa unión y precedencia de etiqueta. Una sesión fake
devuelve las filas que uno le dicta, así que confirmaría la forma del dataclass y nada del
comportamiento que importa. El caso que motivó el módulo (una ODF alcanzada por las DOS vías
automáticas a la vez debe salir UNA sola vez y etiquetada `servicio_resuelto`) es indistinguible de
un bug de doble conteo si no corre contra un motor real.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from db.session import SessionLocal, async_engine
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real

# Mismo criterio de pool que el resto de los `*_real_db`: NullPool para que ninguna conexión
# sobreviva al event loop del test que la abrió.
_engine_test = create_async_engine(async_engine.url.render_as_string(hide_password=False), poolclass=NullPool)
AsyncSessionLocal = async_sessionmaker(_engine_test, expire_on_commit=False)

# Rango sintético propio, separado del 999_900_xxx que ya usa test_cromo_odf_inventario_real_db.py:
# los dos archivos pueden correr en la misma pasada y nunca deben pisarse.
_ODF_CANONICA = 999_910_001
_ODF_SOLO_PELO = 999_910_002
_ODF_AMBAS = 999_910_003
_ODF_OVERRIDE = 999_910_004
_PELO_A = 999_910_101
_PELO_B = 999_910_102
_CONECTOR_BASE = 999_910_200
# Las tres identidades del Servicio, deliberadamente distintas entre sí: si la query matcheara sólo
# por `servicio_id` (la PK externa), los casos montados sobre las otras dos quedarían invisibles.
_NUMERO_ACTUAL = "9999101"
_NUMERO_PRIMERO = "9999102"
_ALIAS = "9999103"


def _insertar_conector(session, n_id: int, odf_n_id: int, *, pelo_n_id=None, servicio_resuelto=None):
    session.execute(
        text(
            "INSERT INTO app.cromo_odf_conectores "
            "(n_id, odf_n_id, numero_conector, pelo_n_id, servicio_resuelto, payload_raw) "
            "VALUES (:n_id, :odf, :num, :pelo, :resuelto, '{}'::jsonb)"
        ),
        {
            "n_id": n_id,
            "odf": odf_n_id,
            "num": str(n_id % 100),
            "pelo": pelo_n_id,
            "resuelto": servicio_resuelto,
        },
    )


def _insertar_odf(session, n_id: int, nombre: str):
    session.execute(
        text(
            "INSERT INTO app.cromo_odfs (n_id, version_id, vmax, clase, nombre, calle, altura, "
            " localidad, tipo_elemento, payload_raw) "
            "VALUES (:n_id, 1, 1, 69, :nombre, 'Calle Test', '100', 'CABA', 'ODF', '{}'::jsonb)"
        ),
        {"n_id": n_id, "nombre": nombre},
    )


@pytest.fixture
def servicio_con_odfs():
    """Monta un Servicio alcanzando cuatro ODFs, una por cada situación que la función distingue:

    - `_ODF_CANONICA`  — un conector con `servicio_resuelto` = el **alias** del Servicio (no su PK
      externa): cubre a la vez la vía canónica y la tercera identidad.
    - `_ODF_SOLO_PELO` — un conector sin `servicio_resuelto`, colgado de un pelo con match.
    - `_ODF_AMBAS`     — dos conectores: uno por `servicio_resuelto`, otro por pelo. Debe volver
      UNA fila, etiquetada `servicio_resuelto`, con `conectores=2`.
    - `_ODF_OVERRIDE`  — sin ninguna vía automática; sólo la asociación manual.
    """
    with SessionLocal() as session:
        servicio_id = int(
            session.execute(
                text(
                    "INSERT INTO app.servicios "
                    "(servicio_id, numero_primer_servicio, alias_ids, categoria, origen_datos, estado_servicio) "
                    "VALUES (:actual, :primero, :alias ::varchar[], 0, 'INFERIDO_CROMO', 'DESCONOCIDO') "
                    "RETURNING id"
                ),
                {"actual": _NUMERO_ACTUAL, "primero": _NUMERO_PRIMERO, "alias": [_ALIAS]},
            ).scalar_one()
        )

        for pelo in (_PELO_A, _PELO_B):
            session.execute(
                text(
                    "INSERT INTO app.cromo_pelos (n_id, tubo_n_id, cable_n_id, servicio_numero) "
                    "VALUES (:pelo, :pelo, :pelo, :numero)"
                ),
                {"pelo": pelo, "numero": _NUMERO_ACTUAL},
            )
            session.execute(
                text(
                    "INSERT INTO app.cromo_servicio_match (pelo_n_id, servicio_numero, servicio_id, metodo) "
                    "VALUES (:pelo, :numero, :servicio_id, 'REGEX_EXACTO')"
                ),
                {"pelo": pelo, "numero": _NUMERO_ACTUAL, "servicio_id": servicio_id},
            )

        _insertar_odf(session, _ODF_CANONICA, "ODF Canonica Test")
        _insertar_odf(session, _ODF_SOLO_PELO, "ODF Solo Pelo Test")
        _insertar_odf(session, _ODF_AMBAS, "ODF Ambas Test")
        _insertar_odf(session, _ODF_OVERRIDE, "ODF Override Test")

        _insertar_conector(session, _CONECTOR_BASE + 1, _ODF_CANONICA, servicio_resuelto=_ALIAS)
        _insertar_conector(session, _CONECTOR_BASE + 2, _ODF_SOLO_PELO, pelo_n_id=_PELO_A)
        _insertar_conector(session, _CONECTOR_BASE + 3, _ODF_AMBAS, servicio_resuelto=_NUMERO_PRIMERO)
        _insertar_conector(session, _CONECTOR_BASE + 4, _ODF_AMBAS, pelo_n_id=_PELO_B)

        session.commit()

    try:
        yield {"servicio_id": servicio_id}
    finally:
        with SessionLocal() as session:
            session.execute(
                text("DELETE FROM app.cromo_servicio_odf_override WHERE servicio_id = :s"),
                {"s": servicio_id},
            )
            session.execute(
                text("DELETE FROM app.cromo_odf_conectores WHERE odf_n_id = ANY(:odfs)"),
                {"odfs": [_ODF_CANONICA, _ODF_SOLO_PELO, _ODF_AMBAS, _ODF_OVERRIDE]},
            )
            session.execute(
                text("DELETE FROM app.cromo_odfs WHERE n_id = ANY(:odfs)"),
                {"odfs": [_ODF_CANONICA, _ODF_SOLO_PELO, _ODF_AMBAS, _ODF_OVERRIDE]},
            )
            session.execute(
                text("DELETE FROM app.cromo_servicio_match WHERE pelo_n_id = ANY(:pelos)"),
                {"pelos": [_PELO_A, _PELO_B]},
            )
            session.execute(
                text("DELETE FROM app.cromo_pelos WHERE n_id = ANY(:pelos)"), {"pelos": [_PELO_A, _PELO_B]}
            )
            session.execute(text("DELETE FROM app.servicios WHERE id = :s"), {"s": servicio_id})
            session.commit()


@pytest.mark.asyncio
async def test_devuelve_las_tres_vias_automaticas_sin_duplicar(servicio_con_odfs):
    from core.services.cromo.verificador import odfs_por_servicio

    async with AsyncSessionLocal() as sesion:
        resultado = await odfs_por_servicio(sesion, servicio_con_odfs["servicio_id"])

    por_id = {odf.odf_n_id: odf for odf in resultado}
    assert set(por_id) == {_ODF_CANONICA, _ODF_SOLO_PELO, _ODF_AMBAS}, (
        "sin override manual sólo deben salir las tres ODFs alcanzadas automáticamente"
    )
    # Una ODF alcanzada por las dos vías no puede volver dos veces: es el bug que este archivo existe
    # para atrapar.
    assert len(resultado) == 3


@pytest.mark.asyncio
async def test_etiqueta_el_origen_de_cada_via(servicio_con_odfs):
    from core.services.cromo.verificador import odfs_por_servicio

    async with AsyncSessionLocal() as sesion:
        resultado = await odfs_por_servicio(sesion, servicio_con_odfs["servicio_id"])

    origen = {odf.odf_n_id: odf.origen for odf in resultado}
    assert origen[_ODF_CANONICA] == "servicio_resuelto"
    assert origen[_ODF_SOLO_PELO] == "pelo"
    # Precedencia: llegar también por la vía canónica gana sobre la de pelo. Al revés, el operador
    # leería "esto no lo ve el gestor Sin ODF" sobre una ODF que sí ve.
    assert origen[_ODF_AMBAS] == "servicio_resuelto"


@pytest.mark.asyncio
async def test_cuenta_conectores_y_pelos_sin_doble_conteo(servicio_con_odfs):
    from core.services.cromo.verificador import odfs_por_servicio

    async with AsyncSessionLocal() as sesion:
        resultado = await odfs_por_servicio(sesion, servicio_con_odfs["servicio_id"])

    por_id = {odf.odf_n_id: odf for odf in resultado}
    assert por_id[_ODF_AMBAS].conectores == 2
    # Sólo uno de los dos conectores de esa ODF cuelga de un pelo; el otro llega por
    # `servicio_resuelto` y tiene `pelo_n_id` NULL, que no debe contarse como pelo.
    assert por_id[_ODF_AMBAS].pelos == 1
    assert por_id[_ODF_CANONICA].conectores == 1
    assert por_id[_ODF_CANONICA].pelos == 0


@pytest.mark.asyncio
async def test_suma_el_override_manual_como_via_propia(servicio_con_odfs):
    from core.services.cromo.servicio_odf_override_service import crear_override
    from core.services.cromo.verificador import odfs_por_servicio

    servicio_id = servicio_con_odfs["servicio_id"]
    async with AsyncSessionLocal() as sesion:
        await crear_override(
            sesion,
            servicio_id=servicio_id,
            odf_n_id=_ODF_OVERRIDE,
            categoria_causa="OTRO",
            usuario="test",
        )
        resultado = await odfs_por_servicio(sesion, servicio_id)

    por_id = {odf.odf_n_id: odf for odf in resultado}
    assert _ODF_OVERRIDE in por_id, "la asociación manual vigente también es una ODF del Servicio"
    assert por_id[_ODF_OVERRIDE].origen == "override_manual"
    # Y no pisa a las automáticas.
    assert por_id[_ODF_CANONICA].origen == "servicio_resuelto"


@pytest.mark.asyncio
async def test_servicio_sin_ninguna_via_devuelve_vacio():
    from core.services.cromo.verificador import odfs_por_servicio

    with SessionLocal() as session:
        servicio_id = int(
            session.execute(
                text(
                    "INSERT INTO app.servicios "
                    "(servicio_id, numero_primer_servicio, categoria, origen_datos, estado_servicio) "
                    "VALUES (:n, :n, 0, 'INFERIDO_CROMO', 'DESCONOCIDO') RETURNING id"
                ),
                {"n": "9999109"},
            ).scalar_one()
        )
        session.commit()
    try:
        async with AsyncSessionLocal() as sesion:
            assert await odfs_por_servicio(sesion, servicio_id) == []
    finally:
        with SessionLocal() as session:
            session.execute(text("DELETE FROM app.servicios WHERE id = :s"), {"s": servicio_id})
            session.commit()
