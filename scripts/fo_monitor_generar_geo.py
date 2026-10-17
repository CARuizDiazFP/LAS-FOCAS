# Nombre de archivo: fo_monitor_generar_geo.py
# Ubicación de archivo: scripts/fo_monitor_generar_geo.py
# Descripción: Carga/actualiza app.fomon_cable_geo (polilíneas WGS84 de cables Cromo) para el mapa de FO Monitor

"""Reproyecta `pts_raw` de los cables vigentes (clases 51/52/59/60) a WGS84 y lo guarda en
`app.fomon_cable_geo`. Incremental por `vmax`: correrlo de nuevo sólo toca cables nuevos o
modificados, y purga los que dejaron de estar vigentes. Lógica en `core/services/fo_monitor/geometria.py`.

Uso:
    python scripts/fo_monitor_generar_geo.py            # incremental
    python scripts/fo_monitor_generar_geo.py --forzar   # recalcula todo
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.services.fo_monitor.geometria import actualizar_geometrias  # noqa: E402
from db.session import SessionLocal  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--forzar", action="store_true", help="recalcula todos los cables aunque no cambie vmax")
    args = ap.parse_args()
    t0 = time.monotonic()
    with SessionLocal() as session:
        r = actualizar_geometrias(session, forzar=args.forzar)
    print(f"actualizados={r.actualizados} sin_geometria={r.sin_geometria} "
          f"marcados_calidad={r.marcados_calidad} purgados={r.purgados} ({time.monotonic() - t0:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
