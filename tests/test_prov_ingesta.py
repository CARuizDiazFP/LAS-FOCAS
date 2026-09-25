# Nombre de archivo: test_prov_ingesta.py
# Ubicación de archivo: tests/test_prov_ingesta.py
# Descripción: Tests puros del parseo del contexto de PROV (sin DB) + integración real del upsert de app.servicios_sync_prov dentro de ingerir_contexto_prov

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.services.prov.ingesta import (
    EquipoUltimaMilla,
    _campos_direccion_desde_equipos,
    _traducir_estado_comercial,
    ingerir_contexto_prov,
    parsear_contexto_prov,
)
from db.models.infra import Servicio
from db.session import SessionLocal, async_engine
from tests.soporte_postgres_real import requiere_postgres_real

_CONTEXTO_SIN_UPGRADES = {
    "id_servicio": "RPV",
    "nro_servicio": "122214",
    "nro_servicio_original": "122214",
    "estado_comercial": "INSTALADO",
    "creacion": "2026-07-14 15:47:15",
    "Descripcion": "BANCO MACRO SA",
    "Direccion1": "RECONQUISTA 590 P.1",
    "Provincia1": "Capital Federal",
    "Nodo1": "CLI_Reconquista590P1_BancoITAU",
    "Equipo1": "SW_Reconquista590P1_BancoITAU",
    "Port1": "GigabitEthernet1/0/5",
}

_CONTEXTO_CON_UPGRADES = {
    "id_servicio": "EWS",
    "nro_servicio": "63871",
    "nro_servicio_original": "15872",
    "nro_servicio_consultado": "15872",
    "nro_servicio_vigente": "63871",
    "fue_upgradeado": True,
    "estado_comercial": "INSTALADO",
    "Descripcion": "CONSEJO PROFESIONAL DE CIENCIAS ECONOMICAS CABA",
    "Direccion1": "AYACUCHO 652",
    "Provincia1": "Capital Federal",
    "Nodo1": "Paraguay2302_CABA",
    "Equipo1": "SW_3_Paraguay2302_CABA",
    "Port1": "6",
    "cadena_upgrade": [
        {
            "nro_servicio": "63871", "estado_comercial": "INSTALADO",
            "fecha_instalacion": "2019-11-01", "fecha_baja": None, "motivo_baja": "", "es_vigente": True,
        },
        {
            "nro_servicio": "46215", "estado_comercial": "DADO BAJA",
            "fecha_instalacion": "2017-11-23", "fecha_baja": "2019-11-01", "motivo_baja": "UPGRADE", "es_vigente": False,
        },
        {
            "nro_servicio": "15872", "estado_comercial": "DADO BAJA",
            "fecha_instalacion": "2012-04-23", "fecha_baja": "2017-11-23", "motivo_baja": "UPGRADE", "es_vigente": False,
        },
    ],
}


def test_parsea_contexto_sin_cadena_de_upgrades_sintetiza_una_fila() -> None:
    parseado = parsear_contexto_prov(_CONTEXTO_SIN_UPGRADES)

    assert parseado.nro_servicio_vigente == "122214"
    assert parseado.nro_servicio_original == "122214"
    assert parseado.tipo_servicio == "RPV"
    assert parseado.nombre_cliente == "BANCO MACRO SA"
    assert len(parseado.historial) == 1
    assert parseado.historial[0].numero_id == "122214"
    assert parseado.historial[0].orden == 0
    assert parseado.historial[0].es_vigente is True
    assert parseado.historial[0].fecha_instalacion == date(2026, 7, 14)

    assert len(parseado.equipos) == 1
    assert parseado.equipos[0].extremo == 1
    assert parseado.equipos[0].nodo == "CLI_Reconquista590P1_BancoITAU"
    assert parseado.equipos[0].puerto == "GigabitEthernet1/0/5"


def test_parsea_cadena_de_upgrades_completa_en_orden() -> None:
    parseado = parsear_contexto_prov(_CONTEXTO_CON_UPGRADES)

    assert parseado.nro_servicio_vigente == "63871"
    assert parseado.nro_servicio_original == "15872"
    assert len(parseado.historial) == 3

    assert parseado.historial[0].numero_id == "63871"
    assert parseado.historial[0].orden == 0
    assert parseado.historial[0].es_vigente is True
    assert parseado.historial[0].fecha_baja is None

    assert parseado.historial[2].numero_id == "15872"
    assert parseado.historial[2].orden == 2
    assert parseado.historial[2].fecha_instalacion == date(2012, 4, 23)
    assert parseado.historial[2].fecha_baja == date(2017, 11, 23)
    assert parseado.historial[2].motivo_baja == "UPGRADE"


def test_parsea_un_solo_extremo_cuando_no_hay_nodo2() -> None:
    parseado = parsear_contexto_prov(_CONTEXTO_CON_UPGRADES)
    assert len(parseado.equipos) == 1


def test_el_eslabon_sintetico_no_se_marca_vigente_si_el_servicio_esta_dado_de_baja() -> None:
    """Sin `cadena_upgrade` el eslabón se sintetiza, y su `es_vigente` tiene que seguir al
    `estado_comercial`: marcarlo siempre True producía un chip "DADO BAJA" junto a la palabra
    "Vigente" en el detalle del servicio."""
    contexto = dict(_CONTEXTO_SIN_UPGRADES, estado_comercial="DADO BAJA")
    parseado = parsear_contexto_prov(contexto)

    assert len(parseado.historial) == 1
    assert parseado.historial[0].estado_comercial == "DADO BAJA"
    assert parseado.historial[0].es_vigente is False


def test_el_eslabon_sintetico_no_se_marca_vigente_con_un_estado_desconocido() -> None:
    contexto = dict(_CONTEXTO_SIN_UPGRADES, estado_comercial="EN CONSTRUCCION")
    parseado = parsear_contexto_prov(contexto)

    assert parseado.historial[0].es_vigente is False


def test_un_estado_comercial_no_mapeado_se_pasa_tal_cual_pero_deja_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="core.services.prov.ingesta"):
        assert _traducir_estado_comercial(" en construccion ") == "en construccion"

    assert "estado_comercial_no_mapeado" in caplog.text
    assert "en construccion" in caplog.text


def test_un_estado_comercial_conocido_no_deja_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="core.services.prov.ingesta"):
        assert _traducir_estado_comercial("INSTALADO") == "Activo"
        assert _traducir_estado_comercial("dado baja") == "Baja"

    assert "estado_comercial_no_mapeado" not in caplog.text


def test_parsea_dos_extremos_cuando_el_payload_trae_nodo2() -> None:
    contexto = dict(_CONTEXTO_SIN_UPGRADES, Nodo2="NODO-B", Equipo2="SW-B", Port2="2", Direccion2="OTRA CALLE 456")
    parseado = parsear_contexto_prov(contexto)

    assert len(parseado.equipos) == 2
    assert parseado.equipos[1].extremo == 2
    assert parseado.equipos[1].nodo == "NODO-B"
    assert parseado.equipos[1].direccion == "OTRA CALLE 456"


def test_campos_direccion_toma_el_extremo_1_para_los_campos_principales() -> None:
    equipos = [
        EquipoUltimaMilla(extremo=1, nodo="N1", equipo="E1", puerto="P1", direccion="CALLE 1", provincia="Buenos Aires"),
        EquipoUltimaMilla(extremo=2, nodo="N2", equipo="E2", puerto="P2", direccion="CALLE 2", provincia="Córdoba"),
    ]
    direccion, provincia, direccion_2 = _campos_direccion_desde_equipos(equipos)
    assert direccion == "CALLE 1"
    assert provincia == "Buenos Aires"
    assert direccion_2 == "CALLE 2"


def test_campos_direccion_no_confunde_el_extremo_2_con_el_principal_si_falta_el_1() -> None:
    """Bug real: si PROV sólo trae datos del extremo 2 (Nodo1 vacío), el código viejo tomaba
    `equipos[0]` a ciegas — que en ese caso ES el extremo 2 — y lo asignaba a los campos
    principales (direccion/provincia) en vez de dejarlos sin tocar."""
    equipos = [
        EquipoUltimaMilla(extremo=2, nodo="N2", equipo="E2", puerto="P2", direccion="CALLE 2", provincia="Córdoba"),
    ]
    direccion, provincia, direccion_2 = _campos_direccion_desde_equipos(equipos)
    assert direccion is None
    assert provincia is None
    assert direccion_2 == "CALLE 2"


def test_campos_direccion_con_lista_vacia_devuelve_todo_none() -> None:
    assert _campos_direccion_desde_equipos([]) == (None, None, None)


# ── Integración real: upsert de app.servicios_sync_prov dentro de ingerir_contexto_prov ──────────
#
# Requiere Postgres real (migración `20260923_02`) — sólo estos tests llevan `@requiere_postgres_real`,
# el resto del archivo es parseo puro y sigue corriendo sin DB. Namespace de IDs sintéticos
# reservado para este archivo: `"900211"`/`"900212"` — distinto del `"9001xx"` de
# `tests/test_servicios_prov_routes.py` y del `"9002xx"` (`"900201"`-`"900206"`) de
# `tests/test_prov_frescura.py`, mismo criterio de rango fresco sin colisiones.

_engine_test = create_async_engine(async_engine.url.render_as_string(hide_password=False), poolclass=NullPool)
_AsyncSessionLocalTest = async_sessionmaker(_engine_test, expire_on_commit=False)

_NUMEROS_DE_TEST_SYNC_PROV = ("900211", "900212")


@pytest.fixture
def _limpiar_servicios_sync_prov_de_test():
    yield
    with SessionLocal() as session:
        # `ON DELETE CASCADE` en `servicios_sync_prov.servicio_id` se encarga de esa tabla solo.
        session.execute(
            text("DELETE FROM app.servicios WHERE numero_primer_servicio = ANY(:numeros ::varchar[])"),
            {"numeros": list(_NUMEROS_DE_TEST_SYNC_PROV)},
        )
        session.commit()


def _crear_servicio_sync_prov_test(numero: str) -> int:
    with SessionLocal() as session:
        pk = session.execute(
            text(
                "INSERT INTO app.servicios "
                "(servicio_id, numero_primer_servicio, numero_linea, estado_servicio, tipo_servicio, origen_datos) "
                "VALUES (:numero, :numero, :numero, 'DESCONOCIDO', 'EWS', 'MANUAL'::app.servicio_origen_datos) "
                "RETURNING id"
            ),
            {"numero": numero},
        ).scalar_one()
        session.commit()
        return int(pk)


def _leer_fila_sync_prov(servicio_pk: int) -> tuple[datetime, datetime | None, str | None, str | None] | None:
    with SessionLocal() as session:
        fila = session.execute(
            text(
                "SELECT ultima_sincronizacion_ok, ultimo_intento, ultimo_error, nro_servicio_consultado "
                "FROM app.servicios_sync_prov WHERE servicio_id = :servicio_id"
            ),
            {"servicio_id": servicio_pk},
        ).one_or_none()
        return tuple(fila) if fila is not None else None


def _contexto_minimo(numero: str) -> dict:
    return {
        "id_servicio": "EWS",
        "nro_servicio": numero,
        "nro_servicio_original": numero,
        "estado_comercial": "INSTALADO",
        "Descripcion": "CLIENTE SYNC PROV TEST",
    }


@requiere_postgres_real
@pytest.mark.asyncio
async def test_ingerir_contexto_prov_crea_la_fila_de_sync_si_no_existia(
    _limpiar_servicios_sync_prov_de_test,
) -> None:
    """El upsert al final de `ingerir_contexto_prov` (Task 7) es el único embudo de escritura de
    `app.servicios_sync_prov` — este test cubre el caso "nunca sincronizado" (el 92,5% real medido
    antes de correr el backfill)."""
    numero = "900211"
    pk = _crear_servicio_sync_prov_test(numero)

    antes = datetime.now(timezone.utc)
    async with _AsyncSessionLocalTest() as sesion:
        servicio = (await sesion.execute(select(Servicio).where(Servicio.id == pk))).scalars().one()
        await ingerir_contexto_prov(sesion, servicio, _contexto_minimo(numero))
        await sesion.commit()
    despues = datetime.now(timezone.utc)

    fila = _leer_fila_sync_prov(pk)
    assert fila is not None
    ultima_sincronizacion_ok, ultimo_intento, ultimo_error, nro_consultado = fila
    assert antes <= ultima_sincronizacion_ok <= despues
    assert antes <= ultimo_intento <= despues
    assert ultimo_error is None
    assert nro_consultado == numero


@requiere_postgres_real
@pytest.mark.asyncio
async def test_ingerir_contexto_prov_reescribe_la_fila_existente_y_limpia_el_error(
    _limpiar_servicios_sync_prov_de_test,
) -> None:
    """Un refresco exitoso tiene que avanzar `ultima_sincronizacion_ok` y limpiar cualquier
    `ultimo_error` viejo — no puede quedar un error pegado después de un intento que sí funcionó."""
    numero = "900212"
    pk = _crear_servicio_sync_prov_test(numero)
    vieja = datetime.now(timezone.utc) - timedelta(hours=200)
    with SessionLocal() as session:
        session.execute(
            text(
                "INSERT INTO app.servicios_sync_prov "
                "(servicio_id, ultima_sincronizacion_ok, ultimo_intento, ultimo_error, nro_servicio_consultado, "
                " created_at, updated_at) "
                "VALUES (:servicio_id, :vieja, :vieja, 'timeout de prueba', 'numero-viejo', :vieja, :vieja)"
            ),
            {"servicio_id": pk, "vieja": vieja},
        )
        session.commit()

    async with _AsyncSessionLocalTest() as sesion:
        servicio = (await sesion.execute(select(Servicio).where(Servicio.id == pk))).scalars().one()
        await ingerir_contexto_prov(sesion, servicio, _contexto_minimo(numero))
        await sesion.commit()

    fila = _leer_fila_sync_prov(pk)
    assert fila is not None
    ultima_sincronizacion_ok, _ultimo_intento, ultimo_error, nro_consultado = fila
    assert ultima_sincronizacion_ok > vieja
    assert ultimo_error is None
    assert nro_consultado == numero


@requiere_postgres_real
@pytest.mark.asyncio
async def test_ingerir_contexto_prov_no_duplica_fila_de_sync_en_dos_llamadas(
    _limpiar_servicios_sync_prov_de_test,
) -> None:
    """`servicio_id` es UNIQUE en `servicios_sync_prov` — dos refrescos del mismo Servicio tienen
    que resolver en upsert (`ON CONFLICT DO UPDATE`), nunca en una segunda fila ni en un
    `IntegrityError`."""
    numero = "900212"
    pk = _crear_servicio_sync_prov_test(numero)

    for _ in range(2):
        async with _AsyncSessionLocalTest() as sesion:
            servicio = (await sesion.execute(select(Servicio).where(Servicio.id == pk))).scalars().one()
            await ingerir_contexto_prov(sesion, servicio, _contexto_minimo(numero))
            await sesion.commit()

    with SessionLocal() as session:
        total = session.execute(
            text("SELECT count(*) FROM app.servicios_sync_prov WHERE servicio_id = :servicio_id"),
            {"servicio_id": pk},
        ).scalar_one()
    assert total == 1
