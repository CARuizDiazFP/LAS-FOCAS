# Nombre de archivo: camara_padre_service.py
# Ubicación de archivo: core/services/cromo/camara_padre_service.py
# Descripción: Extrae el nombre de Cámara padre de una Botella Cromo (sufijo, prefijo, o nombre exacto como fallback) y resuelve/crea la Cámara

"""Vincula una `CromoBotella` (`app.cromo_botellas`) a una `Camara` padre (`app.camaras`), reusando
el mismo mecanismo de resolución que ya usa la jerarquía Bot-N legado
(`core/services/camara_hierarchy_service.py::resolver_o_crear_padre_desde_base`) — advisory lock,
no-promoción de filas existentes, absorción de "peladas".

**Actualización 2026-08-13 (decisión explícita del usuario, revierte la política fail-closed del
2026-08-11)**: toda Cámara padre *nueva* sintetizada acá nace en `LIBRE`, sea porque matcheó un
patrón de nombre (sufijo/prefijo) o porque cayó en el fallback de nombre exacto — una Cámara recién
creada no tiene todavía ningún empalme/ruta propio, así que no puede existir un `IncidenteBaneo`
activo que la afecte (los baneos cruzan vía `servicio_protegido_id`/`ruta_protegida_id` sobre los
empalmes de la cámara); no hay nada real que "chequear" en el momento del alta. Si en cambio se
reutiliza una `Camara` legado ya existente (nombre coincidente), no se toca su estado — ese es dato
real, con auditoría propia, y puede legítimamente estar `BANEADA`; el llamador
(`scripts/cromo_backfill_camara_padre.py`) decide qué hacer con él. Ver `docs/decisiones.md`.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from sqlalchemy.orm import Session

from core.services.camara_hierarchy_service import extraer_base, resolver_o_crear_padre_desde_base
from db.models.infra import Camara, CamaraEstado, CamaraOrigenDatos

logger = logging.getLogger(__name__)

# Patrón de PREFIJO: palabra completa "Botella" + número, AL INICIO del string. Sólo confirmado
# hasta ahora en texto libre de mensajes de Slack de técnicos (normalizado ahí a la forma sufijo
# antes de tocar la DB) — nunca visto en `cromo_botellas.nombre` real. Se contempla igual por
# pedido explícito del negocio; cada match se loguea para poder confirmar/descartar su uso real.
# Ancla ^ deliberada: sólo cubre "al inicio" (lo pedido) — un 3er patrón (p.ej. "Botella N" como
# sufijo con palabra completa) queda fuera de alcance si apareciera en datos reales.
#
# `\.?` antes del `\s*` final (2026-08-14): mismo fix de raíz que `RE_BOT_SUFIJO`
# (`modules/slack_baneo_notifier/camara_search.py`) — un punto inmediatamente después del dígito
# ("Botella 2. Resto...") quedaba sin consumir y sobrevivía como residuo al inicio del nombre
# resultante. Nunca confirmado en datos reales para este camino de PREFIJO específico (a diferencia
# del sufijo, que sí tiene 7 casos reales, ver `docs/decisiones.md` 2026-08-14) — se corrige igual por
# consistencia y para no dejar la misma trampa latente si este patrón empieza a aparecer.
RE_BOTELLA_PREFIJO = re.compile(r"^\s*botella\.?\s*[1-9](?!\d)\.?\s*", re.IGNORECASE)


def extraer_base_cromo(nombre: Optional[str]) -> Optional[str]:
    """Extrae el nombre base de Cámara padre de un nombre de Botella Cromo, en 3 pasos:

    1. Sufijo real "Bot N" (`extraer_base`, probado contra datos reales — ej. n_id 6638808 "Cra
       Plaza de los Ingleses CF" + variantes "Bot 2/3/4").
    2. Prefijo "Botella N <nombre>" (nunca confirmado en datos persistidos reales, sólo visto en
       texto libre de Slack — se contempla igual por pedido explícito).
    3. **Fallback de nombre exacto** (2026-08-12): si ninguno de los dos patrones matchea (ej.
       "Av Rivadavia 6041" — una Botella sin sufijo/prefijo, no un dato "sin información", Cromo ya
       la trackea como sitio real), usar el nombre de la Botella tal cual, limpio de espacios en los
       extremos, como nombre de su propia Cámara padre (relación 1:1 si no hay otra Botella que
       comparta esa misma base). Antes de este fallback, estas Botellas quedaban huérfanas
       (`camara_id IS NULL`) sin ningún camino de resolución automática — ver
       `core/services/cromo/orfanas_service.py` para la resolución manual que sigue existiendo para
       los casos con nombre vacío (únicos que este fallback no puede resolver).

    Orden deliberado entre 1 y 2: el sufijo es el único patrón confirmado en datos reales; probarlo
    primero evita que el prefijo (no confirmado) le robe un match a un nombre que de otro modo
    resolvería por el camino ya probado. Ambos son mutuamente excluyentes por construcción (tras
    "Bot" de `RE_BOT_SUFIJO` viene "ella", nunca punto/espacio/dígito; el prefijo está anclado a `^`,
    nunca matchea un sufijo al final). El fallback de nombre exacto sólo puede devolver `None` si
    `nombre` es vacío/`None` — no hay ningún nombre no vacío que quede sin resolver."""
    base = extraer_base(nombre)
    if base is not None:
        return base
    if not nombre:
        return None
    match = RE_BOTELLA_PREFIJO.match(nombre)
    if match:
        resto = re.sub(r"\s+", " ", nombre[match.end():]).strip()
        if resto:
            logger.info("action=cromo_camara_padre hallazgo=patron_prefijo_matcheo nombre='%s'", nombre)
            return resto
    return nombre.strip() or None


def resolver_o_crear_padre_cromo(
    session: Session, nombre_botella_cromo: Optional[str], *, usuario: str = "cromo_backfill"
) -> Optional[Camara]:
    """Resuelve (o crea) la Cámara padre para una Botella Cromo con `nombre_botella_cromo`, vía
    `extraer_base_cromo` (sufijo, prefijo, o el nombre exacto como último recurso). Devuelve `None`
    únicamente si `nombre_botella_cromo` es vacío/`None` — el llamador no debe tocar
    `CromoBotella.camara_id` en ese caso."""
    base = extraer_base_cromo(nombre_botella_cromo)
    if base is None:
        return None
    return resolver_o_crear_padre_desde_base(
        session,
        base,
        usuario=usuario,
        estado_si_nuevo=CamaraEstado.LIBRE,
        origen_si_nuevo=CamaraOrigenDatos.INFERIDO_CROMO,
    )


__all__ = [
    "RE_BOTELLA_PREFIJO",
    "extraer_base_cromo",
    "resolver_o_crear_padre_cromo",
]
