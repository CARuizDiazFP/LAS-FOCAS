# Nombre de archivo: test_cromo_camino_optico_txt.py
# Ubicación de archivo: tests/test_cromo_camino_optico_txt.py
# Descripción: Pruebas del generador de trackings .txt desde un camino óptico de Cromo, sin red ni base

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.parsers.tracking_parser import parse_tracking
from core.services.cromo.camino_optico_service import (
    ESTADO_OK,
    CaminoOptico,
    _construir_lado,
    _desenvolver_dict,
)
from core.services.cromo.camino_optico_txt import (
    nombre_archivo_tracking,
    renderizar_tracking_txt,
    secuencia_para_tracking,
)

FIXTURE = Path(__file__).parent / "fixtures" / "cromo" / "camino_optico_pelo_10006353_reducido.json"
PELO_RAIZ = 10006353
GENERADO_EN = datetime(2026, 9, 10, 17, 31, 46, tzinfo=timezone.utc)


def _camino_de_la_fixture() -> CaminoOptico:
    """Camino armado desde el payload real congelado.

    La fixture es un recorte de una respuesta real de Cromo y no cambia: el camino es un elemento
    vivo, así que un test que dependiera de Cromo o de un `.txt` almacenado fallaría el día que la
    fibra se rerutee, por una razón legítima y ajena al generador.
    """
    dic = _desenvolver_dict(json.loads(FIXTURE.read_text(encoding="utf-8")))
    raiz_nodos, _ = _construir_lado(dic, [PELO_RAIZ], "RAIZ", {})
    lado_a, _ = _construir_lado(dic, dic[PELO_RAIZ]["a"], "A", {})
    lado_b, _ = _construir_lado(dic, dic[PELO_RAIZ]["b"], "B", {})
    return CaminoOptico(
        estado=ESTADO_OK,
        pelo_n_id=PELO_RAIZ,
        servicio_at62="93154",
        servicio_at61="FO 93154 - ODF Guanahani 580 - X el Bajo X TBA",
        raiz=raiz_nodos[0],
        lado_a=lado_a,
        lado_b=lado_b,
    )


# ── Nombre del archivo ───────────────────────────────────────────────────────


def test_el_nombre_lleva_el_servicio_para_que_el_parser_lo_recupere():
    assert nombre_archivo_tracking("93154", PELO_RAIZ) == "93154 CROMO.txt"


def test_el_nombre_no_finge_ser_un_tracking_numerado_a_mano():
    # El regex de alias del parser exige letra+dígitos (`C21`); `CROMO` no matchea, así que el
    # archivo generado no se confunde con uno cargado manualmente.
    resultado = parse_tracking("", nombre_archivo_tracking("93154", PELO_RAIZ))

    assert resultado.servicio_id == "93154"
    assert resultado.alias_id is None


@pytest.mark.parametrize("numero", [None, "", "12", "abc"])
def test_sin_un_numero_de_servicio_plausible_el_nombre_cae_al_pelo(numero):
    assert nombre_archivo_tracking(numero, 999) == "tracking_cromo_pelo_999.txt"


# ── Orden del archivo ────────────────────────────────────────────────────────


def test_el_orden_es_lado_b_invertido_luego_raiz_luego_lado_a():
    camino = _camino_de_la_fixture()

    secuencia = secuencia_para_tracking(camino)

    esperado = list(reversed(camino.lado_b)) + [camino.raiz] + camino.lado_a
    assert [n.id_cromo for n in secuencia] == [n.id_cromo for n in esperado]


# ── Formato ──────────────────────────────────────────────────────────────────


def test_el_archivo_usa_crlf():
    # Los 45 archivos reales usan CRLF; un `.txt` con LF se vería distinto en las herramientas
    # de campo (Notepad de Windows).
    texto = renderizar_tracking_txt(_camino_de_la_fixture(), generado_en=GENERADO_EN)

    assert "\r\n" in texto
    assert texto.endswith("\r\n")
    assert "\n" not in texto.replace("\r\n", "")


def test_la_cabecera_reproduce_la_gramatica_real():
    texto = renderizar_tracking_txt(_camino_de_la_fixture(), generado_en=GENERADO_EN)
    lineas = texto.split("\r\n")
    cuerpo = [linea for linea in lineas if not linea.startswith("#")]

    assert cuerpo[1].startswith("Cable: ")
    assert "TUBO:" in cuerpo[2]
    assert cuerpo[2].count("⇃") == 10
    assert cuerpo[2].count("⇂") == 10
    assert cuerpo[4] == "+" * 31
    assert cuerpo[5].startswith("Nombre de Pelo: ")


def test_la_cabecera_declara_procedencia_fecha_y_la_ausencia_de_db():
    texto = renderizar_tracking_txt(_camino_de_la_fixture(), generado_en=GENERADO_EN)

    assert "GENERADO desde Cromo" in texto
    assert "no es una medición de campo" in texto
    assert GENERADO_EN.isoformat() in texto  # el camino es vivo: la foto tiene fecha
    assert "NO llevan la columna dB" in texto
    assert "Cromo es la fuente de la verdad" in texto


def test_el_tramo_del_cable_de_cabecera_va_entre_separadores():
    texto = renderizar_tracking_txt(_camino_de_la_fixture(), generado_en=GENERADO_EN)

    assert texto.count("-" * 51) == 2


def test_los_dos_ordinales_van_mas_uno():
    # Verificado contra el archivo de oro: el pelo con `at.74 = 8` y su tubo con `at.72 = 1` se
    # imprimen `(NR / 2 - 9)`.
    dic = {
        1: {
            "class": 130,
            "father": 10,
            "gfather": 20,
            "at": [{"id": 75, "value": "21"}, {"id": 74, "value": "8"}],
        },
        10: {"class": 129, "at": [{"id": 76, "value": "NR"}, {"id": 72, "value": "1"}]},
        20: {
            "class": 51,
            "at": [
                {"id": 26, "value": "F-GAN-80B"},
                {"id": 23, "value": "197"},
                {"id": 24, "value": "201.92"},
            ],
        },
    }
    nodos, _ = _construir_lado(dic, [1], "A", {})
    camino = CaminoOptico(estado=ESTADO_OK, pelo_n_id=1, lado_a=nodos)

    texto = renderizar_tracking_txt(camino, generado_en=GENERADO_EN)

    assert "F-GAN-80B: 21 (NR / 2 - 9) --> 197 / 197 mts * 201.9 mts" in texto


def test_la_linea_de_tramo_no_lleva_db():
    """Decisión de producto blindada: Cromo no publica la atenuación y no se fabrica ninguna.

    Si alguien "arregla" el formato agregando un `0 dB`, ese número entraría como una medición
    real en el maestro de infra al re-subir el archivo. Este test lo impide.
    """
    texto = renderizar_tracking_txt(_camino_de_la_fixture(), generado_en=GENERADO_EN)
    tramos = [
        linea
        for linea in texto.split("\r\n")
        if "-->" in linea and "Sin longitud" not in linea and not linea.startswith("#")
    ]

    assert tramos, "la fixture real tiene al menos un tramo"
    for linea in tramos:
        assert not linea.rstrip().endswith("dB")


def test_el_empalme_usa_el_id_de_la_botella_y_no_el_de_la_fusion():
    # Hallazgo real: `fusión.father` es la botella, y es el id que imprime el tracking legacy.
    dic = {
        1: {"class": 132, "father": 50, "at": [{"id": 84, "value": "21-21"}]},
        50: {"class": 68, "at": [{"id": 34, "value": "Cra Herrera 599 CF"}]},
    }
    nodos, _ = _construir_lado(dic, [1], "A", {})
    camino = CaminoOptico(estado=ESTADO_OK, pelo_n_id=1, lado_a=nodos)

    texto = renderizar_tracking_txt(camino, generado_en=GENERADO_EN)

    assert "Empalme 50: Cra Herrera 599 CF" in texto
    assert "Empalme 1:" not in texto


def test_un_camino_incompleto_declara_el_hueco_en_su_posicion():
    # Los caminos de Cromo vienen incompletos con frecuencia: el archivo lo dice en vez de
    # disimularlo, y en una línea que el parser legacy ignora.
    nodos, _ = _construir_lado({1: {"class": 132}}, [1, 999], "A", {})
    camino = CaminoOptico(estado=ESTADO_OK, pelo_n_id=1, lado_a=nodos)

    texto = renderizar_tracking_txt(camino, generado_en=GENERADO_EN)

    assert "# Elemento 999 del camino no vino resuelto" in texto


# ── Round-trip contra el parser legacy real ──────────────────────────────────


def test_round_trip_el_parser_legacy_recupera_servicio_empalmes_y_puntas():
    camino = _camino_de_la_fixture()
    nombre = nombre_archivo_tracking(camino.servicio_at62, camino.pelo_n_id)

    resultado = parse_tracking(
        renderizar_tracking_txt(camino, generado_en=GENERADO_EN), nombre
    )

    assert resultado.servicio_id == "93154"
    assert resultado.empalmes_count > 0
    # Los terminales de ODF salen de las líneas `O-...: <conector>` y `ODF <nombre>: <conector>`.
    assert resultado.terminal_a is not None
    assert resultado.terminal_b is not None


def test_round_trip_el_parser_no_ve_tramos_porque_no_hay_db():
    """Consecuencia asumida de no fabricar la atenuación, fijada como test.

    `FIBRA_REGEX` exige que la línea termine en un número seguido de `dB`. Sin esa columna el
    parser descarta las líneas de tramo, así que un re-upload recupera empalmes y puntas pero no
    tramos ni atenuaciones. Es el precio elegido: la alternativa era inventar mediciones.
    """
    camino = _camino_de_la_fixture()

    resultado = parse_tracking(
        renderizar_tracking_txt(camino, generado_en=GENERADO_EN),
        nombre_archivo_tracking(camino.servicio_at62, camino.pelo_n_id),
    )

    assert resultado.tramos_count == 0


def test_las_lineas_de_empalme_matchean_el_regex_del_parser_legacy():
    camino = _camino_de_la_fixture()

    resultado = parse_tracking(
        renderizar_tracking_txt(camino, generado_en=GENERADO_EN),
        nombre_archivo_tracking(camino.servicio_at62, camino.pelo_n_id),
    )
    empalmes = resultado.get_empalmes()

    assert empalmes
    for entrada in empalmes:
        assert entrada.empalme_id
        assert entrada.empalme_descripcion
