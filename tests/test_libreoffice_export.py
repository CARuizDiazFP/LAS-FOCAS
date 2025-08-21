# Nombre de archivo: test_libreoffice_export.py
# Ubicación de archivo: tests/test_libreoffice_export.py
# Descripción: Pruebas del helper de conversión a PDF con LibreOffice

from pathlib import Path

from modules.common.libreoffice_export import convert_to_pdf


def test_convert_to_pdf_crea_archivo(monkeypatch, tmp_path):
    docx = tmp_path / "archivo.docx"
    docx.write_text("contenido")
    pdf_esperado = tmp_path / "archivo.pdf"

    def fake_run(cmd, check, stdout, stderr):
        pdf_esperado.write_text("pdf")

    monkeypatch.setattr("modules.common.libreoffice_export.subprocess.run", fake_run)

    ruta_pdf = convert_to_pdf(str(docx), "soffice")
    assert Path(ruta_pdf) == pdf_esperado
    assert pdf_esperado.exists()
