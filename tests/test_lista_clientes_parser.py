# Nombre de archivo: test_lista_clientes_parser.py
# Ubicación de archivo: tests/test_lista_clientes_parser.py
# Descripción: Lectura de archivos tabulares subidos y extracción de nombres de una lista oficial de clientes

from __future__ import annotations

import io

import pandas as pd
import pytest

from core.parsers.archivo_tabular import FormatoNoSoportadoError, leer_tabla
from core.parsers.lista_clientes import extraer_nombres_lista


def _xlsx(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    return buffer.getvalue()


class TestLeerTabla:
    def test_lee_csv_y_xlsx_como_texto(self) -> None:
        df = leer_tabla("lista.CSV", b"a,b\n001,x\n")
        assert df.to_dict("records") == [{"a": "001", "b": "x"}]
        df = leer_tabla("lista.xlsx", _xlsx(pd.DataFrame({"a": ["001"], "b": ["x"]})))
        assert df.to_dict("records") == [{"a": "001", "b": "x"}]

    def test_extension_no_soportada(self) -> None:
        with pytest.raises(FormatoNoSoportadoError):
            leer_tabla("lista.pdf", b"%PDF")


class TestExtraerNombresLista:
    def test_txt_un_nombre_por_linea(self) -> None:
        contenido = "BANCO UNO SA\r\n\n  Banco Dos  \nÑANDÚ SRL\n".encode("utf-8-sig")
        assert extraer_nombres_lista("lista.txt", contenido) == ["BANCO UNO SA", "Banco Dos", "ÑANDÚ SRL"]

    def test_txt_latin1(self) -> None:
        assert extraer_nombres_lista("lista.txt", "CAÑO SA\n".encode("latin-1")) == ["CAÑO SA"]

    def test_csv_detecta_columna_cliente_sin_acentos_ni_mayusculas(self) -> None:
        contenido = "Servicio,nombre  CLIENTE\n1,BANCO UNO\n2,\n3,BANCO DOS\n".encode()
        assert extraer_nombres_lista("lista.csv", contenido) == ["BANCO UNO", "BANCO DOS"]

    def test_xlsx_columna_cliente(self) -> None:
        df = pd.DataFrame({"Id": ["1", "2"], "Cliente": ["BANCO UNO", "BANCO DOS"]})
        assert extraer_nombres_lista("lista.xlsx", _xlsx(df)) == ["BANCO UNO", "BANCO DOS"]

    def test_sin_encabezado_conocido_usa_la_primera_columna(self) -> None:
        df = pd.DataFrame({"Razón social": ["BANCO UNO", "BANCO DOS"], "Otro": ["x", "y"]})
        assert extraer_nombres_lista("lista.xlsx", _xlsx(df)) == ["BANCO UNO", "BANCO DOS"]

    def test_extension_no_soportada(self) -> None:
        with pytest.raises(FormatoNoSoportadoError):
            extraer_nombres_lista("lista.docx", b"x")
