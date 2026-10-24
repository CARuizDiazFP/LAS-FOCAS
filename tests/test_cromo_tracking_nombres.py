# Nombre de archivo: test_cromo_tracking_nombres.py
# Ubicación de archivo: tests/test_cromo_tracking_nombres.py
# Descripción: Pruebas del nombre de archivo del tracking cuando un Servicio tiene varios pelos y del
# nombre por tramo (`{at62} CROMO T{n} pelo {n_id}.txt`) con su orden estable, y de los nombres de
# camino adicional (`A{n}`) y de posición de ODF contra el parser legacy de trackings

from __future__ import annotations

import pytest

from core.parsers.tracking_parser import ALIAS_REGEX, extract_alias_id, extract_servicio_id
from core.services.cromo.camino_optico_txt import (
    nombre_archivo_adicional,
    nombre_archivo_posicion,
    nombre_archivo_tracking,
    nombre_archivo_tramo,
)
from core.services.cromo.tracking_service import nombre_distinguible, ordenar_tramos


class TestNombreDistinguible:
    def test_con_un_solo_pelo_el_nombre_no_cambia(self):
        """Caso PON. El `.txt` mantiene exactamente el nombre de siempre, así que nada de lo que
        lo consume aguas abajo se entera del cambio."""
        assert nombre_distinguible("93154 CROMO.txt", 7554378, distinguir=False) == "93154 CROMO.txt"

    def test_con_varios_pelos_el_nombre_identifica_al_pelo(self):
        """Caso FO / SW bifilar: sin esto los N archivos del mismo Servicio se pisan en Descargas."""
        assert (
            nombre_distinguible("93154 CROMO.txt", 7554378, distinguir=True)
            == "93154 CROMO pelo 7554378.txt"
        )

    def test_dos_pelos_del_mismo_servicio_producen_nombres_distintos(self):
        """El punto del ticket: descargar 2 o más trackings sin que uno tape al otro."""
        base = nombre_archivo_tracking("93154", 7554378)
        uno = nombre_distinguible(base, 7554378, distinguir=True)
        otro = nombre_distinguible(nombre_archivo_tracking("93154", 6967355), 6967355, distinguir=True)
        assert uno != otro
        assert uno.endswith(".txt") and otro.endswith(".txt")

    def test_nombre_sin_extension_tambien_queda_distinguido(self):
        assert nombre_distinguible("tracking", 42, distinguir=True) == "tracking pelo 42"

    def test_no_repite_el_n_id_cuando_el_nombre_ya_lo_trae(self):
        """Sin at.62 plausible el nombre base ya identifica al pelo: sufijarlo sería redundante.

        Encontrado verificando contra Cromo real: los pelos del servicio 122347 caen a este
        fallback y el nombre salía como "tracking_cromo_pelo_6899054 pelo 6899054.txt".
        """
        base = nombre_archivo_tracking(None, 7554378)
        assert base == "tracking_cromo_pelo_7554378.txt"
        assert nombre_distinguible(base, 7554378, distinguir=True) == base


@pytest.mark.parametrize("pelos", [2, 3, 6])
def test_ningun_par_de_pelos_colisiona(pelos):
    """Invariante que hace funcionar la descarga de N archivos sueltos."""
    n_ids = [7554378 + i for i in range(pelos)]
    con_servicio = {
        nombre_distinguible(nombre_archivo_tracking("93154", n), n, distinguir=True) for n in n_ids
    }
    assert len(con_servicio) == pelos
    # Y también en el fallback sin at.62 plausible, que es el caso real del servicio 122347.
    sin_servicio = {
        nombre_distinguible(nombre_archivo_tracking(None, n), n, distinguir=True) for n in n_ids
    }
    assert len(sin_servicio) == pelos


class TestNombreArchivoTramo:
    def test_lleva_servicio_sufijo_cromo_numero_de_tramo_y_pelo(self):
        assert nombre_archivo_tramo("102452", 3, 7655082) == "102452 CROMO T3 pelo 7655082.txt"

    def test_conserva_el_sufijo_cromo_que_el_parser_de_alias_no_reconoce(self):
        """El regex de alias exige letra+dígitos: `CROMO` no matchea, y `T3` va separado por un
        espacio después de `CROMO`, así que el archivo no finge ser un tracking numerado a mano."""
        nombre = nombre_archivo_tramo("93154", 1, 7554378)
        assert nombre.startswith("93154 CROMO ")

    @pytest.mark.parametrize("at62", [None, "", "12", "ABC123"])
    def test_sin_numero_plausible_conserva_el_numero_de_tramo(self, at62):
        """Medido en dev (2026-10-17, servicio 102452): 4 de sus 6 tramos tenían un at.62 no
        plausible y salían todos como `tracking_cromo_pelo_<n_id>.txt`, sin decir qué tramo eran."""
        assert nombre_archivo_tramo(at62, 2, 7554378) == "tracking_cromo T2 pelo 7554378.txt"


def _tracking(pelo, cantidad):
    from datetime import datetime, timezone

    from core.services.cromo.tracking_service import TrackingGenerado

    return TrackingGenerado(
        pelo_n_id=pelo,
        nombre_archivo="x.txt",
        contenido="",
        desde_cache=False,
        generado_at=datetime(2026, 10, 16, tzinfo=timezone.utc),
        duracion_ms=None,
        pelos_camino=frozenset(range(pelo, pelo + cantidad)),
    )


def test_ordenar_tramos_por_pelos_descendente_y_despues_por_pelo():
    tramos = [_tracking(30, 5), _tracking(10, 20), _tracking(20, 20), _tracking(5, 1)]
    assert [t.pelo_n_id for t in ordenar_tramos(tramos)] == [10, 20, 30, 5]


def test_ordenar_tramos_es_estable_ante_el_orden_de_entrada():
    tramos = [_tracking(30, 5), _tracking(10, 20), _tracking(20, 20)]
    assert [t.pelo_n_id for t in ordenar_tramos(list(reversed(tramos)))] == [
        t.pelo_n_id for t in ordenar_tramos(tramos)
    ]


class TestNombreArchivoAdicional:
    def test_lleva_servicio_sufijo_cromo_numero_de_adicional_y_pelo(self):
        assert nombre_archivo_adicional("93150", 1, 7028862) == "93150 CROMO A1 pelo 7028862.txt"

    def test_no_pisa_al_tramo_del_mismo_pelo(self):
        """Un camino puede bajarse como tramo o como adicional según haya declaración: los dos
        nombres no pueden coincidir en Descargas."""
        assert nombre_archivo_adicional("93150", 1, 6799280) != nombre_archivo_tramo("93150", 1, 6799280)

    @pytest.mark.parametrize("numero", [None, "", "12", "ABC123"])
    def test_sin_numero_plausible_conserva_el_numero_de_adicional(self, numero):
        assert nombre_archivo_adicional(numero, 2, 7028862) == "tracking_cromo A2 pelo 7028862.txt"


class TestNombreArchivoPosicion:
    def test_lleva_servicio_sufijo_cromo_patchera_conector_y_pelo(self):
        assert (
            nombre_archivo_posicion("93150", "O-1252871-1", "1", 7028862)
            == "93150 CROMO O-1252871-1_1 pelo 7028862.txt"
        )

    def test_sanea_la_patchera_para_que_no_tenga_espacios_ni_separadores(self):
        """Medido en dev: 5 nombres de patchera tienen coma ("ODF Ruta 6 km 3,5 - 1000") y uno
        tiene `:`. Sin espacios adentro, ningún tramo del nombre arma un alias `<4 dígitos> <A1>`."""
        nombre = nombre_archivo_posicion("93150", "ODF Ruta 6 km 3,5 - 1000", "4", 7028862)
        assert nombre == "93150 CROMO ODF_Ruta_6_km_3_5_-_1000_4 pelo 7028862.txt"
        assert extract_alias_id(nombre) is None

    def test_sin_patchera_igual_identifica_al_conector(self):
        assert nombre_archivo_posicion("93150", None, "5", 7028862) == "93150 CROMO ODF_5 pelo 7028862.txt"

    @pytest.mark.parametrize("numero", [None, "", "12", "ABC123"])
    def test_sin_servicio_empieza_por_sin_servicio(self, numero):
        assert (
            nombre_archivo_posicion(numero, "O-1252871-1", "5", 7028862)
            == "sin_servicio CROMO O-1252871-1_5 pelo 7028862.txt"
        )

    def test_track_odf_sin_servicio_documenta_numero_parseado(self):
        """Limitación asumida (diseño, riesgo P1 de nombres): sin servicio el parser legacy toma el
        primer número de 4 dígitos o más, que es el de la patchera. Un `.txt` así NO es ingerible
        como tracking de un Servicio; este test lo deja escrito para que nadie lo descubra subiéndolo."""
        nombre = nombre_archivo_posicion(None, "O-1252871-1", "5", 7028862)
        assert extract_servicio_id(nombre) == "1252871"
        assert extract_alias_id(nombre) is None


# Los nombres nuevos se prueban contra el parser legacy (`core/parsers/tracking_parser.py`), que
# saca el servicio del NOMBRE del archivo: el primer número de 4 dígitos o más.
_NOMBRES_93150 = [
    nombre_archivo_tramo("93150", 1, 6799280),
    nombre_archivo_tramo("93150", 2, 6799281),
    nombre_archivo_adicional("93150", 1, 7028862),
    nombre_archivo_adicional("93150", 2, 7028863),
    nombre_archivo_posicion("93150", "O-1252871-1", "1", 7028862),
    nombre_archivo_posicion("93150", "O-1239922-1", "5", 7028862),
]


@pytest.mark.parametrize("nombre", _NOMBRES_93150)
def test_extract_servicio_id_de_nombres_nuevos(nombre):
    assert nombre.startswith("93150 CROMO ")
    assert extract_servicio_id(nombre) == "93150"


@pytest.mark.parametrize("nombre", _NOMBRES_93150)
def test_nombres_nuevos_no_matchean_alias_regex(nombre):
    """`CROMO` no es letra+dígitos y `T1`/`A1` van después de `CROMO`, no del número: el archivo no
    finge ser un tracking numerado a mano (`93154 C21.txt`)."""
    assert ALIAS_REGEX.search(nombre) is None
    assert extract_alias_id(nombre) is None


def test_nombre_no_usa_at62_del_pelo_4649():
    """Medido en dev (2026-10-21): el at.62 de los pelos viejos del 93150 es `4649`, un error de
    tipeo del 44649. Ningún nombre puede llevarlo: el parser legacy lo tomaría como el servicio."""
    for nombre in _NOMBRES_93150:
        assert "4649" not in nombre
        assert extract_servicio_id(nombre) != "4649"
