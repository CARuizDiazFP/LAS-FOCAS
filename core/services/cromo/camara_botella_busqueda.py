# Nombre de archivo: camara_botella_busqueda.py
# Ubicación de archivo: core/services/cromo/camara_botella_busqueda.py
# Descripción: Búsqueda extendida por nombre libre que cierra el gap Camara-only, agregando CromoBotella como segunda fuente

"""Componente compartido de búsqueda: resuelve texto libre de técnicos/operadores a una raíz
`Camara`, buscando primero en `app.camaras` (fuente canónica, vía `buscar_camara()` del listener de
Slack de ingreso) y, si no hay match ahí, en `app.cromo_botellas` — el inventario real de Cromo Red
tiene botellas que nunca tuvieron fila propia en `Camara` (ej. "Bot 2 Cra Mitre 440"), y hoy esa
búsqueda las ignora por completo.

Pensado para ser consumido por dos flujos que hoy NO se tocan en esta tarea (quedan para tareas
futuras del mismo plan): el listener de Slack de ingreso de técnicos
(`modules/slack_baneo_notifier/listener.py`) y el flujo "adjuntar tracking" del portal Infra
(`core/services/infra_service.py`).

Riesgo conocido, sin acción en esta tarea: `CromoBotella.nombre` no tiene índice (a diferencia de
`CromoCable.nombre`, que sí lo tiene) — la cascada ILIKE/tokens de este módulo hace table scan sobre
`app.cromo_botellas` en cada llamada. Agregar el índice queda para la migración Alembic de la Tarea 2
de este mismo plan (no se toca `db/models/cromo.py` acá).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from modules.slack_baneo_notifier.camara_search import (
    AmbiguousSearchError,
    _aplicar_sinonimos,
    _expandir_abreviaturas,
    _filtrar_por_numeros,
    _limpiar_puntuacion,
    _normalizar,
    buscar_camara,
)

if TYPE_CHECKING:
    from db.models.infra import Camara
    from db.models.cromo import CromoBotella


@dataclass(slots=True)
class ResultadoBusquedaExtendida:
    """Resultado de `buscar_camara_o_botella_cromo()`.

    Attributes:
        camara:       Cámara raíz a evaluar — propia (``fuente="camara"``) o resuelta desde la
                      ``CromoBotella`` matcheada (``fuente="cromo_botella"``, vía
                      ``CromoBotella.camara``). ``None`` si no hubo match en ninguna fuente.
        nombre_norm:  Nombre normalizado usado para la búsqueda (mismo criterio de
                      normalización que ``buscar_camara()``).
        fuente:       ``"camara"`` | ``"cromo_botella"`` | ``None`` (sin match).
        botella:      La ``CromoBotella`` matcheada, sólo si ``fuente == "cromo_botella"``.
    """

    camara: "Camara | None"
    nombre_norm: str
    fuente: Literal["camara", "cromo_botella"] | None
    botella: "CromoBotella | None"


def _normalizar_pipeline(nombre_raw: str) -> str:
    """Reproduce, sin duplicarlo, el mismo pipeline de preprocesamiento que usa `buscar_camara()`
    internamente: limpiar puntuación → expandir abreviaturas → normalizar → sinónimos. Necesario
    para poder correr una cascada "equivalente" contra `CromoBotella.nombre` con el mismo criterio
    de normalización que ya usa la búsqueda canónica de `Camara`."""
    nombre_limpio = _limpiar_puntuacion(nombre_raw)
    nombre_expandido = _expandir_abreviaturas(nombre_limpio)
    nombre_norm_base = _normalizar(nombre_expandido)
    return _aplicar_sinonimos(nombre_norm_base)


def _buscar_botella_ilike_lista(patron: str, session: Session) -> list["CromoBotella"]:
    """Query ILIKE '%patron%' sobre CromoBotella.nombre. Sin JOIN de alias: a diferencia de
    Camara/CamaraAlias, CromoBotella no tiene una tabla de alias de nombre equivalente."""
    from db.models.cromo import CromoBotella

    return (
        session.query(CromoBotella)
        .filter(func.unaccent(func.lower(CromoBotella.nombre)).ilike(f"%{patron}%"))
        .all()
    )


def _buscar_botella_tokens_lista(tokens: list[str], session: Session) -> list["CromoBotella"]:
    """Busca CromoBotella cuyo nombre contenga TODOS los tokens dados (AND ILIKE)."""
    from db.models.cromo import CromoBotella

    condiciones = [
        func.unaccent(func.lower(CromoBotella.nombre)).ilike(f"%{token}%")
        for token in tokens
    ]
    return session.query(CromoBotella).filter(and_(*condiciones)).all()


def _cascada_botella(nombre_raw: str, session: Session) -> list["CromoBotella"]:
    """Cascada equivalente a los Intentos 1-2 de `buscar_camara()`, pero contra
    `CromoBotella.nombre`: ILIKE con el nombre normalizado completo, y si no reduce a 1 candidato,
    AND-ILIKE por tokens significativos (≥3 chars). En ambos pasos se filtra por números requeridos
    con `_filtrar_por_numeros` (reusado, no reimplementado).

    Fuera de alcance deliberado (no pedido por la tarea): join de alias (no existe tabla de alias
    para CromoBotella) y filtro de bots secundarios (`_filtrar_bots_secundarios` es específico de la
    jerarquía Cámara/Botella de `db.models.infra`, dominio distinto de este módulo).

    Returns:
        Lista vacía (sin match), lista de 1 elemento (match único), o lista de 2+ elementos
        (ambiguo — el grupo más acotado encontrado en la cascada).
    """
    nombre_norm = _normalizar_pipeline(nombre_raw)
    numeros_requeridos: set[str] = set(re.findall(r"\d+", nombre_norm))

    # ── Intento 1: ILIKE con el nombre normalizado completo ──────────────
    candidatos = _filtrar_por_numeros(_buscar_botella_ilike_lista(nombre_norm, session), numeros_requeridos)
    if len(candidatos) == 1:
        return candidatos

    mejor_ambiguo: list["CromoBotella"] = candidatos if len(candidatos) > 1 else []

    # ── Intento 2: todos los tokens (≥3 chars) presentes ─────────────────
    tokens = [t for t in nombre_norm.split() if len(t) >= 3]
    if len(tokens) >= 2:
        candidatos_tokens = _filtrar_por_numeros(
            _buscar_botella_tokens_lista(tokens, session), numeros_requeridos
        )
        if len(candidatos_tokens) == 1:
            return candidatos_tokens
        if candidatos_tokens and (not mejor_ambiguo or len(candidatos_tokens) < len(mejor_ambiguo)):
            mejor_ambiguo = candidatos_tokens

    return mejor_ambiguo


def _fusionar_nombres_dedup(*grupos: list[str]) -> list[str]:
    """Concatena listas de nombres (en el orden dado — la primera es la fuente canónica) y
    deduplica por nombre normalizado, no por identidad ni por id (Camara y CromoBotella son tipos
    de entidad distintos, sin id compartido)."""
    vistos: set[str] = set()
    resultado: list[str] = []
    for nombre in (n for grupo in grupos for n in grupo):
        if not nombre:
            continue
        clave = _normalizar_pipeline(nombre)
        if clave in vistos:
            continue
        vistos.add(clave)
        resultado.append(nombre)
    return resultado


def buscar_camara_o_botella_cromo(nombre_raw: str, session: Session) -> ResultadoBusquedaExtendida:
    """Busca una Cámara por nombre libre, ampliando la búsqueda a `CromoBotella` cuando la cascada
    canónica de `buscar_camara()` no encuentra nada en `Camara`.

    Cascada:
      1. `buscar_camara(nombre_raw, session)` sin modificar — si matchea, listo (no se consulta
         `CromoBotella`, no hay ambigüedad posible entre fuentes cuando ya hay match único).
      2. Si `Camara` no matcheó nada: cascada equivalente contra `CromoBotella.nombre`.
         - Match único con `camara_id` poblado → resuelve la Cámara raíz vía `CromoBotella.camara`.
         - Match único con `camara_id is None` (backfill de cámara padre pendiente) → tratado como
           no-match completo, igual que si no hubiera matcheado nada.
         - Sin match en ninguna de las dos fuentes → resultado vacío.
         - Ambiguo (2+ candidatos que nunca se redujeron a 1) → `AmbiguousSearchError` con las
           `CromoBotella` candidatas (Camara no aportó candidatos porque no matcheó nada).
      3. Si `buscar_camara()` lanza `AmbiguousSearchError` (0 tokens significativos o múltiples
         `Camara` candidatas): se repite la misma cascada contra `CromoBotella.nombre` y se
         fusionan los candidatos de ambas fuentes (Camara primero, fuente canónica; CromoBotella
         completa el resto), deduplicados por nombre normalizado. Se relanza la misma
         `AmbiguousSearchError` con la lista fusionada — el cap a 3 lo aplica el propio
         `__init__` de la excepción.

    Args:
        nombre_raw: Nombre extraído del mensaje/formulario, sin normalizar.
        session:    Sesión SQLAlchemy activa (síncrona, ORM).

    Returns:
        `ResultadoBusquedaExtendida` — nunca lanza para el caso "sin match" (eso es un resultado
        válido con `camara=None`, `fuente=None`); sólo lanza `AmbiguousSearchError` cuando el
        nombre es ambiguo.

    Raises:
        AmbiguousSearchError: nombre insuficientemente específico, o múltiples candidatas sin
            reducirse a una sola entre `Camara` y `CromoBotella`.
    """
    try:
        camara, nombre_norm = buscar_camara(nombre_raw, session)
    except AmbiguousSearchError as exc:
        candidatos_botella = _cascada_botella(nombre_raw, session)
        nombres_botella = [b.nombre for b in candidatos_botella]
        fusionados = _fusionar_nombres_dedup(exc.candidatos, nombres_botella)
        raise AmbiguousSearchError(nombre_raw, len(fusionados), fusionados) from exc

    if camara is not None:
        return ResultadoBusquedaExtendida(
            camara=camara, nombre_norm=nombre_norm, fuente="camara", botella=None
        )

    candidatos_botella = _cascada_botella(nombre_raw, session)

    if len(candidatos_botella) == 1:
        botella = candidatos_botella[0]
        if botella.camara_id is None:
            return ResultadoBusquedaExtendida(
                camara=None, nombre_norm=nombre_norm, fuente=None, botella=None
            )
        return ResultadoBusquedaExtendida(
            camara=botella.camara, nombre_norm=nombre_norm, fuente="cromo_botella", botella=botella
        )

    if len(candidatos_botella) > 1:
        nombres_botella = _fusionar_nombres_dedup([b.nombre for b in candidatos_botella])
        raise AmbiguousSearchError(nombre_raw, len(nombres_botella), nombres_botella)

    return ResultadoBusquedaExtendida(camara=None, nombre_norm=nombre_norm, fuente=None, botella=None)
