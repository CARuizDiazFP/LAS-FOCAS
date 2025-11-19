# Nombre de archivo: alarmas_ciena.py
# Ubicación de archivo: core/parsers/alarmas_ciena.py
# Descripción: Parser para archivos CSV de alarmas Ciena (SiteManager y MCP) con detección automática de formato

"""
Parser de alarmas Ciena.

Soporta dos formatos de CSV exportados desde gestores de red Ciena:
- SiteManager: formato con campos entrecomillados, columnas típicas: Unit, Class, Severity, Service...
- MCP: formato CSV estándar con columnas: Severity, Description, Class, Card type, Device type...

El módulo detecta automáticamente el formato basándose en el encabezado del archivo
y procesa los datos en consecuencia, retornando un DataFrame limpio.
"""

from __future__ import annotations

import io
import logging
from enum import Enum
from typing import BinaryIO

import pandas as pd
from pandas.api.types import is_object_dtype

logger = logging.getLogger(__name__)


class FormatoAlarma(str, Enum):
    """Tipos de formato soportados para alarmas Ciena."""
    
    SITEMANAGER = "SiteManager"
    MCP = "MCP"
    DESCONOCIDO = "Desconocido"


def detectar_formato(content: bytes) -> FormatoAlarma:
    """
    Detecta el formato del CSV de alarmas según su línea de encabezado.
    
    Args:
        content: Contenido binario del archivo CSV
        
    Returns:
        FormatoAlarma indicando el tipo detectado
        
    Ejemplos:
        - SiteManager: "Unit","Class","Severity","Service",...
        - MCP: Severity,Description,Class,Card type,...
    """
    try:
        # Leer primera línea (header)
        first_line = content.split(b'\n', 1)[0].decode('utf-8', errors='ignore').strip()
        
        if not first_line:
            logger.warning("action=detectar_formato result=empty_header")
            return FormatoAlarma.DESCONOCIDO
        
        # SiteManager: campos entre comillas, presencia de "Unit" al inicio
        # y uso masivo de "," para separar campos entrecomillados
        if first_line.startswith('"Unit"') or ('","' in first_line and '"Unit"' in first_line):
            logger.info("action=detectar_formato result=sitemanager")
            return FormatoAlarma.SITEMANAGER
        
        # MCP: campos separados por coma sin comillas masivas,
        # típicamente comienza con Severity,Description,Class
        if first_line.startswith("Severity,Description,Class") or \
           ("Severity" in first_line and "NMS alarm ID" in first_line):
            logger.info("action=detectar_formato result=mcp")
            return FormatoAlarma.MCP
        
        # Intentar detección heurística adicional
        # SiteManager tiene muchos campos entrecomillados
        quoted_count = first_line.count('"')
        if quoted_count > 10:  # Heurística: muchas comillas sugiere SiteManager
            logger.info("action=detectar_formato result=sitemanager_heuristic quotes=%d", quoted_count)
            return FormatoAlarma.SITEMANAGER
        
        logger.warning("action=detectar_formato result=unknown header=%s", first_line[:100])
        return FormatoAlarma.DESCONOCIDO
        
    except Exception as e:
        logger.error("action=detectar_formato error=%s", e, exc_info=True)
        return FormatoAlarma.DESCONOCIDO


def _strip_dataframe_strings(df: pd.DataFrame) -> pd.DataFrame:
    """Elimina espacios en los extremos de todas las columnas string."""

    return df.apply(lambda col: col.str.strip() if is_object_dtype(col) else col)


def parsear_sitemanager(content: bytes) -> pd.DataFrame:
    """
    Parsea un CSV de SiteManager.
    
    Características del formato:
    - Campos entrecomillados
    - Espacios padding en los valores
    - Guiones "-" como placeholder para valores vacíos
    
    Args:
        content: Contenido binario del archivo CSV
        
    Returns:
        DataFrame con las columnas parseadas y limpiadas
        
    Raises:
        ValueError: Si el archivo no puede ser parseado
    """
    try:
        logger.info("action=parsear_sitemanager start=true")
        
        # Leer CSV con pandas, mantener todo como string
        df = pd.read_csv(
            io.BytesIO(content),
            dtype=str,
            keep_default_na=False,
            encoding='utf-8',
            engine='python'
        )
        
        logger.info(
            "action=parsear_sitemanager stage=loaded rows=%d cols=%d",
            len(df), len(df.columns)
        )
        
        # Limpiar espacios en extremos de cada valor
        df = _strip_dataframe_strings(df)
        
        # Reemplazar guiones aislados por cadena vacía
        df = df.replace(to_replace=r'^\s*-\s*$', value='', regex=True)
        
        logger.info("action=parsear_sitemanager stage=cleaned success=true")
        return df
        
    except Exception as e:
        logger.error("action=parsear_sitemanager error=%s", e, exc_info=True)
        raise ValueError(f"Error al parsear CSV de SiteManager: {e}") from e


def parsear_mcp(content: bytes) -> pd.DataFrame:
    """
    Parsea un CSV de MCP (formato estándar).
    
    Características del formato:
    - Campos separados por coma
    - Comillas solo cuando necesario (campos con comas o saltos de línea)
    - Puede contener descripciones multilínea
    
    Args:
        content: Contenido binario del archivo CSV
        
    Returns:
        DataFrame con las columnas parseadas
        
    Raises:
        ValueError: Si el archivo no puede ser parseado
    """
    try:
        logger.info("action=parsear_mcp start=true")
        
        # Usar motor Python para soportar campos multilínea
        df = pd.read_csv(
            io.BytesIO(content),
            dtype=str,
            keep_default_na=False,
            encoding='utf-8',
            engine='python'
        )
        
        logger.info(
            "action=parsear_mcp stage=loaded rows=%d cols=%d",
            len(df), len(df.columns)
        )
        
        # Limpiar espacios si es necesario (MCP normalmente no tiene padding)
        df = _strip_dataframe_strings(df)
        
        logger.info("action=parsear_mcp stage=cleaned success=true")
        return df
        
    except Exception as e:
        logger.error("action=parsear_mcp error=%s", e, exc_info=True)
        raise ValueError(f"Error al parsear CSV de MCP: {e}") from e


def parsear_alarmas_ciena(content: bytes) -> tuple[pd.DataFrame, FormatoAlarma]:
    """
    Parsea un CSV de alarmas Ciena, detectando automáticamente el formato.
    
    Args:
        content: Contenido binario del archivo CSV
        
    Returns:
        Tupla con (DataFrame parseado, FormatoAlarma detectado)
        
    Raises:
        ValueError: Si el formato no es soportado o hay error en el parsing
        
    Example:
        >>> with open("alarmas.csv", "rb") as f:
        ...     content = f.read()
        >>> df, formato = parsear_alarmas_ciena(content)
        >>> print(f"Formato: {formato}, Filas: {len(df)}")
    """
    if not content:
        raise ValueError("El archivo está vacío")
    
    formato = detectar_formato(content)
    
    if formato == FormatoAlarma.DESCONOCIDO:
        raise ValueError(
            "Formato de archivo no soportado. "
            "Por favor verificá que sea un CSV exportado desde SiteManager o MCP."
        )
    
    if formato == FormatoAlarma.SITEMANAGER:
        df = parsear_sitemanager(content)
    else:  # FormatoAlarma.MCP
        df = parsear_mcp(content)
    
    logger.info(
        "action=parsear_alarmas_ciena formato=%s rows=%d cols=%d",
        formato.value, len(df), len(df.columns)
    )
    
    return df, formato


def dataframe_to_excel(df: pd.DataFrame) -> bytes:
    """
    Convierte un DataFrame a un archivo Excel en memoria.
    
    Args:
        df: DataFrame a exportar
        
    Returns:
        Contenido binario del archivo Excel (.xlsx)
        
    Raises:
        ValueError: Si hay error en la generación del Excel
    """
    try:
        output = io.BytesIO()
        
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Alarmas')
        
        excel_content = output.getvalue()
        logger.info(
            "action=dataframe_to_excel rows=%d cols=%d size=%d",
            len(df), len(df.columns), len(excel_content)
        )
        
        return excel_content
        
    except Exception as e:
        logger.error("action=dataframe_to_excel error=%s", e, exc_info=True)
        raise ValueError(f"Error al generar archivo Excel: {e}") from e
