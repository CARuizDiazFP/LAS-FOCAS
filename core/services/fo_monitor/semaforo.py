# Nombre de archivo: semaforo.py
# Ubicación de archivo: core/services/fo_monitor/semaforo.py
# Descripción: Cálculo puro del color de un cable FO a partir de los estados PRE/POST de sus servicios

"""Semáforo de FO Monitor (contrato acordado en el relevamiento 2026-10-14, A2).

Orden de evaluación:
1. GRIS     — sin servicios verificables, o cobertura < 50 % ("desconocido").
2. ROJO     — 100 % de los servicios con resultado conocido están DOWN (gana aunque haya caídas nuevas).
3. AMARILLO — al menos una caída nueva: UP en PRE → DOWN en POST, no reconocida como ajena.
4. VERDE    — ≥ 80 % de los conocidos UP.
5. NARANJA  — el resto (1–79 % UP).

`ADMIN_DOWN` y `NO_SOPORTADO` no cuentan en la cobertura ni en los porcentajes. `DESCONOCIDO`
(timeout, sin línea en la respuesta) cuenta en la cobertura como no conocido: nunca suma a verde.
Sin línea base (PRE inválido) no puede haber amarillo; el flag lo explicita para la UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

GRIS, ROJO, AMARILLO, VERDE, NARANJA = "GRIS", "ROJO", "AMARILLO", "VERDE", "NARANJA"

UP, DOWN, ADMIN_DOWN, DESCONOCIDO, NO_SOPORTADO = "UP", "DOWN", "ADMIN_DOWN", "DESCONOCIDO", "NO_SOPORTADO"
_EXCLUIDOS = {ADMIN_DOWN, NO_SOPORTADO}

UMBRAL_VERDE = 0.8
UMBRAL_COBERTURA = 0.5


@dataclass(frozen=True)
class ResultadoSemaforo:
    color: str
    motivo: str
    servicios: int
    evaluables: int
    conocidos: int
    up: int
    down: int
    cobertura: float | None
    caidas_nuevas: list = field(default_factory=list)
    recuperaciones: list = field(default_factory=list)
    sin_linea_base: bool = False
    fase: str = "PRE"


def calcular_semaforo(
    servicios: Sequence,
    pre: Mapping,
    post: Mapping | None = None,
    *,
    reconocidos: set | frozenset = frozenset(),
    sin_linea_base: bool = False,
) -> ResultadoSemaforo:
    """`servicios`: claves congeladas del cable. `pre`/`post`: clave → estado normalizado (la última
    medición válida de cada fase, ya resuelta la reverificación). `post=None` → todavía en curso: el
    color refleja el PRE y no puede haber caídas nuevas."""
    fase = "POST" if post is not None else "PRE"
    actual = post if post is not None else pre
    estados = {s: actual.get(s, DESCONOCIDO) for s in servicios}
    evaluables = [s for s, e in estados.items() if e not in _EXCLUIDOS]
    up = sum(1 for s in evaluables if estados[s] == UP)
    down = sum(1 for s in evaluables if estados[s] == DOWN)
    conocidos = up + down

    caidas: list = []
    recuperaciones: list = []
    if post is not None:
        for s in servicios:
            antes, despues = pre.get(s), post.get(s)
            if antes == DOWN and despues == UP:
                recuperaciones.append(s)
            if not sin_linea_base and antes == UP and despues == DOWN and s not in reconocidos:
                caidas.append(s)

    base = dict(
        servicios=len(servicios), evaluables=len(evaluables), conocidos=conocidos, up=up, down=down,
        caidas_nuevas=caidas, recuperaciones=recuperaciones, sin_linea_base=sin_linea_base, fase=fase,
    )
    if not evaluables:
        return ResultadoSemaforo(color=GRIS, motivo="sin_verificables", cobertura=None, **base)
    cobertura = conocidos / len(evaluables)
    if cobertura < UMBRAL_COBERTURA:
        return ResultadoSemaforo(color=GRIS, motivo="desconocido", cobertura=cobertura, **base)
    if down == conocidos:
        return ResultadoSemaforo(color=ROJO, motivo="caida_total", cobertura=cobertura, **base)
    if caidas:
        return ResultadoSemaforo(color=AMARILLO, motivo="caida_nueva", cobertura=cobertura, **base)
    if up / conocidos >= UMBRAL_VERDE:
        return ResultadoSemaforo(color=VERDE, motivo="operativo", cobertura=cobertura, **base)
    return ResultadoSemaforo(color=NARANJA, motivo="degradado", cobertura=cobertura, **base)
