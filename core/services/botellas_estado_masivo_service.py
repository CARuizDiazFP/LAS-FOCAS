# Nombre de archivo: botellas_estado_masivo_service.py
# Ubicación de archivo: core/services/botellas_estado_masivo_service.py
# Descripción: Cambio de estado masivo sobre Botellas de origen mixto (Cromo + legado), vía clave compuesta {origen, id}

"""Cambia el estado de un lote de "botellas" del inventario unificado (`core/services/
botellas_unificadas_service.py`) — cada item identificado por la misma clave compuesta `{origen,
id}` que ya expone esa búsqueda, nunca un id numérico solo (`CromoBotella.n_id` y `Camara.id` son
espacios de ID independientes que pueden colisionar en valor).

Origen `legado`: reusa `aplicar_estado_a_grupo` (único punto de escritura sancionado de
`Camara.estado`) — cascada completa al grupo (padre + botellas hermanas), igual que el override
manual de un click en `CamaraDetailView.vue`. Deduplicado por raíz de grupo para no cascadear el
mismo grupo dos veces si el usuario seleccionó más de un miembro del mismo grupo.

Origen `cromo`: `UPDATE` masivo directo sobre `CromoBotella.estado` — es una foto propia,
desacoplada de la cascada en vivo de `Camara.estado` (limitación ya documentada, ver
`docs/PR/2026-08-12.md` "CromoBotella.estado sigue siendo una foto fijada..."); no hay grupo Cromo
que cascadear, cada `CromoBotella` es su propia unidad de estado.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from core.services.camara_estado_service import aplicar_estado_a_grupo
from db.models.cromo import CromoBotella
from db.models.infra import Camara, CamaraEstado

ESTADOS_ADMISIBLES = frozenset(
    {CamaraEstado.LIBRE, CamaraEstado.OCUPADA, CamaraEstado.BANEADA, CamaraEstado.NO_OPERATIVA}
)


class EstadoMasivoError(Exception):
    """Error de validación al cambiar el estado masivo — el llamador (endpoint) lo traduce a un 400,
    no a un 500."""


@dataclass(slots=True)
class ItemBotellaEstado:
    origen: str  # "cromo" | "legado"
    id: int


@dataclass(slots=True)
class ResultadoEstadoMasivo:
    estado_nuevo: str
    legado_actualizadas: int
    cromo_actualizadas: int
    no_encontrados: list[ItemBotellaEstado] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "estado_nuevo": self.estado_nuevo,
            "legado_actualizadas": self.legado_actualizadas,
            "cromo_actualizadas": self.cromo_actualizadas,
            "no_encontrados": [{"origen": item.origen, "id": item.id} for item in self.no_encontrados],
        }


def actualizar_estado_masivo(
    session: Session,
    items: list[ItemBotellaEstado],
    nuevo_estado: CamaraEstado,
    *,
    usuario: str,
    motivo: str,
) -> ResultadoEstadoMasivo:
    if not items:
        raise EstadoMasivoError("No se especificaron botellas a actualizar")
    if nuevo_estado not in ESTADOS_ADMISIBLES:
        raise EstadoMasivoError("Estado inválido")
    if any(item.origen not in ("legado", "cromo") for item in items):
        raise EstadoMasivoError("Origen inválido en al menos un item")

    ids_legado = {item.id for item in items if item.origen == "legado"}
    ids_cromo = {item.id for item in items if item.origen == "cromo"}

    no_encontrados: list[ItemBotellaEstado] = []

    legado_actualizadas = 0
    if ids_legado:
        camaras = session.query(Camara).filter(Camara.id.in_(ids_legado)).all()
        encontrados_legado = {camara.id for camara in camaras}
        no_encontrados.extend(
            ItemBotellaEstado(origen="legado", id=id_) for id_ in ids_legado - encontrados_legado
        )

        raices_procesadas: set[int] = set()
        for camara in camaras:
            raiz = camara.camara_padre or camara
            if raiz.id in raices_procesadas:
                continue
            raices_procesadas.add(raiz.id)
            auditorias = aplicar_estado_a_grupo(session, raiz, nuevo_estado, usuario=usuario, motivo=motivo)
            legado_actualizadas += len(auditorias)

    cromo_actualizadas = 0
    if ids_cromo:
        encontrados_cromo = {
            n_id for (n_id,) in session.query(CromoBotella.n_id).filter(CromoBotella.n_id.in_(ids_cromo)).all()
        }
        no_encontrados.extend(ItemBotellaEstado(origen="cromo", id=id_) for id_ in ids_cromo - encontrados_cromo)
        if encontrados_cromo:
            cromo_actualizadas = (
                session.query(CromoBotella)
                .filter(CromoBotella.n_id.in_(encontrados_cromo))
                .update({CromoBotella.estado: nuevo_estado}, synchronize_session=False)
            )

    session.flush()

    return ResultadoEstadoMasivo(
        estado_nuevo=nuevo_estado.value,
        legado_actualizadas=legado_actualizadas,
        cromo_actualizadas=cromo_actualizadas,
        no_encontrados=no_encontrados,
    )


__all__ = [
    "ESTADOS_ADMISIBLES",
    "EstadoMasivoError",
    "ItemBotellaEstado",
    "ResultadoEstadoMasivo",
    "actualizar_estado_masivo",
]
