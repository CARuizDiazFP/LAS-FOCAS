# Nombre de archivo: test_sla_consumo_builders.py
# Ubicación de archivo: tests/test_sla_consumo_builders.py
# Descripción: Presentación compartida, gráficos y XLSX completo del informe SLA consumido

from __future__ import annotations

import datetime as dt

import openpyxl
import pandas as pd
import pytest
from openpyxl.utils.datetime import to_excel

from core.sla_consumo import charts, presentacion
from core.sla_consumo.presentacion import COLUMNAS, COLORES_SEMAFORO, fmt_bool, fmt_fecha, fmt_horas, fmt_pct
from core.sla_consumo.xlsx_builder import HOJAS, construir_xlsx
from core.utils.excel_duraciones import TZ_AR
from tests.test_sla_consumo_engine import CARRIER, FO, OTROS, _calc, _r, _s

PNG = b"\x89PNG"
sin_utcnow = pytest.mark.filterwarnings("ignore:datetime.datetime.utcnow:DeprecationWarning")


@pytest.fixture
def res():
    servicios = [_s("100"), _s("200", sla=None), _s("300"), _s("400")]
    reclamos = [_r("1", "100", 27, FO, evento="E1", dia=1), _r("2", "100", 1, CARRIER, dia=2),
                _r("3", "300", 4, OTROS, evento="E1", dia=3), _r("4", "200", 2, FO, evento="E2", dia=4),
                _r("5", "999", 3, FO, dia=5)]
    return _calc(servicios, reclamos)


def _col(ws, etiqueta):
    return [c.value for c in ws[1]].index(etiqueta) + 1


def _fila(ws, etiqueta_col, valor):
    j = _col(ws, etiqueta_col)
    return next(f for f in ws.iter_rows(min_row=2) if f[j - 1].value == valor)


@sin_utcnow
def test_xlsx_hojas_y_filas_completas(res, tmp_path):
    wb = openpyxl.load_workbook(construir_xlsx(res, tmp_path / "x.xlsx"))
    assert wb.sheetnames == list(HOJAS)
    for hoja, df in (("Servicios", res.servicios), ("Servicio x Reclamo", res.servicio_reclamo),
                     ("Evento x Servicio", res.evento_servicio), ("Eventos", res.eventos),
                     ("No vinculados", res.no_vinculados), ("Codigo de cierre", res.codigo_cierre)):
        assert wb[hoja].max_row - 1 == len(df), hoja
    assert wb["Codigo de cierre"].cell(1, 2).value == "Eventos + reclamos sin evento"


@sin_utcnow
def test_xlsx_formatos_horas_y_pct(res, tmp_path):
    ws = openpyxl.load_workbook(construir_xlsx(res, tmp_path / "x.xlsx"))["Servicios"]
    fila = _fila(ws, COLUMNAS["servicio_id"][0], "100")
    horas = fila[_col(ws, COLUMNAS["horas_computables"][0]) - 1]
    assert to_excel(horas.value) == pytest.approx(28 / 24) and horas.number_format == "[h]:mm"
    pct = fila[_col(ws, COLUMNAS["pct_real"][0]) - 1]
    esperado = float(res.servicios.set_index("servicio_id").loc["100", "pct_real"]) / 100
    assert pct.value == pytest.approx(esperado) and pct.number_format == "0.00%"
    ev = openpyxl.load_workbook(tmp_path / "x.xlsx")["Servicio x Reclamo"]
    f1 = _fila(ev, COLUMNAS["numero_reclamo"][0], "1")
    assert to_excel(f1[_col(ev, COLUMNAS["horas_computables"][0]) - 1].value) == pytest.approx(27 / 24)
    inicio = f1[_col(ev, COLUMNAS["fecha_inicio"][0]) - 1]
    assert inicio.value == dt.datetime(2026, 9, 1, 10, 0) and inicio.number_format == "dd/mm/yyyy hh:mm"
    assert f1[_col(ev, COLUMNAS["cuenta_sla"][0]) - 1].value == "Sí"


@sin_utcnow
def test_xlsx_formato_condicional_por_semaforo(res, tmp_path):
    ws = openpyxl.load_workbook(construir_xlsx(res, tmp_path / "x.xlsx"))["Servicios"]
    reglas = [r for rango in ws.conditional_formatting for r in rango.rules]
    formulas = " ".join(f for r in reglas for f in r.formula)
    for texto, color in COLORES_SEMAFORO.items():
        if color:
            assert f'"{texto}"' in formulas
    assert len(reglas) >= 3 + 5   # semáforo + estados
    assert all(c.fill.fill_type is None or c.fill.start_color.rgb in ("00000000", "FF1F3864")
               for fila in ws.iter_rows(min_row=2, max_row=3) for c in fila)  # sin rellenos estáticos


@sin_utcnow
def test_xlsx_no_evaluable_sin_pct_ni_inf(res, tmp_path):
    ws = openpyxl.load_workbook(construir_xlsx(res, tmp_path / "x.xlsx"))["Servicios"]
    fila = _fila(ws, COLUMNAS["servicio_id"][0], "200")
    assert fila[_col(ws, COLUMNAS["estado"][0]) - 1].value == "No evaluable"
    for clave in ("pct_real", "pct_visible", "aporte_fo_pct", "horas_restantes", "horas_excedidas", "presupuesto_h"):
        assert fila[_col(ws, COLUMNAS[clave][0]) - 1].value is None, clave


@sin_utcnow
def test_xlsx_inf_y_nan_quedan_vacios(res, tmp_path):
    s = res.servicios.copy()
    s.loc[s.index[0], "pct_real"] = float("inf")
    s.loc[s.index[1], "horas_restantes"] = float("-inf")
    res.servicios = s
    ws = openpyxl.load_workbook(construir_xlsx(res, tmp_path / "x.xlsx"))["Servicios"]
    valores = [c.value for fila in ws.iter_rows() for c in fila]
    assert not any(isinstance(v, float) and v in (float("inf"), float("-inf")) for v in valores)
    assert ws.cell(2, _col(ws, COLUMNAS["pct_real"][0])).value is None


@sin_utcnow
def test_xlsx_filtro_y_panel_congelado_en_toda_hoja(res, tmp_path):
    wb = openpyxl.load_workbook(construir_xlsx(res, tmp_path / "x.xlsx"))
    for ws in wb:
        assert ws.auto_filter.ref, ws.title
        assert ws.freeze_panes == ("A2" if ws.title == HOJAS[0] else "B2"), ws.title
        assert all(d.width <= 50 for d in ws.column_dimensions.values()), ws.title
        assert all(c.font.bold for c in ws[1]), ws.title


@sin_utcnow
def test_resumen_tiene_corte_totales_composicion_y_leyendas(res, tmp_path):
    ws = openpyxl.load_workbook(construir_xlsx(res, tmp_path / "x.xlsx"))["Resumen y leyendas"]
    textos = [str(c.value) for fila in ws.iter_rows() for c in fila if c.value is not None]
    unidos = "\n".join(textos)
    assert "Fecha de corte" in unidos and "365 días" in unidos
    assert "Horas computables (reclamos vinculados)" in unidos
    assert "FO general" in unidos
    for concepto, _ in presentacion.LEYENDAS:
        assert concepto in textos


def test_torta_causas_png_y_none_sin_consumo(res, tmp_path):
    assert charts.torta_causas(res, tmp_path / "t.png").read_bytes()[:4] == PNG
    vacio = _calc([_s("100")], [_r("1", "100", 0, FO)])
    assert charts.torta_causas(vacio, tmp_path / "v.png") is None
    assert not (tmp_path / "v.png").exists()


def test_magnitud_eventos_png_y_none_sin_eventos(res, tmp_path):
    assert charts.magnitud_eventos(res, tmp_path / "m.png", top=5).read_bytes()[:4] == PNG
    sin = _calc([_s("100")], [_r("1", "100", 3, FO)])
    assert charts.magnitud_eventos(sin, tmp_path / "n.png", top=5) is None


def test_fmt():
    assert fmt_horas(27.5) == "27:30" and fmt_horas(0.0) == "0:00" and fmt_horas(100.25) == "100:15"
    assert fmt_horas(None) == "—" and fmt_horas(float("nan")) == "—" and fmt_horas(float("-inf")) == "—"
    assert fmt_pct(12.345) == "12,35 %" and fmt_pct(float("inf")) == "—" and fmt_pct(None) == "—"
    assert fmt_bool(True) == "Sí" and fmt_bool(False) == "No"
    assert fmt_fecha(pd.Timestamp("2026-09-01 10:05", tz=TZ_AR)) == "01/09/2026 10:05"
    assert fmt_fecha(pd.Timestamp("2026-09-01 13:05", tz="UTC")) == "01/09/2026 10:05"
    assert fmt_fecha(pd.NaT) == "—" and fmt_fecha(None) == "—"


def test_fmt_fecha_y_bool_tolerantes_a_textos():
    assert presentacion.fmt("sin fecha", "fecha") == "sin fecha" and presentacion.fmt(pd.NaT, "fecha") == "—"
    assert presentacion.a_fecha_ar("texto") == "texto" and presentacion.a_fecha_ar(pd.NaT) is None
    for falso in ("No", "no", "false", "0"):
        assert presentacion.fmt(falso, "bool") == "No"
    assert presentacion.fmt("Quizás", "bool") == "Quizás" and presentacion.fmt(True, "bool") == "Sí"


def test_columnas_formatos_validos_y_colores():
    assert {f for _, f in COLUMNAS.values()} <= {"texto", "entero", "horas", "pct", "fecha", "bool"}
    assert presentacion.COLORES_SEMAFORO["Sin color"] is None
    assert presentacion.COLORES_CAUSA["Carrier"] == "2980B9"
