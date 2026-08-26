# Nombre de archivo: test_servicios_consolidacion_service.py
# Ubicación de archivo: tests/test_servicios_consolidacion_service.py
# Descripción: Tests del cálculo de verificabilidad y de ID final/alias para la cadena de upgrades de Servicio

from core.services.servicios_consolidacion_service import (
    consolidar_identidad_servicio,
    es_verificable_por_tipo,
)


def test_es_verificable_por_tipo_acepta_los_tipos_del_negocio() -> None:
    for tipo in ("INT", "RPV", "ISI", "ISIS", "TLS", "EWS"):
        assert es_verificable_por_tipo(tipo) is True


def test_es_verificable_por_tipo_rechaza_otros_tipos_y_normaliza_mayusculas() -> None:
    assert es_verificable_por_tipo("int") is True
    assert es_verificable_por_tipo("ATI") is False
    assert es_verificable_por_tipo(None) is False
    assert es_verificable_por_tipo("") is False


def test_consolidar_identidad_alta_nueva_sin_upgrade() -> None:
    resultado = consolidar_identidad_servicio(
        numero_primer_servicio="393",
        numero_linea_excel="393",
        linea_upgrade_de=None,
        linea_upgrade_a=None,
        servicio_id_actual=None,
        numero_linea_actual=None,
        alias_ids_actual=None,
    )
    assert resultado.servicio_id == "393"
    assert resultado.numero_linea == "393"
    assert resultado.alias_ids == []


def test_consolidar_identidad_toma_el_id_mas_alto_como_final() -> None:
    resultado = consolidar_identidad_servicio(
        numero_primer_servicio="393",
        numero_linea_excel="116916",
        linea_upgrade_de="105636",
        linea_upgrade_a=None,
        servicio_id_actual=None,
        numero_linea_actual=None,
        alias_ids_actual=None,
    )
    assert resultado.servicio_id == "116916"
    assert resultado.numero_linea == "116916"
    assert resultado.alias_ids == ["393", "105636"]


def test_consolidar_identidad_acumula_alias_previos_y_avanza_al_nuevo_maximo() -> None:
    resultado = consolidar_identidad_servicio(
        numero_primer_servicio="4397",
        numero_linea_excel="130000",
        linea_upgrade_de="108368",
        linea_upgrade_a=None,
        servicio_id_actual="108368",
        numero_linea_actual="108368",
        alias_ids_actual=["4397"],
    )
    assert resultado.servicio_id == "130000"
    assert resultado.numero_linea == "130000"
    assert resultado.alias_ids == ["4397", "108368"]


def test_consolidar_identidad_no_pisa_servicio_id_no_numerico_de_tracking() -> None:
    resultado = consolidar_identidad_servicio(
        numero_primer_servicio="45789",
        numero_linea_excel="111743",
        linea_upgrade_de=None,
        linea_upgrade_a=None,
        servicio_id_actual="O1C1",
        numero_linea_actual="45789",
        alias_ids_actual=[],
    )
    assert resultado.servicio_id == "O1C1"
    assert resultado.numero_linea == "111743"
    assert resultado.alias_ids == ["45789"]


def test_consolidar_identidad_ignora_guion_como_valor_vacio() -> None:
    resultado = consolidar_identidad_servicio(
        numero_primer_servicio="99761",
        numero_linea_excel="106608",
        linea_upgrade_de="-",
        linea_upgrade_a="118984",
        servicio_id_actual=None,
        numero_linea_actual=None,
        alias_ids_actual=None,
    )
    assert resultado.servicio_id == "118984"
    assert "-" not in resultado.alias_ids


def test_consolidar_identidad_no_duplica_alias_existentes_que_coinciden_con_id_final() -> None:
    """Hallazgo 1: alias_existentes debe filtrarse para no duplicar id_final en alias_ids"""
    resultado = consolidar_identidad_servicio(
        numero_primer_servicio="500",
        numero_linea_excel="500",
        linea_upgrade_de=None,
        linea_upgrade_a=None,
        servicio_id_actual=None,
        numero_linea_actual=None,
        alias_ids_actual=["500"],  # Este "500" fue previo, ahora es id_final
    )
    assert resultado.numero_linea == "500"
    assert resultado.alias_ids == []  # No debe duplicarse, se filtra


def test_consolidar_identidad_filtra_guion_de_alias_existentes() -> None:
    """Hallazgo 1: alias_existentes debe filtrar "-" como se hace en candidatos_str"""
    resultado = consolidar_identidad_servicio(
        numero_primer_servicio="600",
        numero_linea_excel="700",
        linea_upgrade_de=None,
        linea_upgrade_a=None,
        servicio_id_actual=None,
        numero_linea_actual=None,
        alias_ids_actual=["600", "-", "700"],  # Contiene "-" que debe ser filtrado
    )
    assert resultado.numero_linea == "700"
    assert "-" not in resultado.alias_ids
    assert resultado.alias_ids == ["600"]  # Solo "600", no el "-"


def test_consolidar_identidad_canonicaliza_forma_numerica() -> None:
    """Hallazgo 2: Dos representaciones del mismo entero ("093" vs "93") se canonicalizan"""
    resultado = consolidar_identidad_servicio(
        numero_primer_servicio="093",
        numero_linea_excel="93",  # Mismo valor, distinta representación
        linea_upgrade_de=None,
        linea_upgrade_a=None,
        servicio_id_actual=None,
        numero_linea_actual=None,
        alias_ids_actual=None,
    )
    # El id_final debe ser la forma canónica sin ceros a la izquierda
    assert resultado.numero_linea == "93"
    # Ambas formas están en candidatos, pero como representan el mismo número,
    # solo una debe quedar (la canónica), la otra no debe aparecer en alias
    assert resultado.alias_ids == []  # Sin duplicados


def test_consolidar_identidad_filtra_alias_no_canonica_que_coincide_con_id_final() -> None:
    """Fix round 2: alias_ids_actual con forma no canónica del mismo entero que id_final debe filtrarse"""
    resultado = consolidar_identidad_servicio(
        numero_primer_servicio="93",
        numero_linea_excel="93",
        linea_upgrade_de=None,
        linea_upgrade_a=None,
        servicio_id_actual=None,
        numero_linea_actual=None,
        alias_ids_actual=["093"],  # Forma no canónica de 93, debe filtrarse
    )
    assert resultado.numero_linea == "93"
    # "093" representa el mismo entero que id_final="93", así que debe filtrarse
    assert resultado.alias_ids == []  # No duplicado, se filtra por valor numérico
