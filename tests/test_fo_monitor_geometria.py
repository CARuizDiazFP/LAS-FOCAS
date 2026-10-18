# Nombre de archivo: test_fo_monitor_geometria.py
# Ubicación de archivo: tests/test_fo_monitor_geometria.py
# Descripción: Tests de reproyección EPSG:22185→WGS84, simplificación y marca de calidad de cables FO Monitor

import pytest

from core.services.fo_monitor.geometria import calidad, geometria_desde_pts, simplificar

# Valores reales (cable F-PLR-RET → botella "Cra Alem 551 CF": lat -34.601209, lon -58.370162).
PTS_REALES = [5649509.355133, 6170404.585735, 5649509.0, 6170420.0, 5649600.0, 6170500.0]


def test_reproyecta_punto_real_a_menos_de_2_m_de_la_botella():
    geo = geometria_desde_pts(PTS_REALES)
    lon, lat = geo.coords[0]
    assert lat == pytest.approx(-34.601209, abs=2e-5)
    assert lon == pytest.approx(-58.370162, abs=2e-5)
    assert geo.min_lon <= lon <= geo.max_lon


def test_menos_de_dos_puntos_no_tiene_geometria():
    assert geometria_desde_pts([]) is None
    assert geometria_desde_pts([1.0, 2.0]) is None


def test_simplificar_quita_puntos_colineales_y_conserva_extremos():
    puntos = [(0.0, 0.0), (5.0, 0.2), (10.0, 0.0), (10.0, 10.0)]
    assert simplificar(puntos, tolerancia=1.0) == [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]


def test_calidad_tolera_trazado_invertido_y_marca_extremo_lejano():
    geo = geometria_desde_pts(PTS_REALES)
    inicio = (geo.coords[0][1], geo.coords[0][0])
    fin = (geo.coords[-1][1], geo.coords[-1][0])
    assert calidad(geo, fin, inicio) is None  # A/B invertidos respecto del dibujo
    assert calidad(geo, (-34.70, -58.50), None) == "extremo_lejano"
