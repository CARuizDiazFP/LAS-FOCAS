# Nombre de archivo: evidencia.py
# Ubicación de archivo: core/services/cromo/arbitro/evidencia.py
# Descripción: Persiste la evidencia de caminos de las consultas en vivo a Cromo y encola la evaluación del árbitro

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.cromo.arbitro.cola import encolar_evaluacion
from core.services.cromo.arbitro.senales import Alcance
from core.services.cromo.camino_optico_service import MARCA_LADO_CORTADO, CaminoOptico
from core.services.cromo.tracking_service import (
    ResumenCamino,
    TrackingGenerado,
    pelos_del_camino,
    resumen_del_camino,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EvidenciaEntrada:
    pelo_n_id: int
    resumen: ResumenCamino
    pelos_camino: frozenset[int]


def entradas_de_trackings(trackings: Sequence[TrackingGenerado]) -> list[EvidenciaEntrada]:
    """Una entrada por tracking con extremos; los que no los tienen (fakes viejos) se omiten."""
    return [
        EvidenciaEntrada(t.pelo_n_id, t.extremos, t.pelos_camino)
        for t in trackings
        if t.extremos is not None
    ]


def entrada_de_camino(camino: CaminoOptico) -> Optional[EvidenciaEntrada]:
    if camino.estado != "OK" or camino.pelo_n_id is None:
        return None
    return EvidenciaEntrada(camino.pelo_n_id, resumen_del_camino(camino), pelos_del_camino(camino))


def camino_truncado(camino: CaminoOptico) -> bool:
    """Un lado se cortó en `MAX_NODOS_POR_LADO`: el camino no llega hasta el extremo real."""
    return any(MARCA_LADO_CORTADO in a for a in camino.advertencias)


_UPSERT = text(
    """
    INSERT INTO app.cromo_evidencia_camino
        (servicio_id, pelo_n_id, completo, extremos, pelos_camino, fuente, generado_at)
    VALUES
        (:servicio_id, :pelo_n_id, :completo, CAST(:extremos AS jsonb), :pelos_camino, :fuente, now())
    ON CONFLICT (servicio_id, pelo_n_id) DO UPDATE SET
        completo = EXCLUDED.completo,
        extremos = EXCLUDED.extremos,
        pelos_camino = EXCLUDED.pelos_camino,
        fuente = EXCLUDED.fuente,
        generado_at = now()
    """
)


async def registrar_evidencia(
    sesion: AsyncSession,
    servicio_id: int,
    entradas: Sequence[EvidenciaEntrada],
    *,
    completo: bool,
    fuente: str,
) -> int:
    """Upsert por (servicio, pelo). Devuelve las filas escritas; nunca lanza (0 ante error)."""
    if not entradas:
        return 0
    try:
        async with sesion.begin_nested():
            for e in entradas:
                await sesion.execute(
                    _UPSERT,
                    {
                        "servicio_id": servicio_id,
                        "pelo_n_id": e.pelo_n_id,
                        "completo": completo,
                        "extremos": json.dumps([asdict(x) for x in e.resumen.extremos]),
                        "pelos_camino": sorted(e.pelos_camino),
                        "fuente": fuente,
                    },
                )
        await sesion.commit()
        return len(entradas)
    except Exception:  # noqa: BLE001 - la evidencia es accesoria, jamás rompe la consulta
        logger.warning(
            "action=arbitro_evidencia evento=evidencia_fallida servicio_id=%s fuente=%s",
            servicio_id,
            fuente,
            exc_info=True,
        )
        return 0


async def registrar_y_encolar(
    sesion: AsyncSession,
    servicio_id: int,
    entradas: Sequence[EvidenciaEntrada],
    *,
    completo: bool,
    fuente: str,
) -> None:
    """Registra la evidencia y, si escribió algo, encola la evaluación. Nunca lanza."""
    try:
        escritas = await registrar_evidencia(
            sesion, servicio_id, entradas, completo=completo, fuente=fuente
        )
        if escritas > 0:
            await encolar_evaluacion(
                Alcance("SERVICIOS", (servicio_id,)), "REGISTRADOR", motivo=f"evidencia:{fuente}"
            )
    except Exception:  # noqa: BLE001
        logger.warning(
            "action=arbitro_evidencia evento=registrar_y_encolar_fallido servicio_id=%s",
            servicio_id,
            exc_info=True,
        )


__all__ = [
    "EvidenciaEntrada",
    "camino_truncado",
    "entrada_de_camino",
    "entradas_de_trackings",
    "registrar_evidencia",
    "registrar_y_encolar",
]
