# Nombre de archivo: processor.py
# Ubicación de archivo: modules/informes_repetitividad/processor.py
# Descripción: Funciones de carga, normalización y cálculo de repetitividad

import logging
import zipfile
from typing import Optional, List, Dict

import pandas as pd
import unicodedata
import re as _re

from core.utils.timefmt import value_to_minutes

from .config import (
    CLIENTES_PRESERVAR,
    COLUMNAS_MAPPER,
    COLUMNAS_OBLIGATORIAS,
)
from .schemas import ReclamoDetalle, ResultadoRepetitividad, ServicioDetalle

logger = logging.getLogger(__name__)

HORAS_NETAS_MIN_COL = "HORAS_NETAS_MIN"


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


def _clean_key(s: str) -> str:
    """Normaliza un nombre de columna facilitando comparaciones."""

    s = str(s)
    s_no_accents = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    return s_no_accents.lower().replace(" ", "").replace("_", "").replace("\n", "").replace("\r", "")


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza nombres de columnas y formatos de fecha.

    Estrategia:
    1. Aplana MultiIndex si existe.
    2. Para cada columna, se genera una clave de búsqueda (minúsculas, sin acentos, sin espacios).
    3. Se busca esta clave en el `COLUMNAS_MAPPER` y se renombra la columna.
    4. Valida que todas las columnas obligatorias estén presentes después del mapeo.
    """
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = ["_".join(map(str, col)).strip() for col in df.columns.values]

    original_cols = df.columns.tolist()
    rename_map = {}

    # Invertir el mapper para que las claves sean los nombres normalizados
    # Esto permite tener múltiples variantes en el archivo de config apuntando al mismo destino
    mapper_keys_cleaned = {_clean_key(k): v for k, v in COLUMNAS_MAPPER.items()}

    for col in original_cols:
        cleaned_col = _clean_key(col)
        if cleaned_col in mapper_keys_cleaned:
            target_name = mapper_keys_cleaned[cleaned_col]
            rename_map[col] = target_name
            logger.info(f"Mapeando columna: '{col}' -> '{target_name}' (clave: '{cleaned_col}')")

    df = df.rename(columns=rename_map)
    df = _normalize_horas_columns(df)

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


def _normalize_horas_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Detecta y normaliza columnas de horas netas, incluyendo heurística por índice."""

    hora_columns = [
        "Horas Netas Problema Reclamo",
        "Horas Netas Reclamo",
        "Horas Netas",
    ]

    normalized_keys = {_clean_key(name) for name in hora_columns}
    candidates = [col for col in df.columns if _clean_key(col) in normalized_keys]

    if not candidates and len(df.columns) > 17:
        guessed = df.columns[17]
        cleaned = _clean_key(guessed)
        if cleaned in {"", "unnamed17", "col17", "columnr"} or "horas" in cleaned:
            df = df.rename(columns={guessed: "Horas Netas Problema Reclamo"})
            candidates.append("Horas Netas Problema Reclamo")

    minutes_series = pd.Series([pd.NA] * len(df), index=df.index, dtype="Int64") if len(df) else pd.Series(dtype="Int64")

    for column in candidates:
        if column not in df.columns:
            continue
        serie = df[column].map(value_to_minutes)
        serie = pd.Series(serie, index=df.index, dtype="Int64")
        serie = serie.where(serie >= 0)
        minutes_series = serie.where(serie.notna(), minutes_series)

    df[HORAS_NETAS_MIN_COL] = minutes_series

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
    """Calcula servicios con casos repetidos (>=2) y arma detalle por reclamo."""
    grupos = df.groupby("SERVICIO", sort=True)

    if "ID_SERVICIO" in df.columns:
        conteos = grupos["ID_SERVICIO"].nunique(dropna=True)
    else:
        conteos = grupos.size()

    repetitivos = conteos[conteos >= 2]

    servicios: List[ServicioDetalle] = []
    for servicio in repetitivos.index:
        grupo = grupos.get_group(servicio).copy()

        primer = grupo.iloc[0]
        nombre_cliente = str(primer.get("CLIENTE")) if pd.notna(primer.get("CLIENTE")) else None
        tipo_servicio = str(primer.get("TIPO_SERVICIO")) if pd.notna(primer.get("TIPO_SERVICIO")) else None

        detalles_rows: List[ReclamoDetalle] = []
        for _, fila in grupo.iterrows():
            reclamo_id = (
                str(fila.get("ID_SERVICIO")).strip()
                if pd.notna(fila.get("ID_SERVICIO"))
                else None
            )
            if not reclamo_id:
                reclamo_id = str(fila.name)

            geo_lat = float(fila.get("GEO_LAT")) if pd.notna(fila.get("GEO_LAT")) else None
            geo_lon = float(fila.get("GEO_LON")) if pd.notna(fila.get("GEO_LON")) else None

            detalles_rows.append(
                ReclamoDetalle(
                    numero_reclamo=reclamo_id,
                    numero_evento=str(fila.get("ID_EVENTO")) if pd.notna(fila.get("ID_EVENTO")) else None,
                    fecha_inicio=_format_fecha(fila.get("FECHA_INICIO"), fila.get("FECHA")),
                    fecha_cierre=_format_fecha(fila.get("FECHA")),
                    tipo_solucion=_sanitize_str(fila.get("Tipo Solución"))
                    or _sanitize_str(fila.get("TIPO_SOLUCION"))
                    or _sanitize_str(fila.get("Tipo Solución Reclamo")),
                    horas_netas=_parse_horas_netas(fila),
                    descripcion_solucion=_sanitize_str(
                        fila.get("Descripción Solución")
                        or fila.get("Descripcion Solucion Reclamo")
                        or fila.get("Descripción Solución Reclamo")
                    ),
                    latitud=geo_lat,
                    longitud=geo_lon,
                )
            )

        servicios.append(
            ServicioDetalle(
                servicio=servicio,
                nombre_cliente=nombre_cliente,
                tipo_servicio=tipo_servicio,
                casos=int(repetitivos[servicio]),
                reclamos=detalles_rows,
            )
        )

    total_servicios = len(conteos)
    total_repetitivos = len(servicios)

    if "PERIODO" in df.columns:
        periodos_presentes = sorted({str(p) for p in df["PERIODO"].dropna().unique()})
    else:
        periodos_presentes = []

    resultado = ResultadoRepetitividad(
        servicios=servicios,
        total_servicios=total_servicios,
        total_repetitivos=total_repetitivos,
        periodos=periodos_presentes,
        with_geo=any(s.has_geo() for s in servicios),
        source="excel",
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


def _parse_horas_netas(row: pd.Series) -> Optional[int]:
    value = row.get(HORAS_NETAS_MIN_COL)
    if value is not None and not pd.isna(value):
        return int(value)

    candidates = [
        row.get("Horas Netas Problema Reclamo"),
        row.get("Horas Netas Reclamo"),
        row.get("Horas Netas"),
    ]
    for cand in candidates:
        minutes = value_to_minutes(cand)
        if minutes is not None and minutes >= 0:
            return minutes

    return None


def _sanitize_str(value: object) -> Optional[str]:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _format_fecha(*values: object) -> Optional[str]:
    for value in values:
        if value is None or pd.isna(value):
            continue
        try:
            return pd.to_datetime(value, errors="coerce").strftime("%Y-%m-%d %H:%M")
        except Exception:
            continue
    return None
