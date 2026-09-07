# Nombre de archivo: resync_cromo_botella_estado.py
# Ubicación de archivo: scripts/resync_cromo_botella_estado.py
# Descripción: Corrida única que resincroniza CromoBotella.estado con el estado real actual de su Cámara padre

"""Corrige retroactivamente las `CromoBotella` cuyo `estado` quedó desincronizado del estado REAL
actual de su `Camara` padre (hallazgo real, 2026-08-12: 295 filas — 291 en `OCUPADA`/4 en `BANEADA`
con su padre ya en `LIBRE`, 0 `Ingreso`/`IncidenteBaneo` activos en todo el sistema).

**Causa raíz** (ya cerrada estructuralmente, ver `core/services/camara_estado_service.py::
aplicar_estado_a_grupo`): `CromoBotella.estado` era una foto fijada sólo al momento del backfill —
si el padre estaba en `DETECTADA` cuando `scripts/cromo_backfill_camara_padre.py` corrió por primera
vez (2026-08-11, mañana), esa Botella quedó con `estado='OCUPADA'` (mapeo `DETECTADA→OCUPADA`). Horas
después, `scripts/retirar_estado_detectada.py` corrigió el padre a su estado real (`LIBRE`, 0
baneos/ingresos activos) — pero `aplicar_estado_a_grupo`, en ese momento, sólo escribía
`Camara.estado`, nunca las `CromoBotella` ya vinculadas. Desde este commit, `aplicar_estado_a_grupo`
propaga cada cambio real de estado a las `CromoBotella` vinculadas — así que este script es una
corrida única de reparación retroactiva, no un proceso recurrente (cualquier cambio de estado
FUTURO ya se sincroniza solo).

No pega contra ningún sistema externo — sólo lee/escribe `app.camaras`/`app.cromo_botellas`.

Uso:
    source .venv/bin/activate
    python scripts/resync_cromo_botella_estado.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.logging import setup_logging
from core.services.camara_estado_service import MAPEO_ESTADO_CROMO
from db.models.cromo import CromoBotella
from db.models.infra import Camara
from db.session import SessionLocal

logger = setup_logging("resync_cromo_botella_estado")


def main(dry_run: bool) -> None:
    session = SessionLocal()
    try:
        filas = (
            session.query(CromoBotella.n_id, CromoBotella.estado, Camara.estado)
            .join(Camara, CromoBotella.camara_id == Camara.id)
            .filter(CromoBotella.vigente.is_(True))
            .all()
        )
        logger.info("action=resync_cromo_botella_estado vinculadas=%d", len(filas))

        n_ids_por_estado_nuevo: dict = {}
        for n_id, estado_actual, estado_padre_real in filas:
            estado_esperado = MAPEO_ESTADO_CROMO[estado_padre_real]
            if estado_esperado != estado_actual:
                n_ids_por_estado_nuevo.setdefault(estado_esperado, []).append(n_id)

        total_corregidas = 0
        for estado_nuevo, n_ids in n_ids_por_estado_nuevo.items():
            actualizadas = (
                session.query(CromoBotella)
                .filter(CromoBotella.n_id.in_(n_ids))
                .update({CromoBotella.estado: estado_nuevo}, synchronize_session=False)
            )
            total_corregidas += actualizadas
            logger.info(
                "action=resync_cromo_botella_estado estado_nuevo=%s filas_corregidas=%d",
                estado_nuevo.value,
                actualizadas,
            )

        logger.info("action=resync_cromo_botella_estado total_corregidas=%d", total_corregidas)

        if dry_run:
            logger.info("action=resync_cromo_botella_estado modo=dry_run — no se aplican cambios, rollback")
            session.rollback()
        else:
            session.commit()
            logger.info("action=resync_cromo_botella_estado modo=aplicado — cambios commiteados")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Sólo reporta qué se corregiría, sin aplicar cambios")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
