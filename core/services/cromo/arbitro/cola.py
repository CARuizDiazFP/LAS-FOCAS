# Nombre de archivo: cola.py
# Ubicación de archivo: core/services/cromo/arbitro/cola.py
# Descripción: Cola Redis de evaluaciones del árbitro de Cromo (best-effort, comparte la cola del worker de recálculo)

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Optional

from core.cache.redis_client import get_redis
from core.services.botella_recompute_queue import QUEUE_KEY
from core.services.cromo.arbitro.senales import Alcance

logger = logging.getLogger(__name__)

JOB_KIND_ARBITRO = "arbitro_evaluar"


async def encolar_evaluacion(
    alcance: Alcance,
    disparo: str,
    motivo: str = "",
    *,
    evaluacion_id: Optional[int] = None,
    reglas: Optional[Sequence[str]] = None,
) -> bool:
    """Encola una evaluación del árbitro para el worker. Nunca lanza: devuelve True sólo si el
    rpush tuvo éxito (los disparadores automáticos pueden ignorar el resultado; best-effort).

    `evaluacion_id` lo pasa sólo el análisis retroactivo de la UI (que ya creó la fila `EN_COLA`);
    los disparadores automáticos no lo pasan.
    """
    try:
        await get_redis().rpush(
            QUEUE_KEY,
            json.dumps(
                {
                    "kind": JOB_KIND_ARBITRO,
                    "alcance": alcance.a_dict(),
                    "disparo": disparo,
                    "motivo": motivo,
                    "evaluacion_id": evaluacion_id,
                    "reglas": list(reglas) if reglas is not None else None,
                }
            ),
        )
        return True
    except Exception:  # noqa: BLE001 - Redis es best-effort
        logger.warning(
            "action=arbitro_encolar result=fail disparo=%s motivo=%s", disparo, motivo, exc_info=True
        )
        return False


__all__ = ["JOB_KIND_ARBITRO", "encolar_evaluacion"]
