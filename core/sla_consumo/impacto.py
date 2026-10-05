# Nombre de archivo: impacto.py
# Ubicación de archivo: core/sla_consumo/impacto.py
# Descripción: Acumulados por servicio e impacto Evento × Servicio / reclamo sin evento (tres indicadores)

from __future__ import annotations

import numpy as np
import pandas as pd

from core.sla_consumo import metricas as m

INCONS_CARRIER_CON_EVENTO = "Reclamo Carrier con evento"
INCONS_EVENTO_MIXTO = "Evento con causas FO y no FO"
INCONS_NO_VINCULADO = "Reclamo no vinculado a un servicio"
INCONS_NO_EVALUABLE = "Servicio no evaluable (sin presupuesto válido)"

_COL_CAUSA = {m.CAUSA_FO_GENERAL: "horas_fo_general", m.CAUSA_FO_COD3: "horas_fo_cod3",
              m.CAUSA_CARRIER: "horas_carrier", m.CAUSA_OTROS: "horas_otros"}


def _validos(presupuesto: pd.Series) -> pd.Series:
    return presupuesto.map(m.presupuesto_valido).astype(bool)


def acumulados(vinculados: pd.DataFrame) -> pd.DataFrame:
    """Suma las horas completas de cada reclamo en orden fecha_inicio → número de reclamo.

    Es una atribución por orden: no identifica el instante físico en que se rompió el presupuesto.
    """
    df = vinculados.copy()
    df["horas_computables"] = pd.to_numeric(df["horas_computables"], errors="coerce").fillna(0.0)
    df["_orden"] = pd.to_numeric(df["numero_reclamo"], errors="coerce")
    df = df.sort_values(["clave_servicio", "fecha_inicio", "_orden", "numero_reclamo"],
                        kind="mergesort", na_position="last").drop(columns="_orden")
    df["consumo_acum_despues"] = df.groupby("clave_servicio")["horas_computables"].cumsum()
    df["consumo_acum_antes"] = df["consumo_acum_despues"] - df["horas_computables"]
    p = pd.to_numeric(df["presupuesto_h"], errors="coerce")
    valido = _validos(df["presupuesto_h"])
    antes, despues, eps = df["consumo_acum_antes"], df["consumo_acum_despues"], m.EPS_HORAS
    df["restantes_acum"] = np.where(valido, np.maximum(p - despues, 0.0), np.nan)
    df["excedidas_acum"] = np.where(valido, np.maximum(despues - p, 0.0), np.nan)
    df["pct_aporte_real"] = np.where(valido, df["horas_computables"] / p * 100, np.nan)
    df["alcanza_primera_vez"] = valido & (antes < p - eps) & (despues >= p - eps)
    df["supera_primera_vez"] = valido & (antes <= p + eps) & (despues > p + eps)
    return df.reset_index(drop=True)


def _suficiente(horas: float, presupuesto: object) -> str:
    if not m.presupuesto_valido(presupuesto):
        return "No evaluable"
    p = float(presupuesto)
    if horas > p + m.EPS_HORAS:
        return "Excede"
    return "Agota" if abs(horas - p) <= m.EPS_HORAS else "No"


def impacto(acum: pd.DataFrame, servicios: pd.DataFrame, por: str) -> pd.DataFrame:
    if por == "numero_evento":
        sub = acum[acum["numero_evento"].notna()]
    elif por == "numero_reclamo":
        sub = acum[acum["numero_evento"].isna()]
    else:
        raise ValueError(f"por inválido: {por}")
    sub = sub.assign(
        _cruza=sub["alcanza_primera_vez"] | sub["supera_primera_vez"],
        _fo=np.where(sub["causa"].isin(m.CAUSAS_FO), sub["horas_computables"], 0.0),
        _no_fo=np.where(sub["causa"].notna() & ~sub["causa"].isin(m.CAUSAS_FO), sub["horas_computables"], 0.0),
    )
    columnas = [por, "clave_servicio", "servicio_id", "nombre_cliente", "reclamos", "reclamos_ids",
                "horas_computables", "horas_fo", "horas_no_fo", "presupuesto_h", "pct_aporte_real",
                "consumo_total_servicio", "estado_servicio", "suficiente_solo", "cruza_umbral",
                "determinante_al_excluir", "participa_en_agotado_o_excedido"]
    if sub.empty:
        return pd.DataFrame(columns=columnas)
    g = (sub.groupby([por, "clave_servicio"], sort=False)
         .agg(reclamos=("numero_reclamo", "count"),
              reclamos_ids=("numero_reclamo", lambda s: ", ".join(map(str, s))),
              horas_computables=("horas_computables", "sum"), horas_fo=("_fo", "sum"),
              horas_no_fo=("_no_fo", "sum"), cruza_umbral=("_cruza", "any"))
         .reset_index())
    svc = servicios[["clave_servicio", "servicio_id", "nombre_cliente", "presupuesto_h", "horas_computables",
                     "estado"]].rename(columns={"horas_computables": "consumo_total_servicio",
                                                "estado": "estado_servicio"})
    g = g.merge(svc, on="clave_servicio", how="left")
    valido = _validos(g["presupuesto_h"])
    p = pd.to_numeric(g["presupuesto_h"], errors="coerce")
    g["pct_aporte_real"] = np.where(valido, g["horas_computables"] / p * 100, np.nan)
    g["suficiente_solo"] = [_suficiente(h, pr) for h, pr in zip(g["horas_computables"], g["presupuesto_h"])]
    agot = g["estado_servicio"].isin(m.ESTADOS_AGOTADO_O_EXCEDIDO)
    g["participa_en_agotado_o_excedido"] = agot
    g["determinante_al_excluir"] = (agot & valido & (g["horas_computables"] > m.EPS_HORAS)
                                    & ((g["consumo_total_servicio"] - g["horas_computables"]) < p - m.EPS_HORAS))
    g["cruza_umbral"] = g["cruza_umbral"].astype(bool) & valido
    return g[columnas]


def _lista(serie: pd.Series) -> str:
    return ", ".join(sorted(map(str, serie.unique()), key=lambda x: (len(x), x)))


def resumen_eventos(acum: pd.DataFrame, ev_srv: pd.DataFrame) -> pd.DataFrame:
    ev = acum[acum["numero_evento"].notna()]
    if ev.empty:
        return pd.DataFrame(columns=["numero_evento", "inicio_observado", "cierre_observado", "reclamos",
                                     "servicios_afectados", "horas_servicio", *_COL_CAUSA.values(),
                                     "servicios_agotados_o_excedidos", "n_suficiente_solo",
                                     "servicios_suficiente_solo", "n_cruza_umbral", "servicios_cruza_umbral",
                                     "n_determinante", "servicios_determinante"])
    base = ev.groupby("numero_evento").agg(
        inicio_observado=("fecha_inicio", "min"), cierre_observado=("fecha_cierre", "max"),
        reclamos=("numero_reclamo", "count"), servicios_afectados=("clave_servicio", "nunique"),
        horas_servicio=("horas_computables", "sum"))
    causas = (ev[ev["causa"].notna()].pivot_table(index="numero_evento", columns="causa",
                                                   values="horas_computables", aggfunc="sum", fill_value=0.0)
              .reindex(columns=list(_COL_CAUSA), fill_value=0.0).rename(columns=_COL_CAUSA))
    base = base.join(causas).fillna({c: 0.0 for c in _COL_CAUSA.values()})
    es = ev_srv.assign(_suf=ev_srv["suficiente_solo"].isin(["Agota", "Excede"]))
    indic = es.groupby("numero_evento").apply(lambda g: pd.Series({
        "servicios_agotados_o_excedidos": int(g["participa_en_agotado_o_excedido"].sum()),
        "n_suficiente_solo": int(g["_suf"].sum()),
        "servicios_suficiente_solo": _lista(g.loc[g["_suf"], "servicio_id"]),
        "n_cruza_umbral": int(g["cruza_umbral"].sum()),
        "servicios_cruza_umbral": _lista(g.loc[g["cruza_umbral"], "servicio_id"]),
        "n_determinante": int(g["determinante_al_excluir"].sum()),
        "servicios_determinante": _lista(g.loc[g["determinante_al_excluir"], "servicio_id"]),
    }), include_groups=False)
    return base.join(indic).reset_index().sort_values("horas_servicio", ascending=False, kind="mergesort")


def inconsistencias(acum: pd.DataFrame, no_vinculados: pd.DataFrame, servicios: pd.DataFrame) -> pd.DataFrame:
    filas: list[dict] = []
    carrier_ev = acum[(acum["causa"] == m.CAUSA_CARRIER) & acum["numero_evento"].notna()]
    for _, r in carrier_ev.iterrows():
        filas.append({"tipo": INCONS_CARRIER_CON_EVENTO, "numero_evento": r["numero_evento"],
                      "numero_reclamo": r["numero_reclamo"], "servicio_id": r["servicio_id"],
                      "detalle": "La regla de negocio no asocia Carrier a eventos FO: revisar; la causa no se reasigna."})
    con_causa = acum[acum["numero_evento"].notna() & acum["causa"].notna()]
    for evento, g in con_causa.groupby("numero_evento"):
        fo = g["causa"].isin(m.CAUSAS_FO)
        if fo.any() and (~fo).any():
            filas.append({"tipo": INCONS_EVENTO_MIXTO, "numero_evento": evento, "numero_reclamo": None,
                          "servicio_id": None,
                          "detalle": "Causas: " + ", ".join(sorted(g["causa"].unique()))})
    for _, r in no_vinculados.iterrows():
        filas.append({"tipo": INCONS_NO_VINCULADO, "numero_evento": r.get("numero_evento"),
                      "numero_reclamo": r["numero_reclamo"], "servicio_id": None,
                      "detalle": f"Línea {r.get('numero_linea')} / primer servicio {r.get('numero_primer_servicio')} "
                                 "fuera del universo de Servicios: sin presupuesto."})
    for _, s in servicios[servicios["estado"] == m.ESTADO_NO_EVALUABLE].iterrows():
        filas.append({"tipo": INCONS_NO_EVALUABLE, "numero_evento": None, "numero_reclamo": None,
                      "servicio_id": s["servicio_id"], "detalle": "Falta SLA prometido o presupuesto válido."})
    return pd.DataFrame(filas, columns=["tipo", "numero_evento", "numero_reclamo", "servicio_id", "detalle"])
