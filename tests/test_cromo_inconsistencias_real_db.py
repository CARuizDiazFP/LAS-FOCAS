# Nombre de archivo: test_cromo_inconsistencias_real_db.py
# Ubicación de archivo: tests/test_cromo_inconsistencias_real_db.py
# Descripción: Integración contra Postgres real del detector de inconsistencias de Cromo — migración
# 20261017_02, SQL de detección, upsert idempotente, cierre/reapertura y cambio de estado

"""Todo corre dentro de UNA transacción que se revierte al final, migración incluida.

Por qué real: lo que importa es SQL — las tablas temporales del detector, `unnest` de arrays con
`ON CONFLICT ... DO UPDATE ... RETURNING`, el cierre por `NOT (id = ANY(...))`, los CHECK de la
migración. Una sesión fake devolvería lo que uno le dicta.

Si la tabla todavía no existe (la DB de dev no tiene la migración aplicada), el fixture corre el
`upgrade()` real de `20261017_02` sobre la conexión, dentro de la transacción: valida la migración
y no deja nada. El `downgrade()` se prueba en un test propio, también revertido.

Rango sintético propio (999_917_xxx): no lo usa ningún otro `*_real_db`.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from core.services.cromo import inconsistencias_cromo as inc
from db.session import async_engine
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real

_MIGRACION = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "alembic"
    / "versions"
    / "20261017_02_cromo_inconsistencias.py"
)

_SERVICIO = "99991701"
# Isla pura: botella con dos cables que sólo llegan a ella, una fusión 1:1 entre sus pelos.
_BOTELLA = 999_917_001
_CABLE_A = 999_917_011
_CABLE_B = 999_917_012
_PELO_A = 999_917_101
_PELO_B = 999_917_102
_FUSION_PURA = 999_917_201
# Isla dentro de un ODF: siempre MANUAL.
_ODF = 999_917_002
_CABLE_ODF = 999_917_013
_PELO_ODF_1 = 999_917_103
_PELO_ODF_2 = 999_917_104
_FUSION_ODF = 999_917_202
AHORA = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)


def _cargar_migracion(ruta: Path | None = None, nombre: str = "mig_20261017_02"):
    spec = importlib.util.spec_from_file_location(nombre, ruta or _MIGRACION)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _correr(sync_conn, funcion: str, ruta: Path | None = None, nombre: str = "mig_20261017_02") -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    contexto = MigrationContext.configure(sync_conn)
    with Operations.context(contexto):
        getattr(_cargar_migracion(ruta, nombre), funcion)()


async def _insertar_inventario(conn) -> None:
    await conn.execute(
        text(
            "INSERT INTO app.cromo_botellas (n_id, version_id, vmax, clase, nombre, localidad, payload_raw) "
            "VALUES (:n, :n, 1, 68, 'Cra TEST isla', 'Localidad Test', '{}'::jsonb)"
        ),
        {"n": _BOTELLA},
    )
    await conn.execute(
        text(
            "INSERT INTO app.cromo_odfs (n_id, version_id, vmax, clase, nombre, localidad, payload_raw) "
            "VALUES (:n, :n, 1, 69, 'ODF TEST isla', 'Localidad Test', '{}'::jsonb)"
        ),
        {"n": _ODF},
    )
    for cable, a, a_clase, b, b_clase in (
        (_CABLE_A, None, None, _BOTELLA, 68),
        (_CABLE_B, _BOTELLA, 68, None, None),
        (_CABLE_ODF, _ODF, 69, None, None),
    ):
        await conn.execute(
            text(
                "INSERT INTO app.cromo_cables (n_id, version_id, vmax, clase, nombre, "
                "extremo_a_n_id, extremo_a_clase, extremo_b_n_id, extremo_b_clase, payload_raw) "
                "VALUES (:n, :n, 1, 51, :nombre, :a, :ac, :b, :bc, '{}'::jsonb)"
            ),
            {"n": cable, "nombre": f"F-TEST-{cable}", "a": a, "ac": a_clase, "b": b, "bc": b_clase},
        )
    for pelo, cable, en_uso in (
        (_PELO_A, _CABLE_A, True),
        (_PELO_B, _CABLE_B, False),
        (_PELO_ODF_1, _CABLE_ODF, True),
        (_PELO_ODF_2, _CABLE_ODF, False),
    ):
        await conn.execute(
            text(
                "INSERT INTO app.cromo_pelos (n_id, tubo_n_id, cable_n_id, numero_pelo) "
                "VALUES (:p, 1, :c, '1')"
            ),
            {"p": pelo, "c": cable},
        )
        if en_uso:
            await conn.execute(
                text(
                    "INSERT INTO app.cromo_servicio_match (pelo_n_id, servicio_numero, metodo) "
                    "VALUES (:p, :s, 'REGEX_EXACTO')"
                ),
                {"p": pelo, "s": _SERVICIO},
            )
    for fusion, botella, a, b in (
        (_FUSION_PURA, _BOTELLA, _PELO_A, _PELO_B),
        (_FUSION_ODF, _ODF, _PELO_ODF_1, _PELO_ODF_2),
    ):
        await conn.execute(
            text(
                "INSERT INTO app.cromo_fusiones (n_id, botella_n_id, nombre_par, tipo, pelo_a_n_id, pelo_b_n_id) "
                "VALUES (:n, :bot, '1-1', 'FUSION', :a, :b)"
            ),
            {"n": fusion, "bot": botella, "a": a, "b": b},
        )


@pytest_asyncio.fixture
async def entorno():
    engine = create_async_engine(
        async_engine.url.render_as_string(hide_password=False), poolclass=NullPool
    )
    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
            existe = (
                await conn.execute(text("SELECT to_regclass('app.cromo_inconsistencia')"))
            ).scalar()
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


def _caso(tipo: str, objeto: int, revision: str = "MANUAL", pelos=(1,)) -> inc.Caso:
    return inc.Caso(
        tipo=tipo,
        objeto_n_id=objeto,
        objeto_clase=132,
        nombre=f"caso {objeto}",
        localidad="Localidad Test",
        revision=revision,
        evidencia={"motivo": "test", "servicios": [_SERVICIO]},
        pelos=tuple(pelos),
    )


async def _estados(conn) -> dict[int, str]:
    filas = (
        await conn.execute(
            text(
                "SELECT objeto_n_id, estado FROM app.cromo_inconsistencia "
                "WHERE objeto_n_id BETWEEN 999917000 AND 999917999"
            )
        )
    ).all()
    return {int(o): e for o, e in filas}


# ── Migración ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_migracion_check_y_unique(entorno):
    _sesion, conn = entorno
    insertar = (
        "INSERT INTO app.cromo_inconsistencia (tipo, objeto_n_id, revision, estado) "
        "VALUES (:t, :o, :r, :e)"
    )
    await conn.execute(text(insertar), {"t": "ISLA_FUSION", "o": 999917900, "r": "AUTO", "e": "CUARENTENA"})
    for t, r, e in (
        ("OTRO", "AUTO", "CUARENTENA"),
        ("ISLA_FUSION", "SEMI", "CUARENTENA"),
        ("ISLA_FUSION", "AUTO", "BORRADA"),
    ):
        punto = await conn.begin_nested()
        with pytest.raises(Exception):
            await conn.execute(text(insertar), {"t": t, "o": 999917901, "r": r, "e": e})
        await punto.rollback()
    punto = await conn.begin_nested()
    with pytest.raises(Exception):
        await conn.execute(text(insertar), {"t": "ISLA_FUSION", "o": 999917900, "r": "AUTO", "e": "PENDIENTE"})
    await punto.rollback()


@pytest.mark.asyncio
async def test_downgrade_quita_las_dos_tablas(entorno):
    _sesion, conn = entorno
    # La vista de 20261017_03 depende de las tablas: si está aplicada, se baja primero
    # (misma transacción revertida, así que no queda residuo).
    vista = (await conn.execute(text("SELECT to_regclass('app.v_cromo_servicio_match_vigente')"))).scalar()
    if vista is not None:
        mig_03 = _MIGRACION.with_name("20261017_03_cromo_servicio_match_vigente.py")
        await conn.run_sync(_correr, "downgrade", mig_03, "mig_20261017_03")
    await conn.run_sync(_correr, "downgrade")
    for tabla in ("cromo_inconsistencia", "cromo_inconsistencia_pelo"):
        assert (await conn.execute(text(f"SELECT to_regclass('app.{tabla}')"))).scalar() is None


# ── SQL de detección ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_detectar_sobre_inventario_sintetico(entorno):
    """El SQL real encuentra la isla pura, la isla en ODF, los cables sin extremo y los elementos
    isla; sin cliente de Cromo la isla pura queda MANUAL (falla cerrada); con la confirmación en
    vivo, AUTO."""
    sesion, conn = entorno
    await _insertar_inventario(conn)

    lectura = await inc.leer_deteccion(sesion)

    islas = {f.fusion_n_id: f for f in lectura.islas}
    assert _FUSION_PURA in islas and _FUSION_ODF in islas
    pura = islas[_FUSION_PURA]
    assert pura.uso_a and not pura.uso_b and pura.servicios == (_SERVICIO,)
    assert inc.motivo_no_candidato_auto(pura) is None
    assert pura.contenedor_version_id == _BOTELLA  # version_id de la botella sintética
    assert inc.clasificar_isla_fusion(pura, {})[0] == "MANUAL"
    confs = {
        c: inc.ConfirmacionVivo(c, c, c, 1, (_BOTELLA,), False, AHORA.isoformat())
        for c in (_CABLE_A, _CABLE_B)
    }
    assert inc.clasificar_isla_fusion(pura, confs) == ("AUTO", "isla_pura_confirmada")
    assert inc.clasificar_isla_fusion(islas[_FUSION_ODF], confs) == ("MANUAL", "contenedor_odf")

    cables = {c.objeto_n_id: c for c in lectura.cables_sin_extremo}
    assert set(cables) >= {_CABLE_A, _CABLE_ODF} and _CABLE_B not in cables  # B sin pelos en uso
    assert cables[_CABLE_A].pelos == (_PELO_A,)
    assert cables[_CABLE_ODF].evidencia["motivo"] == "cable_con_extremo_odf"
    assert cables[_CABLE_A].localidad == "Localidad Test"

    elementos = {c.objeto_n_id: c for c in lectura.elementos_isla}
    assert elementos[_BOTELLA].evidencia["motivo"] == "elemento_isla"
    assert elementos[_BOTELLA].pelos == (_PELO_A,)
    assert {c["n_id"] for c in elementos[_BOTELLA].evidencia["cables"]} == {_CABLE_A, _CABLE_B}
    assert elementos[_ODF].evidencia["motivo"] == "elemento_odf"

    # Las tablas temporales no quedan.
    assert (await sesion.execute(text("SELECT to_regclass('pg_temp.t_inc_uniones')"))).scalar() is None


@pytest.mark.asyncio
async def test_una_union_extra_rompe_la_isla(entorno):
    """Un conector de ODF sobre el pelo B (p.ej. llegado por una 141) es otra unión: ya no es isla."""
    sesion, conn = entorno
    await _insertar_inventario(conn)
    await conn.execute(
        text(
            "INSERT INTO app.cromo_odf_conectores (n_id, odf_n_id, pelo_n_id, fusion_odf_n_id, payload_raw) "
            "VALUES (999917301, :odf, :p, 999917302, '{}'::jsonb)"
        ),
        {"odf": _ODF, "p": _PELO_B},
    )
    lectura = await inc.leer_deteccion(sesion)
    assert _FUSION_PURA not in {f.fusion_n_id for f in lectura.islas}


# ── Upsert, cierre y reapertura ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aplicar_casos_estados_iniciales_pelos_e_idempotencia(entorno):
    sesion, conn = entorno
    casos = [
        _caso("ISLA_FUSION", 999917401, "AUTO", pelos=(11, 12)),
        _caso("CABLE_SIN_EXTREMO", 999917402, "MANUAL", pelos=(13,)),
    ]
    primero = await inc.aplicar_casos(sesion, casos, ahora=AHORA)
    assert (primero.nuevos, primero.actualizados) == (2, 0)
    assert await _estados(conn) == {999917401: "CUARENTENA", 999917402: "PENDIENTE"}
    pelos = (
        await conn.execute(
            text(
                "SELECT p.pelo_n_id FROM app.cromo_inconsistencia_pelo p "
                "JOIN app.cromo_inconsistencia i ON i.id = p.inconsistencia_id "
                "WHERE i.objeto_n_id = 999917401 ORDER BY 1"
            )
        )
    ).scalars().all()
    assert pelos == [11, 12]

    casos[0].pelos = (12,)
    luego = AHORA + timedelta(hours=1)
    segundo = await inc.aplicar_casos(sesion, casos, ahora=luego)
    assert (segundo.nuevos, segundo.actualizados, segundo.cerrados) == (0, 2, 0)
    fila = (
        await conn.execute(
            text(
                "SELECT primera_vez, ultima_vez, actualizado_por, "
                "(SELECT array_agg(pelo_n_id) FROM app.cromo_inconsistencia_pelo WHERE inconsistencia_id = i.id) "
                "FROM app.cromo_inconsistencia i WHERE objeto_n_id = 999917401"
            )
        )
    ).one()
    assert fila[0] == AHORA and fila[1] == luego and fila[2] == inc.USUARIO_DETECTOR
    assert fila[3] == [12]


@pytest.mark.asyncio
async def test_cierre_automatico_protege_aceptada_y_cierra_reportada(entorno):
    sesion, conn = entorno
    casos = [_caso("ISLA_FUSION", 999917500 + i, "MANUAL") for i in range(4)]
    await inc.aplicar_casos(sesion, casos, ahora=AHORA)
    ids = dict(
        (await conn.execute(
            text("SELECT objeto_n_id, id FROM app.cromo_inconsistencia WHERE objeto_n_id BETWEEN 999917500 AND 999917503")
        )).all()
    )
    resultado = await inc.cambiar_estado(sesion, [ids[999917501]], "ACEPTADA", "ana@metrotel")
    assert resultado["actualizados"] == [ids[999917501]]
    await inc.cambiar_estado(sesion, [ids[999917502]], "REPORTADA", "ana@metrotel")
    await inc.cambiar_estado(sesion, [ids[999917503]], "CUARENTENA", "ana@metrotel")

    # Siguen detectándose: ACEPTADA y REPORTADA no se tocan, la cuarentena manual tampoco.
    await inc.aplicar_casos(sesion, casos, ahora=AHORA)
    assert await _estados(conn) == {
        999917500: "PENDIENTE", 999917501: "ACEPTADA", 999917502: "REPORTADA", 999917503: "CUARENTENA",
    }

    # Ninguno se detecta: todo lo que no es ACEPTADA pasa a CORREGIDA.
    resumen = await inc.aplicar_casos(sesion, [], ahora=AHORA)
    estados = await _estados(conn)
    assert estados == {
        999917500: "CORREGIDA", 999917501: "ACEPTADA", 999917502: "CORREGIDA", 999917503: "CORREGIDA",
    }
    assert resumen.cerrados >= 3

    # Vuelve a aparecer uno corregido: se reabre con el estado inicial de su revisión.
    reapertura = await inc.aplicar_casos(
        sesion, [_caso("ISLA_FUSION", 999917500, "AUTO")], ahora=AHORA
    )
    assert reapertura.reabiertos == 1
    assert (await _estados(conn))[999917500] == "CUARENTENA"


@pytest.mark.asyncio
async def test_cuarentena_manual_se_respeta_y_auto_que_se_degrada_se_levanta(entorno):
    """Una persona puso en CUARENTENA un caso MANUAL: el detector no lo saca mientras siga MANUAL.
    Un caso AUTO (cuarentena automática) que deja de confirmarse vuelve a PENDIENTE."""
    sesion, conn = entorno
    await inc.aplicar_casos(
        sesion,
        [_caso("ISLA_FUSION", 999917601, "MANUAL"), _caso("ISLA_FUSION", 999917602, "AUTO")],
        ahora=AHORA,
    )
    id_manual = (
        await conn.execute(text("SELECT id FROM app.cromo_inconsistencia WHERE objeto_n_id = 999917601"))
    ).scalar_one()
    await inc.cambiar_estado(sesion, [id_manual], "CUARENTENA", "ana@metrotel")
    await inc.aplicar_casos(
        sesion,
        [_caso("ISLA_FUSION", 999917601, "MANUAL"), _caso("ISLA_FUSION", 999917602, "MANUAL")],
        ahora=AHORA,
    )
    estados = await _estados(conn)
    assert estados[999917602] == "PENDIENTE"
    assert estados[999917601] == "CUARENTENA"


@pytest.mark.asyncio
async def test_cambiar_estado_rechaza_con_motivo(entorno):
    sesion, conn = entorno
    await inc.aplicar_casos(sesion, [_caso("ELEMENTO_ISLA", 999917701)], ahora=AHORA)
    id_caso = (
        await conn.execute(text("SELECT id FROM app.cromo_inconsistencia WHERE objeto_n_id = 999917701"))
    ).scalar_one()
    resultado = await inc.cambiar_estado(sesion, [id_caso, -1], "CORREGIDA", "ana@metrotel")
    assert resultado["actualizados"] == []
    assert {r["id"] for r in resultado["rechazados"]} == {id_caso, -1}
    resultado = await inc.cambiar_estado(sesion, [id_caso], "REPORTADA", "ana@metrotel")
    assert resultado == {"actualizados": [id_caso], "rechazados": []}
    fila = (
        await conn.execute(
            text("SELECT estado, actualizado_por FROM app.cromo_inconsistencia WHERE id = :i"), {"i": id_caso}
        )
    ).one()
    assert tuple(fila) == ("REPORTADA", "ana@metrotel")


@pytest.mark.asyncio
async def test_listar_filtra_por_tipo_estado_localidad_y_servicio(entorno):
    sesion, conn = entorno
    await _insertar_inventario(conn)
    await inc.aplicar_casos(
        sesion,
        [
            _caso("ISLA_FUSION", 999917801, "AUTO", pelos=(_PELO_A,)),
            _caso("CABLE_SIN_EXTREMO", 999917802, "MANUAL", pelos=(_PELO_B,)),
        ],
        ahora=AHORA,
    )
    por_servicio = await inc.listar(sesion, servicio=_SERVICIO)
    assert [i["objeto_n_id"] for i in por_servicio["items"]] == [999917801]
    assert por_servicio["items"][0]["pelos"] == 1
    cuarentena = await inc.listar(sesion, estado="CUARENTENA", tipo="ISLA_FUSION", localidad="test")
    assert {i["objeto_n_id"] for i in cuarentena["items"]} >= {999917801}
    assert all(i["estado"] == "CUARENTENA" for i in cuarentena["items"])
    pagina = await inc.listar(sesion, revision="MANUAL", por_pagina=1)
    assert pagina["por_pagina"] == 1 and len(pagina["items"]) == 1


@pytest.mark.asyncio
async def test_listar_desplazamiento_conteos_por_tipo_y_servicios(entorno):
    sesion, conn = entorno
    await _insertar_inventario(conn)
    await inc.aplicar_casos(
        sesion,
        [
            _caso("ISLA_FUSION", 999917801, "AUTO", pelos=(_PELO_A,)),
            _caso("CABLE_SIN_EXTREMO", 999917802, "MANUAL", pelos=(_PELO_A,)),
            _caso("CABLE_SIN_EXTREMO", 999917803, "MANUAL", pelos=(_PELO_A,)),
        ],
        ahora=AHORA,
    )
    todo = await inc.listar(sesion, servicio=_SERVICIO)
    assert todo["conteos_por_tipo"] == {"ISLA_FUSION": 1, "CABLE_SIN_EXTREMO": 2}
    assert all(i["servicios"] == 1 for i in todo["items"])
    # Los conteos ignoran el filtro de tipo; la lista y el total, no.
    filtrado = await inc.listar(sesion, servicio=_SERVICIO, tipo="ISLA_FUSION")
    assert filtrado["total"] == 1 and filtrado["conteos_por_tipo"] == todo["conteos_por_tipo"]
    # offset explícito, independiente de la página.
    segunda = await inc.listar(sesion, servicio=_SERVICIO, por_pagina=2, desplazamiento=2)
    assert len(segunda["items"]) == 1 and segunda["desplazamiento"] == 2


@pytest.mark.asyncio
async def test_listar_por_servicio_id_y_resumen_de_servicio(entorno):
    sesion, conn = entorno
    await _insertar_inventario(conn)
    sid = (await conn.execute(text("SELECT min(id) FROM app.servicios"))).scalar()
    if sid is None:
        pytest.skip("la DB no tiene servicios")
    await conn.execute(
        text("UPDATE app.cromo_servicio_match SET servicio_id = :sid WHERE servicio_numero = :n"),
        {"sid": sid, "n": _SERVICIO},
    )
    await inc.aplicar_casos(
        sesion,
        [
            _caso("ISLA_FUSION", 999917801, "AUTO", pelos=(_PELO_A,)),
            _caso("CABLE_SIN_EXTREMO", 999917802, "MANUAL", pelos=(_PELO_A,)),
        ],
        ahora=AHORA,
    )
    por_id = await inc.listar(sesion, servicio_id=sid)
    assert {999917801, 999917802} <= {i["objeto_n_id"] for i in por_id["items"]}
    base = await inc.resumen_de_servicio(sesion, sid)
    assert base["cuarentena"] >= 1 and base["en_revision"] >= 1
    # Aceptar el caso de cuarentena lo saca del conteo de cuarentena.
    # El caso propio por su `objeto_n_id` sintético: `servicio_id=sid` (el min(id) real de dev)
    # también devuelve casos ISLA_FUSION ajenos, y tomar el [0] aceptaba uno que podía no estar
    # en cuarentena (delta 0 en lugar de -1).
    caso = next(
        i
        for i in (await inc.listar(sesion, servicio_id=sid, tipo="ISLA_FUSION"))["items"]
        if i["objeto_n_id"] == 999917801
    )
    await inc.cambiar_estado(sesion, [caso["id"]], "ACEPTADA", "test")
    despues = await inc.resumen_de_servicio(sesion, sid)
    assert despues["cuarentena"] == base["cuarentena"] - 1
    assert (await inc.resumen_de_servicio(sesion, -1)) == {"cuarentena": 0, "en_revision": 0}


@pytest.mark.asyncio
async def test_detectar_aplicado_de_punta_a_punta_sin_cliente(entorno):
    """`detectar` real sobre la DB (sin Cromo): la isla pura sintética queda MANUAL/PENDIENTE por
    falla cerrada, y la confirmación previa guardada se reutiliza en la corrida siguiente."""
    sesion, conn = entorno
    await _insertar_inventario(conn)
    resumen = await inc.detectar(sesion, cliente=None, ahora=AHORA)
    assert resumen.aplicado and resumen.total >= 5
    estados = await _estados(conn)
    assert estados[_FUSION_PURA] == "PENDIENTE"
    assert estados[_FUSION_ODF] == "PENDIENTE"

    # Simula una confirmación previa en la evidencia: la siguiente detección la reutiliza → AUTO.
    confs = [
        inc.ConfirmacionVivo(c, c, c, 1, (_BOTELLA,), False, AHORA.isoformat()).a_dict()
        for c in (_CABLE_A, _CABLE_B)
    ]
    import json

    await conn.execute(
        text(
            "UPDATE app.cromo_inconsistencia SET evidencia = jsonb_set(evidencia, '{confirmaciones}', "
            "CAST(:c AS jsonb)) WHERE tipo = 'ISLA_FUSION' AND objeto_n_id = :f"
        ),
        {"c": json.dumps(confs), "f": _FUSION_PURA},
    )
    segundo = await inc.detectar(sesion, cliente=None, ahora=AHORA + timedelta(hours=1))
    assert segundo.confirmaciones.reutilizados >= 2
    assert (await _estados(conn))[_FUSION_PURA] == "CUARENTENA"


@pytest.mark.asyncio
async def test_no_inicia_deteccion_con_una_ingesta_en_curso(entorno):
    """Una ingesta EN_CURSO (sin `params.tipo`) impide arrancar: el SQL real de `ingesta_en_curso`."""
    sesion, conn = entorno
    ingesta_id = (
        await conn.execute(
            text(
                "INSERT INTO app.cromo_ingesta_corridas (usuario, estado, params) "
                "VALUES ('test-inconsistencias', 'EN_CURSO', '{\"modo\": \"SOLO_ODF\"}'::jsonb) RETURNING id"
            )
        )
    ).scalar_one()
    assert await inc.ingesta_en_curso(sesion) is not None
    corrida, en_curso = await inc.iniciar_si_no_hay_otra(sesion, usuario="test")
    assert corrida is None and en_curso is not None and en_curso >= ingesta_id


# ── Tarea 5: reporte y config del aviso ──────────────────────────────────────

_MIG_04 = _MIGRACION.with_name("20261017_04_config_cromo_inconsistencias.py")


@pytest.mark.asyncio
async def test_migracion_04_siembra_fila_inactiva_idempotente_y_reversible(entorno):
    _sesion, conn = entorno
    consulta = text(
        "SELECT slack_channels, activo FROM app.config_servicios "
        "WHERE nombre_servicio = 'Cromo Inconsistencias'"
    )
    await conn.run_sync(_correr, "upgrade", _MIG_04, "mig_20261017_04")
    await conn.run_sync(_correr, "upgrade", _MIG_04, "mig_20261017_04")
    filas = (await conn.execute(consulta)).all()
    assert [(c, a) for c, a in filas] == [("", False)]
    await conn.run_sync(_correr, "downgrade", _MIG_04, "mig_20261017_04")
    assert (await conn.execute(consulta)).all() == []


@pytest.mark.asyncio
async def test_aplicar_informa_nuevos_y_reporte_los_recupera(entorno):
    from core.services.cromo import inconsistencias_reporte as rep

    sesion, _conn = entorno
    casos = [
        _caso("ISLA_FUSION", 999_917_801, "AUTO"),
        _caso("ELEMENTO_ISLA", 999_917_802, "MANUAL"),
    ]
    r1 = await inc.aplicar_casos(sesion, casos, ahora=AHORA)
    assert r1.nuevos == 2 and r1.cuarentena_auto == 1
    assert r1.casos_previos >= 0
    assert sorted(r1.nuevos_claves) == [("ELEMENTO_ISLA", 999_917_802), ("ISLA_FUSION", 999_917_801)]
    r2 = await inc.aplicar_casos(sesion, casos, ahora=AHORA + timedelta(hours=1))
    assert r2.nuevos == 0 and r2.nuevos_claves == []

    filas = await rep.filas_de_casos(sesion, r1.nuevos_claves)
    assert {f["ID Cromo"] for f in filas} == {999_917_801, 999_917_802}
    assert {f["Estado"] for f in filas} == {"CUARENTENA", "PENDIENTE"}

    # El reporte por defecto excluye lo cerrado y lo aceptado.
    await inc.cambiar_estado(sesion, [(await _id_de(sesion, 999_917_802))], "ACEPTADA", "tester")
    visibles = {
        f["ID Cromo"]
        for f in await rep.filas_reporte(sesion, localidad="Localidad Test")
        if 999_917_000 <= f["ID Cromo"] <= 999_917_999
    }
    assert visibles == {999_917_801}


async def _id_de(sesion, objeto: int) -> int:
    return (
        await sesion.execute(
            text("SELECT id FROM app.cromo_inconsistencia WHERE objeto_n_id = :o"), {"o": objeto}
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_config_aviso_guardar_y_leer(entorno):
    from core.services.cromo import inconsistencias_reporte as rep

    sesion, conn = entorno
    await conn.run_sync(_correr, "upgrade", _MIG_04, "mig_20261017_04")
    assert await rep.leer_config_aviso(sesion) == {"slack_channels": "", "activo": False, "existe": True}
    await rep.guardar_config_aviso(sesion, "#a,C0123456789", True)
    assert await rep.leer_config_aviso(sesion) == {
        "slack_channels": "#a,C0123456789",
        "activo": True,
        "existe": True,
    }
    assert await rep._leer_config_slack(sesion) == (["#a", "C0123456789"], True)
    await conn.run_sync(_correr, "downgrade", _MIG_04, "mig_20261017_04")
    assert (await rep.leer_config_aviso(sesion))["existe"] is False
    await rep.guardar_config_aviso(sesion, "#b", False)  # inserta si no existe
    assert (await rep.leer_config_aviso(sesion))["slack_channels"] == "#b"
