# Nombre de archivo: cromo_backfill_placeholders_servicios.py
# Ubicación de archivo: scripts/cromo_backfill_placeholders_servicios.py
# Descripción: Backfill retroactivo — crea un Servicio placeholder por cada servicio_numero sin match acumulado (4-6 dígitos) y actualiza todas las filas de cromo_servicio_match que lo comparten

"""Crea retroactivamente un `Servicio` placeholder (`categoria=0`, `origen_datos=INFERIDO_CROMO`)
por cada `servicio_numero` distinto que quedó sin match en `app.cromo_servicio_match`
(`servicio_id IS NULL`) y cuya longitud (4-6 dígitos) es consistente con un número de servicio real
— misma heurística que usa `core/services/cromo/ingesta.py::fase_servicios` para altas en vivo desde
2026-08-14 (ver `core/services/cromo/parser.py::es_numero_servicio_plausible`).

**Escala real** (verificado contra `lasfocasdev-postgres`, 2026-08-14): 115.484 filas de
`cromo_servicio_match` con `servicio_id IS NULL`, 9.078 `servicio_numero` distintos. De esos, 9.054
tienen 4-6 dígitos (462 de 4, 6305 de 5, 2287 de 6 — 112.340 filas de match) y generan placeholder;
los 24 restantes (longitud 1-3 u 8-10, ~3.144 filas) son basura/ruido y NUNCA generan placeholder —
quedan exactamente igual que hoy (`servicio_id=NULL`).

**Un placeholder por NÚMERO, no por fila de match**: ~9.054 `Servicio` nuevos para 112.340 filas de
match — el diseño agrupa por `servicio_numero` antes de escribir nada, mismo criterio que ya usa
`scripts/cromo_backfill_camara_padre.py` (resolución en memoria, sin re-consultar por fila).

**Paso de re-validación (antes de crear nada)**: el flag `servicio_id IS NULL` en
`cromo_servicio_match` es del momento en que corrió `fase_servicios` para ese pelo — puede estar
desactualizado si, DESPUÉS de ese intento fallido, se creó/editó un `Servicio` real cuyo
`alias_ids` ahora cubre ese número (el único camino de match que un `ON CONFLICT` sobre
`servicio_id`/`numero_primer_servicio` NO detecta, porque `alias_ids` no tiene unique constraint).
Este script re-corre el mismo criterio de 3 vías (`servicio_id` / `numero_primer_servicio` /
`ANY(alias_ids)`) contra el estado ACTUAL de `app.servicios` para las candidatas ANTES de decidir
qué números realmente necesitan un placeholder nuevo.

**Concurrencia con la ingesta en vivo**: el `INSERT` de cada placeholder usa
`ON CONFLICT DO NOTHING RETURNING id` (mismo mecanismo que `fase_servicios` usa ahora) — si una
corrida de ingesta en vivo crea el MISMO placeholder mientras este script corre, uno de los dos
pierde la carrera de forma controlada (sin excepción) y este script relee el id del que ganó antes
de armar la actualización de `cromo_servicio_match`. No toma advisory lock (mismo razonamiento que
`core/services/cromo/ingesta.py::_resolver_o_crear_servicio`) — igual que
`cromo_backfill_camara_padre.py`, no está pensado para correr dos instancias de SÍ MISMO en
paralelo (no hay protección contra eso), pero SÍ es seguro contra solaparse con la ingesta en vivo.

**Batch, no fila por fila**: la actualización de `cromo_servicio_match.servicio_id` usa
`UPDATE ... FROM (VALUES ...)` en lotes de 500 pares `(numero, id)` — para ~9.054 números eso son
~19 round-trips en vez de 9.054 (un `UPDATE` por número) o 112.340 (uno por fila de match). Mismo
criterio de evitar N+1 que ya está documentado como lección aprendida en
`scripts/cromo_backfill_camara_padre.py` (25+ min por reusar una función pensada para una sola
llamada dentro de un loop grande).

**Idempotente**: la candidata se selecciona por `cromo_servicio_match.servicio_id IS NULL` — una
segunda corrida no encuentra las mismas candidatas, porque la primera corrida ya dejó
`servicio_id` poblado en esas filas (apuntando al placeholder nuevo o a un real encontrado en la
re-validación). Una segunda corrida SÍ puede encontrar candidatas nuevas si llegaron filas de match
nuevas con `servicio_id IS NULL` desde la corrida anterior (ingesta en vivo corriendo con una
versión vieja del código, por ejemplo) — comportamiento correcto, no un bug de idempotencia.

No pega contra ningún sistema externo — sólo lee/escribe `app.servicios`/`app.cromo_servicio_match`.

Uso:
    source .venv/bin/activate
    python scripts/cromo_backfill_placeholders_servicios.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.logging import setup_logging
from core.services.cromo.parser import LONGITUD_SERVICIO_PLAUSIBLE
from db.models.infra import Servicio, ServicioOrigenDatos
from db.session import SessionLocal

logger = setup_logging("cromo_backfill_placeholders_servicios")

_CHUNK_SIZE = 500

_SQL_CANDIDATAS = text(
    """
    SELECT DISTINCT servicio_numero
    FROM app.cromo_servicio_match
    WHERE servicio_id IS NULL
      AND length(servicio_numero) BETWEEN :min_len AND :max_len
    ORDER BY 1
    """
)

_SQL_RESOLUCION_ACTUAL = text(
    """
    SELECT id, servicio_id, numero_primer_servicio, alias_ids
    FROM app.servicios
    WHERE servicio_id = ANY(:numeros ::varchar[])
       OR numero_primer_servicio = ANY(:numeros ::varchar[])
       OR alias_ids && :numeros ::varchar[]
    """
)


def _chunked(items: list[Any], size: int = _CHUNK_SIZE) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _resolver_contra_servicios_actuales(session, numeros: list[str]) -> dict[str, int]:
    """Re-valida `numeros` contra el estado ACTUAL de `app.servicios` (ver nota de re-validación
    en el docstring del módulo) — cubre el caso `alias_ids`, que ningún `ON CONFLICT` detecta."""
    if not numeros:
        return {}
    resueltos: dict[str, int] = {}
    for chunk in _chunked(numeros):
        numeros_set = set(chunk)
        filas = session.execute(_SQL_RESOLUCION_ACTUAL, {"numeros": chunk}).all()
        for servicio_db_id, servicio_id_col, numero_primer_servicio_col, alias_ids_col in filas:
            for candidato in (servicio_id_col, numero_primer_servicio_col):
                if candidato in numeros_set:
                    resueltos[candidato] = servicio_db_id
            for alias in alias_ids_col or []:
                if alias in numeros_set:
                    resueltos[alias] = servicio_db_id
    return resueltos


def _crear_placeholders(session, numeros: list[str]) -> dict[str, int]:
    """INSERT en lote con `ON CONFLICT DO NOTHING RETURNING` — devuelve sólo los que ESTA llamada
    creó. Los que perdieron la carrera (conflicto) se resuelven aparte, ver `_resolver_perdedores`."""
    creados: dict[str, int] = {}
    for chunk in _chunked(numeros):
        valores = [
            {
                "servicio_id": numero,
                "numero_primer_servicio": numero,
                "categoria": 0,
                "origen_datos": ServicioOrigenDatos.INFERIDO_CROMO,
                "estado_servicio": "DESCONOCIDO",
            }
            for numero in chunk
        ]
        stmt = (
            pg_insert(Servicio)
            .values(valores)
            .on_conflict_do_nothing()
            .returning(Servicio.numero_primer_servicio, Servicio.id)
        )
        for numero, servicio_id in session.execute(stmt).all():
            creados[numero] = servicio_id
    return creados


def _actualizar_matches(session, mapeo: dict[str, int]) -> int:
    """UPDATE ... FROM (VALUES ...) en lotes de `_CHUNK_SIZE` pares — evita un UPDATE por número
    (hasta ~9.054 round-trips) y por supuesto un UPDATE por fila de match (hasta 112.340)."""
    items = list(mapeo.items())
    total_actualizado = 0
    for chunk in _chunked(items):
        placeholders_sql = ", ".join(f"(:numero_{j} ::text, :id_{j} ::integer)" for j in range(len(chunk)))
        params: dict[str, Any] = {}
        for j, (numero, servicio_id) in enumerate(chunk):
            params[f"numero_{j}"] = numero
            params[f"id_{j}"] = servicio_id
        resultado = session.execute(
            text(
                f"""
                UPDATE app.cromo_servicio_match AS m
                SET servicio_id = v.nuevo_servicio_id
                FROM (VALUES {placeholders_sql}) AS v(numero, nuevo_servicio_id)
                WHERE m.servicio_numero = v.numero AND m.servicio_id IS NULL
                """
            ),
            params,
        )
        total_actualizado += resultado.rowcount
    return total_actualizado


def main(dry_run: bool) -> None:
    inicio = time.perf_counter()
    session = SessionLocal()
    try:
        candidatas = [
            fila[0]
            for fila in session.execute(
                _SQL_CANDIDATAS,
                {"min_len": min(LONGITUD_SERVICIO_PLAUSIBLE), "max_len": max(LONGITUD_SERVICIO_PLAUSIBLE)},
            ).all()
        ]
        logger.info("action=backfill_placeholders_servicios candidatas=%d", len(candidatas))

        # Paso 1: re-validar contra el estado ACTUAL de app.servicios (cubre alias_ids, ver docstring).
        ya_reales = _resolver_contra_servicios_actuales(session, candidatas)
        logger.info("action=backfill_placeholders_servicios ya_reales_encontrados=%d", len(ya_reales))

        restantes = [numero for numero in candidatas if numero not in ya_reales]
        logger.info("action=backfill_placeholders_servicios a_crear=%d", len(restantes))

        # Paso 2: creación en lote.
        creados = _crear_placeholders(session, restantes)
        logger.info("action=backfill_placeholders_servicios placeholders_creados=%d", len(creados))

        # Paso 3: resolver a los que perdieron la carrera de creación (concurrencia con ingesta en vivo).
        perdieron_carrera = [numero for numero in restantes if numero not in creados]
        resueltos_por_carrera: dict[str, int] = {}
        if perdieron_carrera:
            resueltos_por_carrera = _resolver_contra_servicios_actuales(session, perdieron_carrera)
            logger.warning(
                "action=backfill_placeholders_servicios hallazgo=carrera_con_otra_sesion "
                "perdieron_carrera=%d resueltos=%d",
                len(perdieron_carrera),
                len(resueltos_por_carrera),
            )

        mapeo_final = {**ya_reales, **creados, **resueltos_por_carrera}

        sin_resolver = [n for n in candidatas if n not in mapeo_final]
        if sin_resolver:
            logger.warning(
                "action=backfill_placeholders_servicios hallazgo=sin_resolver cantidad=%d ejemplos=%s "
                "— no debería pasar nunca (ver carrera de creación); esas filas quedan servicio_id=NULL, "
                "igual que antes de correr este script",
                len(sin_resolver),
                sin_resolver[:10],
            )

        # Paso 4: actualización en lote de cromo_servicio_match.
        filas_actualizadas = _actualizar_matches(session, mapeo_final)
        logger.info("action=backfill_placeholders_servicios filas_match_actualizadas=%d", filas_actualizadas)

        elapsed = time.perf_counter() - inicio
        logger.info(
            "action=backfill_placeholders_servicios modo=%s candidatas=%d placeholders_creados=%d "
            "ya_reales=%d filas_match_actualizadas=%d elapsed_seg=%.1f",
            "dry_run" if dry_run else "aplicado",
            len(candidatas),
            len(creados),
            len(ya_reales) + len(resueltos_por_carrera),
            filas_actualizadas,
            elapsed,
        )

        if dry_run:
            logger.info("action=backfill_placeholders_servicios modo=dry_run — no se aplican cambios, rollback")
            session.rollback()
        else:
            session.commit()
            logger.info("action=backfill_placeholders_servicios modo=aplicado — cambios commiteados")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Sólo reporta qué se crearía/actualizaría, sin aplicar cambios")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
