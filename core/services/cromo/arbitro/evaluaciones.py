# Nombre de archivo: evaluaciones.py
# Ubicación de archivo: core/services/cromo/arbitro/evaluaciones.py
# Descripción: Reconciliación de evaluaciones del árbitro que quedaron EN_CURSO tras un corte del worker

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ERROR_INTERRUMPIDA = "interrumpida"


async def cerrar_evaluaciones_interrumpidas(sesion: AsyncSession, antes_de: datetime) -> int:
    """Cierra como FALLIDA ("interrumpida") las evaluaciones EN_CURSO iniciadas antes de `antes_de`.
    No hace commit. Devuelve cuántas cerró."""
    resultado = await sesion.execute(
        text(
            "UPDATE app.cromo_arbitro_evaluacion SET estado = 'FALLIDA', error = :e, terminada_en = now() "
            "WHERE estado = 'EN_CURSO' AND iniciada_en < :t"
        ),
        {"e": ERROR_INTERRUMPIDA, "t": antes_de},
    )
    return resultado.rowcount or 0
