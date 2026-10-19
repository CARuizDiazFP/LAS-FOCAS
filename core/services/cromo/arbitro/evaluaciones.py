# Nombre de archivo: evaluaciones.py
# Ubicación de archivo: core/services/cromo/arbitro/evaluaciones.py
# Descripción: Evaluaciones del árbitro: cierre de las interrumpidas, listado para la UI y alta del análisis retroactivo

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ERROR_INTERRUMPIDA = "interrumpida"
# Una evaluación EN_COLA/EN_CURSO más vieja que esto se considera trabada, no "en curso".
VENTANA_EN_CURSO_HORAS = 6
_LOCK_NORMALIZADOR = 7_920_013
_SQL_EN_CURSO = (
    "estado IN ('EN_COLA', 'EN_CURSO') "
    f"AND encolada_en > now() - interval '{VENTANA_EN_CURSO_HORAS} hours'"
)


def _iso(valor: Optional[datetime]) -> Optional[str]:
    return valor.isoformat() if valor is not None else None


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


async def listar_evaluaciones(sesion: AsyncSession, limit: int = 10) -> dict:
    """Últimas evaluaciones (más nuevas primero) y el id de la más reciente "en curso" (o None)."""
    filas = (
        await sesion.execute(
            text(
                "SELECT id, disparo, alcance, reglas, estado, resumen, error, solicitada_por, "
                "encolada_en, iniciada_en, terminada_en "
                "FROM app.cromo_arbitro_evaluacion ORDER BY id DESC LIMIT :limit"
            ),
            {"limit": int(limit)},
        )
    ).mappings().all()
    items = []
    for f in filas:
        item = dict(f)
        item["id"] = int(item["id"])
        for campo in ("encolada_en", "iniciada_en", "terminada_en"):
            item[campo] = _iso(item[campo])
        items.append(item)
    en_curso = (
        await sesion.execute(
            text(f"SELECT max(id) FROM app.cromo_arbitro_evaluacion WHERE {_SQL_EN_CURSO}")
        )
    ).scalar()
    return {"items": items, "en_curso": int(en_curso) if en_curso is not None else None}


async def crear_evaluacion_normalizador(
    sesion: AsyncSession, usuario: str, reglas: Optional[Sequence[str]]
) -> tuple[Optional[int], Optional[int]]:
    """Alta de la evaluación retroactiva (`EN_COLA`, alcance TODO). Si ya hay otra NORMALIZADOR
    en curso devuelve `(None, id_en_curso)`. Chequeo y alta bajo advisory lock. No hace commit."""
    await sesion.execute(text("SELECT pg_advisory_xact_lock(:c)"), {"c": _LOCK_NORMALIZADOR})
    previa = (
        await sesion.execute(
            text(
                "SELECT max(id) FROM app.cromo_arbitro_evaluacion "
                f"WHERE disparo = 'NORMALIZADOR' AND {_SQL_EN_CURSO}"
            )
        )
    ).scalar()
    if previa is not None:
        return None, int(previa)
    nuevo = (
        await sesion.execute(
            text(
                "INSERT INTO app.cromo_arbitro_evaluacion "
                "(disparo, alcance, reglas, estado, solicitada_por) "
                "VALUES ('NORMALIZADOR', CAST(:alcance AS jsonb), CAST(:reglas AS text[]), 'EN_COLA', :u) "
                "RETURNING id"
            ),
            {
                "alcance": json.dumps({"tipo": "TODO"}),
                "reglas": list(reglas) if reglas is not None else None,
                "u": usuario,
            },
        )
    ).scalar_one()
    return int(nuevo), None


_ALCANCE_POR_OBJETO = {"SERVICIO": "SERVICIOS", "BOTELLA": "BOTELLAS", "ODF": "ODFS"}


async def alcances_de_propuestas(sesion: AsyncSession, ids: Sequence[int]) -> dict[str, list[int]]:
    """Agrupa los objetos de las propuestas `ids` por tipo de alcance (`SERVICIOS`/`BOTELLAS`/`ODFS`)."""
    if not ids:
        return {}
    filas = (
        await sesion.execute(
            text(
                "SELECT DISTINCT objeto_tipo, objeto_id FROM app.cromo_propuesta "
                "WHERE id = ANY(CAST(:ids AS bigint[]))"
            ),
            {"ids": list(ids)},
        )
    ).all()
    alcances: dict[str, list[int]] = {}
    for objeto_tipo, objeto_id in filas:
        tipo = _ALCANCE_POR_OBJETO.get(objeto_tipo)
        if tipo is not None:
            alcances.setdefault(tipo, []).append(int(objeto_id))
    return alcances
