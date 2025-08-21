# Nombre de archivo: test_repetitividad_flow_validations.py
# Ubicación de archivo: tests/test_repetitividad_flow_validations.py
# Descripción: Pruebas de validaciones del flujo de repetitividad

from types import SimpleNamespace

from bot_telegram.flows.repetitividad import validate_document


def test_validate_document_extension() -> None:
    """Rechaza archivos con extensión diferente a .xlsx."""
    doc = SimpleNamespace(file_name="datos.txt", file_size=100)
    valido, error = validate_document(doc)
    assert not valido
    assert "extensión .xlsx" in error


def test_validate_document_size() -> None:
    """Rechaza archivos mayores a 10MB."""
    doc = SimpleNamespace(file_name="datos.xlsx", file_size=11 * 1024 * 1024)
    valido, error = validate_document(doc)
    assert not valido
    assert "10MB" in error


def test_validate_document_ok() -> None:
    """Acepta archivos válidos."""
    doc = SimpleNamespace(file_name="datos.xlsx", file_size=1024)
    valido, error = validate_document(doc)
    assert valido
    assert error == ""
