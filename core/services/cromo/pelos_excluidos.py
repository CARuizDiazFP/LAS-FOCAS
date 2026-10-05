# Nombre de archivo: pelos_excluidos.py
# Ubicación de archivo: core/services/cromo/pelos_excluidos.py
# Descripción: Exclusión local de pelos de un Servicio — los huérfanos que Cromo sigue etiquetando
# con el Servicio pero que no están en ninguno de sus caminos

"""Sacar (y devolver) un pelo de un Servicio sin tocar Cromo.

Un pelo se mueve por un evento o una tarea y la etiqueta vieja queda en Cromo: sigue matcheando
el Servicio pero no está en ninguno de sus caminos. El tracking ya no lo convierte en un `.txt` de
más (corta en los caminos esperados), pero mientras siga contando como del Servicio ensucia las
semillas, los conteos y la moda de pelos por cable. Excluirlo acá lo saca de todo eso; la etiqueta
en Cromo la corrige quien corresponda, y la exclusión sobrevive a las ingestas.

El filtro vive en las queries de `camino_optico_service` (`_SIN_EXCLUIDOS_SQL`). Este módulo sólo
escribe y lista la tabla.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.cromo.camino_optico_service import pelo_pertenece_al_servicio

logger = logging.getLogger(__name__)


class PeloNoPerteneceAlServicio(ValueError):
    """El pelo no es (o ya no es) del Servicio, así que no hay nada que excluir."""


@dataclass(slots=True)
class PeloExcluido:
    pelo_n_id: int
    numero_pelo: Optional[str]
    color: Optional[str]
    cable_nombre: Optional[str]
    motivo: Optional[str]
    excluido_por: Optional[str]
    created_at: datetime


_SQL_LISTAR = text(
    """
    SELECT x.pelo_n_id, p.numero_pelo, p.color, cab.nombre AS cable_nombre,
           x.motivo, x.excluido_por, x.created_at
    FROM app.cromo_servicio_pelo_excluido x
    LEFT JOIN app.cromo_pelos p ON p.n_id = x.pelo_n_id
    LEFT JOIN app.cromo_cables cab ON cab.n_id = p.cable_n_id
    WHERE x.servicio_id = :servicio_id
    ORDER BY x.created_at DESC, x.pelo_n_id
    """
)

_SQL_INSERTAR = text(
    """
    INSERT INTO app.cromo_servicio_pelo_excluido (servicio_id, pelo_n_id, motivo, excluido_por)
    VALUES (:servicio_id, :pelo_n_id, :motivo, :excluido_por)
    ON CONFLICT (servicio_id, pelo_n_id) DO NOTHING
    """
)

_SQL_BORRAR = text(
    """
    DELETE FROM app.cromo_servicio_pelo_excluido
    WHERE servicio_id = :servicio_id AND pelo_n_id = :pelo_n_id
    """
)


async def listar_excluidos(sesion: AsyncSession, servicio_id: int) -> list[PeloExcluido]:
    filas = (await sesion.execute(_SQL_LISTAR, {"servicio_id": servicio_id})).mappings().all()
    return [PeloExcluido(**dict(fila)) for fila in filas]


async def excluir_pelos(
    sesion: AsyncSession,
    servicio_id: int,
    pelos_n_id: list[int],
    *,
    usuario: Optional[str],
    motivo: Optional[str] = None,
) -> tuple[list[int], list[int]]:
    """Saca los pelos del Servicio. Devuelve `(excluidos, ajenos)`.

    Exige que cada pelo hoy sea del Servicio: excluir uno ajeno no significa nada y dejaría una
    fila que nadie ve. Un pelo ya excluido tampoco pertenece, así que vuelve en `ajenos`. Si todos
    son ajenos se levanta `PeloNoPerteneceAlServicio` y no se escribe nada.

    En lote porque los huérfanos vienen de a decenas: medido el 2026-10-05, 34 en el 42351 y 63 en
    el 93154 (etiquetas que quedaron tras un cambio de ruta, o matches viejos cuyo pelo ya no
    lleva la etiqueta del Servicio en Cromo).
    """
    excluidos: list[int] = []
    ajenos: list[int] = []
    for pelo_n_id in dict.fromkeys(pelos_n_id):
        if await pelo_pertenece_al_servicio(sesion, servicio_id, pelo_n_id):
            excluidos.append(pelo_n_id)
        else:
            ajenos.append(pelo_n_id)
    if not excluidos:
        raise PeloNoPerteneceAlServicio(
            "Ninguno de esos pelos pertenece al Servicio (o ya están excluidos)."
        )
    motivo_limpio = (motivo or "").strip()[:500] or None
    for pelo_n_id in excluidos:
        await sesion.execute(
            _SQL_INSERTAR,
            {
                "servicio_id": servicio_id,
                "pelo_n_id": pelo_n_id,
                "motivo": motivo_limpio,
                "excluido_por": usuario,
            },
        )
    await sesion.commit()
    logger.info(
        "action=cromo_pelo_excluido servicio_id=%s excluidos=%s ajenos=%s user=%s",
        servicio_id,
        excluidos,
        ajenos,
        usuario,
    )
    return excluidos, ajenos


async def restaurar_pelo(
    sesion: AsyncSession, servicio_id: int, pelo_n_id: int, *, usuario: Optional[str]
) -> bool:
    """Devuelve el pelo al Servicio. `False` si no estaba excluido."""
    resultado = await sesion.execute(
        _SQL_BORRAR, {"servicio_id": servicio_id, "pelo_n_id": pelo_n_id}
    )
    await sesion.commit()
    restaurado = (resultado.rowcount or 0) > 0
    logger.info(
        "action=cromo_pelo_restaurado servicio_id=%s pelo_n_id=%s user=%s restaurado=%s",
        servicio_id,
        pelo_n_id,
        usuario,
        restaurado,
    )
    return restaurado


__all__ = [
    "PeloExcluido",
    "PeloNoPerteneceAlServicio",
    "excluir_pelos",
    "listar_excluidos",
    "restaurar_pelo",
]
