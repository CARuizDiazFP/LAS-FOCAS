# Nombre de archivo: test_sla_processor.py
# Ubicación de archivo: tests/test_sla_processor.py
# Descripción: Pruebas del procesamiento y KPIs del informe de SLA

import pandas as pd
import pytest

from pathlib import Path

from modules.informes_sla import processor, runner, report


def test_compute_kpis_sla():
    datos = [
        {
            "ID": "1",
            "CLIENTE": "A",
            "SERVICIO": "VIP",
            "FECHA_APERTURA": "2024-07-01 00:00",
            "FECHA_CIERRE": "2024-07-01 10:00",
        },
        {
            "ID": "2",
            "CLIENTE": "B",
            "SERVICIO": "VIP",
            "FECHA_APERTURA": "2024-07-02 00:00",
            "FECHA_CIERRE": "2024-07-03 18:00",
        },
        {
            "ID": "3",
            "CLIENTE": "C",
            "SERVICIO": "COMUN",
            "FECHA_APERTURA": "2024-07-05 00:00",
            "FECHA_CIERRE": "2024-07-06 00:00",
        },
        {
            "ID": "4",
            "CLIENTE": "D",
            "SERVICIO": "COMUN",
            "FECHA_APERTURA": "2024-07-05 00:00",
            "FECHA_CIERRE": "2024-07-07 00:00",
        },
        {
            "ID": "5",
            "CLIENTE": "E",
            "SERVICIO": "COMUN",
            "FECHA_APERTURA": "2024-07-10 00:00",
            "FECHA_CIERRE": None,
        },
        {
            "ID": "6",
            "CLIENTE": "F",
            "SERVICIO": "OTRO",
            "FECHA_APERTURA": "2024-07-15 00:00",
            "FECHA_CIERRE": "2024-07-15 12:00",
            "SLA_OBJETIVO_HORAS": 8,
        },
    ]
    df = pd.DataFrame(datos)
    df = processor.normalize(df)
    df = processor.filter_period(df, 7, 2024)
    df = processor.apply_sla_target(df)
    res = processor.compute_kpis(df)

    assert res.kpi.total == 5
    assert res.kpi.cumplidos == 2
    assert res.kpi.incumplidos == 3
    assert res.sin_cierre == 1
    assert res.breakdown_por_servicio["VIP"].cumplidos == 1

    detalle = {d.id: d for d in res.detalle}
    assert abs(detalle["1"].ttr_h - 10) < 0.1
    assert detalle["2"].sla_objetivo_h == 12.0
    assert detalle["6"].sla_objetivo_h == 8


def test_normalize_with_work_hours_flag():
    datos = [
        {
            "ID": "1",
            "CLIENTE": "A",
            "SERVICIO": "VIP",
            "FECHA_APERTURA": "2024-07-01 08:00",
            "FECHA_CIERRE": "2024-07-01 18:00",
        }
    ]
    df = pd.DataFrame(datos)
    df_laboral = processor.normalize(df.copy(), work_hours=True)
    assert df_laboral.loc[0, "TTR_h"] == pytest.approx(9)


def test_normalize_rechaza_texto_largo():
    datos = [{
        "ID": "1" * 101,
        "CLIENTE": "A",
        "SERVICIO": "VIP",
        "FECHA_APERTURA": "2024-07-01 00:00",
        "FECHA_CIERRE": "2024-07-01 10:00",
    }]
    df = pd.DataFrame(datos)
    with pytest.raises(ValueError):
        processor.normalize(df)


def test_normalize_rechaza_fecha_invalida():
    datos = [{
        "ID": "1",
        "CLIENTE": "A",
        "SERVICIO": "VIP",
        "FECHA_APERTURA": "no-fecha",
        "FECHA_CIERRE": "2024-07-01 10:00",
    }]
    df = pd.DataFrame(datos)
    with pytest.raises(ValueError):
        processor.normalize(df)


def test_apply_sla_target_rechaza_valores_invalidos():
    df = pd.DataFrame({
        "SERVICIO": ["VIP"],
        "SLA_OBJETIVO_HORAS": [2000],
    })
    with pytest.raises(ValueError):
        processor.apply_sla_target(df)


def test_business_hours_excluye_fines_de_semana():
    datos = [
        {
            "ID": "1",
            "CLIENTE": "A",
            "SERVICIO": "VIP",
            "FECHA_APERTURA": "2024-07-05 17:00",
            "FECHA_CIERRE": "2024-07-08 10:00",
        }
    ]
    df = pd.DataFrame(datos)
    df_laboral = processor.normalize(df, work_hours=True)
    assert df_laboral.loc[0, "TTR_h"] == pytest.approx(2)


def test_run_sin_soffice_bin_informa_error(monkeypatch, tmp_path):
    df = pd.DataFrame(
        {
            "ID": ["1"],
            "CLIENTE": ["A"],
            "SERVICIO": ["VIP"],
            "FECHA_APERTURA": ["2024-07-01 00:00"],
            "FECHA_CIERRE": ["2024-07-01 10:00"],
        }
    )
    monkeypatch.setattr(processor, "load_excel", lambda _: df)
    monkeypatch.setattr(runner, "BASE_REPORTS", tmp_path)

    dummy_docx = tmp_path / "out.docx"
    monkeypatch.setattr(report, "export_docx", lambda *a, **k: str(dummy_docx))

    res = runner.run("archivo.xlsx", 7, 2024, None)
    assert "error" in res
    assert "LibreOffice no configurado" in res["error"]


def test_run_aplica_permisos_archivos(monkeypatch, tmp_path):
    df = pd.DataFrame(
        {
            "ID": ["1"],
            "CLIENTE": ["A"],
            "SERVICIO": ["VIP"],
            "FECHA_APERTURA": ["2024-07-01 00:00"],
            "FECHA_CIERRE": ["2024-07-01 10:00"],
        }
    )
    monkeypatch.setattr(processor, "load_excel", lambda _: df)
    monkeypatch.setattr(runner, "BASE_REPORTS", tmp_path)

    def fake_convert(docx_path, _):
        pdf = Path(docx_path).with_suffix(".pdf")
        pdf.write_text("pdf")
        return str(pdf)

    monkeypatch.setattr(report, "convert_to_pdf", fake_convert)

    res = runner.run("archivo.xlsx", 7, 2024, "/usr/bin/soffice")
    docx_mode = Path(res["docx"]).stat().st_mode & 0o777
    pdf_mode = Path(res["pdf"]).stat().st_mode & 0o777
    assert docx_mode == 0o600
    assert pdf_mode == 0o600
