# Nombre de archivo: test_repetitividad_processor.py
# Ubicación de archivo: tests/test_repetitividad_processor.py
# Descripción: Pruebas del procesamiento de repetitividad

import pandas as pd
import pytest

from modules.informes_repetitividad import processor


def test_compute_repetitividad_preserva_macro():
    datos = [
        {"CLIENTE": "BANCO MACRO SA", "SERVICIO": "S1", "FECHA": "2024-07-01", "ID_SERVICIO": "1"},
        {"CLIENTE": "BANCO MACRO SA", "SERVICIO": "S1", "FECHA": "2024-07-15", "ID_SERVICIO": "2"},
        {"CLIENTE": "OTRO", "SERVICIO": "S2", "FECHA": "2024-07-20", "ID_SERVICIO": "3"},
    ]
    df = pd.DataFrame(datos)
    df = processor.normalize(df)
    res = processor.compute_repetitividad(df)

    assert res.total_servicios == 2
    assert res.total_repetitivos == 1
    assert res.servicios[0].servicio == "S1"
    assert "BANCO MACRO SA" in df["CLIENTE"].unique()
    assert "2024-07" in res.periodos


def test_compute_repetitividad_varios_servicios():
    datos = [
        {"CLIENTE": "A", "SERVICIO": "S1", "FECHA": "2024-07-01", "ID_SERVICIO": "1"},
        {"CLIENTE": "A", "SERVICIO": "S1", "FECHA": "2024-07-02", "ID_SERVICIO": "2"},
        {"CLIENTE": "B", "SERVICIO": "S2", "FECHA": "2024-07-03", "ID_SERVICIO": "3"},
        {"CLIENTE": "B", "SERVICIO": "S2", "FECHA": "2024-07-04", "ID_SERVICIO": "4"},
        {"CLIENTE": "C", "SERVICIO": "S3", "FECHA": "2024-07-05", "ID_SERVICIO": "5"},
    ]
    df = pd.DataFrame(datos)
    df = processor.normalize(df)
    res = processor.compute_repetitividad(df)

    assert res.total_servicios == 3
    assert res.total_repetitivos == 2
    servicios = {item.servicio: item.casos for item in res.servicios}
    assert servicios == {"S1": 2, "S2": 2}
    assert res.periodos == ["2024-07"]


def test_normalize_falla_si_faltan_columnas():
    datos = [{"CLIENTE": "A", "OTRA": "x"}]
    df = pd.DataFrame(datos)
    try:
        processor.normalize(df)
    except ValueError as exc:
        assert "Faltan columnas requeridas" in str(exc)
    else:  # pragma: no cover - sanity
        raise AssertionError("normalize debería fallar")


def test_normalize_acepta_fecha_cierre_problema():
    datos = [
        {
            "Nombre Cliente": "Cliente Demo",
            "Número Línea": "SERV-001",
            "Fecha Cierre Problema Reclamo": "2024-07-10",
            "Número Reclamo": "R-1",
        }
    ]
    df = pd.DataFrame(datos)
    normalizado = processor.normalize(df)

    assert "FECHA" in normalizado.columns
    assert normalizado["FECHA"].dt.strftime("%Y-%m-%d").iloc[0] == "2024-07-10"
    assert normalizado["SERVICIO"].iloc[0] == "SERV-001"


def test_compute_repetitividad_exige_reclamos_distintos():
    datos = [
        {"CLIENTE": "A", "SERVICIO": "S1", "FECHA": "2024-07-01", "ID_SERVICIO": "R1"},
        {"CLIENTE": "A", "SERVICIO": "S1", "FECHA": "2024-07-02", "ID_SERVICIO": "R1"},
        {"CLIENTE": "B", "SERVICIO": "S2", "FECHA": "2024-07-03", "ID_SERVICIO": "R2"},
        {"CLIENTE": "B", "SERVICIO": "S2", "FECHA": "2024-07-04", "ID_SERVICIO": "R3"},
    ]
    df = pd.DataFrame(datos)
    df = processor.normalize(df)
    res = processor.compute_repetitividad(df)

    assert res.total_repetitivos == 1
    servicio = res.servicios[0]
    assert servicio.servicio == "S2"
    assert servicio.casos == 2
    assert [r.numero_reclamo for r in servicio.reclamos] == ["R2", "R3"]


def test_detalles_sin_id_servicio_usa_indice():
    datos = [
        {"CLIENTE": "A", "SERVICIO": "S1", "FECHA": "2024-07-01"},
        {"CLIENTE": "A", "SERVICIO": "S1", "FECHA": "2024-07-05"},
    ]
    df = pd.DataFrame(datos)
    df = processor.normalize(df)
    res = processor.compute_repetitividad(df)

    assert [r.numero_reclamo for r in res.servicios[0].reclamos] == ["0", "1"]


def test_compute_repetitividad_con_geo():
    datos = [
        {"CLIENTE": "Geo", "SERVICIO": "S1", "FECHA": "2024-07-01", "Latitud": -34.6, "Longitud": -58.3},
        {"CLIENTE": "Geo", "SERVICIO": "S1", "FECHA": "2024-07-05", "Latitud": -34.6, "Longitud": -58.3},
    ]
    df = pd.DataFrame(datos)
    df = processor.normalize(df)
    res = processor.compute_repetitividad(df)

    assert res.with_geo is True
    servicio = res.servicios[0]
    assert servicio.servicio == "S1"
    assert servicio.has_geo() is True
    assert round(servicio.reclamos[0].latitud, 1) == -34.6


def test_load_excel_rechaza_archivo_no_xlsx(tmp_path):
    file_path = tmp_path / "archivo.txt"
    file_path.write_text("contenido")

    with pytest.raises(ValueError) as excinfo:
        processor.load_excel(str(file_path))

    assert "no corresponde" in str(excinfo.value)
