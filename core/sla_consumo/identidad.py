# Nombre de archivo: identidad.py
# Ubicación de archivo: core/sla_consumo/identidad.py
# Descripción: Unifica servicios por primer servicio (ID visible = línea numéricamente mayor) y vincula reclamos

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from core.sla_consumo.metricas import presupuesto_horas


@dataclass(frozen=True)
class Unificacion:
    servicios: pd.DataFrame
    linea_a_clave: dict[str, str]


def _texto(valor: object) -> str | None:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)) or valor is pd.NA:
        return None
    texto = str(valor).strip()
    return texto or None


def _orden_linea(linea: str) -> tuple[int, int, str]:
    """Las numéricas ganan a las no numéricas; entre numéricas compara el entero, no el texto."""
    try:
        return (1, int(linea), "")
    except ValueError:
        return (0, 0, linea)


def _clave(primer: object, linea: object) -> str | None:
    return _texto(primer) or _texto(linea)


def unificar_servicios(servicios: pd.DataFrame) -> Unificacion:
    df = servicios.copy()
    df["numero_linea"] = df["numero_linea"].map(_texto)
    df = df[df["numero_linea"].notna()]
    df["clave_servicio"] = [_clave(p, l) for p, l in zip(df["numero_primer_servicio"], df["numero_linea"])]
    filas = []
    for clave, grupo in df.groupby("clave_servicio", sort=False):
        lineas = sorted(grupo["numero_linea"].unique(), key=_orden_linea)
        referencia = grupo[grupo["numero_linea"] == lineas[-1]].iloc[-1]
        filas.append({
            "clave_servicio": clave,
            "servicio_id": lineas[-1],
            "lineas_asociadas": ", ".join(lineas),
            "nombre_cliente": referencia["nombre_cliente"],
            "tipo_servicio": referencia["tipo_servicio"],
            "sla_prometido": referencia["sla_prometido"],
            "presupuesto_h": presupuesto_horas(referencia["sla_prometido"]),
            "sla_entregado_oficial": referencia["sla_entregado"],
            "horas_reclamos_todos_oficial": referencia["horas_reclamos_todos"],
            "horas_restantes_oficial": referencia["horas_restantes"],
        })
    columnas = ["clave_servicio", "servicio_id", "lineas_asociadas", "nombre_cliente", "tipo_servicio",
                "sla_prometido", "presupuesto_h", "sla_entregado_oficial", "horas_reclamos_todos_oficial",
                "horas_restantes_oficial"]
    unificados = pd.DataFrame(filas, columns=columnas)
    unificados["presupuesto_h"] = unificados["presupuesto_h"].astype(float)
    linea_a_clave = dict(zip(df["numero_linea"], df["clave_servicio"]))
    return Unificacion(unificados, linea_a_clave)


def vincular_reclamos(reclamos: pd.DataFrame, unificacion: Unificacion) -> tuple[pd.DataFrame, pd.DataFrame]:
    claves = set(unificacion.servicios["clave_servicio"])

    def _resolver(primer: object, linea: object) -> str | None:
        p = _texto(primer)
        if p is not None and p in claves:
            return p
        return unificacion.linea_a_clave.get(_texto(linea) or "")

    df = reclamos.copy()
    df["clave_servicio"] = [_resolver(p, l) for p, l in zip(df["numero_primer_servicio"], df["numero_linea"])]
    no_vinculados = df[df["clave_servicio"].isna()].drop(columns="clave_servicio").reset_index(drop=True)
    vinculados = df[df["clave_servicio"].notna()].merge(
        unificacion.servicios[["clave_servicio", "servicio_id", "presupuesto_h"]], on="clave_servicio", how="left")
    return vinculados.reset_index(drop=True), no_vinculados
