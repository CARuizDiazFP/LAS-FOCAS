# Nombre de archivo: test_sla_legacy_report.py
# Ubicación de archivo: tests/test_sla_legacy_report.py
# Descripción: Render del informe SLA (plantilla heredada) sobre el motor único: horas P, SLA calculado y fechas reales

from __future__ import annotations

import datetime as dt

import pytest
from docx import Document

from core.services import sla as sla_service
from tests import soporte_sla


def _generar(tmp_path, servicios: bytes, reclamos: bytes):
    cfg = sla_service.SLAReportConfig(reports_dir=tmp_path, uploads_dir=tmp_path)
    return sla_service.generate_report_from_excel_pair(servicios, reclamos, mes=10, anio=2025, config=cfg)


def _filas(tabla) -> list[list[str]]:
    return [[c.text for c in fila.cells] for fila in tabla.rows]


def test_identify_excel_kind() -> None:
    assert sla_service.identify_excel_kind(soporte_sla.servicios_excel()) == "servicios"
    assert sla_service.identify_excel_kind(soporte_sla.reclamos_excel()) == "reclamos"


def test_tabla_principal_suma_columna_p_y_calcula_sla(tmp_path) -> None:
    documento = _generar(tmp_path, soporte_sla.servicios_excel(), soporte_sla.reclamos_excel())
    assert documento.docx.exists() and documento.pdf is None

    filas = _filas(Document(str(documento.docx)).tables[0])[1:]
    # SRV-001: 1:30 + 1:00 de la columna P (la N vale 99 h por reclamo y no cuenta).
    assert filas[0][:4] == ["Fibra", "SRV-002", "Cliente Test", "000:45:00"]
    assert filas[1][:4] == ["Fibra", "SRV-001", "Cliente Test", "002:30:00"]
    assert filas[1][4] == f"{(1 - 2.5 / 8760) * 100:.2f}%"  # 1 − horas / 8760, mayor SLA primero


def test_detalle_con_fechas_reales_y_domicilio(tmp_path) -> None:
    """Hasta P25 el render leía el serial de Excel como 1970 y todas las fechas salían 01-ene-70."""
    documento = _generar(tmp_path, soporte_sla.servicios_excel(), soporte_sla.reclamos_excel())
    doc = Document(str(documento.docx))
    texto = " ".join(c.text for t in doc.tables for f in t.rows for c in f.cells)
    assert "10-oct-25" in texto and "15-oct-25" in texto
    assert "01-ene-70" not in texto
    assert "Av. Siempre Viva 742" in texto
    detalle = next(_filas(t) for t in doc.tables if any(len(f) > 1 and f[1] == "R-001" for f in _filas(t)))
    assert detalle[-1][0] == "Total" and detalle[-1][2] == "2.50"


def test_reclamo_vinculado_por_primer_servicio(tmp_path) -> None:
    servicios = soporte_sla.servicios_excel([soporte_sla.servicio("L-NUEVA", primer="PS-1")])
    reclamos = soporte_sla.reclamos_excel([
        soporte_sla.reclamo("R-9", "L-VIEJA", dt.time(2, 0), inicio=dt.datetime(2025, 10, 1, 8, 0), primer="PS-1"),
    ])
    filas = _filas(Document(str(_generar(tmp_path, servicios, reclamos).docx)).tables[0])[1:]
    assert filas == [["Fibra", "L-VIEJA", "Cliente Test", "002:00:00", f"{(1 - 2 / 8760) * 100:.2f}%"]]


def test_servicio_sin_reclamos_100_por_ciento(tmp_path) -> None:
    servicios = soporte_sla.servicios_excel([soporte_sla.servicio("SRV-001"), soporte_sla.servicio("SRV-SIN")])
    filas = _filas(Document(str(_generar(tmp_path, servicios, soporte_sla.reclamos_excel()).docx)).tables[0])[1:]
    assert ["Fibra", "SRV-SIN", "Cliente Test", "000:00:00", "100.00%"] in filas


def test_falta_columna_p_es_error_claro(tmp_path) -> None:
    import openpyxl, io  # noqa: E401

    wb = openpyxl.load_workbook(io.BytesIO(soporte_sla.reclamos_excel()))
    ws = wb.active
    col = [c.value for c in ws[1]].index("Horas Netas Cierre Problema Reclamo") + 1
    ws.delete_cols(col)
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(ValueError, match="horas_netas_cierre"):
        _generar(tmp_path, soporte_sla.servicios_excel(), buf.getvalue())


def test_pdf_fallido_no_rompe(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("core.sla.legacy_report.intentar_pdf", lambda docx, *, contexto: (None, "office caído"))
    cfg = sla_service.SLAReportConfig(reports_dir=tmp_path, uploads_dir=tmp_path)
    documento = sla_service.generate_report_from_excel_pair(
        soporte_sla.servicios_excel(), soporte_sla.reclamos_excel(), mes=10, anio=2025, incluir_pdf=True, config=cfg)
    assert documento.docx.exists() and documento.pdf is None and documento.pdf_error == "office caído"
