# Nombre de archivo: camara_busqueda_service.py
# Ubicación de archivo: core/services/camara_busqueda_service.py
# Descripción: Búsqueda liviana de Cámaras raíz por nombre — para selectores/autocomplete (unificación, asociación de Botellas huérfanas)

"""Búsqueda liviana de Cámaras raíz (`camara_padre_id IS NULL`) por nombre, pensada para
selectores/autocomplete de UI (picker de "Unificar Cámara", picker de "Asociar a Cámara existente"
en el Caso 1 de Botellas huérfanas) — no para el dashboard principal.

Deliberadamente NO reusa `smart_search_camaras_web`/`SmartSearchRequestModel`: ese endpoint carga
TODAS las cámaras raíz en memoria y recalcula rutas/servicios/cables por cada una (N+1 ya
documentado en `web/app/main.py`) para alimentar tarjetas completas del dashboard — sobre-ingeniería
para un selector que sólo necesita `id/nombre/direccion/estado` de un puñado de candidatas."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from db.models.infra import Camara


@dataclass(slots=True)
class CamaraLigera:
    id: int
    nombre: str
    direccion: Optional[str]
    estado: str
    botellas_count: int
    cables_count: int
    es_botella: bool = False
    camara_padre_id: Optional[int] = None
    camara_padre_nombre: Optional[str] = None


def buscar_camaras_ligero(
    session: Session,
    q: Optional[str],
    *,
    limit: int = 10,
    excluir_id: Optional[int] = None,
    solo_raiz: bool = True,
) -> list[CamaraLigera]:
    """Busca Cámaras por nombre (`ILIKE` parcial). `q` vacío/`None` devuelve las primeras
    `limit` por nombre. `excluir_id` omite una Cámara puntual (ej. la que ya se está viendo en el
    picker, para no ofrecerla como su propia unificación/asociación).

    `solo_raiz=True` (default, preserva el comportamiento histórico) filtra sólo Cámaras raíz
    (`camara_padre_id IS NULL`). `solo_raiz=False` no aplica ese filtro estructural — el `ILIKE`
    corre sobre todas las filas de `Camara` (raíces y Botellas legado), pensado para el picker de
    asociación manual (Tarea 5) donde el admin necesita poder elegir también una Botella hija
    puntual y ver a qué grupo (padre + hermanas) se va a aplicar el baneo.

    `cables_count` (como `botellas_count`) acepta el mismo costo por-candidata ya asumido acá (lista
    acotada a `limit<=50`, no la lista completa de cámaras raíz que sí evita `smart-search`).
    `botellas_count` suma botellas propias (self-FK legado) + Botellas Cromo propias — sin la segunda
    parte, las Cámaras `INFERIDO_CROMO` (la mayoría del dataset real) siempre daban 0."""
    query = session.query(Camara)
    if solo_raiz:
        query = query.filter(Camara.camara_padre_id.is_(None))
    if q and q.strip():
        query = query.filter(Camara.nombre.ilike(f"%{q.strip()}%"))
    if excluir_id is not None:
        query = query.filter(Camara.id != excluir_id)

    candidatas = query.order_by(Camara.nombre).limit(max(1, min(limit, 50))).all()
    return [
        CamaraLigera(
            id=c.id,
            nombre=c.nombre or "",
            direccion=c.direccion,
            estado=c.estado.value if c.estado else "LIBRE",
            botellas_count=len(c.botellas) + len(c.cromo_botellas),
            cables_count=len(c.cables),
            es_botella=c.es_botella,
            camara_padre_id=c.camara_padre_id if c.es_botella else None,
            camara_padre_nombre=(c.camara_padre.nombre if c.camara_padre else None) if c.es_botella else None,
        )
        for c in candidatas
    ]


__all__ = ["CamaraLigera", "buscar_camaras_ligero"]
