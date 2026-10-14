# Nombre de archivo: lista_clientes.py
# Ubicación de archivo: core/parsers/lista_clientes.py
# Descripción: Extrae los nombres de una lista oficial de clientes subida como XLSX, CSV o TXT

"""Lista oficial de clientes de una categoría (la carga el admin en "Clientes por categoría").

- `.txt`: un nombre por línea (UTF-8, con o sin BOM; si no decodifica, Latin-1).
- `.xlsx`/`.xlsm`/`.csv`: la primera fila es el encabezado. La columna de nombres es la que se
  llama "Cliente" o "Nombre Cliente" (sin distinguir mayúsculas, acentos ni espacios); si ninguna
  se llama así, la primera columna.

Las celdas/líneas vacías se descartan; la deduplicación por clave la hace el servicio de dominio.
"""

from __future__ import annotations

from core.parsers.archivo_tabular import EXTENSIONES_TABULARES, FormatoNoSoportadoError, leer_tabla
from core.parsers.servicios_excel import limpiar_clave

EXTENSIONES_LISTA = (*EXTENSIONES_TABULARES, ".txt")
_ENCABEZADOS_CLIENTE = {"cliente", "nombre cliente"}


def _decodificar(contenido: bytes) -> str:
    try:
        return contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        return contenido.decode("latin-1")


def extraer_nombres_lista(nombre_archivo: str, contenido: bytes) -> list[str]:
    """Nombres (sin vacíos, en el orden del archivo) de una lista `.xlsx`/`.xlsm`/`.csv`/`.txt`.
    Levanta `FormatoNoSoportadoError` con otra extensión."""
    if (nombre_archivo or "").lower().endswith(".txt"):
        lineas = _decodificar(contenido).splitlines()
        return [linea.strip() for linea in lineas if linea.strip()]

    df = leer_tabla(nombre_archivo, contenido)
    if df.columns.empty:
        return []
    columna = next((c for c in df.columns if limpiar_clave(c) in _ENCABEZADOS_CLIENTE), df.columns[0])
    return [str(valor).strip() for valor in df[columna] if str(valor).strip()]


__all__ = ["EXTENSIONES_LISTA", "FormatoNoSoportadoError", "extraer_nombres_lista"]
