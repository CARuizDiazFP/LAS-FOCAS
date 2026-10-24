# Nombre de archivo: test_cromo_odf_conectores_real_db.py
# Ubicación de archivo: tests/test_cromo_odf_conectores_real_db.py
# Descripción: Prueba de integración contra Postgres real — el LATERAL JOIN de conectores_de_odf necesita el driver real para ANY(text[]) y para probar la exclusión anti-ambigüedad

"""Este archivo es de integración: necesita un Postgres real con el esquema `app.*` poblado.
Mismo motivo y guard que el resto de los tests `*_real_db.py` de este módulo.

Caso central que justifica este archivo: `conectores_de_odf` resuelve Cliente/Estado de
`servicio_resuelto` contra `app.servicios` con el mismo criterio anti-ambigüedad de
`core/services/cromo/ingesta.py::_SQL_BUSCAR_SERVICIO` (excluye una fila cuya identidad ya fue
absorbida como alias de otra) — reproduce el escenario real que motivó ese fix (par de filas
`servicios` en conflicto, ver docs/decisiones.md 2026-08-31) para confirmar que la ODF resuelve al
Cliente/Estado de la fila vigente, no de la superada, contra el driver real (LATERAL + `ANY` sobre
`text[]` nunca se ejercita con un mock)."""

from __future__ import annotations


import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from db.session import SessionLocal, async_engine
from tests.soporte_postgres_real import requiere_postgres_real

# Guard compartido (2026-09-19): saltea en CI Y en cualquier máquina sin un Postgres respondiendo,
# con un motivo que dice cómo habilitarlos. Ver `tests/soporte_postgres_real.py`.
pytestmark = requiere_postgres_real

_engine_test = create_async_engine(async_engine.url.render_as_string(hide_password=False), poolclass=NullPool)
AsyncSessionLocal = async_sessionmaker(_engine_test, expire_on_commit=False)

# Rango sintético fuera de lo que Cromo/SLA real puede asignar, mismo criterio que el resto de los
# tests real_db — nunca pisa datos reales de dev.
_ODF_N_ID = 999_900_040
_CONECTOR_N_ID = 999_900_041
_NUMERO_AMBIGUO = "9999901"
_NUMERO_ORIGEN_VIGENTE = "9999902"


@pytest.fixture
def escenario_conector_con_ambiguedad():
    """Un conector cuyo `servicio_resuelto` coincide con DOS filas de `app.servicios`: una
    "superada" (su propio `servicio_id` es el número ambiguo, sin cliente real) y una "vigente"
    (absorbió ese número como alias, con cliente real) — mismo patrón que el caso real 49/557."""
    with SessionLocal() as session:
        superada_id = int(
            session.execute(
                text(
                    "INSERT INTO app.servicios "
                    "(servicio_id, numero_primer_servicio, categoria, origen_datos, estado_servicio) "
                    "VALUES (:numero, :numero, 0, 'MANUAL', 'DESCONOCIDO') RETURNING id"
                ),
                {"numero": _NUMERO_AMBIGUO},
            ).scalar_one()
        )
        vigente_id = int(
            session.execute(
                text(
                    "INSERT INTO app.servicios "
                    "(servicio_id, numero_primer_servicio, alias_ids, nombre_cliente, categoria, "
                    " origen_datos, estado_servicio) "
                    "VALUES (:numero_origen, :numero_origen, ARRAY[:alias], 'Cliente Conector Test', 6, "
                    " 'INGEST_EXCEL', 'Activo') RETURNING id"
                ),
                {"numero_origen": _NUMERO_ORIGEN_VIGENTE, "alias": _NUMERO_AMBIGUO},
            ).scalar_one()
        )
        session.execute(
            text(
                "INSERT INTO app.cromo_odf_conectores "
                "(n_id, odf_n_id, numero_conector, servicio_resuelto, payload_raw) "
                "VALUES (:n_id, :odf, '15', :numero, '{}'::jsonb)"
            ),
            {"n_id": _CONECTOR_N_ID, "odf": _ODF_N_ID, "numero": _NUMERO_AMBIGUO},
        )
        session.commit()

    try:
        yield {"superada_id": superada_id, "vigente_id": vigente_id}
    finally:
        with SessionLocal() as session:
            session.execute(
                text("DELETE FROM app.cromo_odf_conectores WHERE n_id = :n_id"), {"n_id": _CONECTOR_N_ID}
            )
            session.execute(
                text("DELETE FROM app.servicios WHERE id = ANY(:ids)"),
                {"ids": [superada_id, vigente_id]},
            )
            session.commit()


@pytest.mark.asyncio
async def test_conectores_de_odf_resuelve_cliente_de_la_fila_vigente_no_la_superada(
    escenario_conector_con_ambiguedad,
):
    from core.services.cromo.odf_conectores import conectores_de_odf

    async with AsyncSessionLocal() as sesion:
        resultado = await conectores_de_odf(sesion, _ODF_N_ID)

    assert len(resultado.conectores) == 1
    conector = resultado.conectores[0]
    assert conector.servicio_resuelto == _NUMERO_AMBIGUO
    assert conector.nombre_cliente == "Cliente Conector Test"
    assert conector.estado_servicio == "Activo"
    assert conector.servicio_id_externo == _NUMERO_ORIGEN_VIGENTE


# ── `track odf`: datos reales de dev, sólo lectura ───────────────────────────
# Patcheras reales medidas el 2026-10-21: O-1252871-1 es una sola bandeja (8604881, ODF San Martin
# 137 P5 D, la del 93150); O-1249273-1 está en dos ODF distintas.


@pytest.mark.asyncio
@pytest.mark.parametrize("nombre", ["O-1252871-1", "o-1252871-1", "0-1252871-1", " O-1252871-1 "])
async def test_bandejas_por_nombre_patchera_unica(nombre):
    from core.services.cromo.odf_conectores import bandejas_por_nombre

    async with AsyncSessionLocal() as sesion:
        bandejas = await bandejas_por_nombre(sesion, nombre)

    assert [(b.bandeja_n_id, b.bandeja_nombre, b.odf_n_id) for b in bandejas] == [
        (8604881, "O-1252871-1", 6644560)
    ]
    assert bandejas[0].odf_nombre == "ODF San Martin 137 P5 D"


@pytest.mark.asyncio
async def test_bandejas_por_nombre_patchera_ambigua_lista_las_dos():
    from core.services.cromo.odf_conectores import bandejas_por_nombre

    async with AsyncSessionLocal() as sesion:
        bandejas = await bandejas_por_nombre(sesion, "O-1249273-1")

    assert len(bandejas) == 2
    assert {b.odf_n_id for b in bandejas} == {6644107, 9193140}


@pytest.mark.asyncio
async def test_conectores_de_bandeja_del_93150():
    from core.services.cromo.odf_conectores import conectores_de_bandeja

    async with AsyncSessionLocal() as sesion:
        conectores = await conectores_de_bandeja(sesion, 8604881, ["1", "2", "5"])

    por_numero = {c.numero_conector: c for c in conectores}
    assert set(por_numero) == {"1", "2", "5"}
    uno = por_numero["1"]
    assert (uno.n_id, uno.pelo_n_id, uno.cable_nombre) == (8604882, 7028862, "F-PC-CC")
    assert (uno.servicio_pk, uno.servicio_numero, uno.estado_servicio) == (4, "93150", "Activo")
    assert uno.nombre_cliente == "BANCO DE LA PROVINCIA DE BUENOS AIRES"
    assert (uno.historico_numero, uno.historico_estado) == ("44649", "Baja")
    assert (uno.etiqueta_numero, uno.etiqueta_estado) == ("44649", "Baja")
    assert por_numero["2"].pelo_n_id == 7028863
    cinco = por_numero["5"]
    assert cinco.pelo_n_id is None and cinco.pelo_efectivo is None
    assert cinco.servicio_pk is None and cinco.etiqueta_numero is None


@pytest.mark.asyncio
async def test_conectores_de_bandeja_sigue_un_salto_de_patch():
    """O-1262507-3:9 (conector 8628719) no tiene pelo pero tiene patch al 8628742, que sí."""
    from core.services.cromo.odf_conectores import conectores_de_bandeja

    async with AsyncSessionLocal() as sesion:
        (conector,) = await conectores_de_bandeja(sesion, 8628710, ["9"])

    assert conector.n_id == 8628719
    assert conector.pelo_n_id is None
    assert conector.patch_conector_n_id == 8628742
    assert conector.patch_pelo_n_id == 10197026
    assert conector.pelo_efectivo == 10197026


@pytest.mark.asyncio
async def test_conectores_de_bandeja_con_odf_da_lo_mismo():
    from core.services.cromo.odf_conectores import conectores_de_bandeja

    async with AsyncSessionLocal() as sesion:
        sin_odf = await conectores_de_bandeja(sesion, 8604881, ["1", "2", "5"])
        con_odf = await conectores_de_bandeja(sesion, 8604881, ["1", "2", "5"], odf_n_id=6644560)
        otra_odf = await conectores_de_bandeja(sesion, 8604881, ["1"], odf_n_id=6644107)

    assert con_odf == sin_odf
    assert otra_odf == []
