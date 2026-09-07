# Nombre de archivo: alias_service.py
# Ubicación de archivo: core/services/cromo/alias_service.py
# Descripción: Carga en memoria y resolución del aliasing manual de Botellas Cromo (app.cromo_botella_alias)

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.cromo import CromoBotellaAlias

ACCION_FUSIONAR = "fusionar"
ACCION_IGNORAR = "ignorar"


@dataclass(slots=True, frozen=True)
class AliasBotella:
    """Snapshot inmutable de una fila de `cromo_botella_alias` — no el objeto ORM vivo, para no
    acoplar el cache en memoria de una corrida a la sesión que lo cargó."""

    accion: str
    id_cromo_destino: Optional[int]


async def cargar_alias_vigentes(sesion: AsyncSession) -> dict[int, AliasBotella]:
    """Una sola query — TODAS las filas de `app.cromo_botella_alias`, indexadas por
    `id_cromo_origen`. Mismo patrón que el cache en memoria de `_resolver_o_crear_servicio`
    (`core/services/cromo/ingesta.py`): cero queries por objeto dentro de las fases.

    Se llama UNA vez por corrida, en `continuar_corrida`, antes de que corran las fases. Una
    corrida es una unidad snapshot-consistente — nunca se resume desde una página intermedia
    (`modules/cromo_worker/worker.py` siempre relanza las 6 fases completas) — así que un alias
    creado mientras la corrida ya está en curso recién aplica en la corrida siguiente.
    """
    filas = (await sesion.execute(select(CromoBotellaAlias))).scalars().all()
    return {
        fila.id_cromo_origen: AliasBotella(accion=fila.accion, id_cromo_destino=fila.id_cromo_destino)
        for fila in filas
    }


def resolver_referencia(n_id: Optional[int], alias_por_origen: dict[int, AliasBotella]) -> Optional[int]:
    """Resuelve una referencia BLANDA ajena (extremo de cable, `parent`/`botella_n_id` de una
    fusión) que apunta a una botella por `n_id` — no la identidad propia de la botella que se
    está por upsertear (para eso, `ingesta.py` consulta `alias_por_origen` directamente).

    - `n_id` es `None` -> `None`.
    - Sin alias para `n_id` -> `n_id` sin cambios.
    - `accion == 'fusionar'` -> `id_cromo_destino` (redirige al golden record).
    - `accion == 'ignorar'` -> `None` (la referencia se anula: apuntaba a basura, no a nada; los
      campos de destino en `CromoCable`/`CromoFusion` ya son nullable y `NULL` ya es la forma
      "normal" para otros casos documentados en `db/models/cromo.py`).

    Salto único, deliberado: si el `id_cromo_destino` de una fila es a su vez el `id_cromo_origen`
    de OTRA fila (cadena A→B, B→C armada por un INSERT manual fuera de las reglas documentadas),
    esta función NO la persigue — devuelve B tal cual. Evita loops por una fila mal cargada; es
    una limitación conocida, no un bug.
    """
    if n_id is None:
        return None
    alias = alias_por_origen.get(n_id)
    if alias is None:
        return n_id
    if alias.accion == ACCION_FUSIONAR:
        return alias.id_cromo_destino
    return None


__all__ = ["ACCION_FUSIONAR", "ACCION_IGNORAR", "AliasBotella", "cargar_alias_vigentes", "resolver_referencia"]
