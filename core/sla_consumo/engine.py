# Nombre de archivo: engine.py
# Ubicación de archivo: core/sla_consumo/engine.py
# Descripción: Calcula el SLA consumido sobre el servicio unificado — semáforos, estados, acumulados e impacto

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core.sla_consumo import metricas as m
from core.sla_consumo.clasificador import (GRUPO_CARRIER, GRUPO_CLIENTE, GRUPOS_ORDEN, clasificar_cierre,
                                         valores_cliente_config)
from core.sla_consumo.identidad import unificar_servicios, vincular_reclamos
from core.sla_consumo.impacto import acumulados, impacto, inconsistencias, resumen_eventos
from core.sla_consumo.metricas import HORAS_ANIO, presupuesto_horas

# Re-exportados: api/app/routes/servicios.py importa presupuesto_horas desde este módulo.
__all__ = ["HORAS_ANIO", "ResultadoSlaConsumo", "calcular", "presupuesto_horas"]

_ORDEN_ESTADO = {m.ESTADO_EXCEDIDO: 0, m.ESTADO_AGOTADO: 1, m.ESTADO_DENTRO: 2, m.ESTADO_SIN_CONSUMO: 3,
                 m.ESTADO_NO_EVALUABLE: 4}
SERVICIOS_COLUMNAS = [
    "clave_servicio", "servicio_id", "lineas_asociadas", "nombre_cliente", "tipo_servicio", "sla_prometido",
    "presupuesto_h", "horas_netas", "horas_computables", "horas_excluidas", "horas_fo", "horas_fo_general",
    "horas_fo_cod3", "horas_carrier", "horas_otros", "horas_restantes", "horas_excedidas", "pct_real",
    "pct_visible", "aporte_fo_pct", "participacion_fo_pct", "reclamos", "eventos_reales", "reclamos_sin_evento",
    "semaforo", "estado", "sla_entregado_oficial", "horas_reclamos_todos_oficial", "horas_restantes_oficial"]


@dataclass
class ResultadoSlaConsumo:
    fecha_corte: dt.date
    servicios: pd.DataFrame
    servicio_reclamo: pd.DataFrame
    eventos: pd.DataFrame
    evento_servicio: pd.DataFrame
    reclamos_sin_evento: pd.DataFrame
    inconsistencias: pd.DataFrame
    no_vinculados: pd.DataFrame
    composicion: pd.DataFrame
    codigo_cierre: pd.DataFrame
    codigo_cierre_detalle: pd.DataFrame
    carrier_cliente: pd.DataFrame
    totales: dict = field(default_factory=dict)


def _clasificar(reclamos: pd.DataFrame) -> pd.DataFrame:
    """Reclasifica siempre desde tipo_solucion: filas legacy o con otra config de Cliente no quedan fuera."""
    df = reclamos.copy()
    valores_cliente = valores_cliente_config()
    tipos = df["tipo_solucion"].astype(object).where(df["tipo_solucion"].notna(), None)
    cierres = {t: clasificar_cierre(t, valores_cliente) for t in tipos.unique()}
    df["grupo_cierre"] = [cierres[t].grupo for t in tipos]
    df["codigo_cierre"] = pd.array([cierres[t].codigo for t in tipos], dtype="Int64")
    df["causa"] = df["grupo_cierre"].map(m.causa_de_grupo)
    df["cuenta_sla"] = df["grupo_cierre"] != GRUPO_CLIENTE
    df["horas_netas"] = pd.to_numeric(df["horas_netas"], errors="coerce").astype(float).fillna(0.0)
    df["horas_computables"] = np.where(df["cuenta_sla"], df["horas_netas"], 0.0)
    df["horas_excluidas"] = np.where(df["cuenta_sla"], 0.0, df["horas_netas"])
    df["indicador"] = [m.indicador_reclamo(c, float(h)) for c, h in zip(df["causa"], df["horas_computables"])]
    df["sin_evento"] = df["numero_evento"].isna()
    df["evento_clave"] = df["numero_evento"].where(df["numero_evento"].notna(),
                                                   "R-" + df["numero_reclamo"].astype(str))
    return df


def _agregados(acum: pd.DataFrame) -> pd.DataFrame:
    base = acum.groupby("clave_servicio").agg(
        horas_netas=("horas_netas", "sum"), horas_computables=("horas_computables", "sum"),
        horas_excluidas=("horas_excluidas", "sum"), reclamos=("numero_reclamo", "count"),
        eventos_reales=("numero_evento", "nunique"), reclamos_sin_evento=("sin_evento", "sum"))
    causas = (acum[acum["causa"].notna()]
              .pivot_table(index="clave_servicio", columns="causa", values="horas_computables",
                           aggfunc="sum", fill_value=0.0)
              .reindex(columns=list(m.COLUMNA_HORAS_POR_CAUSA), fill_value=0.0).rename(columns=m.COLUMNA_HORAS_POR_CAUSA))
    return base.join(causas)


def _metricas_servicios(unificados: pd.DataFrame, acum: pd.DataFrame) -> pd.DataFrame:
    df = unificados.merge(_agregados(acum), left_on="clave_servicio", right_index=True, how="left")
    horas = ["horas_netas", "horas_computables", "horas_excluidas", *m.COLUMNA_HORAS_POR_CAUSA.values()]
    df[horas] = df[horas].astype(float).fillna(0.0)
    for col in ("reclamos", "eventos_reales", "reclamos_sin_evento"):
        df[col] = df[col].fillna(0).astype(int)
    df["horas_fo"] = df["horas_fo_general"] + df["horas_fo_cod3"]
    p = df["presupuesto_h"].astype(float)
    valido = p.map(m.presupuesto_valido).astype(bool)
    c = df["horas_computables"]
    df["horas_restantes"] = np.where(valido, np.maximum(p - c, 0.0), np.nan)
    df["horas_excedidas"] = np.where(valido, np.maximum(c - p, 0.0), np.nan)
    pct = [m.pct_real(h, pr) for h, pr in zip(c, p)]
    df["pct_real"] = pd.array([np.nan if x is None else x for x in pct], dtype=float)
    df["pct_visible"] = [np.nan if x is None else m.pct_visible(x) for x in pct]
    df["aporte_fo_pct"] = np.where(valido, df["horas_fo"] / p.where(valido, 1.0) * 100, np.nan)
    df["participacion_fo_pct"] = np.where(c > m.EPS_HORAS, df["horas_fo"] / c.where(c > m.EPS_HORAS, 1.0) * 100,
                                          np.nan)
    df["semaforo"] = [m.semaforo_servicio(float(fo), float(ca + ot))
                      for fo, ca, ot in zip(df["horas_fo"], df["horas_carrier"], df["horas_otros"])]
    df["estado"] = [m.estado_presupuesto(float(h), pr) for h, pr in zip(c, p)]
    df["_orden"] = df["estado"].map(_ORDEN_ESTADO)
    df = df.sort_values(["_orden", "pct_real"], ascending=[True, False], na_position="last", kind="mergesort")
    return df[SERVICIOS_COLUMNAS].reset_index(drop=True)


def _composicion(acum: pd.DataFrame) -> pd.DataFrame:
    horas = acum[acum["causa"].notna()].groupby("causa")["horas_computables"].sum()
    horas = horas.reindex(list(m.CAUSAS_ORDEN), fill_value=0.0).astype(float)
    total = float(acum["horas_computables"].sum())
    pct = horas / total * 100 if total > m.EPS_HORAS else horas * 0.0
    return pd.DataFrame({"causa": list(m.CAUSAS_ORDEN), "horas": horas.to_numpy(), "pct": pct.to_numpy()})


def _codigo_cierre(clasificados: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    h = clasificados
    total = float(h["horas_netas"].sum())
    codigo = h.groupby("grupo_cierre").agg(eventos=("evento_clave", "nunique"), reclamos=("numero_reclamo", "count"),
                                            horas=("horas_netas", "sum"), horas_sla=("horas_computables", "sum"))
    codigo = codigo.reindex(list(GRUPOS_ORDEN), fill_value=0).rename_axis("grupo").reset_index()
    codigo["pct_horas"] = codigo["horas"] / total * 100 if total else 0.0
    detalle = (h.groupby(["grupo_cierre", "tipo_solucion"], dropna=False)
               .agg(eventos=("evento_clave", "nunique"), reclamos=("numero_reclamo", "count"),
                    horas=("horas_netas", "sum"))
               .reset_index().rename(columns={"grupo_cierre": "grupo"})
               .sort_values(["grupo", "horas"], ascending=[True, False]))
    return codigo, detalle


def _carrier_cliente(clasificados: pd.DataFrame) -> pd.DataFrame:
    h = clasificados[clasificados["grupo_cierre"] == GRUPO_CARRIER]
    h = h.assign(_servicio=h["servicio_id"].where(h["servicio_id"].notna(), h["numero_linea"]))
    return (h.groupby(["nombre_cliente", "carrier"], dropna=False)
            .agg(reclamos=("numero_reclamo", "count"), servicios=("_servicio", "nunique"),
                 horas=("horas_netas", "sum"))
            .reset_index().sort_values("horas", ascending=False))


def _totales(clasificados, acum, no_vinc, svc, eventos, composicion, inc) -> dict:
    estados = svc["estado"].value_counts()
    horas_causa = dict(zip(composicion["causa"], composicion["horas"]))
    return {
        "servicios_universo": int(len(svc)),
        "servicios_con_reclamos": int((svc["reclamos"] > 0).sum()),
        "servicios_dentro": int(estados.get(m.ESTADO_DENTRO, 0)),
        "servicios_agotados": int(estados.get(m.ESTADO_AGOTADO, 0)),
        "servicios_excedidos": int(estados.get(m.ESTADO_EXCEDIDO, 0)),
        "servicios_sin_consumo": int(estados.get(m.ESTADO_SIN_CONSUMO, 0)),
        "servicios_no_evaluables": int(estados.get(m.ESTADO_NO_EVALUABLE, 0)),
        "reclamos": int(len(clasificados)),
        "reclamos_vinculados": int(len(acum)),
        "reclamos_no_vinculados": int(len(no_vinc)),
        "eventos": int(len(eventos)),
        "reclamos_sin_evento": int(acum["sin_evento"].sum()),
        "horas_netas": float(clasificados["horas_netas"].sum()),
        "horas_computables": float(acum["horas_computables"].sum()),
        "horas_excluidas": float(acum["horas_excluidas"].sum()),
        "horas_no_vinculadas": float(no_vinc["horas_netas"].sum()),
        "horas_fo_general": float(horas_causa[m.CAUSA_FO_GENERAL]),
        "horas_fo_cod3": float(horas_causa[m.CAUSA_FO_COD3]),
        "horas_carrier": float(horas_causa[m.CAUSA_CARRIER]),
        "horas_otros": float(horas_causa[m.CAUSA_OTROS]),
        "inconsistencias": int(len(inc)),
    }


def calcular(reclamos: pd.DataFrame, servicios: pd.DataFrame, fecha_corte: dt.date) -> ResultadoSlaConsumo:
    clasificados = _clasificar(reclamos).reset_index(drop=True)
    clasificados["_fila"] = np.arange(len(clasificados))
    uni = unificar_servicios(servicios)
    vinc, no_vinc = vincular_reclamos(clasificados, uni)
    clasificados["servicio_id"] = clasificados["_fila"].map(dict(zip(vinc["_fila"], vinc["servicio_id"])))
    vinc, no_vinc = vinc.drop(columns="_fila"), no_vinc.drop(columns="_fila")
    clasificados = clasificados.drop(columns="_fila")

    acum = acumulados(vinc)
    svc = _metricas_servicios(uni.servicios, acum)
    acum["nombre_cliente"] = acum["clave_servicio"].map(dict(zip(svc["clave_servicio"], svc["nombre_cliente"])))
    ev_srv = impacto(acum, svc, "numero_evento")
    sin_ev = impacto(acum, svc, "numero_reclamo")
    eventos = resumen_eventos(acum, ev_srv)
    inc = inconsistencias(acum, no_vinc, svc)
    composicion = _composicion(acum)
    codigo, detalle = _codigo_cierre(clasificados)
    carrier = _carrier_cliente(clasificados)
    totales = _totales(clasificados, acum, no_vinc, svc, eventos, composicion, inc)
    return ResultadoSlaConsumo(fecha_corte, svc, acum, eventos, ev_srv, sin_ev, inc, no_vinc, composicion,
                               codigo, detalle, carrier, totales)
