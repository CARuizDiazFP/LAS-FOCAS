# Nombre de archivo: test_servicios_excel_parser.py
# Ubicación de archivo: tests/test_servicios_excel_parser.py
# Descripción: Tests unitarios del parser de servicios SLA para aliases y validación mínima

import pandas as pd

from core.parsers.servicios_excel import parse_servicios_df


def test_parse_servicios_df_mapea_aliases_con_simbolos_y_acentos() -> None:
    df = pd.DataFrame(
        {
            "N° Primer Servicio": ["SVC-001"],
            "Razón Social": ["Cliente Demo"],
            "Nro. Línea": ["11445566"],
            "Tipo de Servicio": ["Internet"],
            "SLA": ["24x7"],
            "Domicilio Cliente": ["Av. Siempre Viva 742"],
            "Localidad": ["Rosario"],
            "Provincia": ["Santa Fe"],
            "Dirección 2": ["Piso 1"],
            "Estado del Servicio": ["ACTIVO"],
        }
    )

    parsed, summary = parse_servicios_df(df)

    assert summary.rows_ok == 1
    assert summary.rows_bad == 0
    assert parsed.iloc[0]["numero_primer_servicio"] == "SVC-001"
    assert parsed.iloc[0]["nombre_cliente"] == "Cliente Demo"
    assert parsed.iloc[0]["numero_linea"] == "11445566"
    assert parsed.iloc[0]["direccion"] == "Av. Siempre Viva 742"
    assert parsed.iloc[0]["estado_servicio"] == "ACTIVO"


def test_parse_servicios_df_descarta_filas_sin_id_y_estado_default() -> None:
    df = pd.DataFrame(
        {
            "Servicio ID": ["2001", "", None],
            "Cliente": ["A", "B", "C"],
            "Estado": [None, "ACTIVO", "SUSPENDIDO"],
        }
    )

    parsed, summary = parse_servicios_df(df)

    assert summary.rows_ok == 1
    assert summary.rows_bad == 2
    assert len(parsed) == 1
    assert parsed.iloc[0]["numero_primer_servicio"] == "2001"
    assert parsed.iloc[0]["estado_servicio"] == "DESCONOCIDO"


def test_parse_servicios_df_mapea_encabezados_reales_con_sufijo_servicio() -> None:
    df = pd.DataFrame(
        {
            "Número Primer Servicio": ["393"],
            "Dirección Servicio": ["GODOY CRUZ 2320"],
            "Dirección 2 Servicio": ["SUIPACHA 128 P.3 - D.F"],
            "Localidad Servicio": ["CABA"],
            "Provincia Servicio": ["CABA"],
        }
    )

    parsed, summary = parse_servicios_df(df)

    assert summary.rows_ok == 1
    assert parsed.iloc[0]["direccion"] == "GODOY CRUZ 2320"
    assert parsed.iloc[0]["direccion_2"] == "SUIPACHA 128 P.3 - D.F"
    assert parsed.iloc[0]["localidad"] == "CABA"
    assert parsed.iloc[0]["provincia"] == "CABA"


def test_parse_servicios_df_mapea_columnas_de_cadena_de_upgrades() -> None:
    df = pd.DataFrame(
        {
            "Número Primer Servicio": ["393", "4397"],
            "Nivel Cliente": ["4", "4"],
            "Línea Upgrade (De)": ["105636", "-"],
            "Línea Upgrade (A)": ["-", "-"],
        }
    )

    parsed, summary = parse_servicios_df(df)

    assert summary.rows_ok == 2
    assert parsed.iloc[0]["categoria"] == "4"
    assert parsed.iloc[0]["linea_upgrade_de"] == "105636"
    assert pd.isna(parsed.iloc[1]["linea_upgrade_de"])
    assert pd.isna(parsed.iloc[0]["linea_upgrade_a"])
