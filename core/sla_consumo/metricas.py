# Nombre de archivo: metricas.py
# Ubicación de archivo: core/sla_consumo/metricas.py
# Descripción: Reglas atómicas del informe SLA consumido — causa, indicador, semáforo, estado, porcentajes

from __future__ import annotations

import math

from core.sla_consumo.clasificador import GRUPO_CARRIER, GRUPO_FO, GRUPO_FO_COD3, GRUPO_OTROS

HORAS_ANIO = 8760.0
# Tolerancia de las comparaciones de estado (≈3,6 ms): absorbe el ruido de punto flotante de sumas
# acumuladas sin que un redondeo de presentación cambie un estado.
EPS_HORAS = 1e-6

CAUSA_FO_GENERAL = "FO general"
CAUSA_FO_COD3 = "FO Cod 3"
CAUSA_CARRIER = "Carrier"
CAUSA_OTROS = "Otros"
CAUSAS_ORDEN = (CAUSA_FO_GENERAL, CAUSA_FO_COD3, CAUSA_CARRIER, CAUSA_OTROS)
CAUSAS_FO = frozenset({CAUSA_FO_GENERAL, CAUSA_FO_COD3})

ROJO, AMARILLO, VERDE, SIN_COLOR = "Rojo", "Amarillo", "Verde", "Sin color"

ESTADO_SIN_CONSUMO = "Sin consumo"
ESTADO_DENTRO = "Dentro de SLA"
ESTADO_AGOTADO = "Presupuesto agotado"
ESTADO_EXCEDIDO = "SLA excedido"
ESTADO_NO_EVALUABLE = "No evaluable"
ESTADOS_AGOTADO_O_EXCEDIDO = frozenset({ESTADO_AGOTADO, ESTADO_EXCEDIDO})

_CAUSA_POR_GRUPO = {GRUPO_FO: CAUSA_FO_GENERAL, GRUPO_FO_COD3: CAUSA_FO_COD3,
                    GRUPO_CARRIER: CAUSA_CARRIER, GRUPO_OTROS: CAUSA_OTROS}


def _numero(valor: object) -> float | None:
    if valor is None:
        return None
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(numero) else numero


def presupuesto_horas(sla_prometido: object) -> float | None:
    sla = _numero(sla_prometido)
    return None if sla is None else (1 - sla / 100) * HORAS_ANIO


def presupuesto_valido(presupuesto: object) -> bool:
    p = _numero(presupuesto)
    return p is not None and math.isfinite(p) and p > EPS_HORAS


def causa_de_grupo(grupo: str | None) -> str | None:
    """Cierre Cliente (excluido) y grupos desconocidos no tienen causa."""
    return _CAUSA_POR_GRUPO.get(grupo)


def indicador_reclamo(causa: str | None, horas_computables: float) -> str:
    if causa is None or not horas_computables or horas_computables <= EPS_HORAS:
        return SIN_COLOR
    return ROJO if causa in CAUSAS_FO else VERDE


def semaforo_servicio(horas_fo: float, horas_no_fo: float) -> str:
    hay_fo, hay_no_fo = horas_fo > EPS_HORAS, horas_no_fo > EPS_HORAS
    if hay_fo and hay_no_fo:
        return AMARILLO
    if hay_fo:
        return ROJO
    return VERDE if hay_no_fo else SIN_COLOR


def estado_presupuesto(consumo: float, presupuesto: object) -> str:
    if not presupuesto_valido(presupuesto):
        return ESTADO_NO_EVALUABLE
    p = float(presupuesto)
    if consumo <= EPS_HORAS:
        return ESTADO_SIN_CONSUMO
    if abs(consumo - p) <= EPS_HORAS:
        return ESTADO_AGOTADO
    return ESTADO_EXCEDIDO if consumo > p else ESTADO_DENTRO


def pct_real(horas: float, presupuesto: object) -> float | None:
    return float(horas) / float(presupuesto) * 100 if presupuesto_valido(presupuesto) else None


def pct_visible(pct: float | None) -> float | None:
    return None if pct is None else min(pct, 100.0)
