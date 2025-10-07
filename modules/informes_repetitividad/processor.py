# Nombre de archivo: processor.py
# Ubicación de archivo: modules/informes_repetitividad/processor.py
# Descripción: Funciones de carga, normalización y cálculo de repetitividad

import logging
from typing import Optional, List, Dict

import pandas as pd

from .config import (
    CLIENTES_PRESERVAR,
    COLUMNAS_MAPPER,
    COLUMNAS_OBLIGATORIAS,
)
from .schemas import ItemSalida, ResultadoRepetitividad

logger = logging.getLogger(__name__)


def load_excel(path: str) -> pd.DataFrame:
    """Carga un archivo Excel en un DataFrame.

    Incluye heurísticas mínimas para manejar encabezados desplazados u hojas con filas
    de título antes del header real. Si el primer intento no contiene columnas
    obligatorias, reintenta explorando las primeras 10 filas en busca de una fila
    candidata que contenga al menos 2 de las columnas requeridas.
    """
    try:
        df = pd.read_excel(path, engine="openpyxl")
    except Exception as exc:  # pragma: no cover - logging
        logger.exception("action=load_excel level=error error=%s path=%s", exc, path)
        raise

    # Si ya parece válido retornamos directo
    upper_cols = {str(c).strip().upper() for c in df.columns}
    if all(req in upper_cols for req in COLUMNAS_OBLIGATORIAS):
        logger.debug("action=load_excel stage=initial_ok columns=%s", list(upper_cols))
        return df

    # Reintentar: leer sin header para detectar fila con encabezados
    try:
        df_raw = pd.read_excel(path, engine="openpyxl", header=None)
        candidate_header_row = None
        for i in range(min(10, len(df_raw))):
            row_vals = [str(v).strip().upper() for v in df_raw.iloc[i].tolist()]
            hits = sum(1 for r in COLUMNAS_OBLIGATORIAS if r in row_vals)
            if hits >= 2:  # heurística: suficiente coincidencia
                candidate_header_row = i
                break
        if candidate_header_row is not None:
            df = pd.read_excel(path, engine="openpyxl", header=candidate_header_row)
            logger.info(
                "action=load_excel stage=reheader success_row=%s columns_detected=%s",  # noqa: E501
                candidate_header_row,
                list(df.columns),
            )
        else:
            logger.debug("action=load_excel stage=reheader no_candidate_found")
    except Exception as exc:  # pragma: no cover - logging
        logger.debug("action=load_excel stage=reheader error=%s", exc)

    return df


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza nombres de columnas y formatos de fecha.

    Estrategia:
    1. Aplana MultiIndex si existe.
    2. Para cada columna, se genera una clave de búsqueda (minúsculas, sin acentos, sin espacios).
    3. Se busca esta clave en el `COLUMNAS_MAPPER` y se renombra la columna.
    4. Valida que todas las columnas obligatorias estén presentes después del mapeo.
    """
    import unicodedata

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = ["_".join(map(str, col)).strip() for col in df.columns.values]

    original_cols = df.columns.tolist()
    rename_map = {}

    def clean_key(s: str) -> str:
        """Crea una clave de búsqueda normalizada a partir de un nombre de columna."""
        s = str(s)
        # Quitar acentos
        s_no_accents = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
        # Convertir a minúsculas y reemplazar espacios/guiones bajos/saltos de línea
        return s_no_accents.lower().replace(" ", "").replace("_", "").replace("\n", "").replace("\r", "")

    # Invertir el mapper para que las claves sean los nombres normalizados
    # Esto permite tener múltiples variantes en el archivo de config apuntando al mismo destino
    mapper_keys_cleaned = {clean_key(k): v for k, v in COLUMNAS_MAPPER.items()}

    for col in original_cols:
        cleaned_col = clean_key(col)
        if cleaned_col in mapper_keys_cleaned:
            target_name = mapper_keys_cleaned[cleaned_col]
            rename_map[col] = target_name
            logger.info(f"Mapeando columna: '{col}' -> '{target_name}' (clave: '{cleaned_col}')")

    df = df.rename(columns=rename_map)

    missing = [c for c in COLUMNAS_OBLIGATORIAS if c not in df.columns]
    if missing:
        logger.warning(
            "action=repetitividad_normalize level=warning missing=%s original_cols=%s final_cols=%s",
            missing,
            original_cols,
            df.columns.tolist(),
        )
        raise ValueError(f"Faltan columnas requeridas: {', '.join(missing)}")

    # Limpieza de valores
    df["CLIENTE"] = df["CLIENTE"].astype(str).str.upper().str.strip()
    df["SERVICIO"] = df["SERVICIO"].astype(str).str.strip()

    # Filtrado filas: remover nulos salvo clientes preservados
    df = df[df["CLIENTE"].notna() | df["CLIENTE"].isin(CLIENTES_PRESERVAR)]

    # Parse fecha: intentar con FECHA principal, o usar alternativas
    if "FECHA" in df.columns:
        df["FECHA"] = pd.to_datetime(df["FECHA"], errors="coerce")
    elif "FECHA_CIERRE_PROBLEMA" in df.columns:
        df["FECHA"] = pd.to_datetime(df["FECHA_CIERRE_PROBLEMA"], errors="coerce")
        logger.info("Usando FECHA_CIERRE_PROBLEMA como FECHA principal")
    elif "FECHA_INICIO" in df.columns:
        df["FECHA"] = pd.to_datetime(df["FECHA_INICIO"], errors="coerce")
        logger.info("Usando FECHA_INICIO como FECHA principal")
    else:
        raise ValueError("No se encontró ninguna columna de fecha válida")
    antes = len(df)
    df = df.dropna(subset=["FECHA", "SERVICIO"])
    logger.debug(
        "action=repetitividad_normalize stage=post_drop filas_antes=%s filas_despues=%s",  # noqa: E501
        antes,
        len(df),
    )

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
    grupos = df.groupby("SERVICIO", sort=True)
    conteos = grupos.size()
    repetitivos = conteos[conteos >= 2]

    items: list[ItemSalida] = []
    for servicio in repetitivos.index:
        grupo = grupos.get_group(servicio)
        items.append(
            ItemSalida(
                servicio=servicio,
                casos=int(repetitivos[servicio]),
                detalles=_detalles(grupo),
            )
        )

    total_servicios = len(conteos)
    total_repetitivos = len(repetitivos)

    resultado = ResultadoRepetitividad(
        items=items,
        total_servicios=total_servicios,
        total_repetitivos=total_repetitivos,
    )
    logger.info(
        "action=compute_repetitividad total_servicios=%s total_repetitivos=%s",
        total_servicios,
        total_repetitivos,
    )
    return resultado
