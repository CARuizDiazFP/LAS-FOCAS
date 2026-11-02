# Nombre de archivo: test_api_reports_sla.py
# Ubicación de archivo: tests/test_api_reports_sla.py
# Descripción: Contrato de POST /reports/sla y GET /reports/sla/preview de la API sobre el motor único de SLA (P25)

from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.app.main import create_app
from core.sla import informe as inf
from core.sla_consumo.parser import RECLAMOS_COLS, SERVICIOS_COLS
from core.utils.excel_duraciones import TZ_AR

API_HEADERS = {"Authorization": "Bearer test-api-key"}


@pytest.fixture
def base_falsa(monkeypatch):
    """Un servicio con dos reclamos de septiembre (6 h de columna P) en la "base"."""
    servicios = pd.DataFrame([{**{c: None for c in SERVICIOS_COLS}, "numero_linea": "100", "nombre_cliente": "CLI",
                               "tipo_servicio": "RPV", "sla_prometido": 99.7}], columns=SERVICIOS_COLS)
    inicio = pd.Timestamp("2026-09-10 10:00", tz=TZ_AR)
    reclamos = pd.DataFrame([
        {**{c: None for c in RECLAMOS_COLS}, "numero_reclamo": n, "numero_linea": "100", "nombre_cliente": "CLI",
         "horas_netas_cierre": h, "tipo_solucion": "PE-E-FO Corte de FO", "fecha_inicio": inicio + pd.Timedelta(days=i),
         "fecha_cierre": inicio + pd.Timedelta(days=i, hours=5)}
        for i, (n, h) in enumerate([("1", 4.0), ("2", 2.0)])], columns=RECLAMOS_COLS)
    monkeypatch.setattr(inf, "cargar_ventana_ultima_foto", lambda corte: (reclamos, servicios))


def test_preview_desde_la_base(base_falsa):
    r = TestClient(create_app()).get("/reports/sla/preview", params={"periodo_mes": 9, "periodo_anio": 2026},
                                     headers=API_HEADERS)
    assert r.status_code == 200, r.text
    assert r.headers["X-Source"] == "db"
    cuerpo = r.json()
    assert cuerpo["periodo"] == "2026-09"
    assert cuerpo["resumen"]["downtime_total_h"] == pytest.approx(6.0)
    assert cuerpo["servicios"][0]["disponibilidad_pct"] == pytest.approx((1 - 6 / 8760) * 100, abs=1e-4)
    assert len(cuerpo["anexo"]) == 2


def test_post_sla_desde_la_base_con_headers(base_falsa, monkeypatch, tmp_path):
    from core.services import sla as sla_service

    monkeypatch.setattr(sla_service, "REPORTS_DIR", tmp_path)
    r = TestClient(create_app()).post("/reports/sla", data={"periodo_mes": "9", "periodo_anio": "2026"},
                                      headers=API_HEADERS)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert set(cuerpo) == {"docx", "pdf", "pdf_error", "preview"}
    assert cuerpo["docx"].endswith(".docx") and cuerpo["pdf"] is None
    assert r.headers["X-Source"] == "db" and r.headers["X-Servicios"] == "1"
    assert float(r.headers["X-Disponibilidad"]) == pytest.approx((1 - 6 / 8760) * 100, abs=1e-3)


def test_post_sla_periodo_invalido_es_422():
    r = TestClient(create_app()).post("/reports/sla", data={"periodo_mes": "13", "periodo_anio": "2026"},
                                      headers=API_HEADERS)
    assert r.status_code == 422
