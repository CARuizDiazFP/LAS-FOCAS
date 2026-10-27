# Nombre de archivo: test_informes_repetitividad_service.py
# Ubicación de archivo: tests/test_informes_repetitividad_service.py
# Descripción: Pruebas del servicio local de informes de repetitividad

"""Pruebas del servicio local de informes de repetitividad."""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pytest

from modules.informes_repetitividad import processor
from modules.informes_repetitividad import service as repet_service
from modules.informes_repetitividad.schemas import ResultadoRepetitividad
from modules.informes_repetitividad.service import (
    ReportConfig,
    generar_informe_desde_excel,
)


def _build_excel_bytes(data: dict[str, list[object]]) -> bytes:
    df = pd.DataFrame(data)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    buffer.seek(0)
    return buffer.getvalue()


def test_generar_informe_docx(tmp_path: Path) -> None:
    excel_bytes = _build_excel_bytes(
        {
            "CLIENTE": ["A", "A", "B"],
            "SERVICIO": ["S1", "S1", "S2"],
            "FECHA": ["2024-07-01", "2024-07-15", "2024-07-20"],
            "ID_SERVICIO": [1, 2, 3],
        }
    )
    config = ReportConfig(reports_dir=tmp_path, maps_enabled=False)

    result = generar_informe_desde_excel(excel_bytes, "07/2024", False, config)

    assert result.docx.exists()
    assert result.pdf is None
    assert result.total_filas == 3
    assert result.total_repetitivos == 1
    assert result.periodos_detectados is not None
    assert "2024-07" in result.periodos_detectados


def test_generar_informe_pdf(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    excel_bytes = _build_excel_bytes(
        {
            "CLIENTE": ["A", "A"],
            "SERVICIO": ["S1", "S1"],
            "FECHA": ["2024-08-01", "2024-08-02"],
            "ID_SERVICIO": [1, 2],
        }
    )

    def _fake_pdf(docx_path: Path, *, contexto: str) -> tuple[Path, None]:
        pdf_path = Path(docx_path).with_suffix(".pdf")
        pdf_path.write_bytes(b"PDF")
        return pdf_path, None

    monkeypatch.setattr(repet_service, "intentar_pdf", _fake_pdf)

    config = ReportConfig(reports_dir=tmp_path, maps_enabled=False)

    result = generar_informe_desde_excel(excel_bytes, "08/2024", True, config)

    assert result.docx.exists()
    assert result.pdf is not None
    assert result.pdf.read_bytes() == b"PDF"
    assert result.pdf_error is None


def test_generar_informe_pdf_fallido_entrega_docx_y_motivo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    excel_bytes = _build_excel_bytes(
        {
            "CLIENTE": ["A", "A"],
            "SERVICIO": ["S1", "S1"],
            "FECHA": ["2024-08-01", "2024-08-02"],
            "ID_SERVICIO": [1, 2],
        }
    )
    monkeypatch.setattr(
        repet_service, "intentar_pdf", lambda docx_path, *, contexto: (None, "La conversión a PDF tardó demasiado")
    )

    result = generar_informe_desde_excel(excel_bytes, "08/2024", True, ReportConfig(reports_dir=tmp_path))

    assert result.docx.exists()
    assert result.pdf is None
    assert result.pdf_error == "La conversión a PDF tardó demasiado"


def test_generar_informe_sin_pdf_no_llama_a_office(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    excel_bytes = _build_excel_bytes(
        {"CLIENTE": ["A", "A"], "SERVICIO": ["S1", "S1"], "FECHA": ["2024-08-01", "2024-08-02"], "ID_SERVICIO": [1, 2]}
    )

    def _no_llamar(*args, **kwargs):
        raise AssertionError("no se pidió PDF")

    monkeypatch.setattr(repet_service, "intentar_pdf", _no_llamar)

    result = generar_informe_desde_excel(excel_bytes, "08/2024", False, ReportConfig(reports_dir=tmp_path))

    assert result.pdf is None
    assert result.pdf_error is None


def test_generar_informe_periodo_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    excel_bytes = _build_excel_bytes(
        {
            "CLIENTE": ["A", "B"],
            "SERVICIO": ["S1", "S1"],
            "FECHA": ["2023-01-01", "2023-02-01"],
            "ID_SERVICIO": [1, 2],
        }
    )

    monkeypatch.setattr(
        processor,
        "compute_repetitividad",
        lambda df: ResultadoRepetitividad(
            servicios=[],
            total_servicios=len(df),
            total_repetitivos=0,
            periodos=[],
            with_geo=False,
            source="excel",
        ),
    )

    config = ReportConfig(reports_dir=tmp_path, maps_enabled=False)

    result = generar_informe_desde_excel(excel_bytes, "Informe sin periodo", False, config)

    assert result.docx.exists()
    # Fallback debería generar archivo con 197001 cuando no se puede inferir período
    assert result.docx.name.startswith("repetitividad_1970")


def test_generar_informe_no_filtra_periodos(tmp_path: Path) -> None:
    excel_bytes = _build_excel_bytes(
        {
            "CLIENTE": ["A", "A", "B", "B"],
            "SERVICIO": ["S1", "S1", "S2", "S2"],
            "FECHA": ["2024-07-01", "2024-07-05", "2024-08-01", "2024-08-02"],
            "ID_SERVICIO": [1, 2, 3, 4],
        }
    )

    config = ReportConfig(reports_dir=tmp_path, maps_enabled=False)
    result = generar_informe_desde_excel(excel_bytes, "09/2024", False, config)

    assert result.total_repetitivos == 2
    assert set(result.periodos_detectados or []) == {"2024-07", "2024-08"}
