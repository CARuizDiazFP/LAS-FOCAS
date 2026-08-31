# Nombre de archivo: test_cromo_cable_extremo_odf_real_db.py
# Ubicación de archivo: tests/test_cromo_cable_extremo_odf_real_db.py
# Descripción: Regresión contra Postgres real — un cable con un extremo en una ODF debe resolver el nombre del extremo, no quedar en blanco

"""Bug real (2026-08-31, ticket duplicidad Buscador/ODFs): `inventario.py`/`detalle.py`/
`verificador.py` resuelven `extremo_a_nombre`/`extremo_b_nombre` con `LEFT JOIN app.cromo_botellas`
únicamente. Desde el submódulo ODFs (2026-08-28) un extremo puede terminar en `app.cromo_odfs`
(clase 69) en vez de una Botella — sin el JOIN a esa tabla, el nombre queda NULL y cae al valor
crudo de `cromo_cables.extremo_b_nombre`, que Cromo no manda para ODFs (queda `''`). Reproducido
real contra `lasfocasdev-postgres` con el cable `F-5DJ-NET` (n_id 6594965, extremo B = ODF n_id
6642085 "ODF Rack Netizen 5 de Julio 478 C.F."): `SELECT ... LEFT JOIN cromo_botellas` da
`extremo_b_nombre=''` pese a que la fila SÍ existe, sólo que en `cromo_odfs`.

Mismo motivo/guard que `test_cromo_odf_inventario_real_db.py`: necesita Postgres real con el
esquema `app.*` poblado; un mock nunca ejercita el JOIN SQL en sí.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from db.session import SessionLocal, async_engine

pytestmark = pytest.mark.skipif(
    os.getenv("CI") == "true",
    reason="requiere Postgres real alcanzable; el workflow de CI no tiene ese servicio configurado",
)

_engine_test = create_async_engine(async_engine.url.render_as_string(hide_password=False), poolclass=NullPool)
AsyncSessionLocal = async_sessionmaker(_engine_test, expire_on_commit=False)

# Rango sintético fuera de lo que Cromo real puede asignar, mismo criterio que
# test_cromo_odf_inventario_real_db.py — nunca pisa datos reales de dev.
_ODF_N_ID = 999_900_020
_BOTELLA_N_ID = 999_900_021
_CABLE_N_ID = 999_900_022


@pytest.fixture
def cable_con_extremo_odf():
    """Cable sintético con extremo A en una Botella (caso ya funcionaba) y extremo B en una ODF
    (caso roto): `extremo_b_nombre` crudo se deja vacío a propósito, igual que lo manda Cromo real
    para ODFs (confirmado contra `lasfocasdev-postgres`: `cromo_cables.extremo_b_nombre = ''` para
    F-5DJ-NET pese a que el extremo real sí tiene nombre, sólo que en `cromo_odfs`)."""
    with SessionLocal() as session:
        session.execute(
            text(
                "INSERT INTO app.cromo_botellas (n_id, version_id, vmax, clase, nombre, payload_raw) "
                "VALUES (:n_id, 1, 1, 121, 'Botella Test Extremo A', '{}'::jsonb)"
            ),
            {"n_id": _BOTELLA_N_ID},
        )
        session.execute(
            text(
                "INSERT INTO app.cromo_odfs "
                "(n_id, version_id, vmax, clase, nombre, tipo_elemento, cables_asociados, payload_raw) "
                "VALUES (:n_id, 1, 1, 69, 'ODF Test Extremo B', 'ODF', '[]'::jsonb, '{}'::jsonb)"
            ),
            {"n_id": _ODF_N_ID},
        )
        session.execute(
            text(
                "INSERT INTO app.cromo_cables "
                "(n_id, version_id, vmax, nombre, vigente, "
                " extremo_a_n_id, extremo_a_clase, extremo_a_nombre, "
                " extremo_b_n_id, extremo_b_clase, extremo_b_nombre, payload_raw) "
                "VALUES (:cable, 1, 1, 'Cable Test Extremo ODF', true, "
                " :botella, 121, 'Botella Test Extremo A', "
                " :odf, 69, '', '{}'::jsonb)"
            ),
            {"cable": _CABLE_N_ID, "botella": _BOTELLA_N_ID, "odf": _ODF_N_ID},
        )
        session.commit()

    try:
        yield {"cable_n_id": _CABLE_N_ID, "botella_n_id": _BOTELLA_N_ID, "odf_n_id": _ODF_N_ID}
    finally:
        with SessionLocal() as session:
            session.execute(text("DELETE FROM app.cromo_cables WHERE n_id = :n_id"), {"n_id": _CABLE_N_ID})
            session.execute(text("DELETE FROM app.cromo_odfs WHERE n_id = :n_id"), {"n_id": _ODF_N_ID})
            session.execute(text("DELETE FROM app.cromo_botellas WHERE n_id = :n_id"), {"n_id": _BOTELLA_N_ID})
            session.commit()


@pytest.mark.asyncio
async def test_buscar_cables_resuelve_extremo_b_en_odf_contra_driver_real(cable_con_extremo_odf):
    from core.services.cromo.inventario import buscar_cables

    async with AsyncSessionLocal() as sesion:
        resultado = await buscar_cables(sesion, n_id=_CABLE_N_ID)

    assert len(resultado.cables) == 1
    cable = resultado.cables[0]
    assert cable.extremo_a_nombre == "Botella Test Extremo A"
    assert cable.extremo_b_nombre == "ODF Test Extremo B"


@pytest.mark.asyncio
async def test_obtener_detalle_cable_resuelve_extremo_b_en_odf_contra_driver_real(cable_con_extremo_odf):
    from core.services.cromo.detalle import obtener_detalle_cable

    async with AsyncSessionLocal() as sesion:
        detalle = await obtener_detalle_cable(sesion, _CABLE_N_ID)

    assert detalle.extremo_a_nombre == "Botella Test Extremo A"
    assert detalle.extremo_b_nombre == "ODF Test Extremo B"
    assert detalle.extremo_b_n_id == _ODF_N_ID
    assert detalle.extremo_b_clase == 69


@pytest.mark.asyncio
async def test_servicios_por_cable_resuelve_extremo_b_en_odf_contra_driver_real(cable_con_extremo_odf):
    from core.services.cromo.verificador import servicios_por_cable

    async with AsyncSessionLocal() as sesion:
        resultado = await servicios_por_cable(sesion, _CABLE_N_ID)

    assert resultado.extremo_a_nombre == "Botella Test Extremo A"
    assert resultado.extremo_b_nombre == "ODF Test Extremo B"
