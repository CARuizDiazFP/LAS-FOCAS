# Nombre de archivo: test_libreoffice_export.py
# Ubicación de archivo: tests/test_libreoffice_export.py
# Descripción: Pruebas del helper de conversión a PDF con LibreOffice

from pathlib import Path
import subprocess
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

import pytest

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


def test_convert_to_pdf_levanta_file_not_found(monkeypatch, tmp_path):
    docx = tmp_path / "archivo.docx"
    docx.write_text("contenido")

    def fake_run(cmd, check, stdout, stderr):  # pragma: no cover - logging
        raise FileNotFoundError("soffice")

    monkeypatch.setattr("modules.common.libreoffice_export.subprocess.run", fake_run)
    with pytest.raises(FileNotFoundError):
        convert_to_pdf(str(docx), "soffice")


def test_convert_to_pdf_levanta_called_process_error(monkeypatch, tmp_path):
    docx = tmp_path / "archivo.docx"
    docx.write_text("contenido")

    def fake_run(cmd, check, stdout, stderr):  # pragma: no cover - logging
        raise subprocess.CalledProcessError(1, cmd, stderr=b"fallo")

    monkeypatch.setattr("modules.common.libreoffice_export.subprocess.run", fake_run)
    with pytest.raises(subprocess.CalledProcessError):
        convert_to_pdf(str(docx), "soffice")

def test_convert_to_pdf_falla_si_no_se_genero_pdf(monkeypatch, tmp_path):
    docx = tmp_path / "archivo.docx"
    docx.write_text("contenido")

    def fake_run(cmd, check, stdout, stderr):
        pass

    monkeypatch.setattr("modules.common.libreoffice_export.subprocess.run", fake_run)
    with pytest.raises(FileNotFoundError):
        convert_to_pdf(str(docx), "soffice")
