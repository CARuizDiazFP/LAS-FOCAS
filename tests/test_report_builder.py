# Nombre de archivo: test_report_builder.py
# Ubicación de archivo: tests/test_report_builder.py
# Descripción: Pruebas de generación de reportes DOCX

from pathlib import Path

from docx import Document

from modules.informes_repetitividad.report import export_docx, maybe_export_pdf
from modules.informes_repetitividad.schemas import ItemSalida, Params, ResultadoRepetitividad


def test_export_docx_crea_archivo(tmp_path):
    params = Params(periodo_mes=7, periodo_anio=2024)
    data = ResultadoRepetitividad(
        items=[ItemSalida(servicio="S1", casos=2, detalles=["1", "2"])],
        total_servicios=1,
        total_repetitivos=1,
    )
    path = export_docx(data, params, tmp_path)
    assert Path(path).exists()
    doc = Document(path)
    assert "Julio 2024" in doc.paragraphs[0].text


def test_maybe_export_pdf_sin_soffice(tmp_path):
    docx = tmp_path / "archivo.docx"
    docx.write_text("doc")
    assert maybe_export_pdf(str(docx), None) is None


def test_maybe_export_pdf_ok(monkeypatch, tmp_path):
    docx = tmp_path / "archivo.docx"
    docx.write_text("doc")
    pdf = tmp_path / "archivo.pdf"
    monkeypatch.setattr(
        "modules.informes_repetitividad.report.convert_to_pdf",
        lambda d, s: str(pdf),
    )
    assert maybe_export_pdf(str(docx), "soffice") == str(pdf)
