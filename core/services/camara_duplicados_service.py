# Nombre de archivo: camara_duplicados_service.py
# Ubicación de archivo: core/services/camara_duplicados_service.py
# Descripción: Detección de Cámaras raíz candidatas a duplicado por nombre normalizado extendido

"""La normalización extendida (`normalizar_para_agrupar_extendido`) vive en
`camara_hierarchy_service.py`, no acá — nació en este archivo el 2026-08-14 sólo para sugerir
candidatas a fusión MANUAL, pero horas después `resolver_o_crear_padre_desde_base()` empezó a
usarla también para decidir si ya existe una Cámara padre (cerrar el gap de duplicados nuevos), y
ese archivo ya tenía a este como dependiente (`estado_mas_restrictivo`/`extraer_base`) — moverla en
sentido contrario habría creado un ciclo de import. Este archivo sigue existiendo aparte porque su
responsabilidad (agrupar para sugerir revisión manual, `GrupoDuplicados`/`CamaraDuplicadaItem`)
sigue siendo distinta de la resolución de altas.

Sin similitud difusa (decisión explícita del usuario, 2026-08-14): sólo igualdad exacta de string ya
expandido. `criterio` queda fijo en "normalizacion_extendida" — punto de extensión si más adelante se
agregan otros criterios de detección, sin romper el contrato de `GrupoDuplicados`.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy.orm import Session

from core.services.camara_hierarchy_service import (
    estado_mas_restrictivo,
    extraer_base,
    normalizar_para_agrupar_extendido,
)
from db.models.infra import Camara, CamaraEstado


@dataclass(slots=True)
class CamaraDuplicadaItem:
    id: int
    nombre: str
    estado: str
    botellas_count: int
    cables_count: int


@dataclass(slots=True)
class GrupoDuplicados:
    clave_normalizada: str
    criterio: str
    miembros: list[CamaraDuplicadaItem]
    estados_en_conflicto: bool
    estado_mas_restrictivo: str


def detectar_grupos_duplicados(session: Session) -> list[GrupoDuplicados]:
    """O(n) sobre las Cámaras raíz reales (~10.212 filas, 2026-08-14) — sub-segundo, sin cache.

    Excluye sufijo Bot-N (`extraer_base(...) is not None`, ya resuelto por la jerarquía Cámara/
    Botella) — mismo criterio que `_detectar_duplicados_sin_sufijo` en
    `scripts/camara_backfill_padre_botella.py`, que este servicio reemplaza."""
    filas = (
        session.query(Camara)
        .filter(Camara.camara_padre_id.is_(None))
        .order_by(Camara.nombre)
        .all()
    )

    grupos: dict[str, list[Camara]] = defaultdict(list)
    for camara in filas:
        if extraer_base(camara.nombre) is not None:
            continue
        grupos[normalizar_para_agrupar_extendido(camara.nombre)].append(camara)

    resultado: list[GrupoDuplicados] = []
    for clave, miembros in grupos.items():
        if len(miembros) < 2:
            continue
        estados = [c.estado for c in miembros]
        resultado.append(
            GrupoDuplicados(
                clave_normalizada=clave,
                criterio="normalizacion_extendida",
                miembros=[
                    CamaraDuplicadaItem(
                        id=c.id,
                        nombre=c.nombre or "",
                        estado=(c.estado.value if c.estado else CamaraEstado.LIBRE.value),
                        botellas_count=len(c.botellas) + len(c.cromo_botellas),
                        cables_count=len(c.cables),
                    )
                    for c in miembros
                ],
                estados_en_conflicto=len(set(estados)) > 1,
                estado_mas_restrictivo=estado_mas_restrictivo(estados).value,
            )
        )

    resultado.sort(key=lambda g: g.miembros[0].nombre)
    return resultado


def sugerir_principal(grupo: GrupoDuplicados) -> int:
    """Mismo criterio que ya usa `ModalFusionarGrupo.vue` para pre-seleccionar la principal de un
    grupo: más `botellas_count + cables_count` (más probable que sea la Cámara "real"/más completa),
    empate → id más bajo. Centralizado acá para la fusión masiva (`fusionar_todos_los_grupos`,
    `camara_merge_service.py`), que no tiene un admin eligiendo grupo por grupo."""
    return sorted(grupo.miembros, key=lambda m: (-(m.botellas_count + m.cables_count), m.id))[0].id


__all__ = [
    "CamaraDuplicadaItem",
    "GrupoDuplicados",
    "detectar_grupos_duplicados",
    "sugerir_principal",
]
