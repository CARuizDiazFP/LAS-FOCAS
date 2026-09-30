# Nombre de archivo: servicios_fusionar_por_cadena_prov.py
# Ubicación de archivo: scripts/servicios_fusionar_por_cadena_prov.py
# Descripción: Fusiona las filas de app.servicios que PROV identifica como el mismo servicio y deja el ID operativo (INSTALADO) como servicio_id

"""Una fila por servicio real (ver `core/services/servicios_fusion_prov.py` para el criterio).

Correr DENTRO del contenedor de la API, que ya tiene la conexión a su base:

    docker exec lasfocasdev-api python scripts/servicios_fusionar_por_cadena_prov.py            # dry-run exacto
    docker exec lasfocasdev-api python scripts/servicios_fusionar_por_cadena_prov.py --apply    # aplica

El dry-run ejecuta la fusión de verdad dentro de una transacción que se revierte al final: los
números que reporta son exactamente los que aplicaría `--apply`. Cada grupo corre en su propio
savepoint; un grupo que falla se revierte solo y se reporta, sin abortar el resto.

Después de fusionar, realinea las filas sueltas cuyo `servicio_id` es un upgrade `PENDIENTE CPS` (o un
`ANULADO`) en lugar del `INSTALADO` en uso, si ese ID no lo usa otra fila.

Se saltean (y se listan) los grupos ambiguos: cadenas con más de un ID operativo distinto, o con
dos clientes distintos. La salida termina con una línea `action=fusion_prov modo=... ` de resumen.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:  # pragma: no cover - inicialización
    sys.path.insert(0, str(ROOT_DIR))

from core.logging import setup_logging  # noqa: E402
from core.services.servicios_fusion_prov import (  # noqa: E402
    aplicar_plan,
    cargar_desalineadas,
    cargar_grupos,
    planificar,
    realinear,
)

logger = setup_logging("servicios_fusionar_por_cadena_prov")


def ejecutar(session, *, apply: bool) -> dict[str, int]:
    """Planifica y aplica todos los grupos sobre `session`. No hace commit ni rollback final."""

    resumen = {
        "grupos": 0, "fusionados": 0, "salteados": 0, "errores": 0, "filas_borradas": 0, "matches_movidos": 0,
        "realineadas": 0,
    }
    for filas in cargar_grupos(session):
        resumen["grupos"] += 1
        plan = planificar(filas)
        ids = ",".join(str(f.id) for f in filas)
        if plan.motivo_salteo:
            resumen["salteados"] += 1
            logger.warning(
                "action=fusion_prov evento=salteado motivo=%s filas=%s servicio_ids=%s operativos=%s",
                plan.motivo_salteo,
                ids,
                ",".join(f.servicio_id for f in filas),
                ",".join(sorted(plan.ids_operativos)),
            )
            continue
        try:
            with session.begin_nested():
                movidos = aplicar_plan(session, plan)
        except Exception as exc:  # noqa: BLE001 - un grupo con error no debe abortar el resto
            resumen["errores"] += 1
            logger.error("action=fusion_prov evento=error filas=%s error=%s", ids, exc)
            continue
        resumen["fusionados"] += 1
        resumen["filas_borradas"] += len(plan.perdedores)
        resumen["matches_movidos"] += movidos["matches"]
        logger.info(
            "action=fusion_prov evento=%s sobreviviente=%s perdedores=%s id_antes=%s id_final=%s matches_movidos=%s",
            "fusionado" if apply else "fusionaria",
            plan.sobreviviente.id,
            ",".join(str(p.id) for p in plan.perdedores),
            plan.sobreviviente.servicio_id,
            plan.id_final,
            movidos["matches"],
        )

    # Después de fusionar: filas sueltas con un PENDIENTE CPS/ANULADO como ID en lugar del INSTALADO.
    for r in cargar_desalineadas(session):
        try:
            with session.begin_nested():
                realinear(session, r)
        except Exception as exc:  # noqa: BLE001
            resumen["errores"] += 1
            logger.error("action=fusion_prov evento=error_realineacion fila=%s error=%s", r.id, exc)
            continue
        resumen["realineadas"] += 1
        logger.info(
            "action=fusion_prov evento=%s fila=%s id_antes=%s id_final=%s",
            "realineada" if apply else "realinearia",
            r.id,
            r.servicio_id_antes,
            r.operativo,
        )
    return resumen


def main(apply: bool) -> int:
    from db.session import SessionLocal

    inicio = time.perf_counter()
    with SessionLocal() as session:
        try:
            resumen = ejecutar(session, apply=apply)
            if apply:
                session.commit()
            else:
                session.rollback()
        except Exception:
            session.rollback()
            raise
    logger.info(
        "action=fusion_prov modo=%s grupos=%d fusionados=%d salteados=%d errores=%d filas_borradas=%d "
        "matches_movidos=%d realineadas=%d elapsed_seg=%.1f",
        "aplicado" if apply else "dry_run",
        resumen["grupos"],
        resumen["fusionados"],
        resumen["salteados"],
        resumen["errores"],
        resumen["filas_borradas"],
        resumen["matches_movidos"],
        resumen["realineadas"],
        time.perf_counter() - inicio,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Aplica la fusión (por defecto: dry-run exacto)")
    sys.exit(main(parser.parse_args().apply))
