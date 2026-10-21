# Nombre de archivo: test_web_sla_generar_ramas.py
# Ubicación de archivo: tests/test_web_sla_generar_ramas.py
# Descripción: Caracterización de las ramas de POST /api/reports/sla (validaciones, Excel/DB, PDF, errores, histórico, logs)

from __future__ import annotations

import io
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.services.report_history import InMemoryReportHistory
from tests.test_web_sla_flow import (  # noqa: F401  (fixture autouse reutilizada)
    _login_as_user,
    _reclamos_excel_bytes,
    _reportes_en_tmp,
    _servicios_excel_bytes,
    _excel_bytes,
)
from web.app.main import app  # type: ignore
from web.app.routers import informes as web_informes  # type: ignore

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture()
def historia(monkeypatch: pytest.MonkeyPatch) -> InMemoryReportHistory:
    h = InMemoryReportHistory()
    monkeypatch.setattr(web_informes, "REPORT_HISTORY", h)
    monkeypatch.setenv("TESTING", "true")
    return h


@pytest.fixture()
def cliente(monkeypatch: pytest.MonkeyPatch, historia):  # noqa: ANN001
    c = TestClient(app)
    csrf = _login_as_user(c, monkeypatch)
    monkeypatch.setenv("TESTING", "true")
    c.csrf = csrf  # type: ignore[attr-defined]
    return c


def _post(c: TestClient, files=None, **extra):  # noqa: ANN001
    data = {"mes": "10", "anio": "2025", "pdf_enabled": "false", "use_db": "false", "csrf_token": c.csrf}  # type: ignore[attr-defined]
    data.update(extra)
    data = {k: v for k, v in data.items() if v is not None}
    return c.post("/api/reports/sla", data=data, files=files or None)


def _f(nombre: str, contenido: bytes):
    return ("files", (nombre, io.BytesIO(contenido), XLSX))


def _error_registrado(h: InMemoryReportHistory, codigo: str, mensaje: str, source="excel-legacy") -> None:
    recs = h.list_records(report_type="sla", status="error")
    assert len(recs) == 1
    assert recs[0]["error_code"] == codigo
    assert recs[0]["error_message"] == mensaje
    assert recs[0]["output_metadata"] == {"source": source}


def test_periodo_no_numerico_422_sin_historia(cliente, historia) -> None:  # noqa: ANN001
    r = _post(cliente, mes="abc")
    assert r.status_code == 422
    assert r.json() == {"ok": False, "error": "Mes y año deben ser numéricos"}
    assert historia.list_records(report_type="sla") == []


def test_periodo_ausente_422(cliente) -> None:  # noqa: ANN001
    r = _post(cliente, mes=None, anio=None)
    assert r.status_code == 422
    assert r.json()["error"] == "Mes y año deben ser numéricos"


@pytest.mark.parametrize("mes,anio", [("0", "2025"), ("12", "1999"), ("1", "2101")])
def test_periodo_fuera_de_rango_422(cliente, mes, anio) -> None:  # noqa: ANN001
    r = _post(cliente, mes=mes, anio=anio)
    assert r.status_code == 422
    assert r.json()["error"] == "Mes y año fuera de rango permitido"


def test_periodo_alias_periodo_mes_anio(cliente, historia) -> None:  # noqa: ANN001
    r = _post(cliente, mes=None, anio=None, periodo_mes="3", periodo_anio="2026")
    assert r.status_code == 400
    rec = historia.list_records(report_type="sla")[0]
    assert (rec["period_month"], rec["period_year"]) == (3, 2026)


def test_mes_tiene_prioridad_sobre_alias(cliente, historia) -> None:  # noqa: ANN001
    _post(cliente, mes="4", anio="2024", periodo_mes="3", periodo_anio="2026")
    rec = historia.list_records(report_type="sla")[0]
    assert (rec["period_month"], rec["period_year"]) == (4, 2024)


def test_csrf_invalido_no_registra_historia(monkeypatch, cliente, historia) -> None:  # noqa: ANN001
    monkeypatch.setenv("TESTING", "false")
    r = _post(cliente, files=[_f("a.xlsx", b"x")], csrf_token="malo")
    assert r.status_code == 403
    assert historia.list_records(report_type="sla") == []


def test_historia_inicial_con_metadata_de_entrada(cliente, historia) -> None:  # noqa: ANN001
    _post(cliente, files=[_f("uno.xlsx", b"x")], pdf_enabled="true")
    rec = historia.list_records(report_type="sla")[0]
    assert rec["username"] == "user"
    assert rec["source"] == "excel-legacy"
    assert rec["input_metadata"] == {
        "archivo_count": 1,
        "archivos": ["uno.xlsx"],
        "pdf_enabled": True,
        "use_db": False,
    }
    _error_registrado(historia, "HTTP_400", "Debés adjuntar dos archivos: servicios y reclamos")


def test_extension_invalida_registra_415(cliente, historia) -> None:  # noqa: ANN001
    r = _post(cliente, files=[_f("servicios.txt", b"t"), _f("reclamos.xlsx", b"t")])
    assert r.status_code == 415
    assert r.json()["error"] == "servicios.txt debe tener extensión .xlsx"
    _error_registrado(historia, "HTTP_415", "servicios.txt debe tener extensión .xlsx")


def test_archivo_vacio_400(cliente, historia) -> None:  # noqa: ANN001
    r = _post(cliente, files=[_f("servicios.xlsx", b""), _f("reclamos.xlsx", _reclamos_excel_bytes())])
    assert r.status_code == 400
    assert r.json()["error"] == "servicios.xlsx está vacío"
    _error_registrado(historia, "HTTP_400", "servicios.xlsx está vacío")


def test_excel_no_identificable_422(cliente, historia) -> None:  # noqa: ANN001
    import pandas as pd

    raro = _excel_bytes(pd.DataFrame([{"Columna Rara": 1}]))
    r = _post(cliente, files=[_f("raro.xlsx", raro), _f("reclamos.xlsx", _reclamos_excel_bytes())])
    assert r.status_code == 422
    recs = historia.list_records(report_type="sla", status="error")
    assert recs[0]["error_code"] == "HTTP_422"
    assert recs[0]["error_message"] == r.json()["error"]


def test_excel_corrupto_422(cliente, historia) -> None:  # noqa: ANN001
    r = _post(cliente, files=[_f("roto.xlsx", b"no es excel"), _f("reclamos.xlsx", _reclamos_excel_bytes())])
    assert r.status_code == 422
    assert historia.list_records(report_type="sla", status="error")[0]["error_code"] == "HTTP_422"


def test_dos_servicios_422(cliente, historia) -> None:  # noqa: ANN001
    s = _servicios_excel_bytes()
    r = _post(cliente, files=[_f("s1.xlsx", s), _f("s2.xlsx", s)])
    assert r.status_code == 422
    assert r.json()["error"] == "Se recibió más de un Excel de servicios"
    _error_registrado(historia, "HTTP_422", "Se recibió más de un Excel de servicios")


def test_dos_reclamos_422(cliente, historia) -> None:  # noqa: ANN001
    rc = _reclamos_excel_bytes()
    r = _post(cliente, files=[_f("r1.xlsx", rc), _f("r2.xlsx", rc)])
    assert r.status_code == 422
    assert r.json()["error"] == "Se recibió más de un Excel de reclamos"
    _error_registrado(historia, "HTTP_422", "Se recibió más de un Excel de reclamos")


def _falso_resultado(tmp_path: Path, con_pdf: bool):
    from types import SimpleNamespace

    docx = tmp_path / "reports" / "sla" / "202510" / "InformeSLA_x.docx"
    docx.parent.mkdir(parents=True, exist_ok=True)
    docx.write_bytes(b"d")
    pdf = None
    if con_pdf:
        pdf = docx.with_suffix(".pdf")
        pdf.write_bytes(b"p")
    return SimpleNamespace(docx=docx, pdf=pdf)


def test_excel_exito_con_pdf_historia_y_logs(monkeypatch, cliente, historia, tmp_path, caplog) -> None:  # noqa: ANN001
    llamadas = {}

    def falso(s, r, *, mes, anio, incluir_pdf):  # noqa: ANN001
        llamadas.update(mes=mes, anio=anio, incluir_pdf=incluir_pdf, s=bool(s), r=bool(r))
        return _falso_resultado(tmp_path, True)

    monkeypatch.setattr(web_informes.sla_service, "generate_report_from_excel_pair", falso)
    with caplog.at_level(logging.DEBUG):
        r = _post(
            cliente,
            files=[_f("Servicios.xlsx", _servicios_excel_bytes()), _f("Reclamos.xlsx", _reclamos_excel_bytes())],
            pdf_enabled="true",
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["source"] == "excel-legacy"
    assert body["message"] == "Informe SLA generado correctamente"
    assert set(body["report_paths"]) == {"docx", "pdf"}
    assert body["report_paths"]["pdf"].endswith(".pdf")
    assert llamadas == {"mes": 10, "anio": 2025, "incluir_pdf": True, "s": True, "r": True}
    rec = historia.list_records(report_type="sla", status="success")[0]
    assert rec["output_metadata"] == {
        "source": "excel-legacy",
        "outputs": body["report_paths"],
        "archivo_count": 2,
    }
    msgs = [x.getMessage() for x in caplog.records]
    ordenados = [
        "action=sla_web_report stage=start user=user archivos=2",
        "action=sla_web_report stage=identify file=Servicios.xlsx tipo=servicios",
        "action=sla_web_report stage=identify file=Reclamos.xlsx tipo=reclamos",
        "action=sla_web_report stage=generate_legacy mes=10 anio=2025 pdf=True",
        "action=sla_web_report stage=legacy_ok",
        "action=sla_web_report stage=success user=user source=excel-legacy mes=10 anio=2025 pdf=True archivos=2",
    ]
    pos = -1
    for esperado in ordenados:
        idx = next(i for i, m in enumerate(msgs) if m.startswith(esperado) and i > pos)
        pos = idx


def test_excel_orden_invertido_identifica_por_contenido(monkeypatch, cliente, tmp_path) -> None:  # noqa: ANN001
    vistos = {}

    def falso(s, r, **kw):  # noqa: ANN001, ANN003
        vistos["s"], vistos["r"] = s, r
        return _falso_resultado(tmp_path, False)

    monkeypatch.setattr(web_informes.sla_service, "generate_report_from_excel_pair", falso)
    sb, rb = _servicios_excel_bytes(), _reclamos_excel_bytes()
    r = _post(cliente, files=[_f("r.xlsx", rb), _f("s.xlsx", sb)])
    assert r.status_code == 200
    assert vistos == {"s": sb, "r": rb}
    assert list(r.json()["report_paths"]) == ["docx"]


def test_excel_generador_value_error_422(monkeypatch, cliente, historia) -> None:  # noqa: ANN001
    def falso(*a, **k):  # noqa: ANN002, ANN003
        raise ValueError("datos inconsistentes")

    monkeypatch.setattr(web_informes.sla_service, "generate_report_from_excel_pair", falso)
    r = _post(cliente, files=[_f("s.xlsx", _servicios_excel_bytes()), _f("r.xlsx", _reclamos_excel_bytes())])
    assert r.status_code == 422
    assert r.json() == {"ok": False, "error": "datos inconsistentes"}
    _error_registrado(historia, "HTTP_422", "datos inconsistentes")


def test_excel_generador_error_inesperado_500(monkeypatch, cliente, historia) -> None:  # noqa: ANN001
    def falso(*a, **k):  # noqa: ANN002, ANN003
        raise RuntimeError("boom")

    monkeypatch.setattr(web_informes.sla_service, "generate_report_from_excel_pair", falso)
    r = _post(cliente, files=[_f("s.xlsx", _servicios_excel_bytes()), _f("r.xlsx", _reclamos_excel_bytes())])
    assert r.status_code == 500
    msg = "No se pudo generar el informe SLA: boom"
    assert r.json() == {"ok": False, "error": msg}
    _error_registrado(historia, "HTTP_500", msg)


def test_error_inesperado_sin_mensaje_usa_nombre_de_clase(monkeypatch, cliente, historia) -> None:  # noqa: ANN001
    def falso(*a, **k):  # noqa: ANN002, ANN003
        raise KeyError()

    monkeypatch.setattr(web_informes.sla_service, "generate_report_from_excel_pair", falso)
    r = _post(cliente, files=[_f("s.xlsx", _servicios_excel_bytes()), _f("r.xlsx", _reclamos_excel_bytes())])
    assert r.status_code == 500
    assert r.json()["error"] == "No se pudo generar el informe SLA: KeyError"


def test_db_ignora_archivos_y_registra_source_db(monkeypatch, cliente, historia, tmp_path) -> None:  # noqa: ANN001
    llamadas = []
    monkeypatch.setattr(
        web_informes.sla_service, "compute_from_db", lambda mes, anio: llamadas.append(("compute", mes, anio)) or "comp"
    )

    def falso(comp, incluir_pdf=False):  # noqa: ANN001
        llamadas.append(("gen", comp, incluir_pdf))
        return _falso_resultado(tmp_path, True)

    monkeypatch.setattr(web_informes.sla_service, "generate_report_from_computation", falso)
    r = _post(cliente, files=[_f("cualquiera.xlsx", b"x")], use_db="true", pdf_enabled="true")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "db"
    assert set(body["report_paths"]) == {"docx", "pdf"}
    assert llamadas == [("compute", 10, 2025), ("gen", "comp", True)]
    rec = historia.list_records(report_type="sla", status="success")[0]
    assert rec["source"] == "db"
    assert rec["input_metadata"]["archivo_count"] == 1
    assert rec["input_metadata"]["use_db"] is True
    assert rec["output_metadata"] == {"source": "db", "outputs": body["report_paths"], "archivo_count": 1}


def test_db_value_error_422_source_db(monkeypatch, cliente, historia) -> None:  # noqa: ANN001
    def falso(mes, anio):  # noqa: ANN001
        raise ValueError("sin datos")

    monkeypatch.setattr(web_informes.sla_service, "compute_from_db", falso)
    r = _post(cliente, use_db="true")
    assert r.status_code == 422
    _error_registrado(historia, "HTTP_422", "sin datos", source="db")


def test_db_error_inesperado_500_source_db(monkeypatch, cliente, historia) -> None:  # noqa: ANN001
    def falso(mes, anio):  # noqa: ANN001
        raise RuntimeError("db caída")

    monkeypatch.setattr(web_informes.sla_service, "compute_from_db", falso)
    r = _post(cliente, use_db="true")
    assert r.status_code == 500
    _error_registrado(historia, "HTTP_500", "No se pudo generar el informe SLA: db caída", source="db")


def test_logs_de_validacion_y_error(monkeypatch, cliente, caplog) -> None:  # noqa: ANN001
    with caplog.at_level(logging.DEBUG):
        _post(cliente, files=[_f("uno.xlsx", b"x")])
    msgs = [x.getMessage() for x in caplog.records]
    assert "action=sla_web_report stage=start user=user archivos=1" in msgs
    assert "action=sla_web_report stage=validation error=archivos_incorrectos count=1" in msgs

    def falso(mes, anio):  # noqa: ANN001
        raise ValueError("x")

    monkeypatch.setattr(web_informes.sla_service, "compute_from_db", falso)
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        _post(cliente, use_db="true")
    msgs = [x.getMessage() for x in caplog.records]
    assert "action=sla_web_report stage=validation user=user source=db mes=10 anio=2025 error=x" in msgs
