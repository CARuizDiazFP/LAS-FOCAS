# Nombre de archivo: test_cromo_parser.py
# Ubicación de archivo: tests/test_cromo_parser.py
# Descripción: Pruebas del parser puro de payloads de Cromo Red, sin red ni base de datos

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.services.cromo.parser import (
    ClaseExcluidaError,
    ClaseNoSoportadaError,
    _resolver_geo,
    atributo,
    clasificar_tipo_elemento_odf,
    extraer_tipo_servicio_display,
    extraer_tubos_y_pelos,
    parse_arbol_botella,
    parse_botella,
    parse_cable,
    parse_objeto,
    parse_odf,
    parse_pagina,
    parse_pelo,
    resolver_lat_lon,
    resolver_lat_lon_gauss_kruger,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "cromo"


def _cargar_fixture(nombre: str) -> dict:
    with open(FIXTURES_DIR / nombre, encoding="utf-8") as f:
        return json.load(f)


# ── atributo() ────────────────────────────────────────────────────────────────


def test_atributo_resuelve_por_id_no_por_posicion():
    obj = {"at": [{"seq": 5, "id": 61, "value": "primero"}, {"seq": 1, "id": 34, "value": "segundo"}]}
    assert atributo(obj, 34) == "segundo"
    assert atributo(obj, 61) == "primero"


def test_atributo_devuelve_none_si_no_existe():
    obj = {"at": [{"seq": 1, "id": 34, "value": "x"}]}
    assert atributo(obj, 999) is None


def test_atributo_tolera_ausencia_de_at():
    assert atributo({}, 34) is None


# ── ll → latitud/longitud ───────────────────────────────────────────────────


def test_resolver_lat_lon_orden_correcto():
    # ll viene como [longitud, latitud]. Si se invierte el mapeo, este test falla.
    latitud, longitud = resolver_lat_lon([-58.4173, -34.6037])
    assert latitud == -34.6037
    assert longitud == -58.4173


def test_resolver_lat_lon_ausente():
    assert resolver_lat_lon(None) == (None, None)
    assert resolver_lat_lon([]) == (None, None)


# ── pts (Gauss-Krüger Faja 5) → latitud/longitud (Etapa 8) ──────────────────
# `ll` nunca aparece en un barrido real (0/11.100 botellas verificadas) — el dato geo real viaja en
# `pts`, proyectado (POSGAR94 Faja 5, EPSG:22185), no en grados. Valores reales de dos direcciones
# conocidas verificadas contra Cromo real: Av. Santa Fe 2600 CABA y Saenz Valiente 2420 San Isidro.


def test_resolver_lat_lon_gauss_kruger_direccion_real_caba():
    latitud, longitud = resolver_lat_lon_gauss_kruger([5646459.588986, 6171230.830909])
    assert latitud == pytest.approx(-34.5942, abs=1e-3)
    assert longitud == pytest.approx(-58.4035, abs=1e-3)


def test_resolver_lat_lon_gauss_kruger_direccion_real_san_isidro():
    latitud, longitud = resolver_lat_lon_gauss_kruger([5635059.104375, 6182088.510236])
    assert latitud == pytest.approx(-34.4979, abs=1e-3)
    assert longitud == pytest.approx(-58.5295, abs=1e-3)


def test_resolver_lat_lon_gauss_kruger_ausente():
    assert resolver_lat_lon_gauss_kruger(None) == (None, None)
    assert resolver_lat_lon_gauss_kruger([]) == (None, None)


def test_resolver_geo_prioriza_ll_si_esta_presente():
    # Defensivo: si algún día un objeto sí trae "ll", no debe ignorarse a favor de "pts".
    obj = {"ll": [-58.4173, -34.6037], "pts": [5646459.588986, 6171230.830909]}
    latitud, longitud = _resolver_geo(obj)
    assert (latitud, longitud) == (-34.6037, -58.4173)


def test_resolver_geo_usa_pts_si_no_hay_ll():
    obj = {"pts": [5646459.588986, 6171230.830909]}
    latitud, longitud = _resolver_geo(obj)
    assert latitud == pytest.approx(-34.5942, abs=1e-3)
    assert longitud == pytest.approx(-58.4035, abs=1e-3)


def test_resolver_geo_sin_ll_ni_pts():
    assert _resolver_geo({}) == (None, None)


# ── n_id como PK, id como version_id ────────────────────────────────────────


def test_n_id_es_pk_e_id_es_version_id_sobre_objeto_con_historial():
    obj = _cargar_fixture("botella_con_arbol.json")
    assert len(obj["hist"]) == 2
    botella = parse_botella(obj)
    assert botella.n_id == 10178728
    assert botella.version_id == 10193090
    assert botella.n_id != botella.version_id


def test_n_id_faltante_usa_id_como_fallback():
    obj = {"id": 42, "class": 68, "at": []}
    botella = parse_botella(obj)
    assert botella.n_id == 42


# ── clase 120 excluida ───────────────────────────────────────────────────────


def test_clase_120_es_rechazada_con_error_explicito():
    obj = _cargar_fixture("parcela_clase_120.json")
    with pytest.raises(ClaseExcluidaError):
        parse_objeto(obj)
    with pytest.raises(ClaseExcluidaError):
        parse_botella(obj)


def test_clase_124_se_marca_no_homologada():
    obj = _cargar_fixture("botella_no_homologada.json")
    botella = parse_botella(obj)
    assert botella.clase_no_homologada is True


# ── parent resuelve contra n_id, no contra id ───────────────────────────────


def test_parent_resuelve_contra_n_id_no_contra_id():
    obj = _cargar_fixture("botella_con_arbol.json")
    cable_embebido = obj["tp"][0]
    tubos, pelos, errores = extraer_tubos_y_pelos(cable_embebido)
    assert not errores

    n_ids_tubos = {t.n_id for t in tubos}
    # El primer tubo tiene id=60099 pero n_id=60010: sus pelos deben matchear n_id, no id.
    tubo_con_historia = next(t for t in tubos if t.n_id == 60010)
    assert tubo_con_historia.n_id != 60099  # id original del fixture, nunca debe usarse como PK

    pelos_del_tubo = [p for p in pelos if p.tubo_n_id == tubo_con_historia.n_id]
    assert len(pelos_del_tubo) == 2
    assert all(p.tubo_n_id in n_ids_tubos for p in pelos)


# ── atributo(obj, id) ya cubierto arriba; helper reutilizado en todos los parsers ──


def test_pelo_sin_at61_se_parsea_sin_excepcion():
    obj = {"id": 1, "n_id": 1, "class": 130, "parent": 60010, "at": [{"id": 75, "value": "9"}]}
    pelo = parse_pelo(obj)
    assert pelo.servicio_numero is None
    assert pelo.tipo_asociacion == "INDETERMINADO"
    assert pelo.servicio_raw is None


def test_pelo_con_at61_extrae_numero_de_servicio():
    obj = {
        "id": 1,
        "n_id": 1,
        "class": 130,
        "parent": 60010,
        "at": [{"id": 61, "value": "FO 114830 - EDGE - CIRION - Pelo 1 de 2"}],
    }
    pelo = parse_pelo(obj)
    assert pelo.servicio_numero == "114830"
    assert pelo.servicio_raw == "FO 114830 - EDGE - CIRION - Pelo 1 de 2"
    # Hallazgo real (Etapa 8): un servicio_numero extraído es justamente lo opuesto de "libre" — este
    # assert faltaba y dejó pasar un swap semántico (quedaba "LIBRE" en vez de "CLIENTE").
    assert pelo.tipo_asociacion == "CLIENTE"


@pytest.mark.parametrize(
    "servicio_raw,numero_esperado",
    [
        ("TLS 79932 - Cecilia Grierson 355 Piso 25", "79932"),
        ("DWDM 91719 - Prisma Medios de Pago SA (x LU)", "91719"),
        ("INT 45678 - Cliente X", "45678"),
        ("EWS 12345 - Cliente Y", "12345"),
        ("RPV 60207 / RPV 60209 - Macacha Güemes 515", "60207"),
        ("TDM 555 - Cliente Z", "555"),
        ("TRUNK 512 - SIDERCA - TENARIS CAMPANA", "512"),
        ("VID 525 - Cliente W", "525"),
        ("tls 79932 minúscula", "79932"),
    ],
)
def test_pelo_con_at61_extrae_numero_con_prefijos_no_fo(servicio_raw, numero_esperado):
    """Hallazgo real (Etapa 9c): el regex original sólo reconocía "FO" — ~89.361 pelos vigentes con
    descripción real (`servicio_raw`) nunca intentaban matchear porque usan otro prefijo de tipo de
    servicio. `app.servicios.tipo_servicio` ya trackea TLS/DWDM/INT/EWS/RPV/TDM/VID con el mismo
    esquema de numeración que FO — no son prefijos inventados."""
    obj = {"id": 1, "n_id": 1, "class": 130, "parent": 60010, "at": [{"id": 61, "value": servicio_raw}]}
    pelo = parse_pelo(obj)
    assert pelo.servicio_numero == numero_esperado
    assert pelo.tipo_asociacion == "CLIENTE"


def test_pelo_con_at61_prefijo_no_reconocido_queda_indeterminado():
    """Prefijos con match real 0 en la muestra (ej. "OS", "RED") quedan deliberadamente afuera —
    mayor riesgo de falso positivo que valor real agregado."""
    obj = {
        "id": 1,
        "n_id": 1,
        "class": 130,
        "parent": 60010,
        "at": [{"id": 61, "value": "OS 2749 - texto libre sin relación a un servicio"}],
    }
    pelo = parse_pelo(obj)
    assert pelo.servicio_numero is None
    assert pelo.tipo_asociacion == "INDETERMINADO"


def test_pelo_con_at61_infono_no_matchea_por_falta_de_word_boundary():
    """El `\\b` antes del prefijo evita que "INFO" (contiene "FO" como substring) o similares
    disparen un falso positivo — antes de Etapa 9c el regex viejo no tenía este boundary tampoco
    delante de "FO", así que no es una regresión, es una mejora agregada junto con los prefijos nuevos."""
    obj = {
        "id": 1,
        "n_id": 1,
        "class": 130,
        "parent": 60010,
        "at": [{"id": 61, "value": "INFO 12345 - esto no es un número de servicio real"}],
    }
    pelo = parse_pelo(obj)
    assert pelo.servicio_numero is None
    assert pelo.tipo_asociacion == "INDETERMINADO"


# ── extraer_tipo_servicio_display() ──────────────────────────────────────────
# Regex NUEVO e independiente de `_REGEX_SERVICIO`/`parsear_servicio` — sólo para la columna
# "Servicio" de la tabla de detalle de cable y el bot de Slack. Lista de prefijos más amplia a
# propósito (incluye ISIS/ATI, excluidos del regex de ingesta por 0 matches reales en la muestra de
# Etapa 9c) porque acá el peor caso es un texto mal etiquetado en una columna de UI, no una
# clasificación de datos real ni un `Servicio` placeholder creado de más.


@pytest.mark.parametrize(
    "servicio_raw,tipo_esperado",
    [
        ("FO 114830 - EDGE - CIRION - Pelo 1 de 2", "FO"),
        ("FO-DWDM 55512 - Trunk backbone", "FO-DWDM"),
        ("DWDM 91719 - Prisma Medios de Pago SA (x LU)", "DWDM"),
        ("INT 45678 - Cliente X", "INT"),
        ("ISIS 30021 - Cliente Y", "ISIS"),
        ("RPV 60207 / RPV 60209 - Macacha Güemes 515", "RPV"),
        ("EWS 12345 - Cliente Z", "EWS"),
        ("TLS 79932 - Cecilia Grierson 355 Piso 25", "TLS"),
        ("ATI 999 - Cliente W", "ATI"),
        ("tls 79932 minúscula", "TLS"),
        # VID/TDM/ATD/TRUNK: ya probados y seguros en `_REGEX_SERVICIO` (matchean de verdad contra
        # `app.servicios` en ingesta, a diferencia de ISI/ATI) — verificado real contra
        # `lasfocasdev-postgres` 2026-08-25: sin ellos, un pelo con "VID 93727 ..." mostraba Línea Y
        # Cliente ya resueltos (vía el match de ingesta) pero "Servicio" en "-", inconsistencia visual
        # sin motivo — agregarlos no reabre el riesgo de falso positivo de ISI/ATI, es distinto.
        ("VID 525 - Cliente W", "VID"),
        ("TDM 555 - Cliente Z", "TDM"),
        ("ATD 321 - Cliente Y", "ATD"),
        ("TRUNK 512 - SIDERCA - TENARIS CAMPANA", "TRUNK"),
    ],
)
def test_extraer_tipo_servicio_display_reconoce_prefijo(servicio_raw, tipo_esperado):
    assert extraer_tipo_servicio_display(servicio_raw) == tipo_esperado


def test_extraer_tipo_servicio_display_prioriza_compuesto_fo_dwdm_sobre_fo_suelto():
    assert extraer_tipo_servicio_display("FO-DWDM 55512 - Trunk backbone") == "FO-DWDM"


def test_extraer_tipo_servicio_display_sin_match_devuelve_guion():
    assert extraer_tipo_servicio_display("OS 2749 - texto libre sin relación a un servicio") == "-"


def test_extraer_tipo_servicio_display_vacio_devuelve_guion():
    assert extraer_tipo_servicio_display(None) == "-"
    assert extraer_tipo_servicio_display("") == "-"


# ── botella.inner[] → sólo fusiones ──────────────────────────────────────────


def test_botella_inner_produce_fusiones_y_nunca_tubos_ni_pelos():
    obj = _cargar_fixture("botella_con_arbol.json")
    arbol = parse_arbol_botella(obj)
    assert len(arbol.fusiones) == 1
    assert arbol.fusiones[0].nombre_par == "53-17"
    assert arbol.fusiones[0].tipo == "FUSION"
    # Las fusiones vienen de inner[]; tubos y pelos vienen de tp[] → cable.inner[], nunca de acá.
    assert arbol.tubos  # sí hay tubos, pero originados en el cable, no en botella.inner[]
    assert arbol.pelos


# ── cable.inner[] → tubos y pelos, pelo asociado a su tubo ──────────────────


def test_cable_inner_produce_tubos_y_pelos_asociados():
    obj = _cargar_fixture("botella_con_arbol.json")
    arbol = parse_arbol_botella(obj)
    assert len(arbol.cables) == 1
    assert len(arbol.tubos) == 2
    assert len(arbol.pelos) == 3

    n_ids_tubos = {t.n_id for t in arbol.tubos}
    for pelo in arbol.pelos:
        assert pelo.tubo_n_id in n_ids_tubos
        assert pelo.cable_n_id == arbol.cables[0].n_id


def test_cable_parseado_desde_barrido_directo():
    obj = _cargar_fixture("cable_barrido_directo.json")
    cable = parse_cable(obj)
    assert cable.n_id == 50010
    assert cable.version_id == 50199
    assert cable.nombre == "F-PLB-ART"
    assert cable.capacidad == "72-BRUG"
    assert cable.capacidad_pelos == 72
    assert cable.propietario == "Metrotel"
    assert cable.jerarquia == "Troncal"
    assert cable.extremo_a_n_id == 10178728
    assert cable.extremo_a_clase == 68
    assert cable.extremo_b_n_id == 10444555
    assert cable.extremo_b_clase == 124


# ── iterar_coleccion / tolerancia de página: cubiertas del lado del parser ──


def test_objeto_malformado_en_pagina_no_impide_procesar_el_resto():
    valido_1 = {"id": 1, "n_id": 1, "class": 68, "at": []}
    malformado = {"id": 2, "n_id": 2, "class": 9999, "at": []}  # clase sin parser asociado
    valido_2 = {"id": 3, "n_id": 3, "class": 51, "at": []}

    ok, errores = parse_pagina([valido_1, malformado, valido_2])

    assert len(ok) == 2
    assert len(errores) == 1
    assert errores[0].n_id == 2
    assert errores[0].clase == 9999


def test_clase_132_no_asume_siempre_fusion():
    obj = {
        "id": 1,
        "n_id": 1,
        "class": 132,
        "parent": 10,
        "at": [{"id": 84, "value": "X-Y"}, {"id": 85, "value": "OTRO_TIPO"}],
        "tp": [],
    }
    from core.services.cromo.parser import parse_fusion

    fusion = parse_fusion(obj)
    assert fusion.tipo == "OTRO_TIPO"


# ── clasificar_tipo_elemento_odf() (class 69 = ODF) ──────────────────────────
# Diagnóstico real (30 objetos clase 69 de Cromo, ver Tarea 0 del plan): 26/30 nombres empiezan
# con "ODF " seguido de una dirección libre; 4/30 son direcciones libres sin ninguna palabra
# clave. Cero matchean "O-"/"Patch"/"F-"/"Empalme" en la muestra real de Cromo — esos patrones
# pertenecen a `O-1238223-1/-2/-#` etc., que el ticket original asumía de Cromo pero resultó ser
# de OTRO sistema (parser de tracking de rutas, ver task-1-brief.md / task-7-brief.md de este
# plan). Por eso "O-1238223-1" y "Patch algo" NO matchean acá — se prueban explícitamente como
# SIN_CLASIFICAR, no como "ODF": el objetivo de este test es la consistencia interna del
# clasificador con sus propias reglas documentadas (`_REGEX_ODF`/`_REGEX_EMPALME`), no que
# reconozca patrones de un sistema distinto (ver también task-6-brief.md, punto 4).


@pytest.mark.parametrize(
    "nombre,tipo_esperado",
    [
        ("ODF Calle 9 Nro 593 PILAR", "ODF"),  # muestra real dominante (26/30)
        ("ODF Saenz Valiente 2420 San Isidro", "ODF"),
        ("odf calle falsa 123", "ODF"),  # case-insensitive
        ("F-4521", "EMPALME"),
        ("Empalme 123: algo", "EMPALME"),
        ("empalme minúscula", "EMPALME"),  # case-insensitive
        ("Arias 3751 P12", "SIN_CLASIFICAR"),  # dirección libre sin palabra clave, muestra real (4/30)
        ("O-1238223-1", "SIN_CLASIFICAR"),  # patrón del ticket original, de otro sistema, no de Cromo
        ("Patch algo", "SIN_CLASIFICAR"),  # ídem
    ],
)
def test_clasificar_tipo_elemento_odf(nombre, tipo_esperado):
    assert clasificar_tipo_elemento_odf(nombre) == tipo_esperado


def test_clasificar_tipo_elemento_odf_none_o_vacio_no_lanza_excepcion():
    assert clasificar_tipo_elemento_odf(None) == "SIN_CLASIFICAR"
    assert clasificar_tipo_elemento_odf("") == "SIN_CLASIFICAR"


# ── parse_odf() (class 69) ────────────────────────────────────────────────────
# Hallazgo real (Tarea 0): el item de `tp[]` de un cable referenciado trae tanto `n_id` (el
# identificador ESTABLE del cable) como `id_to` (un id de versión, distinto y que NO debe
# usarse — mismo problema de "ID dual" ya conocido en otras partes de este ingestor).


def test_parse_odf_cables_asociados_usa_n_id_no_id_to():
    obj = {
        "id": 900001,
        "n_id": 800001,
        "class": 69,
        "vmax": 3,
        "at": [
            {"id": 34, "value": "ODF Calle 9 Nro 593 PILAR"},
            {"id": 47, "value": "Metrotel"},
        ],
        "tp": [
            {
                "type": 0,
                "nfrom": 0,
                "id_to": 9739619,
                "nto": 0,
                "class": 51,
                "n_id": 6613848,
                "name": "F-CLL9-543",
                "at": [],
                "tp": [],
                "inner": [],
            }
        ],
    }
    odf = parse_odf(obj)
    assert odf.cables_asociados == [6613848]
    assert 9739619 not in odf.cables_asociados


def test_parse_odf_ignora_items_de_tp_que_no_son_cable():
    obj = {
        "id": 900002,
        "n_id": 800002,
        "class": 69,
        "at": [{"id": 34, "value": "ODF Otra Direccion 456"}],
        "tp": [{"class": 999, "n_id": 111111, "id_to": 222222}],
    }
    odf = parse_odf(obj)
    assert odf.cables_asociados == []


def test_parse_odf_sin_tp_en_absoluto_deja_cables_asociados_en_none():
    obj = {"id": 900003, "n_id": 800003, "class": 69, "at": [{"id": 34, "value": "ODF Sin tp"}]}
    odf = parse_odf(obj)
    assert odf.cables_asociados is None


def test_parse_odf_lee_atributos_compartidos_con_botella():
    obj = {
        "id": 900004,
        "n_id": 800004,
        "class": 69,
        "vmax": 7,
        "at": [
            {"id": 34, "value": "ODF Calle 9 Nro 593 PILAR"},
            {"id": 41, "value": "MOD-1"},
            {"id": 91, "value": "LEGACY-1"},
            {"id": 35, "value": "una nota"},
            {"id": 67, "value": "Calle 9"},
            {"id": 16, "value": "593"},
            {"id": 68, "value": "PILAR"},
            {"id": 69, "value": "Buenos Aires"},
            {"id": 118, "value": "http://ejemplo/foto.jpg"},
            {"id": 20, "value": "Subterraneo"},
            {"id": 47, "value": "Metrotel"},
        ],
    }
    odf = parse_odf(obj)
    assert odf.n_id == 800004
    assert odf.version_id == 900004
    assert odf.vmax == 7
    assert odf.clase == 69
    assert odf.nombre == "ODF Calle 9 Nro 593 PILAR"
    assert odf.codigo_modelo == "MOD-1"
    assert odf.id_legacy == "LEGACY-1"
    assert odf.notas == "una nota"
    assert odf.calle == "Calle 9"
    assert odf.altura == "593"
    assert odf.localidad == "PILAR"
    assert odf.provincia == "Buenos Aires"
    assert odf.ubicacion_fisica == "http://ejemplo/foto.jpg"
    assert odf.tendido == "Subterraneo"
    assert odf.propietario == "Metrotel"
    assert odf.tipo_elemento == "ODF"


def test_parse_odf_payload_raw_es_siempre_dict_del_objeto_completo():
    obj = {"id": 900005, "n_id": 800005, "class": 69, "at": [], "algo_extra": "valor"}
    odf = parse_odf(obj)
    assert odf.payload_raw == obj
    assert odf.payload_raw is not obj  # copia, no la misma referencia


def test_clase_69_despachada_por_parse_objeto_ya_no_lanza_clase_no_soportada():
    """Contrato central de este task: antes de registrar `_CLASE_ODF` en `_DISPATCH`, esto
    lanzaba `ClaseNoSoportadaError` (clase 69 sin parser asociado). Se prueba a través de la
    función general de despacho (`parse_objeto`), no llamando a `parse_odf` directamente, para
    verificar el registro real en la tabla de despacho."""
    obj = {"id": 1, "n_id": 1, "class": 69, "at": [{"id": 34, "value": "ODF Direccion X"}]}
    resultado = parse_objeto(obj)
    assert resultado.tipo_elemento == "ODF"
    assert resultado.n_id == 1


def test_clase_69_sigue_siendo_no_soportada_solo_si_no_estuviera_registrada():
    """Sanity check inverso: una clase realmente sin parser (9998, elegida para no chocar con la
    clase 9999 ya usada en otro test de este archivo) sigue lanzando `ClaseNoSoportadaError` —
    confirma que el test anterior prueba el registro real de 69, no un despacho que acepta
    cualquier clase."""
    obj = {"id": 1, "n_id": 1, "class": 9998, "at": []}
    with pytest.raises(ClaseNoSoportadaError):
        parse_objeto(obj)
