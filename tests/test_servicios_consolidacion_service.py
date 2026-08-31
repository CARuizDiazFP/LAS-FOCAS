# Nombre de archivo: test_servicios_consolidacion_service.py
# Ubicación de archivo: tests/test_servicios_consolidacion_service.py
# Descripción: Tests del cálculo de verificabilidad y de ID final/alias para la cadena de upgrades de Servicio

from core.services.servicios_consolidacion_service import (
    consolidar_identidad_servicio,
    es_verificable_por_tipo,
    resolver_estado_servicio,
)


def _formas_duplicadas_del_mismo_entero(alias_ids: list[str]) -> list[int]:
    """Enteros que aparecen representados por más de un string dentro de `alias_ids`.

    Invariante del resultado (ronda 4): para cada entero distinto representado en `alias_ids` debe
    haber UNA SOLA forma de string. Devuelve la lista de enteros que violan el invariante (vacía si
    el resultado está bien). No usa helpers privados del módulo para no acoplarse a su interna.
    """
    vistos: dict[int, set[str]] = {}
    for valor in alias_ids:
        try:
            entero = int(valor.strip())
        except (ValueError, AttributeError):
            continue
        vistos.setdefault(entero, set()).add(valor)
    return [entero for entero, formas in vistos.items() if len(formas) > 1]


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
    # `servicio_id` queda en manos del tracking físico, pero el número de línea vigente ("111743")
    # sí entra como alias: es el ID por el que Cromo va a buscar esta familia.
    assert resultado.alias_ids == ["45789", "111743"]


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


def test_consolidar_identidad_preserva_alias_no_numerico_distinto_de_servicio_id_tracking() -> None:
    """Fix round 3: alias_ids_actual con otro valor no numérico debe preservarse (no colisión None==None)"""
    resultado = consolidar_identidad_servicio(
        numero_primer_servicio="45789",
        numero_linea_excel="111743",
        linea_upgrade_de=None,
        linea_upgrade_a=None,
        servicio_id_actual="O1C1",      # no numérico, se preserva como servicio_id_final
        numero_linea_actual=None,
        alias_ids_actual=["O2C2"],      # otro alias no numérico DISTINTO, debe sobrevivir
    )
    assert resultado.servicio_id == "O1C1"  # preservado
    assert resultado.numero_linea == "111743"  # máximo numérico
    # "O2C2" es distinto de id_final y de servicio_id_final, debe estar en alias
    # "45789" (numero_primer_servicio) también es candidato legítimo
    assert "O2C2" in resultado.alias_ids  # No se pierden aliases legítimos no numéricos
    # "111743" (id_final) también entra: con `servicio_id` en manos del tracking físico, el número de
    # línea vigente sólo queda alcanzable para Cromo a través de alias_ids.
    assert resultado.alias_ids == ["O2C2", "45789", "111743"]  # Ordenado correctamente


def test_consolidar_identidad_dedupe_dos_formas_del_mismo_entero_en_alias_actual() -> None:
    """Ronda 4 / Repro A: dos formas del mismo entero ya presentes en alias_ids_actual.

    "093" y "93" son el mismo ID de línea; sólo la forma canónica debe sobrevivir en alias_ids.
    """
    resultado = consolidar_identidad_servicio(
        numero_primer_servicio="200",
        numero_linea_excel="300",
        linea_upgrade_de=None,
        linea_upgrade_a=None,
        servicio_id_actual=None,
        numero_linea_actual=None,
        alias_ids_actual=["093", "93"],
    )
    assert resultado.numero_linea == "300"
    assert resultado.alias_ids == ["93", "200"]
    assert _formas_duplicadas_del_mismo_entero(resultado.alias_ids) == []


def test_consolidar_identidad_dedupe_alias_actual_no_canonica_contra_candidato_nuevo() -> None:
    """Ronda 4 / Repro B: forma no canónica en alias_ids_actual + candidato nuevo del mismo entero.

    alias_ids_actual=["093"] y linea_upgrade_de="93" son el mismo ID: una sola forma en alias_ids.
    """
    resultado = consolidar_identidad_servicio(
        numero_primer_servicio="200",
        numero_linea_excel="300",
        linea_upgrade_de="93",
        linea_upgrade_a=None,
        servicio_id_actual=None,
        numero_linea_actual=None,
        alias_ids_actual=["093"],
    )
    assert resultado.numero_linea == "300"
    assert resultado.alias_ids == ["93", "200"]
    assert _formas_duplicadas_del_mismo_entero(resultado.alias_ids) == []


def test_consolidar_identidad_dedupe_dos_columnas_del_excel_con_el_mismo_entero() -> None:
    """Ronda 4 / caso 3 (auto-revisión): el choque no viene de alias_ids_actual sino de dos columnas
    del Excel con formato distinto para el mismo ID ("0300" en Número Primer Servicio y "300" en
    Línea Upgrade (De)). Debe quedar una sola forma canónica en alias_ids.
    """
    resultado = consolidar_identidad_servicio(
        numero_primer_servicio="0300",
        numero_linea_excel="500",
        linea_upgrade_de="300",
        linea_upgrade_a=None,
        servicio_id_actual=None,
        numero_linea_actual=None,
        alias_ids_actual=None,
    )
    assert resultado.numero_linea == "500"
    assert resultado.alias_ids == ["300"]
    assert _formas_duplicadas_del_mismo_entero(resultado.alias_ids) == []


def test_consolidar_identidad_avanza_por_excel_true_cuando_el_id_final_lo_aporta_el_excel() -> None:
    """El Excel trae el ID más alto conocido: es una ingesta vigente, no un catch-up histórico."""
    resultado = consolidar_identidad_servicio(
        numero_primer_servicio="38929",
        numero_linea_excel="112922",
        linea_upgrade_de=None,
        linea_upgrade_a=None,
        servicio_id_actual="53597",
        numero_linea_actual="53597",
        alias_ids_actual=[],
    )
    assert resultado.numero_linea == "112922"
    assert resultado.avanza_por_excel is True


def test_consolidar_identidad_avanza_por_excel_false_cuando_el_id_final_ya_estaba_en_la_db() -> None:
    """El Excel sólo repite un ID viejo (ej. un archivo histórico subido para completar el
    encadenado); lo ya conocido en la DB es mayor, así que esta fila no es la más vigente."""
    resultado = consolidar_identidad_servicio(
        numero_primer_servicio="38929",
        numero_linea_excel="38929",
        linea_upgrade_de=None,
        linea_upgrade_a=None,
        servicio_id_actual="112922",
        numero_linea_actual="112922",
        alias_ids_actual=[],
    )
    assert resultado.numero_linea == "112922"
    assert resultado.avanza_por_excel is False


def test_consolidar_identidad_avanza_por_excel_true_sin_datos_existentes() -> None:
    """Alta nueva, sin fila previa en la DB: no hay nada más vigente que atrasar."""
    resultado = consolidar_identidad_servicio(
        numero_primer_servicio="393",
        numero_linea_excel="393",
        linea_upgrade_de=None,
        linea_upgrade_a=None,
        servicio_id_actual=None,
        numero_linea_actual=None,
        alias_ids_actual=None,
    )
    assert resultado.avanza_por_excel is True


def test_resolver_estado_servicio_preserva_activo_si_el_excel_no_avanza_la_identidad() -> None:
    """Regla de negocio confirmada con el usuario: un Excel histórico (no trae el ID más alto)
    no puede degradar un servicio ya Activo a Baja/otro estado."""
    assert (
        resolver_estado_servicio(estado_actual="Activo", estado_excel="Baja", avanza_identidad=False)
        == "Activo"
    )


def test_resolver_estado_servicio_respeta_baja_del_excel_cuando_si_avanza_la_identidad() -> None:
    """Si el Excel sí trae el ID más vigente, es la fuente autoritativa y se respeta tal cual."""
    assert (
        resolver_estado_servicio(estado_actual="Activo", estado_excel="Baja", avanza_identidad=True)
        == "Baja"
    )


def test_resolver_estado_servicio_no_protege_estados_distintos_de_activo() -> None:
    """La protección es específica de "Activo" — otros estados actuales siguen el pass-through normal."""
    assert (
        resolver_estado_servicio(estado_actual="Baja", estado_excel="DESCONOCIDO", avanza_identidad=False)
        == "DESCONOCIDO"
    )


def test_resolver_estado_servicio_reconoce_activo_sin_distinguir_mayusculas() -> None:
    assert (
        resolver_estado_servicio(estado_actual="ACTIVO", estado_excel="Baja", avanza_identidad=False)
        == "ACTIVO"
    )


def test_resolver_estado_servicio_sin_fila_previa_usa_directo_el_valor_del_excel() -> None:
    assert (
        resolver_estado_servicio(estado_actual=None, estado_excel="Baja", avanza_identidad=True)
        == "Baja"
    )
