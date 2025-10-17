# Nombre de archivo: test_web_repetitividad_flow.py
# Ubicación de archivo: tests/test_web_repetitividad_flow.py
# Descripción: Pruebas del endpoint web /api/flows/repetitividad

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[1] / "web"))

from modules.informes_repetitividad.service import ReportConfig, ReportResult  # type: ignore  # noqa: E402
from web_app import main as web_main  # type: ignore  # noqa: E402
from web_app.main import app  # type: ignore  # noqa: E402

from tests.test_web_admin import _connect_user_ok  # noqa: E402


def _excel_bytes() -> bytes:
    df = pd.DataFrame({"CLIENTE": ["A"], "SERVICIO": ["S1"], "FECHA": ["2024-07-01"], "ID_SERVICIO": ["1"]})
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    buffer.seek(0)
    return buffer.getvalue()


def _login_as_user(client: TestClient, monkeypatch, password: str = "userpass") -> str:
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok(password))
    client.post("/login", data={"username": "user", "password": password})
    html = client.get("/").text
    csrf = re.search(r"window.CSRF_TOKEN = \"([\w-]+)\";", html).group(1)
    return csrf


def test_flow_repetitividad_success_excel(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = TestClient(app)
    csrf = _login_as_user(client, monkeypatch)

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    config = ReportConfig(reports_dir=reports_dir, soffice_bin=None, maps_enabled=False)
    monkeypatch.setattr(web_main, "REPORT_SERVICE_CONFIG", config)

    docx_path = reports_dir / "reporte.docx"
    docx_path.write_bytes(b"DOCX")
    pdf_path = reports_dir / "reporte.pdf"
    pdf_path.write_bytes(b"PDF")
    map_path = reports_dir / "reporte_map.png"
    map_path.write_bytes(b"PNG")

    async def _fake_to_thread(func, *args, **kwargs):  # noqa: ANN001, ANN003
        return func(*args, **kwargs)

    def _fake_generar_informe(excel_bytes, periodo_titulo, export_pdf, config_arg, with_geo=False):  # noqa: ANN001, ANN002
        assert periodo_titulo == "07/2024"
        assert export_pdf is True
        assert config_arg.reports_dir == reports_dir
        assert with_geo is False
        return ReportResult(
            docx=docx_path,
            pdf=pdf_path,
            map_images=[map_path],
            total_filas=4,
            total_repetitivos=2,
            periodos_detectados=["2024-07"],
        )

    monkeypatch.setattr(web_main.asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(web_main, "generar_informe_desde_excel", _fake_generar_informe)

    files = {"file": ("casos.xlsx", io.BytesIO(_excel_bytes()), "application/vnd.openxmlformats-officedocument-spreadsheetml.sheet")}
    data = {"mes": 7, "anio": 2024, "csrf_token": csrf}
    response = client.post("/api/flows/repetitividad", data=data, files=files)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body.get("docx") == f"/reports/{docx_path.name}"
    assert body.get("pdf") == f"/reports/{pdf_path.name}"
    assert body.get("maps") == []
    assert body.get("map_images") == [f"/reports/{map_path.name}"]
    assert body.get("map_image") == f"/reports/{map_path.name}"
    assert body.get("map") is None
    assert body.get("with_geo") is False
    assert body.get("source") == "excel"
    assert body.get("stats") == {"filas": 4, "repetitivos": 2, "periodos": ["2024-07"]}


def test_flow_repetitividad_success_excel_with_geo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = TestClient(app)
    csrf = _login_as_user(client, monkeypatch)

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    config = ReportConfig(reports_dir=reports_dir, soffice_bin=None, maps_enabled=True)
    monkeypatch.setattr(web_main, "REPORT_SERVICE_CONFIG", config)

    docx_path = reports_dir / "reporte.docx"
    docx_path.write_bytes(b"DOCX")
    map_path_png = reports_dir / "mapa_servicio_a.png"
    map_path_png.write_bytes(b"PNG")

    async def _fake_to_thread(func, *args, **kwargs):  # noqa: ANN001, ANN003
        return func(*args, **kwargs)

    def _fake_generar_informe(excel_bytes, periodo_titulo, export_pdf, config_arg, with_geo=False):  # noqa: ANN001, ANN002
        assert with_geo is True
        return ReportResult(
            docx=docx_path,
            pdf=None,
            map_images=[map_path_png],
            total_filas=10,
            total_repetitivos=5,
            periodos_detectados=["2024-07"],
        )

    monkeypatch.setattr(web_main.asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(web_main, "generar_informe_desde_excel", _fake_generar_informe)

    files = {"file": ("casos.xlsx", io.BytesIO(_excel_bytes()), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    data = {"mes": 7, "anio": 2024, "csrf_token": csrf, "with_geo": "true", "include_pdf": "false"}
    response = client.post("/api/flows/repetitividad", data=data, files=files)

    assert response.status_code == 200
    body = response.json()
    assert body["with_geo"] is True
    assert body["source"] == "excel"
    assert body["maps"] == []
    assert body["map_images"] == [f"/reports/{map_path_png.name}"]
    assert body.get("map") is None
    assert body["map_image"] == f"/reports/{map_path_png.name}"
    assert body.get("pdf") is None


def test_flow_repetitividad_success_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = TestClient(app)
    csrf = _login_as_user(client, monkeypatch)

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    config = ReportConfig(reports_dir=reports_dir, soffice_bin=None, maps_enabled=True)
    monkeypatch.setattr(web_main, "REPORT_SERVICE_CONFIG", config)

    df_raw = pd.DataFrame({"numero_reclamo": [1], "cliente": ["Metrotel"], "servicio": ["FO"], "fecha": ["2024-07-01"]})

    async def _fake_to_thread(func, *args, **kwargs):  # noqa: ANN001, ANN003
        return func(*args, **kwargs)

    def _fake_generar_informe_dataframe(df, periodo_titulo, export_pdf, config_arg, with_geo=False, source_label="db"):  # noqa: ANN001, ANN002
        assert with_geo is True
        assert source_label == "db"
        assert len(df) == 1
        docx_path = reports_dir / "db.docx"
        docx_path.write_bytes(b"DOCX")
        return ReportResult(
            docx=docx_path,
            pdf=None,
            map_images=[],
            total_filas=1,
            total_repetitivos=0,
            periodos_detectados=["2024-07"],
        )

    monkeypatch.setattr(web_main.asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(web_main, "reclamos_from_db", lambda mes, anio: df_raw)  # noqa: ARG005
    monkeypatch.setattr(web_main, "db_to_processor_frame", lambda df: df)
    monkeypatch.setattr(web_main, "generar_informe_desde_dataframe", _fake_generar_informe_dataframe)

    data = {"mes": 7, "anio": 2024, "csrf_token": csrf, "use_db": "true", "with_geo": "true", "include_pdf": "false"}
    response = client.post("/api/flows/repetitividad", data=data)

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "db"
    assert body["with_geo"] is True
    assert body["maps"] == []
    assert body["map_images"] == []
    assert body["assets"] == []
    assert body["docx"].endswith("/db.docx")


def test_flow_repetitividad_db_sin_datos(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = TestClient(app)
    csrf = _login_as_user(client, monkeypatch)

    config = ReportConfig(reports_dir=tmp_path, soffice_bin=None, maps_enabled=True)
    monkeypatch.setattr(web_main, "REPORT_SERVICE_CONFIG", config)
    monkeypatch.setattr(web_main, "reclamos_from_db", lambda mes, anio: pd.DataFrame())  # noqa: ARG005
    monkeypatch.setattr(web_main, "db_to_processor_frame", lambda df: df)

    data = {"mes": 7, "anio": 2024, "csrf_token": csrf, "use_db": "true"}
    response = client.post("/api/flows/repetitividad", data=data)

    assert response.status_code == 404
    assert "No hay reclamos" in response.json()["error"]


def test_flow_repetitividad_invalid_csrf(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(app)
    _login_as_user(client, monkeypatch)

    files = {"file": ("casos.xlsx", io.BytesIO(_excel_bytes()), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    data = {"mes": 7, "anio": 2024, "csrf_token": "malo"}
    response = client.post("/api/flows/repetitividad", data=data, files=files)

    assert response.status_code == 403
    assert response.json()["error"] == "CSRF inválido"


def test_flow_repetitividad_validation_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = TestClient(app)
    csrf = _login_as_user(client, monkeypatch)

    config = ReportConfig(reports_dir=tmp_path, soffice_bin=None, maps_enabled=False)
    monkeypatch.setattr(web_main, "REPORT_SERVICE_CONFIG", config)

    async def _fake_to_thread(func, *args, **kwargs):  # noqa: ANN001, ANN003
        raise ValueError("Columnas faltantes")

    monkeypatch.setattr(web_main.asyncio, "to_thread", _fake_to_thread)

    files = {"file": ("casos.xlsx", io.BytesIO(_excel_bytes()), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    data = {"mes": 7, "anio": 2024, "csrf_token": csrf}

    resp = client.post("/api/flows/repetitividad", data=data, files=files)

    assert resp.status_code == 422
    assert "Columnas" in resp.json()["error"]


def test_flow_repetitividad_error_generico(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = TestClient(app)
    csrf = _login_as_user(client, monkeypatch)

    config = ReportConfig(reports_dir=tmp_path, soffice_bin=None, maps_enabled=False)
    monkeypatch.setattr(web_main, "REPORT_SERVICE_CONFIG", config)

    async def _fake_to_thread(func, *args, **kwargs):  # noqa: ANN001, ANN003
        raise RuntimeError("boom")

    monkeypatch.setattr(web_main.asyncio, "to_thread", _fake_to_thread)

    files = {"file": ("casos.xlsx", io.BytesIO(_excel_bytes()), "application/vnd.openxmlformats-officedocument-spreadsheetml.sheet")}
    data = {"mes": 7, "anio": 2024, "csrf_token": csrf}

    resp = client.post("/api/flows/repetitividad", data=data, files=files)

    assert resp.status_code == 500
    assert "No se pudo generar" in resp.json()["error"]


def test_flow_repetitividad_rechaza_archivo_no_xlsx(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(app)
    csrf = _login_as_user(client, monkeypatch)

    called = False

    async def _should_not_run(*args, **kwargs):  # noqa: ANN002, ANN003
        nonlocal called
        called = True
        raise AssertionError("no debería ejecutarse")

    monkeypatch.setattr(web_main.asyncio, "to_thread", _should_not_run)

    files = {"file": ("casos.xlsx", io.BytesIO(b"not-a-zip"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    data = {"mes": 7, "anio": 2024, "csrf_token": csrf}

    resp = client.post("/api/flows/repetitividad", data=data, files=files)

    assert resp.status_code == 400
    assert "no es un Excel" in resp.json()["error"]
    assert called is False
