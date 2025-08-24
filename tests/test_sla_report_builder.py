# Nombre de archivo: test_sla_report_builder.py
# Ubicación de archivo: tests/test_sla_report_builder.py
# Descripción: Pruebas de generación de reportes DOCX para SLA

from pathlib import Path

import pandas as pd
from docx import Document

from modules.informes_sla import processor, runner, report
from modules.informes_sla.report import export_docx, maybe_export_pdf
from modules.informes_sla.schemas import (
    FilaDetalle,
    KPI,
    Params,
    ResultadoSLA,
)


def test_export_docx_crea_archivo(tmp_path):
    params = Params(periodo_mes=7, periodo_anio=2024)
    kpi = KPI(
        total=1,
        cumplidos=1,
        incumplidos=0,
        pct_cumplimiento=100.0,
        ttr_promedio_h=5.0,
        ttr_mediana_h=5.0,
    )
    detalle = [
        FilaDetalle(
            id="1",
            cliente="A",
            servicio="VIP",
            ttr_h=5.0,
            sla_objetivo_h=12.0,
            cumplido=True,
        )
    ]
    data = ResultadoSLA(
        kpi=kpi,
        detalle=detalle,
        breakdown_por_servicio={"VIP": kpi},
        sin_cierre=0,
    )
    path = export_docx(data, params, tmp_path)
    assert Path(path).exists()
    doc = Document(path)
    assert "Julio 2024" in doc.paragraphs[0].text


def test_run_informa_error_pdf(monkeypatch, tmp_path):
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

    dummy_docx = tmp_path / "out.docx"
    dummy_docx.write_text("doc")
    monkeypatch.setattr(report, "export_docx", lambda *a, **k: str(dummy_docx))

    def fake_pdf(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(report, "maybe_export_pdf", fake_pdf)

    res = runner.run("archivo.xlsx", 7, 2024, "/usr/bin/soffice")
    assert "error" in res
    assert "No se pudo convertir a PDF" in res["error"]


def test_maybe_export_pdf_sin_soffice(tmp_path):
    docx = tmp_path / "archivo.docx"
    docx.write_text("doc")
    assert maybe_export_pdf(str(docx), None) is None


def test_maybe_export_pdf_ok(monkeypatch, tmp_path):
    docx = tmp_path / "archivo.docx"
    docx.write_text("doc")
    pdf = tmp_path / "archivo.pdf"
    def fake_convert(d, s):
        pdf.write_text("pdf")
        return str(pdf)

    monkeypatch.setattr("modules.informes_sla.report.convert_to_pdf", fake_convert)
    assert maybe_export_pdf(str(docx), "soffice") == str(pdf)
