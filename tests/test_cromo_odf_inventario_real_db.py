# Nombre de archivo: test_cromo_odf_inventario_real_db.py
# Ubicación de archivo: tests/test_cromo_odf_inventario_real_db.py
# Descripción: Pruebas de integración contra un Postgres real para el submódulo ODFs (Tarea 4) — el bug de inferencia de tipos de asyncpg sólo lo detecta un driver real, nunca un mock

"""Este archivo es de integración: necesita un Postgres real alcanzable con el esquema `app.*`
poblado (`cromo_odfs`, `cromo_cables`, `cromo_pelos`, `cromo_servicio_match`, `servicios`). Mismo
motivo y mismo guard que `tests/test_servicios_ingest_routes.py`: el workflow de CI corre
`pytest -q tests` sin un servicio Postgres, así que ahí estos tests fallarían por conexión, no por
regresión. Localmente hace falta apuntar `POSTGRES_HOST`/`POSTGRES_PORT` al Postgres de dev (el host
`postgres` del compose no resuelve desde la máquina, ver la skill `docker-rebuild`).

El caso central que justifica este archivo (no alcanza con los tests de `test_cromo_odf_inventario.py`
contra sesión fake): `buscar_odfs`/`obtener_detalle_odf`/`servicios_por_odf` con TODOS los filtros
opcionales en NULL a la vez, contra el driver `asyncpg` real. Sin el guard `CAST(:param AS <tipo>)`
en cada filtro opcional, asyncpg no puede inferir el tipo del primer parámetro NULL en la primera
preparación del statement y tira `AmbiguousParameterError: could not determine data type of
parameter $1` — reproducido real contra `lasfocasdev-postgres` (127.0.0.1:5433) al escribir este
módulo. Un mock nunca lo detecta porque nunca prepara un statement real.
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

# `db.session.AsyncSessionLocal` está atado al pool singleton `db.session.async_engine`
# (`AsyncAdaptedQueuePool`, un proceso = un pool), pero acá cada test async corre en su propio event
# loop (function-scoped, default de pytest-asyncio): una conexión pooleada creada en el loop de un
# test revienta con `RuntimeError: ... attached to a different loop` al intentar el pre-ping desde el
# loop del test siguiente. `NullPool` evita el problema de raíz (nunca reusa una conexión entre
# checkouts, así que no hay nada que sobreviva al cierre del loop) en vez de parchear con
# `dispose()` entre tests. Misma URL que ya resuelve `db.session.async_engine` (reusa la que ya
# armó el engine real, sin duplicar la lógica de `_async_engine_url()`).
# `str(url)` enmascara la contraseña (`hide_password=True` por default en SQLAlchemy) — hace falta
# `render_as_string(hide_password=False)` explícito o `create_async_engine` intenta conectar con la
# contraseña literal "***".
_engine_test = create_async_engine(async_engine.url.render_as_string(hide_password=False), poolclass=NullPool)
AsyncSessionLocal = async_sessionmaker(_engine_test, expire_on_commit=False)

# Rango sintético fuera de lo que Cromo real puede asignar (n_ids de Cromo son mucho más bajos que
# esto), mismo criterio que `_PELO_N_ID_FUSION` de `test_servicios_ingest_routes.py`: nunca pisa
# datos reales de dev.
_ODF_N_ID = 999_900_001
_CABLE_N_ID = 999_900_002
_PELO_N_ID = 999_900_003
_SERVICIO_NUMERO = "9999001"


@pytest.fixture
def odf_con_servicio():
    """Inserta el árbol mínimo real: un ODF con `cables_asociados=[_CABLE_N_ID]`, un pelo sobre ese
    mismo `cable_n_id` (sin fila propia de `cromo_cables`/`cromo_tubos` — no tienen FK dura, mismo
    hallazgo que documenta `test_servicios_ingest_routes.py::_crear_placeholder_cromo_con_match`),
    un servicio placeholder y el match que los conecta. Limpieza en el `finally`, nunca deja basura
    si el test falla a mitad de camino."""
    with SessionLocal() as session:
        servicio_id = int(
            session.execute(
                text(
                    "INSERT INTO app.servicios "
                    "(servicio_id, numero_primer_servicio, categoria, origen_datos, estado_servicio) "
                    "VALUES (:numero, :numero, 0, 'INFERIDO_CROMO', 'DESCONOCIDO') RETURNING id"
                ),
                {"numero": _SERVICIO_NUMERO},
            ).scalar_one()
        )
        session.execute(
            text(
                "INSERT INTO app.cromo_pelos (n_id, tubo_n_id, cable_n_id, servicio_numero) "
                "VALUES (:pelo, :pelo, :cable, :numero)"
            ),
            {"pelo": _PELO_N_ID, "cable": _CABLE_N_ID, "numero": _SERVICIO_NUMERO},
        )
        session.execute(
            text(
                "INSERT INTO app.cromo_servicio_match (pelo_n_id, servicio_numero, servicio_id, metodo) "
                "VALUES (:pelo, :numero, :servicio_id, 'REGEX_EXACTO')"
            ),
            {"pelo": _PELO_N_ID, "numero": _SERVICIO_NUMERO, "servicio_id": servicio_id},
        )
        session.execute(
            text(
                "INSERT INTO app.cromo_odfs "
                "(n_id, version_id, vmax, clase, nombre, calle, altura, localidad, propietario, "
                " tipo_elemento, cables_asociados, payload_raw) "
                "VALUES (:n_id, 1, 1, 69, 'ODF Test Tarea 4', 'Calle Test', '100', 'CABA', 'Metrotel', "
                " 'ODF', :cables_asociados, '{}'::jsonb)"
            ),
            {"n_id": _ODF_N_ID, "cables_asociados": '[%d]' % _CABLE_N_ID},
        )
        session.commit()

    try:
        yield {"odf_n_id": _ODF_N_ID, "cable_n_id": _CABLE_N_ID, "servicio_numero": _SERVICIO_NUMERO}
    finally:
        with SessionLocal() as session:
            session.execute(text("DELETE FROM app.cromo_odfs WHERE n_id = :n_id"), {"n_id": _ODF_N_ID})
            session.execute(
                text("DELETE FROM app.cromo_servicio_match WHERE pelo_n_id = :pelo"), {"pelo": _PELO_N_ID}
            )
            session.execute(text("DELETE FROM app.cromo_pelos WHERE n_id = :pelo"), {"pelo": _PELO_N_ID})
            session.execute(
                text("DELETE FROM app.servicios WHERE numero_primer_servicio = :numero"),
                {"numero": _SERVICIO_NUMERO},
            )
            session.commit()


# ── buscar_odfs — todos los filtros opcionales en NULL, contra asyncpg real ──


@pytest.mark.asyncio
async def test_buscar_odfs_todos_los_filtros_null_no_revienta_contra_driver_real():
    """El caso explícito que pide el brief: `buscar_odfs(sesion)` sin ningún filtro puesto (los 5
    parámetros opcionales llegan `None` a la vez) no debe lanzar `AmbiguousParameterError` contra
    asyncpg real — sólo lo detecta un driver real, nunca la sesión fake de
    `test_cromo_odf_inventario.py`."""
    from core.services.cromo.odf_inventario import buscar_odfs

    async with AsyncSessionLocal() as sesion:
        resultado = await buscar_odfs(sesion)

    assert resultado.limit == 50
    assert resultado.offset == 0
    assert resultado.total >= 0  # no importa el conteo real de dev, sólo que no reviente


@pytest.mark.asyncio
async def test_buscar_odfs_cada_filtro_individual_no_revienta_contra_driver_real():
    """Cada filtro puesto en solitario (el resto en NULL) tampoco debe reventar — cubre la
    combinatoria de CASTs sin necesitar datos reales para cada uno."""
    from core.services.cromo.odf_inventario import buscar_odfs

    async with AsyncSessionLocal() as sesion:
        await buscar_odfs(sesion, q="odf-que-no-existe-en-dev")
        await buscar_odfs(sesion, n_id=-1)
        await buscar_odfs(sesion, vigente=True)
        await buscar_odfs(sesion, vigente=False)
        await buscar_odfs(sesion, tipo_elemento="ODF")
        await buscar_odfs(sesion, servicio="servicio-que-no-existe-en-dev")


@pytest.mark.asyncio
async def test_buscar_odfs_encuentra_el_odf_sintetico_por_filtros(odf_con_servicio):
    from core.services.cromo.odf_inventario import buscar_odfs

    async with AsyncSessionLocal() as sesion:
        por_n_id = await buscar_odfs(sesion, n_id=_ODF_N_ID)
        por_q = await buscar_odfs(sesion, q="ODF Test Tarea 4")
        por_tipo = await buscar_odfs(sesion, tipo_elemento="ODF", n_id=_ODF_N_ID)
        por_servicio = await buscar_odfs(sesion, servicio=_SERVICIO_NUMERO)

    assert [o.n_id for o in por_n_id.odfs] == [_ODF_N_ID]
    assert por_n_id.odfs[0].cantidad_cables_asociados == 1
    assert por_n_id.odfs[0].cantidad_servicios == 1
    assert _ODF_N_ID in [o.n_id for o in por_q.odfs]
    assert [o.n_id for o in por_tipo.odfs] == [_ODF_N_ID]
    # `servicio` atraviesa cables_asociados -> cromo_pelos -> cromo_servicio_match -> servicios
    # contra datos reales, no un mock — confirma que el EXISTS correlacionado funciona de punta a
    # punta contra asyncpg.
    assert _ODF_N_ID in [o.n_id for o in por_servicio.odfs]


# ── obtener_detalle_odf — contra driver real ─────────────────────────────────


@pytest.mark.asyncio
async def test_obtener_detalle_odf_no_encontrado_contra_driver_real():
    from core.services.cromo.odf_detalle import obtener_detalle_odf
    from core.services.cromo.verificador import ObjetoNoEncontrado

    async with AsyncSessionLocal() as sesion:
        with pytest.raises(ObjetoNoEncontrado):
            await obtener_detalle_odf(sesion, -999)


@pytest.mark.asyncio
async def test_obtener_detalle_odf_resuelve_cable_asociado_real(odf_con_servicio):
    from core.services.cromo.odf_detalle import obtener_detalle_odf

    async with AsyncSessionLocal() as sesion:
        detalle = await obtener_detalle_odf(sesion, _ODF_N_ID)

    assert detalle.n_id == _ODF_N_ID
    assert detalle.calle == "Calle Test"
    # El cable no tiene fila propia en `cromo_cables` (referencia colgada deliberada del fixture,
    # mismo criterio "sin FK dura" que el resto de Cromo) -> aparece igual, con nombre=None.
    assert detalle.cables_asociados == [{"n_id": _CABLE_N_ID, "nombre": None}]


# ── servicios_por_odf — contra driver real ───────────────────────────────────


@pytest.mark.asyncio
async def test_servicios_por_odf_no_encontrado_contra_driver_real():
    from core.services.cromo.verificador import ObjetoNoEncontrado, servicios_por_odf

    async with AsyncSessionLocal() as sesion:
        with pytest.raises(ObjetoNoEncontrado):
            await servicios_por_odf(sesion, -999)


@pytest.mark.asyncio
async def test_servicios_por_odf_resuelve_servicio_via_pelos_y_match_real(odf_con_servicio):
    from core.services.cromo.verificador import servicios_por_odf

    async with AsyncSessionLocal() as sesion:
        resultado = await servicios_por_odf(sesion, _ODF_N_ID)

    assert resultado.odf_n_id == _ODF_N_ID
    assert len(resultado.servicios) == 1
    assert resultado.servicios[0].numero_primer_servicio == _SERVICIO_NUMERO
    assert resultado.servicios[0].servicio_numero_match == _SERVICIO_NUMERO
