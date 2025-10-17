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

    # Horas netas convertidas a minutos y no negativas
    assert int(df_ok.iloc[0]["horas_netas"]) == 90
    assert int(df_ok.iloc[1]["horas_netas"]) == 45

