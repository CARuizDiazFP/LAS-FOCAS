# Nombre de archivo: test_web_repetitividad_flow.py
# Ubicación de archivo: tests/test_web_repetitividad_flow.py
# Descripción: Pruebas del endpoint web /api/flows/repetitividad

from __future__ import annotations

import io
import re
from pathlib import Path
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[1] / "web"))

from modules.informes_repetitividad.service import ReportResult  # type: ignore  # noqa: E402
from web_app import main as web_main  # type: ignore  # noqa: E402
from web_app.main import app  # type: ignore  # noqa: E402

from tests.test_web_admin import _connect_user_ok  # noqa: E402


def _login_as_user(client: TestClient, monkeypatch, password: str = "userpass") -> str:
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok(password))
    client.post("/login", data={"username": "user", "password": password})
    html = client.get("/").text
    csrf = re.search(r"window.CSRF_TOKEN = \"([\w-]+)\";", html).group(1)
    return csrf


def test_flow_repetitividad_success(monkeypatch, tmp_path):
    client = TestClient(app)
    csrf = _login_as_user(client, monkeypatch)

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    monkeypatch.setattr(web_main, "REPORTS_DIR", reports_dir)

    docx_path = reports_dir / "reporte.docx"
    docx_path.write_bytes(b"DOCX")
    pdf_path = reports_dir / "reporte.pdf"
    pdf_path.write_bytes(b"PDF")

    async def _fake_generate_report(file_path, mes, anio, output_dir, include_pdf=True):  # noqa: FBT002
        assert include_pdf is True
        assert file_path.exists()
        return ReportResult(docx=docx_path, pdf=pdf_path if include_pdf else None)

    monkeypatch.setattr(web_main, "generate_report", _fake_generate_report)

    files = {"file": ("casos.xlsx", io.BytesIO(b"excel"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    data = {"mes": 7, "anio": 2024, "csrf_token": csrf}
    response = client.post("/api/flows/repetitividad", data=data, files=files)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body.get("docx") == f"/reports/{docx_path.name}"
    assert body.get("pdf") == f"/reports/{pdf_path.name}"


def test_flow_repetitividad_invalid_csrf(monkeypatch):
    client = TestClient(app)
    _login_as_user(client, monkeypatch)

    files = {"file": ("casos.xlsx", io.BytesIO(b"excel"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    data = {"mes": 7, "anio": 2024, "csrf_token": "malo"}
    response = client.post("/api/flows/repetitividad", data=data, files=files)

    assert response.status_code == 403
    assert response.json()["error"] == "CSRF inválido"


def test_flow_repetitividad_http_status_error(monkeypatch, tmp_path):
    client = TestClient(app)
    csrf = _login_as_user(client, monkeypatch)

    monkeypatch.setattr(web_main, "REPORTS_DIR", tmp_path)

    request = httpx.Request("POST", "http://api/reports/repetitividad")
    response = httpx.Response(422, request=request, json={"detail": "Archivo inválido"})
    error = httpx.HTTPStatusError("Detail", request=request, response=response)

    async def _fake_generate_report(*args, **kwargs):  # noqa: ANN002, ANN003
        raise error

    monkeypatch.setattr(web_main, "generate_report", _fake_generate_report)

    files = {"file": ("casos.xlsx", io.BytesIO(b"excel"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    data = {"mes": 7, "anio": 2024, "csrf_token": csrf}

    resp = client.post("/api/flows/repetitividad", data=data, files=files)

    assert resp.status_code == 502
    assert "Archivo inválido" in resp.json()["error"]
