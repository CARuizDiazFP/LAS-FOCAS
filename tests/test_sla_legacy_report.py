# Nombre de archivo: test_sla_legacy_report.py
# Ubicación de archivo: tests/test_sla_legacy_report.py
# Descripción: Pruebas del flujo legacy para generación del informe SLA

from __future__ import annotations

import io

import pandas as pd
import pytest

from core.sla import legacy_report as legacy_report_module
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
                "Número Primer Servicio": "SRV-BASE-01",
                "Número Línea": "SRV-REAL-01",
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
                "Número Primer Servicio": "SRV-BASE-01",
                "Número Línea": "SRV-REAL-01",
                "Número Reclamo": "R-001",
                "Horas Netas Reclamo": "1.5",
                "Horas Totales Cierre Problema Reclamo": "2.0",
                "Horas Netas Cierre Problema Reclamo": "1:15:00",
                "Tipo Solución Reclamo": "Corte",
                "Fecha Inicio Reclamo": "2025-06-10 08:00",
            },
            {
                "Número Primer Servicio": "SRV-BASE-01",
                "Número Línea": "SRV-REAL-01",
                "Número Reclamo": "R-002",
                "Horas Netas Reclamo": "0:15:00",
                "Horas Totales Cierre Problema Reclamo": "0.5",
                "Horas Netas Cierre Problema Reclamo": "0:25:00",
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


def test_load_reclamos_prefiere_horas_netas_cierre(reclamos_excel: bytes) -> None:
    dataset = legacy_report_module.load_reclamos_excel(reclamos_excel)
    columna, origen = legacy_report_module._columna_horas_reclamos(dataset)

    assert origen == "horas_netas_cierre"
    assert dataset.optional["horas_netas_cierre"] == columna
    valores = dataset.dataframe[columna].tolist()
    assert valores[0] == pytest.approx(1.25, rel=1e-3)  # 1h15m
    assert valores[1] == pytest.approx(25 / 60, rel=1e-3)


def test_load_reclamos_sin_horas_netas_cierre_error(reclamos_excel: bytes) -> None:
    df = pd.read_excel(io.BytesIO(reclamos_excel))
    df.drop(columns=["Horas Netas Cierre Problema Reclamo"], inplace=True)

    with pytest.raises(ValueError) as excinfo:
        legacy_report_module.load_reclamos_excel(_excel_bytes(df))
    assert "Horas Netas Cierre Problema Reclamo" in str(excinfo.value)


def test_load_servicios_prefiere_numero_linea(servicios_excel: bytes) -> None:
    dataset = legacy_report_module.load_servicios_excel(servicios_excel)

    assert dataset.columns["numero_linea"] == "Número Línea"
    assert dataset.optional["numero_primer_servicio"] == "Número Primer Servicio"
    assert dataset.dataframe.iloc[0]["Número Línea"] == "SRV-REAL-01"


def test_load_reclamos_prefiere_numero_linea(reclamos_excel: bytes) -> None:
    dataset = legacy_report_module.load_reclamos_excel(reclamos_excel)

    assert dataset.columns["numero_linea"] == "Número Línea"
    assert dataset.optional["numero_primer_servicio"] == "Número Primer Servicio"
    assert dataset.dataframe.iloc[0]["Número Línea"] == "SRV-REAL-01"


def test_matching_por_numero_linea_suma_horas(servicios_excel: bytes, reclamos_excel: bytes) -> None:
    servicios_dataset = legacy_report_module.load_servicios_excel(servicios_excel)
    reclamos_dataset = legacy_report_module.load_reclamos_excel(reclamos_excel)

    service_line = servicios_dataset.dataframe.iloc[0][servicios_dataset.columns["numero_linea"]]
    recl_linea_col = reclamos_dataset.columns["numero_linea"]
    horas_columna, _ = legacy_report_module._columna_horas_reclamos(reclamos_dataset)

    subset = reclamos_dataset.dataframe[reclamos_dataset.dataframe[recl_linea_col] == service_line]
    assert len(subset) == 2
    total = subset[horas_columna].sum()
    assert total == pytest.approx(1.25 + (25 / 60), rel=1e-3)


def test_normaliza_numero_linea_int_vs_str() -> None:
    servicios_df = pd.DataFrame(
        [
            {
                "Tipo Servicio": "EWS",
                "Número Línea": 83241,
                "Nombre Cliente": "Cirion",
                "Horas Reclamos Todos": "00:00:00",
                "SLA Entregado": 0.9968,
            }
        ]
    )
    reclamos_df = pd.DataFrame(
        [
            {
                "Número Línea": "83241",
                "Número Reclamo": "R-100",
                "Horas Netas Reclamo": "0.5",
                "Horas Netas Cierre Problema Reclamo": "00:45:00",
                "Tipo Solución Reclamo": "Fibra",
                "Fecha Inicio Reclamo": "2025-11-01",
            }
        ]
    )

    servicios_dataset = legacy_report_module.load_servicios_excel(_excel_bytes(servicios_df))
    reclamos_dataset = legacy_report_module.load_reclamos_excel(_excel_bytes(reclamos_df))

    srv_line = servicios_dataset.dataframe.iloc[0][servicios_dataset.columns["numero_linea"]]
    recl_line_col = reclamos_dataset.columns["numero_linea"]

    assert srv_line == "83241"
    assert reclamos_dataset.dataframe.iloc[0][recl_line_col] == "83241"

    horas_columna, _ = legacy_report_module._columna_horas_reclamos(reclamos_dataset)
    subset = reclamos_dataset.dataframe[reclamos_dataset.dataframe[recl_line_col] == srv_line]
    assert len(subset) == 1
    assert subset[horas_columna].iloc[0] == pytest.approx(0.75, rel=1e-3)


def test_subset_usa_numero_primer_servicio_para_sumar() -> None:
    servicios_df = pd.DataFrame(
        [
            {
                "Tipo Servicio": "EWS",
                "Número Línea": "40601",
                "Número Primer Servicio": "40601",
                "Nombre Cliente": "Cirion",
                "Horas Reclamos Todos": "00:00:00",
                "SLA Entregado": 0.9968,
            }
        ]
    )
    reclamos_df = pd.DataFrame(
        [
            {
                "Número Línea": "83241",
                "Número Primer Servicio": "40601",
                "Número Reclamo": "R-200",
                "Horas Netas Reclamo": "0.5",
                "Horas Netas Cierre Problema Reclamo": "01:00:00",
                "Tipo Solución Reclamo": "Fibra",
                "Fecha Inicio Reclamo": "2025-11-02",
            }
        ]
    )

    servicios_dataset = legacy_report_module.load_servicios_excel(_excel_bytes(servicios_df))
    reclamos_dataset = legacy_report_module.load_reclamos_excel(_excel_bytes(reclamos_df))

    subset, linea_display = legacy_report_module._subset_reclamos_por_servicio(
        servicios_dataset.dataframe.iloc[0],
        servicios_dataset,
        reclamos_dataset,
    )

    assert not subset.empty
    assert linea_display == "83241"
    horas_columna, _ = legacy_report_module._columna_horas_reclamos(reclamos_dataset)
    total = subset[horas_columna].sum()
    assert total == pytest.approx(1.0, rel=1e-3)


def test_horas_decimal_soporta_tipos_excel() -> None:
    assert legacy_report_module._horas_decimal("01:30:00") == pytest.approx(1.5, rel=1e-3)

    timestamp = pd.Timestamp("1900-01-02 06:50:26")
    horas = legacy_report_module._horas_decimal(timestamp)
    assert horas == pytest.approx(54.840555, rel=1e-3)

    hora_simple = pd.Timestamp("1900-01-01 03:48:06").to_pydatetime().time()
    assert legacy_report_module._horas_decimal(hora_simple) == pytest.approx(3.801666, rel=1e-3)

    delta = pd.Timedelta(hours=2, minutes=30)
    assert legacy_report_module._horas_decimal(delta) == pytest.approx(2.5, rel=1e-3)
