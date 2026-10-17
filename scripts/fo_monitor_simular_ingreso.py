# Nombre de archivo: fo_monitor_simular_ingreso.py
# Ubicación de archivo: scripts/fo_monitor_simular_ingreso.py
# Descripción: Simula un ingreso/egreso de técnico (vía registrar_movimiento_ingreso) para probar FO Monitor en dev

"""Registra un movimiento en `app.ingresos` por el MISMO camino que el listener de Slack
(`core/services/ingreso_service.registrar_movimiento_ingreso`), nunca con un INSERT directo, para
que FO Monitor lo vea exactamente como vería un ingreso real.

Sólo para dev: se niega a correr si `POSTGRES_DB` no es la base de desarrollo.

Uso:
    python scripts/fo_monitor_simular_ingreso.py --sugerir             # cámaras con pocos servicios
    python scripts/fo_monitor_simular_ingreso.py --camara-id 2531 --tipo Ingreso
    python scripts/fo_monitor_simular_ingreso.py --camara-id 2531 --botella-n-id 6632152 --tipo Egreso
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from core.services.ingreso_service import registrar_movimiento_ingreso  # noqa: E402
from db.models.cromo import CromoBotella  # noqa: E402
from db.models.infra import Camara  # noqa: E402
from db.session import SessionLocal  # noqa: E402

TECNICO = "SIMULACION-FOMON"
THREAD_TS = "1700000000.000001"


def _sugerir(session) -> None:
    filas = session.execute(
        text(
            """
            SELECT b.camara_id, c.nombre, count(DISTINCT cb.n_id) cables, count(DISTINCT sv.id) servicios
            FROM app.cromo_botellas b
            JOIN app.camaras c ON c.id = b.camara_id
            JOIN app.cromo_cables cb ON cb.vigente AND cb.clase IN (51,52,59,60)
                 AND (cb.extremo_a_n_id = b.n_id OR cb.extremo_b_n_id = b.n_id)
            JOIN app.cromo_pelos p ON p.cable_n_id = cb.n_id AND p.vigente
            JOIN app.cromo_servicio_match m ON m.pelo_n_id = p.n_id
            JOIN app.servicios sv ON sv.id = m.servicio_id AND sv.es_verificable AND lower(sv.estado_servicio) = 'activo'
            WHERE b.vigente
            GROUP BY b.camara_id, c.nombre
            HAVING count(DISTINCT sv.id) BETWEEN 2 AND 6
            ORDER BY count(DISTINCT sv.id), b.camara_id
            LIMIT 10
            """
        )
    ).all()
    for camara_id, nombre, cables, servicios in filas:
        print(f"camara_id={camara_id:<6} cables={cables:<3} servicios={servicios:<3} {nombre}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sugerir", action="store_true")
    ap.add_argument("--camara-id", type=int)
    ap.add_argument("--botella-n-id", type=int)
    ap.add_argument("--tipo", choices=["Ingreso", "Egreso"], default="Ingreso")
    ap.add_argument("--thread-ts", default=THREAD_TS)
    args = ap.parse_args()

    if os.getenv("POSTGRES_DB") != "focas_dev":
        raise SystemExit("Sólo dev: exportá POSTGRES_DB=focas_dev (y el resto de las variables de la DB de dev).")

    with SessionLocal() as session:
        if args.sugerir:
            _sugerir(session)
            return 0
        camara = session.get(Camara, args.camara_id)
        if camara is None:
            raise SystemExit(f"No existe la cámara {args.camara_id}")
        botella = session.get(CromoBotella, args.botella_n_id) if args.botella_n_id else None
        ingreso = registrar_movimiento_ingreso(
            session, camara=camara, botella=botella, tipo_movimiento=args.tipo, tecnico_nombre=TECNICO,
            thread_ts=args.thread_ts, canal_id="C08UB8ML3LP",
        )
        print(f"{args.tipo} registrado: ingreso_id={ingreso.id} camara={camara.nombre} "
              f"botella={botella.nombre if botella else '(Botella 1)'} fecha_fin={ingreso.fecha_fin}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
