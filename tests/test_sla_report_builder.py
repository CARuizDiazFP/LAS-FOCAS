# Nombre de archivo: test_sla_report_builder.py
# Ubicación de archivo: tests/test_sla_report_builder.py
# Descripción: Pruebas de generación de reportes DOCX para SLA

from pathlib import Path

from docx import Document

from modules.informes_sla.report import export_docx
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
