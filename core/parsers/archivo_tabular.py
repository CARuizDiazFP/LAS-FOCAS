# Nombre de archivo: archivo_tabular.py
# Ubicación de archivo: core/parsers/archivo_tabular.py
# Descripción: Lectura compartida de archivos tabulares subidos (XLSX/XLSM/CSV) a un DataFrame de texto

"""Una sola implementación de "bytes subidos → DataFrame" para los endpoints que reciben planillas
(ingesta de servicios, lista oficial de clientes por categoría). Todo se lee como texto
(`dtype=str`, sin NaN) para no perder ceros a la izquierda ni convertir IDs a float."""

from __future__ import annotations

import io

import pandas as pd

EXTENSIONES_EXCEL = (".xlsx", ".xlsm")
EXTENSIONES_TABULARES = (*EXTENSIONES_EXCEL, ".csv")


class FormatoNoSoportadoError(ValueError):
    """La extensión del archivo no es una de las soportadas — el endpoint lo traduce a 415."""


def leer_tabla(nombre_archivo: str, contenido: bytes) -> pd.DataFrame:
    """DataFrame (todo texto) de un `.xlsx`/`.xlsm`/`.csv`. Levanta `FormatoNoSoportadoError` con
    otra extensión; cualquier error de lectura de pandas/openpyxl se propaga tal cual."""
    nombre = (nombre_archivo or "").lower()
    if nombre.endswith(EXTENSIONES_EXCEL):
        return pd.read_excel(io.BytesIO(contenido), engine="openpyxl", dtype=str, keep_default_na=False)
    if nombre.endswith(".csv"):
        return pd.read_csv(io.BytesIO(contenido), dtype=str, keep_default_na=False)
    raise FormatoNoSoportadoError(f"Formato no soportado: {nombre_archivo!r}")


__all__ = ["EXTENSIONES_EXCEL", "EXTENSIONES_TABULARES", "FormatoNoSoportadoError", "leer_tabla"]
