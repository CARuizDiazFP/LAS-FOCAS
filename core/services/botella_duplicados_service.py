# Nombre de archivo: botella_duplicados_service.py
# Ubicación de archivo: core/services/botella_duplicados_service.py
# Descripción: Detección de Botellas (Cromo + legado) candidatas a duplicado dentro de la misma Cámara padre

"""A diferencia de `camara_duplicados_service.py` (duplicados entre Cámaras RAÍZ, agrupando
globalmente), acá el "duplicado" es entre dos HIJAS (Botella legado self-FK y/o `CromoBotella`) de
la MISMA Cámara padre — el mismo sitio físico ingresado dos veces por dos vías distintas del sistema
(ej. real: una Cámara ya tenía una botella legado "Bot 2" y, tras fusionar dos Cámaras duplicadas
-ver `camara_merge_service.py`-, también terminó con una `CromoBotella` "Botella 2" bajo el mismo
padre).

Performance: NO se itera cada Cámara raíz consultando `CromoBotella` una por una (N+1 real a la
escala de ~10.212 Cámaras raíz, 2026-08-14) — se hacen exactamente 2 queries con `joinedload` sobre
la relación al padre, y se agrupa en Python. Ambas queries se materializan en lotes (`yield_per`,
2026-08-22) con un `time.sleep(0)` entre lotes para no retener el GIL de forma continua durante la
construcción de miles de objetos ORM — ver docstring de `detectar_grupos_duplicados_botellas`.

Sin similitud difusa (misma decisión que `camara_duplicados_service.py`, 2026-08-14): igualdad
exacta de `normalizar_para_agrupar_extendido`. A diferencia de la detección de Cámaras, acá NO se
excluye por sufijo Bot-N — "Bot 2" es justamente el caso a detectar entre hermanas, y esa
normalización no toca dígitos (nunca colapsa "Bot 2" con "Bot 3")."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session, joinedload

from core.services.camara_hierarchy_service import estado_mas_restrictivo, normalizar_para_agrupar_extendido
from db.models.cromo import CromoBotella
from db.models.infra import Camara, CamaraEstado

# Filas entre cada `time.sleep(0)` durante la materialización ORM (ver `detectar_grupos_duplicados_botellas`).
_BATCH_SIZE = 500


@dataclass(slots=True)
class BotellaDuplicadaItem:
    origen: Literal["legado", "cromo"]
    id: int  # Camara.id si origen="legado"; CromoBotella.n_id si origen="cromo" — clave compuesta
    nombre: str
    estado: str


@dataclass(slots=True)
class GrupoBotellasDuplicadas:
    camara_padre_id: int
    camara_padre_nombre: str
    clave_normalizada: str
    criterio: str
    miembros: list[BotellaDuplicadaItem]
    estados_en_conflicto: bool
    estado_mas_restrictivo: str
    resoluble: bool


def detectar_grupos_duplicados_botellas(session: Session) -> list[GrupoBotellasDuplicadas]:
    """2 queries totales (con `joinedload` al padre) + agrupación en Python — sin iterar Cámaras raíz
    una por una. `resoluble` sólo es `True` para grupos de exactamente 2 miembros con 1 legado + 1
    cromo — el único caso con política de resolución automática definida (ver
    `botella_merge_service.py::apropiar_legado_a_cromo`).

    Materialización en lotes de `_BATCH_SIZE` filas (`yield_per` en vez de `.all()`) con un
    `time.sleep(0)` entre lotes: `joinedload` many-to-one es compatible con `yield_per` (no multiplica
    filas, a diferencia de una colección), y el `sleep(0)` fuerza un checkpoint de liberación del GIL
    a intervalos predecibles — sin él, medido en vivo el 2026-08-22, la construcción de miles de
    objetos ORM seguidos retiene el GIL el tiempo suficiente para bloquear el hilo del event loop que
    espera este cómputo vía `asyncio.to_thread` (worker y `web/app/main.py`)."""
    # Agrupar primero por Cámara padre, luego dentro de cada padre por nombre normalizado extendido.
    por_padre: dict[int, dict[str, list[BotellaDuplicadaItem]]] = defaultdict(lambda: defaultdict(list))
    padres_nombre: dict[int, str] = {}
    estados_por_clave: dict[tuple[int, str], list[CamaraEstado]] = defaultdict(list)

    legado_query = (
        session.query(Camara)
        .filter(Camara.camara_padre_id.isnot(None))
        .options(joinedload(Camara.camara_padre))
        .yield_per(_BATCH_SIZE)
    )
    for indice, botella in enumerate(legado_query, start=1):
        padre = botella.camara_padre
        if padre is not None:
            clave = normalizar_para_agrupar_extendido(botella.nombre)
            padres_nombre[padre.id] = padre.nombre or ""
            por_padre[padre.id][clave].append(
                BotellaDuplicadaItem(
                    origen="legado",
                    id=botella.id,
                    nombre=botella.nombre or "",
                    estado=(botella.estado.value if botella.estado else CamaraEstado.LIBRE.value),
                )
            )
            estados_por_clave[(padre.id, clave)].append(botella.estado or CamaraEstado.LIBRE)
        if indice % _BATCH_SIZE == 0:
            time.sleep(0)

    cromo_query = (
        session.query(CromoBotella)
        .filter(CromoBotella.camara_id.isnot(None), CromoBotella.vigente.is_(True))
        .options(joinedload(CromoBotella.camara))
        .yield_per(_BATCH_SIZE)
    )
    for indice, cromo_botella in enumerate(cromo_query, start=1):
        padre = cromo_botella.camara
        if padre is not None:
            clave = normalizar_para_agrupar_extendido(cromo_botella.nombre)
            padres_nombre[padre.id] = padre.nombre or ""
            por_padre[padre.id][clave].append(
                BotellaDuplicadaItem(
                    origen="cromo",
                    id=cromo_botella.n_id,
                    nombre=cromo_botella.nombre or "",
                    estado=(cromo_botella.estado.value if cromo_botella.estado else CamaraEstado.LIBRE.value),
                )
            )
            estados_por_clave[(padre.id, clave)].append(cromo_botella.estado or CamaraEstado.LIBRE)
        if indice % _BATCH_SIZE == 0:
            time.sleep(0)

    resultado: list[GrupoBotellasDuplicadas] = []
    for padre_id, grupos_por_clave in por_padre.items():
        for clave, miembros in grupos_por_clave.items():
            if len(miembros) < 2:
                continue
            cuenta_legado = sum(1 for m in miembros if m.origen == "legado")
            cuenta_cromo = sum(1 for m in miembros if m.origen == "cromo")
            estados = estados_por_clave[(padre_id, clave)]
            resultado.append(
                GrupoBotellasDuplicadas(
                    camara_padre_id=padre_id,
                    camara_padre_nombre=padres_nombre[padre_id],
                    clave_normalizada=clave,
                    criterio="normalizacion_extendida",
                    miembros=miembros,
                    estados_en_conflicto=len(set(estados)) > 1,
                    estado_mas_restrictivo=estado_mas_restrictivo(estados).value,
                    resoluble=(len(miembros) == 2 and cuenta_legado == 1 and cuenta_cromo == 1),
                )
            )

    resultado.sort(key=lambda g: (g.camara_padre_nombre, g.clave_normalizada))
    return resultado


@dataclass(slots=True)
class SugerenciaConsolidacionPlaceholders:
    id_destino_cromo: int
    ids_origen_cromo: list[int]


def sugerir_consolidacion_placeholders(
    grupo: GrupoBotellasDuplicadas, operativos: set[int]
) -> SugerenciaConsolidacionPlaceholders | None:
    """Grupo 100% Cromo (sin miembros legado) donde EXACTAMENTE un miembro tiene cables
    asociados (`operativos`, ver core/services/cromo/verificador.py::tiene_cables_asociados_batch_sync)
    — ese es el destino; el resto son placeholders vacíos (mismo nombre, sin cables, creados por
    corridas sucesivas antes del fix de raíz de "ID dual"). None si no aplica: hay algún miembro
    legado, o el conteo de operativos no es exactamente 1 (0 = nada que hacer, 2+ = ambigüo, no
    es este patrón)."""
    if any(m.origen == "legado" for m in grupo.miembros):
        return None
    miembros_cromo = [m for m in grupo.miembros if m.origen == "cromo"]
    if len(miembros_cromo) < 2:
        return None
    con_cables = [m for m in miembros_cromo if m.id in operativos]
    sin_cables = [m for m in miembros_cromo if m.id not in operativos]
    if len(con_cables) != 1 or not sin_cables:
        return None
    return SugerenciaConsolidacionPlaceholders(
        id_destino_cromo=con_cables[0].id, ids_origen_cromo=[m.id for m in sin_cables]
    )


def sugerir_apropiacion(grupo: GrupoBotellasDuplicadas) -> tuple[int, int] | None:
    """Devuelve `(legado_id, cromo_n_id)` si el grupo es `resoluble` (único caso con política de
    resolución automática, ver `botella_merge_service.py::apropiar_legado_a_cromo`), o `None` si no
    hay una única pareja legado/cromo inequívoca. Centralizado acá para la apropiación masiva
    (`web/app/main.py::botellas_apropiar_masivo_web`), que no tiene un admin eligiendo grupo por
    grupo."""
    if not grupo.resoluble:
        return None
    legado = next((m for m in grupo.miembros if m.origen == "legado"), None)
    cromo = next((m for m in grupo.miembros if m.origen == "cromo"), None)
    if legado is None or cromo is None:
        return None
    return legado.id, cromo.id


__all__ = [
    "BotellaDuplicadaItem",
    "GrupoBotellasDuplicadas",
    "SugerenciaConsolidacionPlaceholders",
    "detectar_grupos_duplicados_botellas",
    "sugerir_apropiacion",
    "sugerir_consolidacion_placeholders",
]
