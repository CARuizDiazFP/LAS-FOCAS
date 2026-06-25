# Nombre de archivo: test_report_history.py
# Ubicación de archivo: tests/test_report_history.py
# Descripción: Pruebas del histórico persistente de reportes del panel web

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from starlette.datastructures import Headers, UploadFile

from core.services.report_history import InMemoryReportHistory
from modules.informes_repetitividad.service import ReportConfig, ReportResult
from web.app import main as web_main


def _fake_request(csrf: str = "csrf-test") -> SimpleNamespace:
    return SimpleNamespace(session={"username": "user", "role": "user", "csrf": csrf})


def _upload(name: str, content: bytes) -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(content), headers=Headers())


def _excel_bytes() -> bytes:
    df = pd.DataFrame({"CLIENTE": ["A"], "SERVICIO": ["S1"], "FECHA": ["2024-07-01"], "ID_SERVICIO": ["1"]})
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    buffer.seek(0)
    return buffer.getvalue()


def test_inmemory_report_history_filtra_y_cierra_registros() -> None:
    history = InMemoryReportHistory()
    report_id = history.start(
        report_type="sla",
        username="user",
        source="excel-legacy",
        period_month=6,
        period_year=2026,
        input_metadata={"archivo_count": 2},
    )

    history.finish_success(report_id, output_metadata={"outputs": {"docx": "/reports/a.docx"}})

    records = history.list_records(report_type="sla", status="success", month=6, year=2026)
    assert len(records) == 1
    assert records[0]["status"] == "success"
    assert records[0]["output_metadata"]["outputs"]["docx"] == "/reports/a.docx"


def test_reports_history_endpoint_devuelve_items_autenticado(monkeypatch: pytest.MonkeyPatch) -> None:
    history = InMemoryReportHistory()
    report_id = history.start(
        report_type="repetitividad",
        username="user",
        source="excel",
        period_month=7,
        period_year=2024,
        input_metadata={},
    )
    history.finish_error(report_id, error_code="HTTP_422", error_message="Archivo inválido")
    monkeypatch.setattr(web_main, "REPORT_HISTORY", history)

    response = asyncio.run(
        web_main.api_reports_history(
            _fake_request(),
            type="repetitividad",
            status="error",
        )
    )

    assert response.status_code == 200
    body = json_from_response(response)
    assert body["items"][0]["report_type"] == "repetitividad"
    assert body["items"][0]["error_code"] == "HTTP_422"


def test_sla_missing_files_registra_error(monkeypatch: pytest.MonkeyPatch) -> None:
    history = InMemoryReportHistory()
    monkeypatch.setattr(web_main, "REPORT_HISTORY", history)
    monkeypatch.setenv("TESTING", "true")
    csrf = "csrf-test"

    response = asyncio.run(
        web_main.generar_informe_sla_web(
            _fake_request(csrf),
            mes="6",
            anio="2026",
            pdf_enabled=False,
            use_db=False,
            csrf_token=csrf,
            files=[],
        )
    )

    assert response.status_code == 400
    records = history.list_records(report_type="sla", status="error")
    assert len(records) == 1
    assert records[0]["error_code"] == "HTTP_400"
    assert records[0]["period_month"] == 6


def test_repetitividad_success_registra_salidas(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    history = InMemoryReportHistory()
    monkeypatch.setattr(web_main, "REPORT_HISTORY", history)
    csrf = "csrf-test"

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    config = ReportConfig(reports_dir=reports_dir, soffice_bin=None, maps_enabled=False)
    monkeypatch.setattr(web_main, "REPORT_SERVICE_CONFIG", config)

    docx_path = reports_dir / "reporte.docx"
    docx_path.write_bytes(b"DOCX")

    async def _fake_to_thread(func, *args, **kwargs):  # noqa: ANN001, ANN003
        return func(*args, **kwargs)

    def _fake_generar_informe(excel_bytes, periodo_titulo, export_pdf, config_arg, with_geo=False):  # noqa: ANN001, ANN002
        return ReportResult(
            docx=docx_path,
            pdf=None,
            map_images=[],
            total_filas=4,
            total_repetitivos=2,
            periodos_detectados=["2024-07"],
        )

    monkeypatch.setattr(web_main.asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(web_main, "generar_informe_desde_excel", _fake_generar_informe)

    response = asyncio.run(
        web_main.flow_repetitividad(
            _fake_request(csrf),
            file=_upload("casos.xlsx", _excel_bytes()),
            mes=7,
            anio=2024,
            include_pdf=False,
            csrf_token=csrf,
            with_geo=False,
            use_db=False,
        )
    )

    assert response.status_code == 200
    records = history.list_records(report_type="repetitividad", status="success")
    assert len(records) == 1
    assert records[0]["output_metadata"]["outputs"]["docx"] == "/reports/reporte.docx"
    assert records[0]["output_metadata"]["stats"]["filas"] == 4


def json_from_response(response) -> dict:  # noqa: ANN001
    return json.loads(response.body.decode("utf-8"))
