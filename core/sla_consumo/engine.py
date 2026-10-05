# Nombre de archivo: engine.py
# Ubicación de archivo: core/sla_consumo/engine.py
# Descripción: Calcula el SLA consumido por evento, servicio, reclamo y código de cierre (pandas puro)

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core.sla_consumo.clasificador import GRUPO_CARRIER, GRUPO_CLIENTE, GRUPOS_ORDEN

HORAS_ANIO = 8760.0


def presupuesto_horas(sla_prometido: float | None) -> float | None:
    if sla_prometido is None or pd.isna(sla_prometido):
        return None
    return (1 - float(sla_prometido) / 100) * HORAS_ANIO


def _col_grupo(grupo: str) -> str:
    return "horas_" + {
        "FO (excepto Cod 3)": "fo", "FO Cod 3 (Corte en Bandeja)": "fo_cod3", "Carrier": "carrier",
        "Otros": "otros", "Cierre Cliente": "cliente"}[grupo]


@dataclass
class ResultadoSlaConsumo:
    fecha_corte: dt.date
    hechos: pd.DataFrame
    eventos: pd.DataFrame
    servicios: pd.DataFrame
    servicio_reclamo: pd.DataFrame
    codigo_cierre: pd.DataFrame
    codigo_cierre_detalle: pd.DataFrame
    carrier_cliente: pd.DataFrame
    totales: dict = field(default_factory=dict)


def _hechos(reclamos: pd.DataFrame, servicios: pd.DataFrame) -> pd.DataFrame:
    sla = servicios[["numero_linea", "sla_prometido"]].drop_duplicates("numero_linea")
    h = reclamos.merge(sla, on="numero_linea", how="left")
    h["horas_netas"] = pd.to_numeric(h["horas_netas"], errors="coerce").fillna(0.0)
    h["presupuesto_h"] = h["sla_prometido"].map(presupuesto_horas).astype(float)
    h["sin_sla_prometido"] = h["presupuesto_h"].isna()
    h["cuenta_sla"] = h["grupo_cierre"] != GRUPO_CLIENTE
    h["horas_sla"] = np.where(h["cuenta_sla"], h["horas_netas"], 0.0)
    h["pct_presupuesto"] = h["horas_sla"] / h["presupuesto_h"] * 100
    h["pp_disponibilidad"] = h["horas_sla"] / HORAS_ANIO * 100
    h["evento_clave"] = h["numero_evento"].where(h["numero_evento"].notna(), "R-" + h["numero_reclamo"].astype(str))
    return h


def _servicios(h: pd.DataFrame, servicios: pd.DataFrame) -> pd.DataFrame:
    pivote = h.pivot_table(index="numero_linea", columns="grupo_cierre", values="horas_netas",
                           aggfunc="sum", fill_value=0.0)
    pivote = pivote.reindex(columns=list(GRUPOS_ORDEN), fill_value=0.0)
    pivote.columns = [_col_grupo(g) for g in pivote.columns]
    base = h.groupby("numero_linea").agg(
        nombre_cliente=("nombre_cliente", "first"), tipo_servicio=("tipo_servicio", "first"),
        reclamos=("numero_reclamo", "count"), horas_sla=("horas_sla", "sum"))
    df = base.join(pivote).reset_index()
    oficial = servicios[["numero_linea", "sla_prometido", "sla_entregado", "horas_reclamos_todos"]]
    df = df.merge(oficial, on="numero_linea", how="left")
    df["presupuesto_h"] = df["sla_prometido"].map(presupuesto_horas).astype(float)
    df["pct_presupuesto"] = df["horas_sla"] / df["presupuesto_h"] * 100
    df["pp_disponibilidad"] = df["horas_sla"] / HORAS_ANIO * 100
    df["sla_calculado"] = 1 - df["horas_sla"] / HORAS_ANIO
    df["sla_oficial"] = df["sla_entregado"]
    df["diferencia_horas_oficial"] = df["horas_sla"] - df["horas_reclamos_todos"]
    df["horas_restantes_calc"] = (df["presupuesto_h"] - df["horas_sla"]).clip(lower=0)
    df["excedido"] = df["horas_sla"] > df["presupuesto_h"]
    return df.drop(columns=["sla_entregado"]).sort_values("pct_presupuesto", ascending=False, na_position="last")


def _eventos(h: pd.DataFrame, por_servicio_evento_excedido: pd.DataFrame) -> pd.DataFrame:
    def _predominante(g: pd.DataFrame) -> pd.Series:
        horas = g.groupby("grupo_cierre")["horas_netas"].sum()
        return pd.Series({"grupo_predominante": horas.idxmax() if len(horas) else None,
                          "mixto": g["grupo_cierre"].nunique() > 1})

    agg = h.groupby("evento_clave").agg(
        numero_evento=("numero_evento", "first"), inicio=("fecha_inicio", "min"), cierre=("fecha_cierre", "max"),
        reclamos=("numero_reclamo", "count"), servicios_afectados=("numero_linea", "nunique"),
        horas_sla=("horas_sla", "sum"), pct_presupuesto_medio=("pct_presupuesto", "mean"),
        pct_presupuesto_max=("pct_presupuesto", "max"))
    agg = agg.join(h.groupby("evento_clave")[["grupo_cierre", "horas_netas"]].apply(_predominante))
    agg = agg.join(por_servicio_evento_excedido)
    agg["servicios_excedidos"] = agg["servicios_excedidos"].fillna(0).astype(int)
    agg["es_aislado"] = agg["numero_evento"].isna()
    return agg.reset_index().sort_values("horas_sla", ascending=False)


def calcular(reclamos: pd.DataFrame, servicios: pd.DataFrame, fecha_corte: dt.date) -> ResultadoSlaConsumo:
    h = _hechos(reclamos, servicios)
    svc = _servicios(h, servicios)
    excedidos = set(svc.loc[svc["excedido"], "numero_linea"])
    exc_evento = (h[h["numero_linea"].isin(excedidos)].groupby("evento_clave")["numero_linea"]
                  .nunique().rename("servicios_excedidos").to_frame())
    eventos = _eventos(h, exc_evento)

    servicio_reclamo = h[["numero_linea", "nombre_cliente", "numero_reclamo", "numero_evento", "fecha_inicio",
                          "fecha_cierre", "tipo_solucion", "grupo_cierre", "codigo_cierre", "horas_netas",
                          "horas_sla", "presupuesto_h", "pct_presupuesto", "pp_disponibilidad"]
                         ].sort_values(["numero_linea", "fecha_inicio"])

    total_horas = h["horas_netas"].sum()
    codigo = h.groupby("grupo_cierre").agg(eventos=("evento_clave", "nunique"), reclamos=("numero_reclamo", "count"),
                                            horas=("horas_netas", "sum"), horas_sla=("horas_sla", "sum"))
    codigo = codigo.reindex(list(GRUPOS_ORDEN), fill_value=0).reset_index().rename(columns={"index": "grupo"})
    codigo = codigo.rename(columns={"grupo_cierre": "grupo"})
    codigo["pct_horas"] = codigo["horas"] / total_horas * 100 if total_horas else 0.0
    detalle = (h.groupby(["grupo_cierre", "tipo_solucion"], dropna=False)
               .agg(eventos=("evento_clave", "nunique"), reclamos=("numero_reclamo", "count"), horas=("horas_netas", "sum"))
               .reset_index().rename(columns={"grupo_cierre": "grupo"}).sort_values(["grupo", "horas"], ascending=[True, False]))
    carrier = (h[h["grupo_cierre"] == GRUPO_CARRIER]
               .groupby(["nombre_cliente", "carrier"], dropna=False)
               .agg(reclamos=("numero_reclamo", "count"), servicios=("numero_linea", "nunique"), horas=("horas_netas", "sum"))
               .reset_index().sort_values("horas", ascending=False))

    totales = {"reclamos": int(len(h)), "eventos": int(h["numero_evento"].nunique()),
               "reclamos_aislados": int(h["numero_evento"].isna().sum()),
               "servicios": int(svc["numero_linea"].nunique()), "servicios_excedidos": int(svc["excedido"].sum()),
               "horas": float(total_horas), "horas_sla": float(h["horas_sla"].sum())}
    return ResultadoSlaConsumo(fecha_corte, h, eventos, svc, servicio_reclamo, codigo, detalle, carrier, totales)
