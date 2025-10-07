# Nombre de archivo: processor.py
# Ubicación de archivo: modules/informes_sla/processor.py
# Descripción: Funciones de procesamiento de datos para el informe de SLA

import pandas as pd

from .config import COLUMNAS_MAPPER, COLUMNAS_OBLIGATORIAS, SLA_POR_SERVICIO
from .schemas import FilaDetalle, KPI, ResultadoSLA


def load_excel(path: str) -> pd.DataFrame:
    """Carga un archivo Excel en un DataFrame."""
    return pd.read_excel(path, engine="openpyxl")


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza nombres de columnas y calcula TTR en horas."""
    df = df.rename(columns={k: v for k, v in COLUMNAS_MAPPER.items() if k in df.columns})

    faltantes = [c for c in COLUMNAS_OBLIGATORIAS if c not in df.columns]
    if faltantes:
        raise ValueError(f"Faltan columnas requeridas: {', '.join(faltantes)}")

    df["FECHA_APERTURA"] = pd.to_datetime(df["FECHA_APERTURA"], errors="coerce")
    df["FECHA_CIERRE"] = pd.to_datetime(df["FECHA_CIERRE"], errors="coerce")
    df["TTR_h"] = (df["FECHA_CIERRE"] - df["FECHA_APERTURA"]).dt.total_seconds() / 3600
    return df


def filter_period(df: pd.DataFrame, mes: int, anio: int) -> pd.DataFrame:
    """Filtra los casos cuyo cierre pertenece al período indicado.

    También preserva los casos abiertos cuyo mes/año de apertura coinciden
    con el período para poder reportarlos como excluidos.
    """
    mask_cierre = (df["FECHA_CIERRE"].dt.month == mes) & (
        df["FECHA_CIERRE"].dt.year == anio
    )
    mask_abiertos = df["FECHA_CIERRE"].isna() & (
        (df["FECHA_APERTURA"].dt.month == mes)
        & (df["FECHA_APERTURA"].dt.year == anio)
    )
    return df[mask_cierre | mask_abiertos]


def apply_sla_target(df: pd.DataFrame) -> pd.DataFrame:
    """Aplica la columna de SLA objetivo en horas."""
    if "SLA_OBJETIVO_HORAS" not in df.columns:
        df["SLA_OBJETIVO_HORAS"] = df["SERVICIO"].map(SLA_POR_SERVICIO).fillna(
            SLA_POR_SERVICIO.get("Default", 24.0)
        )
    else:
        df["SLA_OBJETIVO_HORAS"] = df["SLA_OBJETIVO_HORAS"].fillna(
            df["SERVICIO"].map(SLA_POR_SERVICIO)
        )
        df["SLA_OBJETIVO_HORAS"] = df["SLA_OBJETIVO_HORAS"].fillna(
            SLA_POR_SERVICIO.get("Default", 24.0)
        )
    return df


def compute_kpis(df: pd.DataFrame) -> ResultadoSLA:
    """Calcula KPIs globales y por servicio."""
    df_valido = df.dropna(subset=["FECHA_CIERRE"]).copy()
    sin_cierre = len(df) - len(df_valido)

    df_valido["cumplido"] = df_valido["TTR_h"] <= df_valido["SLA_OBJETIVO_HORAS"]

    total = len(df_valido)
    cumplidos = int(df_valido["cumplido"].sum())
    incumplidos = total - cumplidos
    pct = (cumplidos / total * 100) if total else 0.0
    prom = float(df_valido["TTR_h"].mean()) if total else 0.0
    med = float(df_valido["TTR_h"].median()) if total else 0.0

    detalle = [
        FilaDetalle(
            id=str(row["ID"]),
            cliente=row["CLIENTE"],
            servicio=row["SERVICIO"],
            ttr_h=float(row["TTR_h"]),
            sla_objetivo_h=float(row["SLA_OBJETIVO_HORAS"]),
            cumplido=bool(row["cumplido"]),
        )
        for _, row in df_valido.iterrows()
    ]

    breakdown = {}
    for servicio, grupo in df_valido.groupby("SERVICIO"):
        total_s = len(grupo)
        cumplidos_s = int(grupo["cumplido"].sum())
        incumplidos_s = total_s - cumplidos_s
        pct_s = (cumplidos_s / total_s * 100) if total_s else 0.0
        prom_s = float(grupo["TTR_h"].mean()) if total_s else 0.0
        med_s = float(grupo["TTR_h"].median()) if total_s else 0.0
        breakdown[servicio] = KPI(
            total=total_s,
            cumplidos=cumplidos_s,
            incumplidos=incumplidos_s,
            pct_cumplimiento=pct_s,
            ttr_promedio_h=prom_s,
            ttr_mediana_h=med_s,
        )

    kpi_global = KPI(
        total=total,
        cumplidos=cumplidos,
        incumplidos=incumplidos,
        pct_cumplimiento=pct,
        ttr_promedio_h=prom,
        ttr_mediana_h=med,
    )

    return ResultadoSLA(kpi=kpi_global, detalle=detalle, breakdown_por_servicio=breakdown, sin_cierre=sin_cierre)
