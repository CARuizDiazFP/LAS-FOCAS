# Nombre de archivo: test_cromo_semillas_seleccion.py
# Ubicación de archivo: tests/test_cromo_semillas_seleccion.py
# Descripción: Pruebas de la selección de semillas para el tracking multipelo — funciones puras

from __future__ import annotations

import pytest

from core.services.cromo.camino_optico_service import (
    PeloAjenoAlServicio,
    PeloSemilla,
    seleccionar_semillas,
    semillas_por_defecto,
)


def _semilla(pelo_n_id: int, *, conector: bool = False) -> PeloSemilla:
    return PeloSemilla(
        pelo_n_id=pelo_n_id,
        servicio_numero="122347",
        metodo="AT62",
        confianza=100,
        numero_pelo="1",
        color="azul",
        cable_n_id=51,
        cable_nombre="F-822-ARSA",
        tiene_conector_odf=conector,
        servicio_raw=None,
    )


class TestSemillasPorDefecto:
    def test_preselecciona_las_posiciones_de_odf_del_servicio(self):
        """El default son los pelos que ya son posición de patchera, y pueden ser varios."""
        semillas = [_semilla(1), _semilla(2, conector=True), _semilla(3, conector=True)]
        assert [s.pelo_n_id for s in semillas_por_defecto(semillas)] == [2, 3]

    def test_sin_conectores_cae_a_la_primera_del_ranking(self):
        """Caso real del servicio 122347: 6 pelos, ninguno con conector ODF ingerido."""
        semillas = [_semilla(7554378), _semilla(7412193), _semilla(6967355)]
        assert [s.pelo_n_id for s in semillas_por_defecto(semillas)] == [7554378]

    def test_sin_semillas_devuelve_lista_vacia(self):
        assert semillas_por_defecto([]) == []


class TestSeleccionarSemillas:
    def test_sin_pedido_explicito_usa_el_default(self):
        semillas = [_semilla(1), _semilla(2, conector=True)]
        assert [s.pelo_n_id for s in seleccionar_semillas(semillas, None)] == [2]

    def test_lista_vacia_se_trata_como_sin_pedido(self):
        semillas = [_semilla(1), _semilla(2, conector=True)]
        assert [s.pelo_n_id for s in seleccionar_semillas(semillas, [])] == [2]

    def test_devuelve_los_pelos_pedidos(self):
        semillas = [_semilla(1), _semilla(2), _semilla(3)]
        assert [s.pelo_n_id for s in seleccionar_semillas(semillas, [1, 3])] == [1, 3]

    def test_un_pelo_ajeno_al_servicio_es_rechazado(self):
        """Mismo guard que el endpoint de un solo pelo: no es un /path genérico de la red."""
        semillas = [_semilla(1), _semilla(2)]
        with pytest.raises(PeloAjenoAlServicio) as exc:
            seleccionar_semillas(semillas, [1, 999])
        assert "999" in str(exc.value)

    def test_los_duplicados_no_generan_dos_entradas(self):
        """Pedir dos veces el mismo pelo no puede producir dos .txt idénticos en el ZIP."""
        semillas = [_semilla(1), _semilla(2)]
        assert [s.pelo_n_id for s in seleccionar_semillas(semillas, [2, 2, 2])] == [2]

    def test_el_orden_de_salida_es_el_del_ranking_no_el_del_pedido(self):
        """Dos pedidos con los mismos ids tienen que producir exactamente el mismo archivo."""
        semillas = [_semilla(10), _semilla(20), _semilla(30)]
        assert [s.pelo_n_id for s in seleccionar_semillas(semillas, [30, 10])] == [10, 30]
        assert [s.pelo_n_id for s in seleccionar_semillas(semillas, [10, 30])] == [10, 30]
