# Nombre de archivo: aviso.py
# Ubicación de archivo: core/services/cromo/arbitro/aviso.py
# Descripción: Aviso por WebSocket y Slack de las evaluaciones del árbitro de Cromo (nunca lanza)

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from core.services.cromo.arbitro.motor import ResumenEvaluacion

logger = logging.getLogger(__name__)

TIPO_WS_EVALUADO = "arbitro_cromo_evaluado"
TIPO_WS_EN_CURSO = "arbitro_cromo_en_curso"


async def _publicar(payload: dict) -> None:
    from core.cache.redis_client import get_redis
    from core.services.botella_recompute_queue import ADMIN_NOTIFICATIONS_CHANNEL

    await get_redis().publish(ADMIN_NOTIFICATIONS_CHANNEL, json.dumps(payload))


async def avisar_en_curso(evaluacion_id: Optional[int]) -> None:
    """Avisa por WS que una evaluación pasó a EN_CURSO. Nunca lanza."""
    try:
        await _publicar({"type": TIPO_WS_EN_CURSO, "evaluacion_id": evaluacion_id})
    except Exception as exc:  # noqa: BLE001 - el aviso jamás rompe la evaluación
        logger.warning("action=arbitro_aviso evento=ws_en_curso_error error=%s", exc)


def _texto_slack(resumen: "ResumenEvaluacion") -> str:
    partes = [
        f"{len(resumen.aplicadas_auto)} aplicadas en automático",
        f"{len(resumen.revertidas)} revertidas",
    ]
    if resumen.presupuesto_excedido:
        partes.append(f"presupuesto excedido en: {', '.join(resumen.presupuesto_excedido)}")
    return "Árbitro de Cromo: " + ", ".join(partes)


async def avisar_evaluacion(resumen: "ResumenEvaluacion", evaluacion_id: Optional[int]) -> None:
    """Publica el resultado por WS y, si hubo cambios, lo manda a Slack. Nunca lanza."""
    try:
        try:
            await _publicar(
                {
                    "type": TIPO_WS_EVALUADO,
                    "evaluacion_id": evaluacion_id,
                    "nuevas": resumen.nuevas,
                    "aplicadas_auto": len(resumen.aplicadas_auto),
                    "revertidas": len(resumen.revertidas),
                    "presupuesto_excedido": list(resumen.presupuesto_excedido),
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("action=arbitro_aviso evento=ws_error error=%s", exc)

        if not (resumen.aplicadas_auto or resumen.revertidas or resumen.presupuesto_excedido):
            return
        try:
            from core.services.cromo import inconsistencias_reporte as rep
            from db.session import AsyncSessionLocal

            async with AsyncSessionLocal() as sesion:
                canales, activo = await rep._leer_config_slack(sesion)
            if not (activo and canales):
                return
            token = rep._token_slack()
            if not token:
                logger.warning("action=arbitro_aviso evento=slack_omitido motivo=sin_token")
                return
            await asyncio.to_thread(
                rep._enviar_slack_sync, canales, token, _texto_slack(resumen), None, ""
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("action=arbitro_aviso evento=slack_error error=%s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("action=arbitro_aviso evento=aviso_error error=%s", exc)


__all__ = ["avisar_en_curso", "avisar_evaluacion"]
