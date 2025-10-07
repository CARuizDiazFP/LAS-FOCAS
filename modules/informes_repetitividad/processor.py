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
    2. Genera una versión estandarizada de cada nombre (upper, espacios->_, quita tildes simples si aparecen).
    3. Aplica un diccionario de sinónimos y el mapeo existente.
    4. Valida columnas obligatorias, agregando logging diagnóstico si faltan.
    """
    import unicodedata

    # Flatten MultiIndex si fuese el caso
    if isinstance(df.columns, pd.MultiIndex):  # pragma: no cover - raro pero defensivo
        df.columns = ["_".join([str(p) for p in tup if p not in (None, '')]) for tup in df.columns]

    original_cols: List[str] = [str(c) for c in df.columns]

    def _std(s: str) -> str:
        s2 = ''.join(ch for ch in unicodedata.normalize('NFKD', s) if not unicodedata.combining(ch))
        return s2.strip().upper().replace(" ", "_")

    std_map: Dict[str, str] = {_std(c): c for c in original_cols}

    # Sinónimos ampliados (upper ya estandarizados)
    SYNONYMS = {
        "CLIENTE": "CLIENTE",
        "CLIENT": "CLIENTE",
        "CLIENTE_NOMBRE": "CLIENTE",
        "SERVICIO": "SERVICIO",
        "SERVICE": "SERVICIO",
        "ID_SERVICIO": "ID_SERVICIO",
        "ID-SERVICIO": "ID_SERVICIO",
        "FECHA": "FECHA",
        "FECHA_APERTURA": "FECHA",
        "FECHA-APERTURA": "FECHA",
        "DATE": "FECHA",
    }

    rename_map: Dict[str, str] = {}
    for std_key, original in std_map.items():
        target = SYNONYMS.get(std_key, std_key)
        # Aplicar mapeo explícito si existiese (COLUMNAS_MAPPER claves exactas)
        if original in COLUMNAS_MAPPER:
            target = COLUMNAS_MAPPER[original]
        rename_map[original] = target

    df = df.rename(columns=rename_map)
    # Upper final
    df.columns = [c.upper() for c in df.columns]

    missing = [c for c in COLUMNAS_OBLIGATORIAS if c not in df.columns]
    if missing:
        logger.warning(
            "action=repetitividad_normalize level=warning missing=%s original_cols=%s renamed_cols=%s",  # noqa: E501
            missing,
            original_cols,
            list(df.columns),
        )
        raise ValueError(f"Faltan columnas requeridas: {', '.join(missing)}")

    # Limpieza de valores
    df["CLIENTE"] = df["CLIENTE"].astype(str).str.upper().str.strip()
    df["SERVICIO"] = df["SERVICIO"].astype(str).str.strip()

    # Filtrado filas: remover nulos salvo clientes preservados
    df = df[df["CLIENTE"].notna() | df["CLIENTE"].isin(CLIENTES_PRESERVAR)]

    # Parse fecha
    df["FECHA"] = pd.to_datetime(df["FECHA"], errors="coerce")
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
