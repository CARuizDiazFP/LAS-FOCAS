# Nombre de archivo: test_sla_informe.py
# Ubicación de archivo: tests/test_sla_informe.py
# Descripción: Informe SLA mensual sobre el motor único (modo base, contrato JSON de la ex pila 1b y preview)

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from core.services import sla as sla_service
from core.sla import informe as inf
from core.sla.preview import construir_preview
from core.sla_consumo.parser import RECLAMOS_COLS, SERVICIOS_COLS
from core.utils.excel_duraciones import TZ_AR
from tests import soporte_sla


def _s(linea, cliente="CLI", sla=99.7, tipo="RPV"):
    fila = {c: None for c in SERVICIOS_COLS}
    fila.update(numero_linea=linea, numero_primer_servicio=linea, nombre_cliente=cliente, sla_prometido=sla,
                tipo_servicio=tipo)
    return fila


def _r(numero, linea, horas_p, inicio, horas=3, evento=None, tipo="PE-E-FO Corte de FO"):
    ini = pd.Timestamp(inicio, tz=TZ_AR)
    fila = {c: None for c in RECLAMOS_COLS}
    fila.update(numero_reclamo=numero, numero_linea=linea, numero_primer_servicio=linea, nombre_cliente="CLI",
                horas_netas=99.0, horas_netas_cierre=horas_p, tipo_solucion=tipo, numero_evento=evento,
                fecha_inicio=ini, fecha_cierre=ini + pd.Timedelta(hours=horas))
    return fila


@pytest.fixture
def informe_sep() -> inf.InformeSla:
    servicios = pd.DataFrame([_s("100"), _s("200", cliente="OTRO", tipo="INT"), _s("300")], columns=SERVICIOS_COLS)
    reclamos = pd.DataFrame([
        _r("1", "100", 10.0, "2026-03-01 10:00"),                 # meses antes: suma a la ventana de 12 meses
        _r("2", "100", 4.0, "2026-09-10 10:00", evento="E1"),     # cierra en septiembre
        _r("3", "100", 2.0, "2026-09-12 10:00", evento="E1"),
        _r("4", "200", 8.76, "2026-09-30 22:00", horas=5),        # abre en sep y cierra en oct: no es de sep
        _r("5", "300", 1.0, "2026-08-31 22:00", horas=4),         # abre en ago y cierra en sep: sí es de sep
    ], columns=RECLAMOS_COLS)
    return inf._informe_db(reclamos, servicios, mes=9, anio=2026)


def test_modo_base_lista_servicios_con_reclamos_del_mes(informe_sep):
    assert informe_sep.fecha_corte == dt.date(2026, 9, 30)
    assert {s.servicio_id for s in informe_sep.servicios} == {"100", "300"}


def test_modo_base_suma_toda_la_ventana_y_usa_la_p(informe_sep):
    srv = {s.servicio_id: s for s in informe_sep.servicios}
    assert srv["100"].horas == pytest.approx(16.0)                 # 10 + 4 + 2 de la P; la N (99 h) no cuenta
    assert srv["100"].sla_entregado == pytest.approx(1 - 16 / 8760)
    assert list(srv["100"].reclamos["numero_reclamo"]) == ["1", "2", "3"]


def test_contrato_json_conserva_claves_y_semantica_p25(informe_sep):
    comp = inf.a_computation(informe_sep)
    vista = construir_preview(comp)
    assert set(vista) == {"periodo", "resumen", "servicios", "anexo"}
    assert set(vista["resumen"]) == {"disponibilidad_pct", "downtime_total_h", "downtime_total_hhmm", "servicios",
                                     "incidentes", "tickets", "mttr_h", "mtbf_h"}
    assert vista["periodo"] == "2026-09"
    s100 = next(s for s in vista["servicios"] if s["service_id"] == "100")
    assert s100["disponibilidad_pct"] == pytest.approx((1 - 16 / 8760) * 100, abs=1e-4)
    assert s100["downtime_h"] == pytest.approx(16.0)
    assert (s100["incidentes_agrupados"], s100["tickets_unicos"]) == (2, 3)  # evento E1 + reclamo sin evento
    assert s100["mttr_h"] == pytest.approx(8.0)
    assert vista["resumen"]["servicios"] == 2 and vista["resumen"]["downtime_total_h"] == pytest.approx(17.0)
    assert vista["resumen"]["disponibilidad_pct"] == pytest.approx((1 - 17 / (8760 * 2)) * 100, abs=1e-4)
    fila = next(a for a in vista["anexo"] if a["tickets"] == ["2"])
    assert fila["duracion_h"] == pytest.approx(4.0) and fila["causas"] == ["FO (excepto Cod 3)"]


def test_preview_filtra_por_cliente_y_tipo(informe_sep):
    comp = inf.a_computation(informe_sep)
    assert construir_preview(comp, cliente="cli")["servicios"] != []
    assert construir_preview(comp, service_id="300")["anexo"][0]["service_id"] == "300"
    assert construir_preview(comp, servicio="int")["servicios"] == []


def test_mes_sin_reclamos_da_informe_vacio():
    servicios = pd.DataFrame([_s("100")], columns=SERVICIOS_COLS)
    reclamos = pd.DataFrame([_r("1", "100", 1.0, "2026-03-01 10:00")], columns=RECLAMOS_COLS)
    comp = inf.a_computation(inf._informe_db(reclamos, servicios, mes=9, anio=2026))
    assert comp.servicios == [] and comp.resumen.servicios == 0 and comp.resumen.disponibilidad_pct == 0.0


def test_compute_from_db_usa_la_ultima_foto(monkeypatch):
    llamadas = []
    servicios = pd.DataFrame([_s("100")], columns=SERVICIOS_COLS)
    reclamos = pd.DataFrame([_r("1", "100", 1.0, "2026-09-02 10:00")], columns=RECLAMOS_COLS)
    monkeypatch.setattr(inf, "cargar_ventana_ultima_foto", lambda corte: llamadas.append(corte) or (reclamos, servicios))
    comp = sla_service.compute_from_db(mes=9, anio=2026)
    assert llamadas == [dt.date(2026, 9, 30)]
    assert comp.informe is not None and comp.resumen.servicios == 1


@pytest.mark.parametrize("mes, anio", [(13, 2026), (0, 2026), (5, 1999)])
def test_periodo_invalido(mes, anio):
    with pytest.raises(ValueError):
        inf.desde_db(mes=mes, anio=anio)


def test_un_excel_de_reclamos_sin_fotos_en_la_base(monkeypatch):
    vacios = (pd.DataFrame(columns=RECLAMOS_COLS), pd.DataFrame(columns=SERVICIOS_COLS))
    monkeypatch.setattr(inf, "cargar_ventana_ultima_foto", lambda corte: vacios)
    with pytest.raises(ValueError, match="fotos de servicios"):
        sla_service.compute_from_excel(soporte_sla.reclamos_excel(), mes=10, anio=2025)


def test_un_excel_de_reclamos_con_fotos_genera_docx(monkeypatch, tmp_path):
    servicios = pd.DataFrame([_s("SRV-001"), _s("SRV-002")], columns=SERVICIOS_COLS)
    monkeypatch.setattr(inf, "cargar_ventana_ultima_foto", lambda corte: (None, servicios))
    cfg = sla_service.SLAReportConfig(reports_dir=tmp_path, uploads_dir=tmp_path)
    resultado = sla_service.generate_report_from_excel(soporte_sla.reclamos_excel(), mes=10, anio=2025, config=cfg)
    assert resultado.docx.exists()
    assert resultado.computation.resumen.servicios == 2
    assert resultado.preview["resumen"]["downtime_total_h"] == pytest.approx(3.25)
