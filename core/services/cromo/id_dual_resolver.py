# Nombre de archivo: id_dual_resolver.py
# Ubicación de archivo: core/services/cromo/id_dual_resolver.py
# Descripción: Resolución compartida de "ID dual" (hist[]/next_id) de un objeto Cromo — usada por
# Cables (repoblacion_service.py, caso real B2-FO-CAR 2026-08-21) y por Botellas (tareas futuras)

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from core.services.cromo.client import CromoClient, CromoClientError

logger = logging.getLogger(__name__)

# Cota defensiva de saltos hist[]/next_id: el caso real observado (B2-FO-CAR, 2026-08-21)
# resuelve en 1-2 requests porque hist[] trae la cadena completa de entrada — este límite sólo
# protege contra una cadena rota, cíclica o anormalmente larga.
MAX_HOPS_HIST = 5


def ids_de_hist(obj: dict[str, Any]) -> set[int]:
    return {entrada["id"] for entrada in (obj.get("hist") or []) if isinstance(entrada, dict) and entrada.get("id") is not None}


def next_id_de(obj: dict[str, Any], id_actual: Optional[int]) -> Optional[int]:
    """Busca, dentro del propio `hist[]` de `obj`, la entrada cuyo `id` es `id_actual` y devuelve
    su `next_id` (0 = no hay más — es la vigente). Sigue la cadena salto a salto por el id propio
    de cada objeto, no "salta directo" a la entrada con `next_id == 0`: así funciona igual si
    `hist[]` trae la cadena completa (confirmado real, caso B2-FO-CAR, 2 saltos) o sólo una
    ventana parcial alrededor del id consultado."""
    for entrada in obj.get("hist") or []:
        if isinstance(entrada, dict) and entrada.get("id") == id_actual:
            return entrada.get("next_id") or None
    return None


async def fetch_objeto(cliente: CromoClient, n_id: int) -> dict[str, Any]:
    """Desenvuelve el `{"st": ..., "response": {...}}` con el que responde Cromo — confirmado real
    contra `GET /db/objects/{id}?show=TOPOLOGIES&show=REL_ATTRIBUTE` (Paso 0, 2026-08-21)."""
    respuesta = await cliente.get_objeto_con_topologia(n_id)
    return respuesta.get("response", respuesta)


async def resolver_cadena_objetos(
    cliente: CromoClient, n_id: int, obj_inicial: dict[str, Any], esta_vigente: Callable[[dict], bool]
) -> tuple[dict[str, Any], set[int]]:
    """Devuelve el objeto con la topología VIGENTE (según el criterio `esta_vigente`) + el set de ids de toda la
    cadena `hist` (insumo del anclaje de extremo).

    Confirmado con datos reales: `hist[]` trae la cadena completa sin importar qué id de la cadena
    se consulte, así que 1-2 requests alcanzan casi siempre — el loop acotado por
    `MAX_HOPS_HIST` es puramente defensivo (cadena que sigue en movimiento, respuesta parcial).
    """
    obj = obj_inicial
    id_actual = obj.get("id", n_id)
    ids_cadena = {n_id} | ids_de_hist(obj)
    visitados = {n_id}
    saltos = 0
    while not esta_vigente(obj) and saltos < MAX_HOPS_HIST:
        siguiente_id = next_id_de(obj, id_actual)
        if siguiente_id is None or siguiente_id in visitados:
            break
        visitados.add(siguiente_id)
        try:
            obj = await fetch_objeto(cliente, siguiente_id)
        except CromoClientError as exc:
            logger.warning(
                "action=cromo_resolviendo_cadena evento=hop_no_resuelve n_id_inicial=%s siguiente_id=%s error=%s",
                n_id,
                siguiente_id,
                exc,
            )
            break
        id_actual = siguiente_id
        ids_cadena.add(siguiente_id)
        ids_cadena |= ids_de_hist(obj)
        saltos += 1
    return obj, ids_cadena


__all__ = ["MAX_HOPS_HIST", "ids_de_hist", "next_id_de", "fetch_objeto", "resolver_cadena_objetos"]
