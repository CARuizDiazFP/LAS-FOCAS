# Nombre de archivo: cromo_backfill_estado_no_operativa_retroactivo.py
# Ubicación de archivo: scripts/cromo_backfill_estado_no_operativa_retroactivo.py
# Descripción: Corrige retroactivamente a LIBRE las Cámaras padre Cromo que nacieron NO_OPERATIVA bajo el default fail-closed ya revertido, sin auditoría propia (nunca tocadas por un humano ni por otro proceso)

"""Corrige retroactivamente el `estado` de las Cámaras padre `origen_datos=INFERIDO_CROMO` que
nacieron `NO_OPERATIVA` bajo la política fail-closed vigente hasta el 2026-08-13 — decisión revertida
ese mismo día (Cámara padre nueva ahora nace `LIBRE`, ver `docs/decisiones.md`), pero explícitamente
sin re-correr el backfill sobre las filas ya existentes en ese momento. Este script cierra ese
pendiente.

**Candidatas**: `origen_datos=INFERIDO_CROMO` + `estado=NO_OPERATIVA` + sin ninguna fila propia en
`app.camaras_estado_auditoria`. El filtro es "sin ninguna fila de auditoría" (no una lista de
usuarios-bot a excluir): verificado contra `lasfocasdev-postgres` (2026-08-14) que de las 9770
Cámaras `INFERIDO_CROMO`, sólo 98 tienen auditoría propia y el 100% de esas 98 fueron escritas por
procesos automáticos (`cromo_backfill`, `retiro_detectada`) — cero humanos tocaron una Cámara de este
origen. El filtro `NOT EXISTS` da hoy el mismo resultado que una lista explícita de bots a excluir,
pero es más simple y se auto-actualiza: si a futuro una fila recibe auditoría real (humana o de
cualquier proceso), deja de ser candidata sin mantenimiento extra.

**Escritura**: vía `core/services/camara_estado_service.py::aplicar_estado_a_grupo` — único punto de
escritura sancionado de `Camara.estado`, sincroniza `CromoBotella.estado` vinculada en la misma
transacción (invariante establecido el 2026-08-12/13, evita repetir el gap de 295 filas
desincronizadas ya documentado en `scripts/resync_cromo_botella_estado.py`) y deja auditoría propia
por cada miembro modificado. A diferencia de `resolver_o_crear_padre_desde_base` (la función que causó
el incidente real de 25+ min/78% CPU documentado en `scripts/cromo_backfill_camara_padre.py` por
re-escanear TODAS las cámaras raíz en cada llamada), `aplicar_estado_a_grupo` opera sólo sobre
`camara.botellas` (precargada acá con `selectinload`) + un `UPDATE` acotado a las `CromoBotella` del
grupo puntual — no se espera el mismo problema, pero el `--dry-run` mide el tiempo real igual
(`elapsed_seg` en el log) para no asumirlo sin verificar.

Idempotente: una segunda corrida no encuentra candidatas (las filas ya corregidas tienen ahora su
propia fila de auditoría, el filtro `NOT EXISTS` las excluye solo). No pega contra ningún sistema
externo — sólo lee/escribe `app.camaras`/`app.camaras_estado_auditoria`/`app.cromo_botellas`.

Uso:
    source .venv/bin/activate
    python scripts/cromo_backfill_estado_no_operativa_retroactivo.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import exists
from sqlalchemy.orm import selectinload

from core.logging import setup_logging
from core.services.camara_estado_service import aplicar_estado_a_grupo
from db.models.infra import Camara, CamaraEstado, CamaraEstadoAuditoria, CamaraOrigenDatos
from db.session import SessionLocal

logger = setup_logging("cromo_backfill_estado_no_operativa_retroactivo")

_USUARIO = "cromo_backfill_estado_retroactivo"
_MOTIVO = (
    "Backfill retroactivo (2026-08-14) — corrige NO_OPERATIVA heredado del default fail-closed "
    "previo a la reversión de política del 2026-08-13 (Cámara padre nueva ahora nace LIBRE); "
    "sin auditoría previa, ni humana ni de proceso automático."
)


def main(dry_run: bool) -> None:
    inicio = time.perf_counter()
    session = SessionLocal()
    try:
        sin_auditoria = ~exists().where(CamaraEstadoAuditoria.camara_id == Camara.id)
        candidatas = (
            session.query(Camara)
            .filter(
                Camara.origen_datos == CamaraOrigenDatos.INFERIDO_CROMO,
                Camara.estado == CamaraEstado.NO_OPERATIVA,
                sin_auditoria,
            )
            .options(selectinload(Camara.botellas))
            .order_by(Camara.id)
            .all()
        )
        logger.info("action=backfill_estado_retroactivo candidatas=%d", len(candidatas))

        modificadas = 0
        for i, candidata in enumerate(candidatas, start=1):
            auditorias = aplicar_estado_a_grupo(
                session,
                candidata,
                CamaraEstado.LIBRE,
                usuario=_USUARIO,
                motivo=_MOTIVO,
            )
            modificadas += len(auditorias)
            if i % 500 == 0:
                logger.info("action=backfill_estado_retroactivo progreso=%d/%d", i, len(candidatas))

        elapsed = time.perf_counter() - inicio
        logger.info(
            "action=backfill_estado_retroactivo modo=%s candidatas=%d filas_modificadas=%d elapsed_seg=%.1f",
            "dry_run" if dry_run else "aplicado",
            len(candidatas),
            modificadas,
            elapsed,
        )

        if dry_run:
            logger.info("action=backfill_estado_retroactivo modo=dry_run — no se aplican cambios, rollback")
            session.rollback()
        else:
            session.commit()
            logger.info("action=backfill_estado_retroactivo modo=aplicado — cambios commiteados")
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
