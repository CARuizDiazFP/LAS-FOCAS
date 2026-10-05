# Nombre de archivo: parser.py
# Ubicación de archivo: core/sla_consumo/parser.py
# Descripción: Lee los Excel Servicios/Reclamos del informe SLA consumido con tipos reales (sin dtype=str)

from __future__ import annotations

import datetime as dt
import io

import pandas as pd

from core.sla.legacy_report import _normalize, _normalize_line_value
from core.sla_consumo.clasificador import clasificar_cierre, valores_cliente_config
from core.utils.excel_duraciones import TZ_AR, duracion_a_horas, fecha_excel

# encabezado normalizado (_normalize) → columna destino
_RECLAMOS_MAP = {
    "numero reclamo": "numero_reclamo",
    "numero evento": "numero_evento",
    "numero linea": "numero_linea",
    "numero primer servicio": "numero_primer_servicio",
    "tipo servicio": "tipo_servicio",
    "nombre cliente": "nombre_cliente",
    "fecha inicio problema reclamo": "fecha_inicio",
    "fecha cierre problema reclamo": "fecha_cierre",
    "horas totales problema reclamo": "horas_totales_problema",
    "horas indisponibilidad problema reclamo": "horas_indisponibilidad_problema",
    "horas netas problema reclamo": "horas_netas",
    "horas netas escalamientos carriers": "horas_netas_escalamiento_carrier",
    "sector responsable reclamo": "sector_responsable",
    "descripcion problema reclamo": "descripcion_problema",
    "tipo solucion reclamo": "tipo_solucion",
    "descripcion solucion reclamo": "descripcion_solucion",
    "carrier reclamo": "carrier",
    "numero reclamo carrier": "numero_reclamo_carrier",
}
_RECLAMOS_OBLIGATORIAS = ["numero_reclamo", "numero_linea", "nombre_cliente", "fecha_inicio",
                          "fecha_cierre", "horas_netas", "tipo_solucion"]
_RECLAMOS_HORAS = ["horas_totales_problema", "horas_indisponibilidad_problema", "horas_netas",
                   "horas_netas_escalamiento_carrier"]
RECLAMOS_COLS = list(dict.fromkeys(_RECLAMOS_MAP.values())) + ["codigo_cierre", "grupo_cierre"]

_SERVICIOS_MAP = {
    "numero linea": "numero_linea",
    "numero primer servicio": "numero_primer_servicio",
    "nombre cliente": "nombre_cliente",
    "tipo servicio": "tipo_servicio",
    "sla prometido": "sla_prometido",
    "sla entregado": "sla_entregado",
    "horas reclamos mes": "horas_reclamos_mes",
    "horas carriers mes": "horas_carriers_mes",
    "horas reclamos todos": "horas_reclamos_todos",
    "horas carriers todos": "horas_carriers_todos",
    "horas restantes limite sla": "horas_restantes",
    "abono usd": "abono_usd",
    "cantidad reclamos todos": "cantidad_reclamos_todos",
}
_SERVICIOS_OBLIGATORIAS = ["numero_linea", "nombre_cliente", "sla_prometido", "horas_reclamos_todos"]
_SERVICIOS_HORAS = ["horas_reclamos_mes", "horas_carriers_mes", "horas_reclamos_todos",
                    "horas_carriers_todos", "horas_restantes"]
SERVICIOS_COLS = list(_SERVICIOS_MAP.values())


def _leer(content: bytes, mapa: dict[str, str], obligatorias: list[str], tipo: str) -> pd.DataFrame:
    # Primera hoja siempre (Servicios trae una "Hoja2" filtrada a mano que se ignora).
    df = pd.read_excel(io.BytesIO(content), sheet_name=0, engine="openpyxl")
    renombres = {}
    for col in df.columns:
        destino = mapa.get(_normalize(str(col)))
        if destino and destino not in renombres.values():
            renombres[col] = destino
    df = df.rename(columns=renombres)
    faltan = [c for c in obligatorias if c not in df.columns]
    if faltan:
        raise ValueError(f"Faltan columnas en {tipo}: {', '.join(faltan)}")
    for col in mapa.values():
        if col not in df.columns:
            df[col] = None
    return df[list(dict.fromkeys(mapa.values()))]


def _texto(valor: object) -> str | None:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    texto = _normalize_line_value(valor)
    return None if texto in ("", "-") else texto


def parse_reclamos(content: bytes) -> pd.DataFrame:
    df = _leer(content, _RECLAMOS_MAP, _RECLAMOS_OBLIGATORIAS, "reclamos")
    df["numero_reclamo"] = df["numero_reclamo"].map(_texto)
    df = df[df["numero_reclamo"].notna() & (df["numero_reclamo"].str.lower() != "totales")].copy()
    for col in ("numero_evento", "numero_linea", "numero_primer_servicio", "numero_reclamo_carrier",
                "carrier", "tipo_servicio", "nombre_cliente", "sector_responsable", "tipo_solucion",
                "descripcion_problema", "descripcion_solucion"):
        df[col] = df[col].map(_texto)
    for col in _RECLAMOS_HORAS:
        df[col] = df[col].map(duracion_a_horas)
    df["fecha_inicio"] = df["fecha_inicio"].map(fecha_excel)
    df["fecha_cierre"] = df["fecha_cierre"].map(fecha_excel)
    df = df[df["numero_linea"].notna() & df["fecha_inicio"].notna()]
    valores_cliente = valores_cliente_config()
    cierres = df["tipo_solucion"].map(lambda t: clasificar_cierre(t, valores_cliente))
    df["codigo_cierre"] = cierres.map(lambda c: c.codigo).astype("Int64")
    df["grupo_cierre"] = cierres.map(lambda c: c.grupo)
    df = df.drop_duplicates(subset="numero_reclamo", keep="last").reset_index(drop=True)
    return df[RECLAMOS_COLS]


def _sla_pct(valor: object) -> float | None:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    numero = float(str(valor).replace("%", "").replace(",", ".").strip())
    return numero


def parse_servicios(content: bytes) -> pd.DataFrame:
    df = _leer(content, _SERVICIOS_MAP, _SERVICIOS_OBLIGATORIAS, "servicios")
    for col in ("numero_linea", "numero_primer_servicio", "nombre_cliente", "tipo_servicio"):
        df[col] = df[col].map(_texto)
    df = df[df["numero_linea"].notna()].copy()
    df["sla_prometido"] = df["sla_prometido"].map(_sla_pct)          # 99.7
    df["sla_entregado"] = df["sla_entregado"].map(_sla_pct)
    df.loc[df["sla_entregado"] > 1, "sla_entregado"] /= 100            # siempre fracción 0-1
    for col in _SERVICIOS_HORAS:
        df[col] = df[col].map(duracion_a_horas)
    df["abono_usd"] = pd.to_numeric(df["abono_usd"], errors="coerce")
    df["cantidad_reclamos_todos"] = pd.to_numeric(df["cantidad_reclamos_todos"], errors="coerce").astype("Int64")
    return df.drop_duplicates(subset="numero_linea", keep="last").reset_index(drop=True)[SERVICIOS_COLS]


def fecha_corte(reclamos: pd.DataFrame) -> dt.date:
    maximo = reclamos["fecha_cierre"].dropna().max()
    if maximo is None or pd.isna(maximo):
        maximo = reclamos["fecha_inicio"].max()
    return pd.Timestamp(maximo).tz_convert(TZ_AR).date()
