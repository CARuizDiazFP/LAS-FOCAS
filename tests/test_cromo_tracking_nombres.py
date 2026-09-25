# Nombre de archivo: test_cromo_tracking_nombres.py
# Ubicación de archivo: tests/test_cromo_tracking_nombres.py
# Descripción: Pruebas del nombre de archivo del tracking cuando un Servicio tiene varios pelos

from __future__ import annotations

import pytest

from core.services.cromo.camino_optico_txt import nombre_archivo_tracking
from core.services.cromo.tracking_service import nombre_distinguible


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
