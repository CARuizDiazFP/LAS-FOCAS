# Nombre de archivo: test_repetitividad_processor.py
# Ubicación de archivo: tests/test_repetitividad_processor.py
# Descripción: Pruebas del procesamiento de repetitividad

import pandas as pd

from modules.informes_repetitividad import processor


def test_compute_repetitividad_preserva_macro():
    datos = [
        {"CLIENTE": "BANCO MACRO SA", "SERVICIO": "S1", "FECHA": "2024-07-01", "ID_SERVICIO": "1"},
        {"CLIENTE": "BANCO MACRO SA", "SERVICIO": "S1", "FECHA": "2024-07-15", "ID_SERVICIO": "2"},
        {"CLIENTE": "OTRO", "SERVICIO": "S2", "FECHA": "2024-07-20", "ID_SERVICIO": "3"},
    ]
    df = pd.DataFrame(datos)
    df = processor.normalize(df)
    df = processor.filter_period(df, 7, 2024)
    res = processor.compute_repetitividad(df)

    assert res.total_servicios == 2
    assert res.total_repetitivos == 1
    assert res.items[0].servicio == "S1"
    assert "BANCO MACRO SA" in df["CLIENTE"].unique()


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
    df = processor.filter_period(df, 7, 2024)
    res = processor.compute_repetitividad(df)

    assert res.total_servicios == 3
    assert res.total_repetitivos == 2
    servicios = {item.servicio: item.casos for item in res.items}
    assert servicios == {"S1": 2, "S2": 2}


def test_normalize_falla_si_faltan_columnas():
    datos = [{"CLIENTE": "A", "OTRA": "x"}]
    df = pd.DataFrame(datos)
    try:
        processor.normalize(df)
    except ValueError as exc:
        assert "Faltan columnas requeridas" in str(exc)
    else:  # pragma: no cover - sanity
        raise AssertionError("normalize debería fallar")


def test_detalles_sin_id_servicio_usa_indice():
    datos = [
        {"CLIENTE": "A", "SERVICIO": "S1", "FECHA": "2024-07-01"},
        {"CLIENTE": "A", "SERVICIO": "S1", "FECHA": "2024-07-05"},
    ]
    df = pd.DataFrame(datos)
    df = processor.normalize(df)
    df = processor.filter_period(df, 7, 2024)
    res = processor.compute_repetitividad(df)

    assert res.items[0].detalles == ["0", "1"]
