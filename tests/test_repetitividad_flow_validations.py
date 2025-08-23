# Nombre de archivo: test_repetitividad_flow_validations.py
# Ubicación de archivo: tests/test_repetitividad_flow_validations.py
# Descripción: Pruebas de validaciones del flujo de repetitividad

from types import SimpleNamespace
from pathlib import Path

from bot_telegram.flows.repetitividad import (
    cleanup_files,
    validate_document,
    validate_period,
)


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


def test_validate_document_rejects_path(tmp_path: Path) -> None:
    """Rechaza nombres de archivo con rutas embebidas."""
    doc = SimpleNamespace(file_name="../datos.xlsx", file_size=1024)
    valido, error = validate_document(doc)
    assert not valido
    assert "nombre del archivo" in error


def test_validate_period_format() -> None:
    """Valida que el formato sea mm/aaaa."""
    valido, error, _, _ = validate_period("2024-07")
    assert not valido
    assert "Formato" in error


def test_validate_period_range() -> None:
    """Rechaza períodos fuera de rango."""
    valido, error, _, _ = validate_period("13/1999")
    assert not valido
    assert "rango" in error


def test_validate_period_ok() -> None:
    """Acepta períodos válidos."""
    valido, error, mes, anio = validate_period("07/2024")
    assert valido
    assert error == ""
    assert (mes, anio) == (7, 2024)


def test_cleanup_files(tmp_path: Path) -> None:
    """Elimina archivos temporales sin errores."""
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    for f in (f1, f2):
        f.write_text("data")
        assert f.exists()
    cleanup_files(str(f1), str(f2))
    assert not f1.exists() and not f2.exists()
