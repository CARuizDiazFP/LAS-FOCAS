# Nombre de archivo: test_sla_legacy_report.py
# Ubicación de archivo: tests/test_sla_legacy_report.py
# Descripción: Pruebas del flujo legacy para generación del informe SLA

from __future__ import annotations

import io

import pandas as pd
import pytest

from core.services import sla as sla_service


def _excel_bytes(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:  # type: ignore[arg-type]
        df.to_excel(writer, index=False)
    buffer.seek(0)
    return buffer.read()


@pytest.fixture
def servicios_excel() -> bytes:
    data = pd.DataFrame(
        [
            {
                "Tipo Servicio": "Fibra",
                "Número Línea": "SRV-01",
                "Nombre Cliente": "Cliente Demo",
                "Horas Reclamos Todos": "01:30:00",
                "SLA Entregado": 0.985,
            }
        ]
    )
    return _excel_bytes(data)


@pytest.fixture
def reclamos_excel() -> bytes:
    data = pd.DataFrame(
        [
            {
                "Número Línea": "SRV-01",
                "Número Reclamo": "R-001",
                "Horas Netas Reclamo": "1.5",
                "Tipo Solución Reclamo": "Corte",
                "Fecha Inicio Reclamo": "2025-06-10 08:00",
            },
            {
                "Número Línea": "SRV-01",
                "Número Reclamo": "R-002",
                "Horas Netas Reclamo": "0:15:00",
                "Tipo Solución Reclamo": "Fibra",
                "Fecha Inicio Reclamo": "2025-06-10 10:00",
            },
        ]
    )
    return _excel_bytes(data)


def test_identify_excel_kind(servicios_excel: bytes, reclamos_excel: bytes) -> None:
    assert sla_service.identify_excel_kind(servicios_excel) == "servicios"
    assert sla_service.identify_excel_kind(reclamos_excel) == "reclamos"


def test_generate_report_from_excel_pair(tmp_path, servicios_excel: bytes, reclamos_excel: bytes) -> None:
    cfg = sla_service.SLAReportConfig(
        reports_dir=tmp_path,
        uploads_dir=tmp_path,
        soffice_bin=None,
    )

    resultado = sla_service.generate_report_from_excel_pair(
        servicios_excel,
        reclamos_excel,
        mes=6,
        anio=2025,
        incluir_pdf=False,
        config=cfg,
    )

    assert resultado.docx.exists()
    assert resultado.pdf is None


def test_generate_report_from_excel_pair_missing_column(tmp_path, servicios_excel: bytes, reclamos_excel: bytes) -> None:
    servicios_df = pd.read_excel(io.BytesIO(servicios_excel))
    servicios_df.drop(columns=["SLA Entregado"], inplace=True)
    servicios_bytes = _excel_bytes(servicios_df)

    with pytest.raises(ValueError) as excinfo:
        sla_service.generate_report_from_excel_pair(
            servicios_bytes,
            reclamos_excel,
            mes=6,
            anio=2025,
            incluir_pdf=False,
            config=sla_service.SLAReportConfig(
                reports_dir=tmp_path,
                uploads_dir=tmp_path,
                soffice_bin=None,
            ),
        )
    assert "Faltan columnas en Excel de servicios" in str(excinfo.value)
