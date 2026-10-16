# Nombre de archivo: test_cromo_tracking_nombres.py
# Ubicación de archivo: tests/test_cromo_tracking_nombres.py
# Descripción: Pruebas del nombre de archivo del tracking cuando un Servicio tiene varios pelos y del
# nombre por tramo (`{at62} CROMO T{n} pelo {n_id}.txt`) con su orden estable

from __future__ import annotations

import pytest

from core.services.cromo.camino_optico_txt import nombre_archivo_tracking, nombre_archivo_tramo
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
    def test_sin_at62_plausible_cae_al_nombre_por_pelo(self, at62):
        assert nombre_archivo_tramo(at62, 2, 7554378) == "tracking_cromo_pelo_7554378.txt"


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
