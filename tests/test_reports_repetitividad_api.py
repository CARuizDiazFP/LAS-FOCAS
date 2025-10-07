# Nombre de archivo: test_reports_repetitividad_api.py
# Ubicación de archivo: tests/test_reports_repetitividad_api.py
# Descripción: Pruebas del endpoint /reports/repetitividad

import io
import zipfile
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from api.app.main import create_app


def _sample_excel() -> bytes:
    df = pd.DataFrame(
        [
            {"CLIENTE": "A", "SERVICIO": "Servicio 1", "FECHA": "2024-07-01", "ID_SERVICIO": "1"},
            {"CLIENTE": "A", "SERVICIO": "Servicio 1", "FECHA": "2024-07-05", "ID_SERVICIO": "2"},
            {"CLIENTE": "B", "SERVICIO": "Servicio 2", "FECHA": "2024-07-07", "ID_SERVICIO": "3"},
        ]
    )
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False)
    buffer.seek(0)
    return buffer.getvalue()


def test_generar_informe_repetitividad_devuelve_docx(tmp_path, monkeypatch):
    plantilla_path = Path("Templates/Plantilla_Informe_Repetitividad.docx").resolve()
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    monkeypatch.setenv("REP_TEMPLATE_PATH", str(plantilla_path))
    monkeypatch.setenv("SOFFICE_BIN", "")

    from modules.informes_repetitividad import config as repet_config
    from modules.informes_repetitividad import report as report_module
    from api_app.routes import reports as api_reports

    repet_config.REPORTS_DIR = Path(tmp_path)
    repet_config.REP_TEMPLATE_PATH = Path(plantilla_path)
    repet_config.SOFFICE_BIN = None
    report_module.REP_TEMPLATE_PATH = Path(plantilla_path)
    api_reports.REPORTS_DIR = Path(tmp_path)
    api_reports.SOFFICE_BIN = None

    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    files = {"file": ("casos.xlsx", _sample_excel(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    data = {"periodo_mes": 7, "periodo_anio": 2024}

    response = client.post("/reports/repetitividad", data=data, files=files)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert response.headers["content-disposition"].endswith('.docx"')
    assert response.headers["x-pdf-requested"] == "false"
    assert response.headers["x-pdf-generated"] == "false"
    assert len(list(tmp_path.glob("*.docx"))) == 1


def test_generar_informe_repetitividad_zip_con_pdf(tmp_path, monkeypatch):
    plantilla_path = Path("Templates/Plantilla_Informe_Repetitividad.docx").resolve()
    fake_soffice = tmp_path / "soffice"
    fake_soffice.write_text("#!/bin/sh\nexit 0\n")
    fake_soffice.chmod(0o755)
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    monkeypatch.setenv("REP_TEMPLATE_PATH", str(plantilla_path))
    monkeypatch.setenv("SOFFICE_BIN", str(fake_soffice))

    from modules.informes_repetitividad import config as repet_config
    from modules.informes_repetitividad import report as report_module
    from api_app.routes import reports as api_reports

    repet_config.REPORTS_DIR = Path(tmp_path)
    repet_config.REP_TEMPLATE_PATH = Path(plantilla_path)
    repet_config.SOFFICE_BIN = str(fake_soffice)
    report_module.REP_TEMPLATE_PATH = Path(plantilla_path)
    api_reports.REPORTS_DIR = Path(tmp_path)
    api_reports.SOFFICE_BIN = str(fake_soffice)

    def fake_convert_to_pdf(docx_path: str, soffice_bin: str) -> str:
        pdf_path = Path(docx_path).with_suffix(".pdf")
        pdf_path.write_bytes(b"%PDF-1.4\n%mock")
        return str(pdf_path)

    monkeypatch.setattr(
        "modules.common.libreoffice_export.convert_to_pdf",
        fake_convert_to_pdf,
    )
    monkeypatch.setattr(
        "modules.informes_repetitividad.report.convert_to_pdf",
        fake_convert_to_pdf,
    )

    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    files = {"file": ("casos.xlsx", _sample_excel(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    data = {"periodo_mes": 7, "periodo_anio": 2024, "incluir_pdf": "true"}

    response = client.post("/reports/repetitividad", data=data, files=files)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment; filename=")
    assert disposition.endswith(".zip")
    assert response.headers["x-pdf-requested"] == "true"
    assert response.headers["x-pdf-generated"] == "true"

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        filenames = {Path(name).name for name in archive.namelist()}

    assert "repetitividad_202407.docx" in filenames
    assert "repetitividad_202407.pdf" in filenames


def test_reporte_repetitividad_rechaza_extension_incorrecta(tmp_path, monkeypatch):
    plantilla_path = Path("Templates/Plantilla_Informe_Repetitividad.docx").resolve()
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    monkeypatch.setenv("REP_TEMPLATE_PATH", str(plantilla_path))

    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    files = {"file": ("casos.csv", b"1,2,3", "text/csv")}
    data = {"periodo_mes": 7, "periodo_anio": 2024}

    response = client.post("/reports/repetitividad", data=data, files=files)

    assert response.status_code == 400
    assert response.json()["detail"] == "El archivo debe tener extensión .xlsx"


def test_reporte_repetitividad_error_en_procesamiento(tmp_path, monkeypatch):
    plantilla_path = Path("Templates/Plantilla_Informe_Repetitividad.docx").resolve()
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    monkeypatch.setenv("REP_TEMPLATE_PATH", str(plantilla_path))
    monkeypatch.setenv("SOFFICE_BIN", "")

    from modules.informes_repetitividad import config as repet_config
    from api_app.routes import reports as api_reports

    repet_config.REPORTS_DIR = Path(tmp_path)
    repet_config.REP_TEMPLATE_PATH = Path(plantilla_path)
    repet_config.SOFFICE_BIN = None
    api_reports.REPORTS_DIR = Path(tmp_path)
    api_reports.SOFFICE_BIN = None

    def _fail_load_excel(path):  # noqa: ANN001
        raise ValueError("Faltan columnas requeridas")

    monkeypatch.setattr(api_reports.processor, "load_excel", _fail_load_excel)

    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    files = {"file": ("casos.xlsx", _sample_excel(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    data = {"periodo_mes": 7, "periodo_anio": 2024}

    response = client.post("/reports/repetitividad", data=data, files=files)

    assert response.status_code == 500
    assert "Faltan columnas" in response.text
