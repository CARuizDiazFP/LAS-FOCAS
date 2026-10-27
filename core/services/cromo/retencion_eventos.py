# Nombre de archivo: retencion_eventos.py
# Ubicación de archivo: core/services/cromo/retencion_eventos.py
# Descripción: Retención de app.cromo_ingesta_eventos (90 días por defecto) y purga opcional de los SIN_CAMBIOS históricos, por lotes de ids

"""Retención de los eventos de ingesta Cromo (decisión del usuario, 2026-10-27).

- Se borran los eventos con `created_at` anterior al corte (`ahora - dias`, 90 por defecto).
- Opcionalmente, todos los `SIN_CAMBIOS` históricos, sin importar la edad: desde 2026-10-27
  `ingesta.registrar_evento` ya no los escribe, pero quedan los de antes.
- Nunca se tocan los eventos de una corrida `EN_CURSO`: la reanudación de las fases de pelos lee
  `CABLE_INNER_OK` / `CABLE_SNAPSHOT_OK` de la propia corrida.
- Las filas de `cromo_ingesta_corridas` se conservan: tienen los contadores por acción (`sin_cambios`
  incluido), que es lo que muestra la UI.

El borrado recorre la tabla por rangos de `id` (la PK), así cada `DELETE` es un range scan corto y,
con commit por lote, nunca retiene un lock largo. Hoy no hay ingestas periódicas (scheduler
deshabilitado): se corre a mano con `scripts/cromo_retencion_eventos.py`, y `purgar_eventos` está
lista para engancharse al scheduler cuando se reactive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DIAS_RETENCION = 90
LOTE_IDS = 20_000

_CRITERIO = (
    "c.id = e.corrida_id AND c.estado <> 'EN_CURSO' "
    "AND (e.created_at < :corte OR (CAST(:sin_cambios AS boolean) AND e.accion = 'SIN_CAMBIOS'))"
)

_SQL_CONTAR = text(
    "SELECT e.accion, count(*) FROM app.cromo_ingesta_eventos e "
    f"JOIN app.cromo_ingesta_corridas c ON {_CRITERIO} GROUP BY e.accion ORDER BY count(*) DESC"
)
_SQL_RANGO = text("SELECT min(id), max(id) FROM app.cromo_ingesta_eventos")
_SQL_BORRAR_LOTE = text(
    "DELETE FROM app.cromo_ingesta_eventos e USING app.cromo_ingesta_corridas c "
    f"WHERE e.id >= :desde AND e.id < :hasta AND {_CRITERIO}"
)


@dataclass(slots=True)
class ResultadoRetencion:
    corte: datetime
    por_accion: dict[str, int] = field(default_factory=dict)
    borrados: int = 0
    lotes: int = 0

    @property
    def total(self) -> int:
        return sum(self.por_accion.values())


def calcular_corte(dias: int = DIAS_RETENCION, ahora: Optional[datetime] = None) -> datetime:
    if dias < 1:
        raise ValueError("La retención tiene que ser de al menos 1 día.")
    return (ahora or datetime.now(timezone.utc)) - timedelta(days=dias)


async def contar_purgables(sesion: AsyncSession, corte: datetime, *, incluir_sin_cambios: bool) -> dict[str, int]:
    """Eventos que `purgar_eventos` borraría con el mismo corte, por `accion` (sólo lectura)."""
    filas = await sesion.execute(_SQL_CONTAR, {"corte": corte, "sin_cambios": incluir_sin_cambios})
    return {accion: cantidad for accion, cantidad in filas.all()}


async def purgar_eventos(
    sesion: AsyncSession,
    corte: datetime,
    *,
    incluir_sin_cambios: bool,
    lote_ids: int = LOTE_IDS,
    commit_por_lote: bool = True,
) -> ResultadoRetencion:
    """Borra los eventos purgables por rangos de `lote_ids` ids. Devuelve el conteo previo y lo borrado.

    `commit_por_lote=False` deja todo en la transacción del llamador (tests, o un dry-run exacto que
    termina en rollback).
    """
    resultado = ResultadoRetencion(
        corte=corte, por_accion=await contar_purgables(sesion, corte, incluir_sin_cambios=incluir_sin_cambios)
    )
    if resultado.total == 0:
        return resultado

    minimo, maximo = (await sesion.execute(_SQL_RANGO)).one()
    desde = minimo
    while desde <= maximo:
        hasta = desde + lote_ids
        borrados = await sesion.execute(
            _SQL_BORRAR_LOTE,
            {"desde": desde, "hasta": hasta, "corte": corte, "sin_cambios": incluir_sin_cambios},
        )
        resultado.borrados += borrados.rowcount or 0
        resultado.lotes += 1
        if commit_por_lote:
            await sesion.commit()
        desde = hasta
    return resultado
