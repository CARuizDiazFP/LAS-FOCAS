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

    def falso(servicios_bytes, reclamos_bytes, *, usuario, incluir_pdf, reports_dir):
        llamado.update(servicios=servicios_bytes, reclamos=reclamos_bytes, usuario=usuario, pdf=incluir_pdf)
        xlsx = Path(reports_dir) / "sla_consumo" / "202610" / "a.xlsx"
        xlsx.parent.mkdir(parents=True, exist_ok=True)
        xlsx.write_bytes(b"x")
        docx = xlsx.with_suffix(".docx")
        docx.write_bytes(b"x")
        return InformeSlaConsumo(xlsx, docx, None, _INGESTA, {"reclamos": 12, "horas": 3.5})

    monkeypatch.setattr(web_main.sla_consumo_service, "generar_informe_sla_consumo", falso)
    monkeypatch.setenv("TESTING", "true")
    client = TestClient(app)
    csrf = _login_as_user(client, monkeypatch)
    resp = client.post("/api/reports/sla-consumo", data={"csrf_token": csrf, "pdf_enabled": "false"}, files=[
        ("files", ("servicios.xlsx", io.BytesIO(_servicios_excel_bytes()))),
        ("files", ("reclamos.xlsx", io.BytesIO(_reclamos_excel_bytes()))),
    ])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True and body["fecha_corte"] == "2026-10-01"
    assert body["reclamos_insertados"] == 10 and body["reclamos_actualizados"] == 2
    assert body["totales"] == {"reclamos": 12, "horas": 3.5}
    assert body["report_paths"]["xlsx"] == "/reports/sla_consumo/202610/a.xlsx"
    assert "pdf" not in body["report_paths"]
    assert llamado["servicios"] == _servicios_excel_bytes() and llamado["usuario"] == "user"


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


def test_orquestador_genera_xlsx_docx_sin_pdf(monkeypatch, tmp_path):
    reclamos = pd.DataFrame([_r("1", "L1", 13.14, GRUPO_FO, evento="E1"),
                             _r("2", "L2", 20.0, GRUPO_FO, evento="E1")], columns=RECLAMOS_COLS)
    servicios = pd.DataFrame([_s("L1", 99.7, 13.0), _s("L2", 99.9, 20.0)], columns=SERVICIOS_COLS)
    monkeypatch.setattr(orquestador, "parse_servicios", lambda _b: servicios)
    monkeypatch.setattr(orquestador, "parse_reclamos", lambda _b: reclamos)
    monkeypatch.setattr(orquestador, "ingerir", lambda *a, **k: _INGESTA)
    monkeypatch.setattr(orquestador, "cargar_ventana", lambda fecha, engine=None: (reclamos, servicios))
    monkeypatch.setenv("SOFFICE_BIN", "/no/existe")

    informe = orquestador.generar_informe_sla_consumo(b"s", b"r", usuario="user", incluir_pdf=False,
                                                      reports_dir=tmp_path)
    assert informe.xlsx.exists() and informe.docx.exists() and informe.pdf is None
    assert tmp_path in informe.xlsx.parents and informe.ingesta is _INGESTA
    assert informe.totales["reclamos"] == 2


def test_orquestador_reclamos_vacios_falla(monkeypatch, tmp_path):
    monkeypatch.setattr(orquestador, "parse_servicios", lambda _b: pd.DataFrame(columns=SERVICIOS_COLS))
    monkeypatch.setattr(orquestador, "parse_reclamos", lambda _b: pd.DataFrame(columns=RECLAMOS_COLS))
    with pytest.raises(ValueError):
        orquestador.generar_informe_sla_consumo(b"s", b"r", usuario=None, incluir_pdf=False, reports_dir=tmp_path)


def test_totales_json_safe():
    assert orquestador._json_safe({"a": np.int64(3), "b": np.float64(1.5), "c": dt.date(2026, 1, 2)}) == \
        {"a": 3, "b": 1.5, "c": "2026-01-02"}
