# Nombre de archivo: test_ingest_parser.py
# Ubicación de archivo: tests/test_ingest_parser.py
# Descripción: Pruebas unitarias del parser de reclamos (Excel/CSV) para validar mapeo, fechas y GEO

from __future__ import annotations

import pandas as pd

from core.parsers.reclamos_excel import parse_reclamos_df


def test_parse_reclamos_df_mapea_columnas_y_fechas():
    df = pd.DataFrame(
        [
            {
                "Número Reclamo": "R-1",
                "Numero Línea": "L-100",
                "Nombre Cliente": "ACME",
                "Fecha Inicio Problema Reclamo": "01/07/2024",
                "Fecha Cierre Problema Reclamo": "02/07/2024",
                "Horas Netas Problema Reclamo": "1,5",
                "Latitud Reclamo": -34.6,
                "Longitud Reclamo": -58.38,
            },
            {
                "Número Reclamo": "R-2",
                "Numero Línea": "L-100",
                "Nombre Cliente": "ACME",
                "Fecha Inicio Problema Reclamo": "05/07/2024",
                "Fecha Cierre Problema Reclamo": None,
                "Horas Netas Problema Reclamo": "0,75",
                "Latitud Reclamo": -91.0,  # fuera de rango → NaN
                "Longitud Reclamo": 181.0,  # fuera de rango → NaN
            },
            {
                # Fila inválida: falta cliente o fechas → descartado
                "Número Reclamo": "R-3",
                "Numero Línea": "L-200",
                "Nombre Cliente": None,
                "Fecha Inicio Problema Reclamo": None,
                "Fecha Cierre Problema Reclamo": None,
                "Horas Netas Problema Reclamo": "-5",  # negativo → NaN
            },
        ]
    )

    df_ok, summary = parse_reclamos_df(df)

    # Debe conservar 2 filas válidas (R-1 y R-2)
    assert len(df_ok) == 2
    assert summary.rows_ok == 2
    assert summary.rows_bad == 1

    # Columnas esperadas
    for col in [
        "numero_reclamo",
        "numero_linea",
        "nombre_cliente",
        "fecha_inicio",
        "fecha_cierre",
        "horas_netas",
        "latitud",
        "longitud",
    ]:
        assert col in df_ok.columns

    # Tipos principales
    assert pd.api.types.is_datetime64_any_dtype(df_ok["fecha_inicio"])  # type: ignore[attr-defined]
    assert pd.api.types.is_datetime64_any_dtype(df_ok["fecha_cierre"])  # type: ignore[attr-defined]

    # Rango GEO inválido debe setear NaN (segunda fila)
    row2 = df_ok.iloc[1]
    assert pd.isna(row2["latitud"]) and pd.isna(row2["longitud"])  # type: ignore[attr-defined]

    # Horas netas en horas decimales y no negativas
    assert float(df_ok.iloc[0]["horas_netas"]) == 1.5
    assert float(df_ok.iloc[1]["horas_netas"]) == 0.75



def test_parse_reclamos_df_excel_real_con_celdas_vacias():
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Número Reclamo", "Número Evento", "Numero Línea", "Nombre Cliente", "Fecha Inicio Problema Reclamo"])
    ws.append([33001, 555, 7001, "ACME", "01/07/2024"])
    ws.append([None, 556, 7002, "ACME", "01/07/2024"])      # sin número de reclamo
    ws.append([33002, None, 7003, "ACME", "02/07/2024"])    # evento vacío
    ws.append([33003, "-", None, "ACME", "02/07/2024"])     # sin línea
    ws.append([33004, 557, 7004, None, "02/07/2024"])       # sin cliente
    buf = io.BytesIO()
    wb.save(buf)
    df = pd.read_excel(io.BytesIO(buf.getvalue()), engine="openpyxl")

    df_ok, summary = parse_reclamos_df(df)

    assert list(df_ok["numero_reclamo"]) == ["33001", "33002"]
    assert list(df_ok["numero_linea"]) == ["7001", "7003"]
    assert df_ok.iloc[0]["numero_evento"] == "555"
    assert df_ok.iloc[1]["numero_evento"] is None
    assert (summary.rows_ok, summary.rows_bad) == (2, 3)
