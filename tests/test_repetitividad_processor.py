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
