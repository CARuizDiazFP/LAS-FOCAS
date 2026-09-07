# Nombre de archivo: servicios_backfill_no_verificable_por_baja.py
# Ubicación de archivo: scripts/servicios_backfill_no_verificable_por_baja.py
# Descripción: Corrige retroactivamente a No verificable los Servicios en Baja que quedaron marcados verificables antes de que `es_verificable_por_tipo_y_estado` existiera

"""Backfill de una sola corrida para la regla de negocio confirmada con el usuario (2026-08-31): un
Servicio en "Baja" nunca es verificable, sin importar `tipo_servicio` — no tiene sentido correr
verificación física de tracking sobre un servicio dado de baja. `es_verificable_por_tipo_y_estado`
(`core/services/servicios_consolidacion_service.py`) ya aplica esta regla en cada ingesta nueva; este
script corrige las filas que ya estaban en "Baja" ANTES de ese cambio, con `es_verificable=true`
calculado sólo por `tipo_servicio`.

**Candidatas**: `estado_servicio ILIKE 'baja'` AND `es_verificable = true` AND
`es_verificable_override IS NULL` — el mismo criterio que ya respeta la ingesta: un override manual
del admin (`es_verificable_override`) nunca se pisa, esté en Baja o no.

Idempotente: una segunda corrida no encuentra candidatas (ya quedaron en `es_verificable=false`).

Uso:
    source .venv/bin/activate
    python scripts/servicios_backfill_no_verificable_por_baja.py            # sólo reporta (dry-run)
    python scripts/servicios_backfill_no_verificable_por_baja.py --apply    # aplica el cambio
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import and_

from core.logging import setup_logging
from db.models.infra import Servicio
from db.session import SessionLocal

logger = setup_logging("servicios_backfill_no_verificable_por_baja")

_CRITERIO_CANDIDATAS = and_(
    Servicio.estado_servicio.ilike("baja"),
    Servicio.es_verificable.is_(True),
    Servicio.es_verificable_override.is_(None),
)


def main(apply: bool) -> None:
    inicio = time.perf_counter()
    session = SessionLocal()
    try:
        candidatas = session.query(Servicio.id).filter(_CRITERIO_CANDIDATAS).all()
        logger.info("action=backfill_no_verificable_por_baja candidatas=%d", len(candidatas))

        if apply and candidatas:
            actualizadas = (
                session.query(Servicio)
                .filter(_CRITERIO_CANDIDATAS)
                .update({Servicio.es_verificable: False}, synchronize_session=False)
            )
        else:
            actualizadas = 0

        elapsed = time.perf_counter() - inicio
        logger.info(
            "action=backfill_no_verificable_por_baja modo=%s candidatas=%d filas_modificadas=%d elapsed_seg=%.1f",
            "aplicado" if apply else "dry_run",
            len(candidatas),
            actualizadas,
            elapsed,
        )

        if apply:
            session.commit()
            logger.info("action=backfill_no_verificable_por_baja modo=aplicado — cambios commiteados")
        else:
            session.rollback()
            logger.info("action=backfill_no_verificable_por_baja modo=dry_run — no se aplican cambios, rollback")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Aplica el cambio (por defecto sólo reporta)")
    args = parser.parse_args()
    main(apply=args.apply)
