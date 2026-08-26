# Nombre de archivo: cromo_backfill_reconciliar_servicio_final.py
# Ubicación de archivo: scripts/cromo_backfill_reconciliar_servicio_final.py
# Descripción: Backfill retroactivo — re-resuelve TODAS las filas de cromo_servicio_match (no sólo servicio_id IS NULL) contra el estado actual de app.servicios, para reflejar consolidaciones de la cadena de upgrades SLA

"""Re-resuelve `cromo_servicio_match.servicio_id` para TODOS los `servicio_numero` conocidos
(no sólo los que tienen `servicio_id IS NULL`, a diferencia de
`scripts/cromo_backfill_placeholders_servicios.py`) contra el estado ACTUAL de `app.servicios`.

Necesario porque la consolidación de la cadena de upgrades de Servicios SLA
(`api/app/routes/servicios.py::ingest_servicios` + `core/services/servicios_consolidacion_service.py`)
puede mover un `numero_linea` histórico desde un `Servicio` placeholder (`origen_datos=
INFERIDO_CROMO`) hacia la fila real consolidada, agregándolo a su `alias_ids`. Sin este backfill,
un pelo cuyo match ya apuntaba al placeholder viejo se queda ahí para siempre — la fase regular de
ingesta de Cromo (`core/services/cromo/ingesta.py::fase_servicios`) sólo procesa pares
`(pelo_n_id, servicio_numero)` SIN fila de match previa (`_SQL_PELOS_SIN_MATCH`), nunca reevalúa
matches ya resueltos.

No toca `cromo_pelos.servicio_raw` ni `servicio_numero` — sólo `cromo_servicio_match.servicio_id`.
Mismo patrón que `scripts/cromo_backfill_placeholders_servicios.py`: batch, `--dry-run`, idempotente.

Uso:
    source .venv/bin/activate
    python scripts/cromo_backfill_reconciliar_servicio_final.py [--dry-run]
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

from core.logging import setup_logging
from db.session import SessionLocal

logger = setup_logging("cromo_backfill_reconciliar_servicio_final")

_CHUNK_SIZE = 500

_SQL_TODOS_LOS_NUMEROS = text(
    """
    SELECT DISTINCT servicio_numero, servicio_id
    FROM app.cromo_servicio_match
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


def _actualizar_matches_cambiados(session, cambios: dict[str, int]) -> int:
    items = list(cambios.items())
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
                WHERE m.servicio_numero = v.numero
                  AND m.servicio_id IS DISTINCT FROM v.nuevo_servicio_id
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
        filas = session.execute(_SQL_TODOS_LOS_NUMEROS).all()
        numeros = [servicio_numero for servicio_numero, _ in filas]
        guardado_por_numero = {servicio_numero: guardado for servicio_numero, guardado in filas}
        logger.info("action=backfill_reconciliar_servicio_final numeros_distintos=%d", len(numeros))

        resueltos = _resolver_contra_servicios_actuales(session, numeros)

        cambios = {
            numero: nuevo_id
            for numero, nuevo_id in resueltos.items()
            if guardado_por_numero.get(numero) != nuevo_id
        }
        logger.info(
            "action=backfill_reconciliar_servicio_final resueltos=%d cambios_detectados=%d",
            len(resueltos),
            len(cambios),
        )

        filas_actualizadas = _actualizar_matches_cambiados(session, cambios)
        logger.info("action=backfill_reconciliar_servicio_final filas_match_actualizadas=%d", filas_actualizadas)

        elapsed = time.perf_counter() - inicio
        logger.info(
            "action=backfill_reconciliar_servicio_final modo=%s numeros_distintos=%d cambios=%d "
            "filas_match_actualizadas=%d elapsed_seg=%.1f",
            "dry_run" if dry_run else "aplicado",
            len(numeros),
            len(cambios),
            filas_actualizadas,
            elapsed,
        )

        if dry_run:
            logger.info("action=backfill_reconciliar_servicio_final modo=dry_run — no se aplican cambios, rollback")
            session.rollback()
        else:
            session.commit()
            logger.info("action=backfill_reconciliar_servicio_final modo=aplicado — cambios commiteados")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Sólo reporta qué cambiaría, sin aplicar cambios")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
