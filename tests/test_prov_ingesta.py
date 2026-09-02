# Nombre de archivo: test_prov_ingesta.py
# Ubicación de archivo: tests/test_prov_ingesta.py
# Descripción: Tests puros del parseo del contexto de PROV (sin DB) — mapeo de campos, cadena de upgrades y fallback sin cadena

from __future__ import annotations

from datetime import date

from core.services.prov.ingesta import parsear_contexto_prov

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


def test_parsea_dos_extremos_cuando_el_payload_trae_nodo2() -> None:
    contexto = dict(_CONTEXTO_SIN_UPGRADES, Nodo2="NODO-B", Equipo2="SW-B", Port2="2", Direccion2="OTRA CALLE 456")
    parseado = parsear_contexto_prov(contexto)

    assert len(parseado.equipos) == 2
    assert parseado.equipos[1].extremo == 2
    assert parseado.equipos[1].nodo == "NODO-B"
    assert parseado.equipos[1].direccion == "OTRA CALLE 456"
