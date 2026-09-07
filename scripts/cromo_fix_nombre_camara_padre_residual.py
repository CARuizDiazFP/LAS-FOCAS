# Nombre de archivo: cromo_fix_nombre_camara_padre_residual.py
# Ubicación de archivo: scripts/cromo_fix_nombre_camara_padre_residual.py
# Descripción: Corrige el punto residual al inicio del nombre de Cámaras padre sintetizadas desde Cromo, dejado por un bug ya corregido en RE_BOT_SUFIJO/RE_BOTELLA_PREFIJO

"""Corrige retroactivamente el nombre de las Cámaras padre `origen_datos=INFERIDO_CROMO` que quedaron
con un punto residual al inicio (ej. `". Cra Marcos Sastre y Colectora Este"`) — causado por un bug
real ya corregido (2026-08-14) en `RE_BOT_SUFIJO`
(`modules/slack_baneo_notifier/camara_search.py`) y `RE_BOTELLA_PREFIJO`
(`core/services/cromo/camara_padre_service.py`): ninguno de los dos regex consumía un punto
INMEDIATAMENTE DESPUÉS del dígito de "Bot N" — cuando el nombre real de Cromo traía el punto ahí
(ej. `"Bot 2. Cra Marcos Sastre y Colectora Este"`), el punto sobrevivía como residuo.

**Corrección quirúrgica, no re-derivación**: el residuo es matemáticamente equivalente a "quitar el
punto + espacios iniciales del valor ya guardado" — el regex corregido y esta limpieza directa dan el
mismo resultado, verificado a mano contra los casos reales conocidos, incluido uno con un punto
interno legítimo que debe preservarse intacto (`". Poste Est . Bs. As. C.F"` → `"Poste Est . Bs. As. C.F"`,
el punto de `"Est ."` no es parte del bug). Se prefiere sobre re-derivar desde la `CromoBotella`
vinculada porque no depende de que exista un hijo vinculado ni de decidir cuál usar si hay varios.

**Alcance confirmado contra `lasfocasdev-postgres` real (2026-08-14)**: sólo 7 Cámaras
`INFERIDO_CROMO` tienen este residuo (de 9770 totales de ese origen) — el punto AL FINAL del nombre
(ej. `"...C.F."`, 732 filas reales) es formato legítimo original de Cromo, no el bug, y este script no
lo toca (el filtro es "empieza con un punto", sólo el inicio del string).

Idempotente: una segunda corrida no encuentra candidatas (el filtro `nombre ~ '^[.]'` deja de matchear
una vez corregido el nombre). No pega contra ningún sistema externo — sólo lee/escribe `app.camaras`.

Uso:
    source .venv/bin/activate
    python scripts/cromo_fix_nombre_camara_padre_residual.py [--dry-run]
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.logging import setup_logging
from db.models.infra import Camara, CamaraOrigenDatos
from db.session import SessionLocal

logger = setup_logging("cromo_fix_nombre_camara_padre_residual")

_RE_RESIDUO_PUNTO_INICIAL = re.compile(r"^\.\s*")


def main(dry_run: bool) -> None:
    inicio = time.perf_counter()
    session = SessionLocal()
    try:
        candidatas = (
            session.query(Camara)
            .filter(Camara.origen_datos == CamaraOrigenDatos.INFERIDO_CROMO, Camara.nombre.op("~")(r"^\."))
            .order_by(Camara.id)
            .all()
        )
        logger.info("action=fix_nombre_residual candidatas=%d", len(candidatas))

        ahora = datetime.now(timezone.utc)
        for camara in candidatas:
            nombre_anterior = camara.nombre
            nuevo_nombre = re.sub(r"\s+", " ", _RE_RESIDUO_PUNTO_INICIAL.sub("", nombre_anterior)).strip()
            logger.info(
                "action=fix_nombre_residual camara_id=%s nombre_anterior=%r nombre_nuevo=%r",
                camara.id,
                nombre_anterior,
                nuevo_nombre,
            )
            camara.nombre = nuevo_nombre
            camara.last_update = ahora

        elapsed = time.perf_counter() - inicio
        logger.info(
            "action=fix_nombre_residual modo=%s candidatas=%d elapsed_seg=%.1f",
            "dry_run" if dry_run else "aplicado",
            len(candidatas),
            elapsed,
        )

        if dry_run:
            logger.info("action=fix_nombre_residual modo=dry_run — no se aplican cambios, rollback")
            session.rollback()
        else:
            session.commit()
            logger.info("action=fix_nombre_residual modo=aplicado — cambios commiteados")
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
