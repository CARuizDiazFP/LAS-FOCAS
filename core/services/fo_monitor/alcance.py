# Nombre de archivo: alcance.py
# Ubicación de archivo: core/services/fo_monitor/alcance.py
# Descripción: Resuelve qué cables y servicios verificables abarca una intervención (cámara → botellas → cables → servicios)

"""Alcance de una intervención de FO Monitor.

Regla acordada (relevamiento 2026-10-14, A10): primero la botella intervenida —la que nombra el
técnico o, si no nombra ninguna, la Botella 1— y después el resto de las botellas vigentes de la
misma cámara (la manipulación puede dañar bandejas de botellas vecinas).

- Botellas: `CromoBotella.camara_id == camara_id AND vigente` (mismo filtro que
  `GET /api/infra/camaras/{id}/botellas`, `web/app/main.py`).
- Botella 1: la hija SIN sufijo "Bot N" (convención "Botella 1 = cámara principal", ver
  `modules/slack_baneo_notifier/camara_search.py`); si todas lo llevan, la de "Bot 1"; si tampoco
  existe, la de número más bajo (`botella_1_inferida=True`).
- Cables: vigentes, clase {51, 52, 59, 60} (`CLASES_CABLE`), con algún extremo en esas botellas.
  Un cable entre dos botellas de la misma cámara se cuenta una vez, en la objetivo si la toca.
- Servicios: `servicios_unicos_por_cable_sync` filtrado por `es_verificable` y estado "Activo".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from core.services.cromo.camino_optico_service import CLASES_CABLE
from core.services.cromo.verificador import ObjetoNoEncontrado, ServicioUnico, servicios_unicos_por_cable_sync
from db.models.cromo import CromoBotella
from modules.slack_baneo_notifier.camara_search import RE_BOT_SUFIJO


@dataclass
class CableAlcance:
    n_id: int
    nombre: Optional[str]
    clase: int
    botella_n_id: int
    es_objetivo: bool
    servicios: list[ServicioUnico] = field(default_factory=list)


@dataclass
class AlcanceIntervencion:
    camara_id: int
    botella_objetivo_n_id: Optional[int]
    botella_1_inferida: bool
    botellas: dict[int, str]  # n_id → nombre
    cables: list[CableAlcance]

    def servicios_unicos(self) -> list[ServicioUnico]:
        """Un servicio que pasa por varios cables se consulta una sola vez. Orden: primero los que
        tocan la botella objetivo (prioridad de envío), luego el resto, cada grupo por PK."""
        vistos: dict[int, tuple[bool, ServicioUnico]] = {}
        for cable in self.cables:
            for s in cable.servicios:
                previo = vistos.get(s.servicio_id)
                if previo is None or (cable.es_objetivo and not previo[0]):
                    vistos[s.servicio_id] = (cable.es_objetivo, s)
        return [s for _, (_, s) in sorted(vistos.items(), key=lambda kv: (not kv[1][0], kv[0]))]


def _numero_bot(nombre: str) -> Optional[int]:
    m = RE_BOT_SUFIJO.search(nombre or "")
    if not m:
        return None
    digitos = [c for c in m.group(0) if c.isdigit()]
    return int(digitos[0]) if digitos else None


def elegir_botella_1(botellas: list[tuple[int, str]]) -> tuple[Optional[int], bool]:
    """Devuelve `(n_id, inferida)` de la Botella 1 entre las botellas vigentes de una cámara."""
    if not botellas:
        return None, False
    sin_sufijo = [b for b in botellas if _numero_bot(b[1]) is None]
    if sin_sufijo:
        return sorted(sin_sufijo)[0][0], False
    numeradas = sorted(botellas, key=lambda b: (_numero_bot(b[1]) or 99, b[0]))
    return numeradas[0][0], _numero_bot(numeradas[0][1]) != 1


_SQL_CABLES = text(
    """
    SELECT n_id, nombre, clase, extremo_a_n_id, extremo_b_n_id
    FROM app.cromo_cables
    WHERE vigente
      AND clase = ANY(:clases ::smallint[])
      AND (extremo_a_n_id = ANY(:botellas ::bigint[]) OR extremo_b_n_id = ANY(:botellas ::bigint[]))
    ORDER BY n_id
    """
)


def _es_activo_verificable(s: ServicioUnico) -> bool:
    return bool(s.es_verificable) and (s.estado_servicio or "").strip().lower() == "activo"


def resolver_alcance(session: Session, camara_id: int, botella_objetivo_n_id: Optional[int]) -> AlcanceIntervencion:
    filas = (
        session.query(CromoBotella.n_id, CromoBotella.nombre)
        .filter(CromoBotella.camara_id == camara_id, CromoBotella.vigente.is_(True))
        .order_by(CromoBotella.n_id)
        .all()
    )
    botellas = {int(n_id): nombre or "" for n_id, nombre in filas}
    inferida = False
    objetivo = botella_objetivo_n_id if botella_objetivo_n_id in botellas else None
    if objetivo is None:
        objetivo, inferida = elegir_botella_1(list(botellas.items()))

    cables: list[CableAlcance] = []
    if botellas:
        filas_cables = session.execute(
            _SQL_CABLES, {"clases": sorted(CLASES_CABLE), "botellas": list(botellas)}
        ).all()
        for n_id, nombre, clase, ext_a, ext_b in filas_cables:
            toca_objetivo = objetivo is not None and objetivo in (ext_a, ext_b)
            botella = objetivo if toca_objetivo else (ext_a if ext_a in botellas else ext_b)
            try:
                servicios = servicios_unicos_por_cable_sync(session, int(n_id)).servicios
            except ObjetoNoEncontrado:  # cable sin pelos ingeridos
                servicios = []
            cables.append(
                CableAlcance(
                    n_id=int(n_id),
                    nombre=nombre,
                    clase=int(clase),
                    botella_n_id=int(botella),
                    es_objetivo=toca_objetivo,
                    servicios=[s for s in servicios if _es_activo_verificable(s)],
                )
            )
    cables.sort(key=lambda c: (not c.es_objetivo, c.n_id))
    return AlcanceIntervencion(
        camara_id=camara_id,
        botella_objetivo_n_id=objetivo,
        botella_1_inferida=inferida,
        botellas=botellas,
        cables=cables,
    )
