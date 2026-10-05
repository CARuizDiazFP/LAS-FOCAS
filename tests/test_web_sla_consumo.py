# Nombre de archivo: test_web_sla_consumo.py
# Ubicación de archivo: tests/test_web_sla_consumo.py
# Descripción: Orquestador y endpoint web /api/reports/sla-consumo (sin DB: persistencia mockeada)

from __future__ import annotations

import datetime as dt
import io
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from core.services import sla_consumo as orquestador
from core.services.sla_consumo import InformeSlaConsumo
from core.sla_consumo.clasificador import GRUPO_FO
from core.sla_consumo.persistencia import ResultadoIngesta
from tests.test_sla_consumo_engine import _r, _s
from tests.test_web_sla_flow import _login_as_user, _reclamos_excel_bytes, _servicios_excel_bytes
from web.app import main as web_main  # type: ignore
from web.app.main import app  # type: ignore
from core.sla_consumo.parser import RECLAMOS_COLS, SERVICIOS_COLS

pytestmark = pytest.mark.filterwarnings("ignore:datetime.datetime.utcnow:DeprecationWarning")  # openpyxl

_INGESTA = ResultadoIngesta(7, dt.date(2026, 10, 1), False, 10, 2, 5)


def test_sla_consumo_ok(monkeypatch, tmp_path):
    llamado = {}

    def falso(servicios_bytes, reclamos_bytes, *, usuario, incluir_pdf, reports_dir, report_history_id=None):
        llamado.update(servicios=servicios_bytes, reclamos=reclamos_bytes, usuario=usuario, pdf=incluir_pdf)
        xlsx = Path(reports_dir) / "sla_consumo" / "202610" / "a.xlsx"
        xlsx.parent.mkdir(parents=True, exist_ok=True)
        xlsx.write_bytes(b"x")
        ejecutivo = xlsx.with_name("a_ejecutivo.docx")
        exhaustivo = xlsx.with_name("a_exhaustivo.docx")
        pdf = xlsx.with_name("a_ejecutivo.pdf")
        for archivo in (ejecutivo, exhaustivo, pdf):
            archivo.write_bytes(b"x")
        return InformeSlaConsumo(xlsx, ejecutivo, exhaustivo, pdf, None, _INGESTA, {"reclamos": 12, "horas": 3.5})

    monkeypatch.setattr(web_main.sla_consumo_service, "generar_informe_sla_consumo", falso)
    monkeypatch.setenv("TESTING", "true")
    client = TestClient(app)
    csrf = _login_as_user(client, monkeypatch)
    servicios_bytes, reclamos_bytes = _servicios_excel_bytes(), _reclamos_excel_bytes()  # una sola generación
    resp = client.post("/api/reports/sla-consumo", data={"csrf_token": csrf, "pdf_enabled": "false"}, files=[
        ("files", ("servicios.xlsx", io.BytesIO(servicios_bytes))),
        ("files", ("reclamos.xlsx", io.BytesIO(reclamos_bytes)))
    ])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True and body["fecha_corte"] == "2026-10-01"
    assert body["reclamos_insertados"] == 10 and body["reclamos_actualizados"] == 2
    assert body["totales"] == {"reclamos": 12, "horas": 3.5}
    assert body["report_paths"]["xlsx"] == "/reports/sla_consumo/202610/a.xlsx"
    assert body["report_paths"]["docx_ejecutivo"] == "/reports/sla_consumo/202610/a_ejecutivo.docx"
    assert body["report_paths"]["docx_exhaustivo"] == "/reports/sla_consumo/202610/a_exhaustivo.docx"
    assert body["report_paths"]["pdf_ejecutivo"] == "/reports/sla_consumo/202610/a_ejecutivo.pdf"
    assert "pdf_exhaustivo" not in body["report_paths"] and "docx" not in body["report_paths"]
    assert llamado["servicios"] == servicios_bytes and llamado["reclamos"] == reclamos_bytes and llamado["usuario"] == "user"


def test_sla_consumo_pasa_history_id_y_reporta_pdf_omitido(monkeypatch, tmp_path):
    llamado = {}

    class _Historial:
        def start(self, **_kw):
            return 321

        def finish_success(self, *_a, **_kw):
            pass

        def finish_error(self, *_a, **_kw):
            pass

    def falso(servicios_bytes, reclamos_bytes, *, usuario, incluir_pdf, reports_dir, report_history_id=None):
        llamado["history"] = report_history_id
        xlsx = Path(reports_dir) / "sla_consumo" / "202610" / "b.xlsx"
        xlsx.parent.mkdir(parents=True, exist_ok=True)
        xlsx.write_bytes(b"x")
        ejecutivo = xlsx.with_name("b_ejecutivo.docx")
        exhaustivo = xlsx.with_name("b_exhaustivo.docx")
        ejecutivo.write_bytes(b"x")
        exhaustivo.write_bytes(b"x")
        return InformeSlaConsumo(xlsx, ejecutivo, exhaustivo, None, None, _INGESTA, {},
                                 pdf_omitido="LibreOffice no configurado")

    monkeypatch.setattr(web_main, "REPORT_HISTORY", _Historial())
    monkeypatch.setattr(web_main.sla_consumo_service, "generar_informe_sla_consumo", falso)
    monkeypatch.setenv("TESTING", "true")
    client = TestClient(app)
    csrf = _login_as_user(client, monkeypatch)
    resp = client.post("/api/reports/sla-consumo", data={"csrf_token": csrf, "pdf_enabled": "true"}, files=[
        ("files", ("servicios.xlsx", io.BytesIO(_servicios_excel_bytes()))),
        ("files", ("reclamos.xlsx", io.BytesIO(_reclamos_excel_bytes()))),
    ])
    assert resp.status_code == 200, resp.text
    assert llamado["history"] == 321
    assert resp.json()["pdf_omitido"] == "LibreOffice no configurado"
    assert resp.json()["reclamos_sin_cambios"] == 0


def test_sla_consumo_error_inesperado_sin_mensaje_usa_nombre_de_clase(monkeypatch):
    def falso(*_a, **_kw):
        raise RuntimeError()

    monkeypatch.setattr(web_main.sla_consumo_service, "generar_informe_sla_consumo", falso)
    monkeypatch.setenv("TESTING", "true")
    client = TestClient(app)
    csrf = _login_as_user(client, monkeypatch)
    resp = client.post("/api/reports/sla-consumo", data={"csrf_token": csrf}, files=[
        ("files", ("servicios.xlsx", io.BytesIO(_servicios_excel_bytes()))),
        ("files", ("reclamos.xlsx", io.BytesIO(_reclamos_excel_bytes()))),
    ])
    assert resp.status_code == 500
    assert "RuntimeError" in resp.json()["error"]


def test_sla_consumo_un_solo_archivo_400(monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    client = TestClient(app)
    csrf = _login_as_user(client, monkeypatch)
    resp = client.post("/api/reports/sla-consumo", data={"csrf_token": csrf},
                       files=[("files", ("s.xlsx", io.BytesIO(_servicios_excel_bytes())))])
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


def test_sla_consumo_sin_sesion_rechazado():
    resp = TestClient(app).post("/api/reports/sla-consumo")
    assert resp.status_code in (401, 403)


def _preparar(monkeypatch, reclamos, servicios):
    monkeypatch.setattr(orquestador, "parse_servicios", lambda _b: servicios)
    monkeypatch.setattr(orquestador, "parse_reclamos", lambda _b: reclamos)
    monkeypatch.setattr(orquestador, "ingerir", lambda *a, **k: _INGESTA)
    monkeypatch.setattr(orquestador, "cargar_ventana", lambda fecha, engine=None: (reclamos, servicios))


def _datos():
    reclamos = pd.DataFrame([_r("1", "L1", 13.14, GRUPO_FO, evento="E1"),
                             _r("2", "L2", 20.0, GRUPO_FO, evento="E1", dia=2)], columns=RECLAMOS_COLS)
    servicios = pd.DataFrame([_s("L1", 99.7), _s("L2", 99.9)], columns=SERVICIOS_COLS)
    return reclamos, servicios


def test_orquestador_genera_xlsx_y_dos_docx_sin_pdf(monkeypatch, tmp_path):
    _preparar(monkeypatch, *_datos())
    monkeypatch.setenv("SOFFICE_BIN", "/no/existe")
    informe = orquestador.generar_informe_sla_consumo(b"s", b"r", usuario="user", incluir_pdf=False,
                                                      reports_dir=tmp_path)
    base = informe.xlsx.stem
    assert base.startswith("SLA_consumido_2026-10-01_")
    assert informe.xlsx.suffix == ".xlsx" and informe.xlsx.exists()
    assert informe.docx_ejecutivo.name == f"{base}_ejecutivo.docx" and informe.docx_ejecutivo.exists()
    assert informe.docx_exhaustivo.name == f"{base}_exhaustivo.docx" and informe.docx_exhaustivo.exists()
    assert informe.pdf_ejecutivo is None and informe.pdf_exhaustivo is None and informe.pdf_omitido is None
    assert tmp_path / "sla_consumo" / "202610" == informe.xlsx.parent and informe.ingesta is _INGESTA
    assert informe.totales["reclamos"] == 2 and informe.totales["servicios_universo"] == 2


def test_orquestador_pdf_convierte_solo_el_ejecutivo(monkeypatch, tmp_path):
    _preparar(monkeypatch, *_datos())
    monkeypatch.setenv("SOFFICE_BIN", "/fake/soffice")
    convertidos = []

    def falso(docx, soffice):
        convertidos.append(Path(docx).name)
        pdf = Path(docx).with_suffix(".pdf")
        pdf.write_bytes(b"%PDF")
        return str(pdf)

    import modules.common.libreoffice_export as lo
    monkeypatch.setattr(lo, "convert_to_pdf", falso)
    informe = orquestador.generar_informe_sla_consumo(b"s", b"r", usuario="u", incluir_pdf=True, reports_dir=tmp_path)
    assert convertidos == [informe.docx_ejecutivo.name]
    assert informe.pdf_ejecutivo.exists() and informe.pdf_exhaustivo is None
    assert "exhaustivo" in informe.pdf_omitido and "no se genera en línea" in informe.pdf_omitido


def test_orquestador_falla_conversion_ejecutiva_no_rompe(monkeypatch, tmp_path):
    _preparar(monkeypatch, *_datos())
    monkeypatch.setenv("SOFFICE_BIN", "/fake/soffice")

    def falso(docx, soffice):
        raise FileNotFoundError("No se generó el PDF en /app/secreto/x.pdf")

    import modules.common.libreoffice_export as lo
    monkeypatch.setattr(lo, "convert_to_pdf", falso)
    informe = orquestador.generar_informe_sla_consumo(b"s", b"r", usuario="u", incluir_pdf=True, reports_dir=tmp_path)
    assert informe.pdf_ejecutivo is None and informe.pdf_exhaustivo is None
    assert informe.xlsx.exists() and informe.docx_exhaustivo.exists()
    assert informe.pdf_omitido.startswith("No se pudo generar el PDF ejecutivo")
    assert "/app" not in informe.pdf_omitido and "FileNotFoundError" not in informe.pdf_omitido
    assert "secreto" not in informe.pdf_omitido


def test_orquestador_pdf_sin_soffice_informa_omision_y_pasa_history_id(monkeypatch, tmp_path):
    reclamos = pd.DataFrame([_r("1", "L1", 13.14, GRUPO_FO)], columns=RECLAMOS_COLS)
    servicios = pd.DataFrame([_s("L1", 99.7)], columns=SERVICIOS_COLS)
    recibido = {}

    def falso_ingerir(*_a, **kw):
        recibido.update(kw)
        return _INGESTA

    monkeypatch.setattr(orquestador, "parse_servicios", lambda _b: servicios)
    monkeypatch.setattr(orquestador, "parse_reclamos", lambda _b: reclamos)
    monkeypatch.setattr(orquestador, "ingerir", falso_ingerir)
    monkeypatch.setattr(orquestador, "cargar_ventana", lambda fecha, engine=None: (reclamos, servicios))
    monkeypatch.delenv("SOFFICE_BIN", raising=False)
    informe = orquestador.generar_informe_sla_consumo(b"s", b"r", usuario="u", incluir_pdf=True,
                                                      reports_dir=tmp_path, report_history_id=55)
    assert informe.pdf_ejecutivo is None and "LibreOffice" in informe.pdf_omitido
    assert recibido["report_history_id"] == 55


def test_orquestador_reclamos_vacios_falla(monkeypatch, tmp_path):
    monkeypatch.setattr(orquestador, "parse_servicios", lambda _b: pd.DataFrame(columns=SERVICIOS_COLS))
    monkeypatch.setattr(orquestador, "parse_reclamos", lambda _b: pd.DataFrame(columns=RECLAMOS_COLS))
    with pytest.raises(ValueError):
        orquestador.generar_informe_sla_consumo(b"s", b"r", usuario=None, incluir_pdf=False, reports_dir=tmp_path)


def test_totales_json_safe():
    assert orquestador._json_safe({"a": np.int64(3), "b": np.float64(1.5), "c": dt.date(2026, 1, 2)}) == \
        {"a": 3, "b": 1.5, "c": "2026-01-02"}
