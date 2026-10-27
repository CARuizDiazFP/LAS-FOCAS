# Nombre de archivo: test_web_sla_flow.py
# Ubicación de archivo: tests/test_web_sla_flow.py
# Descripción: Pruebas end-to-end del endpoint web /api/reports/sla

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient


from web.app import main as web_main  # type: ignore  # noqa: E402
from web.app.routers import informes as web_informes  # type: ignore  # noqa: E402
from web.app.main import app  # type: ignore  # noqa: E402

from tests.test_web_admin import _connect_user_ok  # noqa: E402


def _excel_bytes(df: pd.DataFrame) -> bytes:
    """Helper para crear archivos Excel en memoria."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:  # type: ignore[arg-type]
        df.to_excel(writer, index=False)
    buffer.seek(0)
    return buffer.getvalue()


def _servicios_excel_bytes() -> bytes:
    """Crea un Excel de servicios fuera de SLA."""
    df = pd.DataFrame(
        [
            {
                "Tipo Servicio": "Fibra",
                "Número Línea": "SRV-001",
                "Nombre Cliente": "Cliente Test 1",
                "Horas Reclamos Todos": "02:30:00",
                "SLA Entregado": 0.95,
            },
            {
                "Tipo Servicio": "Internet",
                "Número Línea": "SRV-002",
                "Nombre Cliente": "Cliente Test 2",
                "Horas Reclamos Todos": "01:15:00",
                "SLA Entregado": 0.98,
            },
        ]
    )
    return _excel_bytes(df)


def _reclamos_excel_bytes() -> bytes:
    """Crea un Excel de reclamos SLA."""
    df = pd.DataFrame(
        [
            {
                "Número Línea": "SRV-001",
                "Número Reclamo": "R-001",
                "Horas Netas Reclamo": "1.5",
                "Horas Totales Cierre Problema Reclamo": "2.0",
                "Horas Netas Cierre Problema Reclamo": "1:30:00",
                "Tipo Solución Reclamo": "Corte Masivo",
                "Fecha Inicio Reclamo": "2025-10-10 08:00",
            },
            {
                "Número Línea": "SRV-001",
                "Número Reclamo": "R-002",
                "Horas Netas Reclamo": "1:00:00",
                "Horas Totales Cierre Problema Reclamo": "1.5",
                "Horas Netas Cierre Problema Reclamo": "1:00:00",
                "Tipo Solución Reclamo": "Fibra Cortada",
                "Fecha Inicio Reclamo": "2025-10-15 14:30",
            },
            {
                "Número Línea": "SRV-002",
                "Número Reclamo": "R-003",
                "Horas Netas Reclamo": "0:45:00",
                "Horas Totales Cierre Problema Reclamo": "1.0",
                "Horas Netas Cierre Problema Reclamo": "0:45:00",
                "Tipo Solución Reclamo": "Configuración",
                "Fecha Inicio Reclamo": "2025-10-20 09:15",
            },
        ]
    )
    return _excel_bytes(df)


def _login_as_user(client: TestClient, monkeypatch, password: str = "userpass") -> str:
    """Helper para login y obtención del CSRF token."""
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok(password))
    res = client.post("/api/auth/login", json={"username": "user", "password": password})
    return res.json()["csrf"]


@pytest.fixture(autouse=True)
def _reportes_en_tmp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Aísla los informes: las constantes se calculan al importar, el env no alcanza."""
    from core.services import sla as sla_service_mod

    monkeypatch.setattr(sla_service_mod, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(web_informes, "REPORTS_DIR", tmp_path / "reports")


def test_sla_flow_success_with_two_excel_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Test del flujo completo: dos archivos Excel -> informe SLA generado."""
    client = TestClient(app)
    csrf = _login_as_user(client, monkeypatch)

    # Configurar directorios temporales
    reports_dir = tmp_path / "reports" / "sla" / "202510"
    reports_dir.mkdir(parents=True)
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()
    templates_dir = Path("Templates").resolve()

    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("UPLOADS_DIR", str(uploads_dir))
    monkeypatch.setenv("TEMPLATES_DIR", str(templates_dir))
    monkeypatch.setenv("TESTING", "true")

    # Preparar archivos
    servicios_bytes = _servicios_excel_bytes()
    reclamos_bytes = _reclamos_excel_bytes()

    files = [
        ("files", ("Servicios Fuera de SLA.xlsx", io.BytesIO(servicios_bytes), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ("files", ("Reclamos Sla.xlsx", io.BytesIO(reclamos_bytes), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
    ]

    data = {
        "mes": "10",
        "anio": "2025",
        "pdf_enabled": "false",
        "use_db": "false",
        "csrf_token": csrf,
    }

    response = client.post("/api/reports/sla", data=data, files=files)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "report_paths" in body
    assert "docx" in body["report_paths"]
    # Verificar que la ruta contiene el nombre del informe y la extensión correcta
    assert "InformeSLA_" in body["report_paths"]["docx"]
    assert body["report_paths"]["docx"].endswith(".docx")
    assert body.get("source") == "excel-legacy"


def test_sla_flow_error_missing_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test de error: no se adjuntan archivos."""
    client = TestClient(app)
    csrf = _login_as_user(client, monkeypatch)

    monkeypatch.setenv("TESTING", "true")

    data = {
        "mes": "10",
        "anio": "2025",
        "pdf_enabled": "false",
        "use_db": "false",
        "csrf_token": csrf,
    }

    response = client.post("/api/reports/sla", data=data)

    assert response.status_code == 400
    body = response.json()
    assert body["ok"] is False
    assert "Debés adjuntar dos archivos" in body["error"]


def test_sla_flow_error_only_one_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test de error: solo se adjunta un archivo."""
    client = TestClient(app)
    csrf = _login_as_user(client, monkeypatch)

    monkeypatch.setenv("TESTING", "true")

    servicios_bytes = _servicios_excel_bytes()

    files = [
        ("files", ("Servicios Fuera de SLA.xlsx", io.BytesIO(servicios_bytes), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
    ]

    data = {
        "mes": "10",
        "anio": "2025",
        "pdf_enabled": "false",
        "use_db": "false",
        "csrf_token": csrf,
    }

    response = client.post("/api/reports/sla", data=data, files=files)

    assert response.status_code == 400
    body = response.json()
    assert body["ok"] is False
    assert "Debés adjuntar dos archivos" in body["error"]


def test_sla_flow_error_invalid_extension(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test de error: archivos con extensión inválida."""
    client = TestClient(app)
    csrf = _login_as_user(client, monkeypatch)

    monkeypatch.setenv("TESTING", "true")

    files = [
        ("files", ("servicios.txt", io.BytesIO(b"texto plano"), "text/plain")),
        ("files", ("reclamos.csv", io.BytesIO(b"csv data"), "text/csv")),
    ]

    data = {
        "mes": "10",
        "anio": "2025",
        "pdf_enabled": "false",
        "use_db": "false",
        "csrf_token": csrf,
    }

    response = client.post("/api/reports/sla", data=data, files=files)

    assert response.status_code == 415  # Unsupported Media Type
    body = response.json()
    assert body["ok"] is False
    assert ".xlsx" in body["error"]  # El mensaje contiene "debe tener extensión .xlsx"


def test_sla_flow_error_invalid_period(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test de error: período inválido."""
    client = TestClient(app)
    csrf = _login_as_user(client, monkeypatch)

    monkeypatch.setenv("TESTING", "true")

    servicios_bytes = _servicios_excel_bytes()
    reclamos_bytes = _reclamos_excel_bytes()

    files = [
        ("files", ("Servicios Fuera de SLA.xlsx", io.BytesIO(servicios_bytes), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ("files", ("Reclamos Sla.xlsx", io.BytesIO(reclamos_bytes), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
    ]

    data = {
        "mes": "13",  # Mes inválido
        "anio": "2025",
        "pdf_enabled": "false",
        "use_db": "false",
        "csrf_token": csrf,
    }

    response = client.post("/api/reports/sla", data=data, files=files)

    assert response.status_code == 422
    body = response.json()
    assert body["ok"] is False
    assert "Mes y año fuera de rango permitido" in body["error"]


def test_sla_flow_use_db_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Test del flujo en modo DB (sin archivos Excel)."""
    client = TestClient(app)
    csrf = _login_as_user(client, monkeypatch)

    # Configurar directorios temporales
    reports_dir = tmp_path / "reports" / "sla" / "202510"
    reports_dir.mkdir(parents=True)
    templates_dir = Path("Templates").resolve()

    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("TEMPLATES_DIR", str(templates_dir))
    monkeypatch.setenv("TESTING", "true")

    # Mock de la función que genera desde DB
    def _fake_compute_from_db(mes: int, anio: int):  # noqa: ANN001
        # Simular retorno exitoso desde DB - retorna SLAComputation
        from core.sla import engine
        import pandas as pd
        from zoneinfo import ZoneInfo
        
        tz = ZoneInfo("America/Argentina/Buenos_Aires")
        
        # Crear datos mínimos para la computación con timezone
        reclamos_df = pd.DataFrame({
            "ticket_id": ["R-001"],
            "service_id": ["SRV-001"],
            "cliente": ["Cliente Test"],
            "tipo_servicio": ["Fibra"],
            "inicio": [pd.Timestamp("2025-10-10 08:00", tz=tz)],
            "fin": [pd.Timestamp("2025-10-10 10:00", tz=tz)],
            "duracion_h": [2.0],
        })
        
        return engine.calcular_sla(
            reclamos_df,
            mes=mes,
            anio=anio,
            servicios=None,
            merge_gap_minutes=15,
        )
    
    def _fake_generate_from_computation(computation, incluir_pdf: bool = False):  # noqa: ANN001
        # Simular generación del documento desde la computación
        from core.services.sla import SLAReportResult
        docx_path = reports_dir / f"InformeSLA_{computation.anio}{computation.mes:02d}_db_test.docx"
        docx_path.write_bytes(b"DOCX from DB")
        
        # Crear preview mínimo
        preview = {"periodos": [f"{computation.anio}-{computation.mes:02d}"]}
        
        return SLAReportResult(
            docx=docx_path,
            pdf=None,
            computation=computation,
            preview=preview,
        )

    monkeypatch.setattr("core.services.sla.compute_from_db", _fake_compute_from_db)
    monkeypatch.setattr("core.services.sla.generate_report_from_computation", _fake_generate_from_computation)

    data = {
        "mes": "10",
        "anio": "2025",
        "pdf_enabled": "false",
        "use_db": "true",  # Activar modo DB
        "csrf_token": csrf,
    }

    response = client.post("/api/reports/sla", data=data)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "report_paths" in body
    assert "docx" in body["report_paths"]
    assert "/reports/" in body["report_paths"]["docx"]  # Verificar que está en la ruta de reportes
    assert "InformeSLA_202510" in body["report_paths"]["docx"]
    assert body["report_paths"]["docx"].endswith(".docx")


def test_sla_flow_csrf_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test de validación CSRF."""
    client = TestClient(app)
    _login_as_user(client, monkeypatch)

    monkeypatch.setenv("TESTING", "false")  # Habilitar CSRF

    servicios_bytes = _servicios_excel_bytes()
    reclamos_bytes = _reclamos_excel_bytes()

    files = [
        ("files", ("Servicios Fuera de SLA.xlsx", io.BytesIO(servicios_bytes), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ("files", ("Reclamos Sla.xlsx", io.BytesIO(reclamos_bytes), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
    ]

    data = {
        "mes": "10",
        "anio": "2025",
        "pdf_enabled": "false",
        "use_db": "false",
        "csrf_token": "token_invalido",
    }

    response = client.post("/api/reports/sla", data=data, files=files)

    assert response.status_code == 403
    assert response.json() == {"error": "CSRF inválido"}


def _post_sla_dos_excel(client: TestClient, csrf: str, pdf_enabled: bool):
    files = [
        ("files", ("Servicios Fuera de SLA.xlsx", io.BytesIO(_servicios_excel_bytes()), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ("files", ("Reclamos Sla.xlsx", io.BytesIO(_reclamos_excel_bytes()), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
    ]
    data = {"mes": "10", "anio": "2025", "pdf_enabled": str(pdf_enabled).lower(), "use_db": "false", "csrf_token": csrf}
    return client.post("/api/reports/sla", data=data, files=files)


def test_sla_excel_pdf_via_office_queda_en_report_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_pdf(docx_path, *, contexto):  # noqa: ANN001
        pdf = Path(docx_path).with_suffix(".pdf")
        pdf.write_bytes(b"%PDF")
        return pdf, None

    monkeypatch.setattr("core.sla.legacy_report.intentar_pdf", _fake_pdf)
    client = TestClient(app)
    csrf = _login_as_user(client, monkeypatch)

    body = _post_sla_dos_excel(client, csrf, pdf_enabled=True).json()

    assert body["ok"] is True
    assert body["report_paths"]["pdf"].endswith(".pdf")
    assert "pdf_error" not in body


def test_sla_excel_pdf_fallido_entrega_docx_y_pdf_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.sla.legacy_report.intentar_pdf",
        lambda docx_path, *, contexto: (None, "El servicio de conversión a PDF no está disponible"),
    )
    client = TestClient(app)
    csrf = _login_as_user(client, monkeypatch)

    response = _post_sla_dos_excel(client, csrf, pdf_enabled=True)

    assert response.status_code == 200
    body = response.json()
    assert body["report_paths"]["docx"].endswith(".docx")
    assert "pdf" not in body["report_paths"]
    assert body["pdf_error"] == "El servicio de conversión a PDF no está disponible"


def test_flow_sla_db_expone_pdf_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from core.services.sla import SLAReportResult
    from core.sla import engine

    computation = engine.calcular_sla(
        pd.DataFrame(columns=["ticket_id", "service_id", "cliente", "tipo_servicio", "inicio", "fin", "duracion_h"]),
        mes=10,
        anio=2025,
        servicios=None,
        merge_gap_minutes=15,
    )
    docx = tmp_path / "sla_202510.docx"
    docx.write_bytes(b"DOCX")

    monkeypatch.setattr("core.services.sla.compute_from_db", lambda mes, anio: computation)
    monkeypatch.setattr(
        "core.services.sla.generate_report_from_computation",
        lambda computation, **kw: SLAReportResult(
            docx=docx, pdf=None, computation=computation, preview={}, pdf_error="La conversión a PDF tardó demasiado"
        ),
    )
    client = TestClient(app)
    csrf = _login_as_user(client, monkeypatch)

    response = client.post(
        "/api/flows/sla", data={"mes": "10", "anio": "2025", "include_pdf": "true", "use_db": "true", "csrf_token": csrf}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["pdf"] is None
    assert body["pdf_error"] == "La conversión a PDF tardó demasiado"
