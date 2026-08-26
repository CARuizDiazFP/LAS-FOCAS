# Nombre de archivo: test_servicios_consolidacion_service.py
# Ubicación de archivo: tests/test_servicios_consolidacion_service.py
# Descripción: Tests del cálculo de verificabilidad y de ID final/alias para la cadena de upgrades de Servicio

from core.services.servicios_consolidacion_service import (
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
