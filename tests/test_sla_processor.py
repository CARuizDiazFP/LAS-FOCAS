# Nombre de archivo: test_sla_processor.py
# Ubicación de archivo: tests/test_sla_processor.py
# Descripción: Pruebas del procesamiento y KPIs del informe de SLA

import pandas as pd
import pytest

from modules.informes_sla import processor


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
    df_cal = processor.normalize(df.copy())
    df_laboral = processor.normalize(df.copy(), work_hours=True)
    assert df_laboral.loc[0, "TTR_h"] == df_cal.loc[0, "TTR_h"] * 0.5


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
