# Nombre de archivo: processor.py
# Ubicación de archivo: modules/informes_repetitividad/processor.py
# Descripción: Funciones de carga, normalización y cálculo de repetitividad

import logging
from typing import Optional

import pandas as pd

from .config import (
    CLIENTES_PRESERVAR,
    COLUMNAS_MAPPER,
    COLUMNAS_OBLIGATORIAS,
)
from .schemas import ItemSalida, ResultadoRepetitividad

logger = logging.getLogger(__name__)


def load_excel(path: str) -> pd.DataFrame:
    """Carga un archivo Excel en un DataFrame."""
    try:
        return pd.read_excel(path, engine="openpyxl")
    except Exception as exc:  # pragma: no cover - logging
        logger.exception("action=load_excel error=%s path=%s", exc, path)
        raise


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza nombres de columnas y formatos de fecha."""
    df = df.rename(columns={k: v for k, v in COLUMNAS_MAPPER.items() if k in df.columns})
    df.columns = [c.upper() for c in df.columns]

    missing = [c for c in COLUMNAS_OBLIGATORIAS if c not in df.columns]
    if missing:
        raise ValueError(f"Faltan columnas requeridas: {', '.join(missing)}")

    df["CLIENTE"] = df["CLIENTE"].astype(str).str.upper()
    df["SERVICIO"] = df["SERVICIO"].astype(str).str.strip()

    # Eliminamos filas con datos faltantes, preservando clientes críticos
    df = df[df["CLIENTE"].notna() | df["CLIENTE"].isin(CLIENTES_PRESERVAR)]

    df["FECHA"] = pd.to_datetime(df["FECHA"], errors="coerce")
    df = df.dropna(subset=["FECHA", "SERVICIO"])

    df["PERIODO"] = df["FECHA"].dt.strftime("%Y-%m")
    return df


def filter_period(df: pd.DataFrame, mes: int, anio: int) -> pd.DataFrame:
    """Filtra el DataFrame por un período específico."""
    periodo = f"{anio:04d}-{mes:02d}"
    filtrado = df[df["PERIODO"] == periodo]
    return filtrado


def _detalles(grupo: pd.DataFrame) -> list[str]:
    if "ID_SERVICIO" in grupo.columns and grupo["ID_SERVICIO"].notna().any():
        return grupo["ID_SERVICIO"].astype(str).tolist()
    return grupo.index.astype(str).tolist()


def compute_repetitividad(df: pd.DataFrame) -> ResultadoRepetitividad:
    """Calcula servicios con casos repetidos (>=2 en el período)."""
    total_servicios = df["SERVICIO"].nunique()
    items: list[ItemSalida] = []

    for servicio, grupo in df.groupby("SERVICIO"):
        conteo = len(grupo)
        if conteo >= 2:
            items.append(
                ItemSalida(servicio=servicio, casos=conteo, detalles=_detalles(grupo))
            )

    resultado = ResultadoRepetitividad(
        items=items,
        total_servicios=total_servicios,
        total_repetitivos=len(items),
    )
    logger.info(
        "action=compute_repetitividad total_servicios=%s total_repetitivos=%s",
        total_servicios,
        len(items),
    )
    return resultado
