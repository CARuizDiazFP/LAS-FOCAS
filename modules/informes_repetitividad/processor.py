# Nombre de archivo: processor.py
# Ubicación de archivo: modules/informes_repetitividad/processor.py
# Descripción: Funciones de carga, normalización y cálculo de repetitividad

import logging
import zipfile
from typing import Optional, List, Dict

import pandas as pd

from .config import (
    CLIENTES_PRESERVAR,
    COLUMNAS_MAPPER,
    COLUMNAS_OBLIGATORIAS,
)
from .schemas import GeoPoint, ItemSalida, ResultadoRepetitividad

logger = logging.getLogger(__name__)


def load_excel(path: str) -> pd.DataFrame:
    """Carga un archivo Excel en un DataFrame.

    Incluye heurísticas mínimas para manejar encabezados desplazados u hojas con filas
    de título antes del header real. Si el primer intento no contiene columnas
    obligatorias, reintenta explorando las primeras 10 filas en busca de una fila
    candidata que contenga al menos 2 de las columnas requeridas.
    """
    if not zipfile.is_zipfile(path):
        logger.warning("action=load_excel level=warning reason=bad_signature path=%s", path)
        raise ValueError("Archivo inválido: el contenido no corresponde a un Excel .xlsx")

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

    fecha_source_col = None
    if "FECHA" in df.columns:
        fecha_source_col = "FECHA"
    elif "FECHA_CIERRE_PROBLEMA" in df.columns:
        fecha_source_col = "FECHA_CIERRE_PROBLEMA"
    elif "FECHA_INICIO" in df.columns:
        fecha_source_col = "FECHA_INICIO"

    missing = [
        c for c in COLUMNAS_OBLIGATORIAS if c != "FECHA" and c not in df.columns
    ]
    if fecha_source_col is None:
        missing.append("FECHA")

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

    # Parse fecha: usar columna primaria o alternativas ya detectadas
    if fecha_source_col != "FECHA":
        df["FECHA"] = df[fecha_source_col].copy()
        logger.info("Usando %s como FECHA principal", fecha_source_col)
    df["FECHA"] = pd.to_datetime(df["FECHA"], errors="coerce")
    antes = len(df)
    df = df.dropna(subset=["FECHA", "SERVICIO"])
    logger.debug(
        "action=repetitividad_normalize stage=post_drop filas_antes=%s filas_despues=%s",  # noqa: E501
        antes,
        len(df),
    )

    df["PERIODO"] = df["FECHA"].dt.strftime("%Y-%m")

    # Normalizar datos geoespaciales opcionales
    for geo_col in ("GEO_LABEL", "GEO_REGION"):
        if geo_col in df.columns:
            df[geo_col] = df[geo_col].astype(str).str.strip()

    # Limpieza y parse robusto de lat/lon (admite comas como separador decimal y texto mezclado)
    import re as _re
    def _to_float_series(s: pd.Series) -> pd.Series:
        # Convierte a string, reemplaza comas por puntos y extrae el primer número con signo y decimal
        s_str = s.astype(str).str.replace(",", ".", regex=False)
        # Extraer patrón de número (e.g., -31.42)
        pattern = _re.compile(r"[-+]?\d{1,3}(?:\.\d+)?")
        def _extract(v: str):
            m = pattern.search(v)
            return float(m.group(0)) if m else None
        return s_str.map(_extract)

    for geo_col in ("GEO_LAT", "GEO_LON"):
        if geo_col in df.columns:
            df[geo_col] = _to_float_series(df[geo_col])
            logger.debug(
                "action=repetitividad_normalize stage=geo_clean column=%s valid=%s",
                geo_col,
                int(df[geo_col].notna().sum()),
            )
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

    if "ID_SERVICIO" in df.columns:
        conteos = grupos["ID_SERVICIO"].nunique(dropna=True)
    else:
        conteos = grupos.size()

    repetitivos = conteos[conteos >= 2]

    items: list[ItemSalida] = []
    for servicio in repetitivos.index:
        grupo = grupos.get_group(servicio)
        if "ID_SERVICIO" in grupo.columns:
            detalles = (
                grupo["ID_SERVICIO"].dropna().astype(str).str.strip().unique().tolist()
            )
        else:
            detalles = _detalles(grupo)
        items.append(
            ItemSalida(
                servicio=servicio,
                casos=int(repetitivos[servicio]),
                detalles=detalles,
            )
        )

    total_servicios = len(conteos)
    total_repetitivos = len(repetitivos)

    if "PERIODO" in df.columns:
        periodos_presentes = sorted({str(p) for p in df["PERIODO"].dropna().unique()})
    else:
        periodos_presentes = []

    geo_points: list[GeoPoint] = []
    if {"GEO_LAT", "GEO_LON"}.issubset(df.columns):
        df_geo = df[df["GEO_LAT"].notna() & df["GEO_LON"].notna()].copy()
        if not df_geo.empty:
            repetitivos_servicios = set(repetitivos.index)
            df_geo = df_geo[df_geo["SERVICIO"].isin(repetitivos_servicios)]
            for servicio, grupo in df_geo.groupby("SERVICIO"):
                lat = float(grupo["GEO_LAT"].mean())
                lon = float(grupo["GEO_LON"].mean())
                primer = grupo.iloc[0]
                geo_points.append(
                    GeoPoint(
                        servicio=servicio,
                        casos=int(repetitivos[servicio]),
                        lat=lat,
                        lon=lon,
                        cliente=str(primer.get("CLIENTE")) if pd.notna(primer.get("CLIENTE")) else None,
                        label=str(primer.get("GEO_LABEL")) if "GEO_LABEL" in grupo.columns and pd.notna(primer.get("GEO_LABEL")) else None,
                        region=str(primer.get("GEO_REGION")) if "GEO_REGION" in grupo.columns and pd.notna(primer.get("GEO_REGION")) else None,
                    )
                )

    resultado = ResultadoRepetitividad(
        items=items,
        total_servicios=total_servicios,
        total_repetitivos=total_repetitivos,
        periodos=periodos_presentes,
        geo_points=geo_points,
    )
    logger.info(
        "action=compute_repetitividad total_servicios=%s total_repetitivos=%s",
        total_servicios,
        total_repetitivos,
    )
    if total_repetitivos:
        top = repetitivos.sort_values(ascending=False).head(5)
        logger.debug("action=compute_repetitividad leaders=%s", top.to_dict())
    return resultado
