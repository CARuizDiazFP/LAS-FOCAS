# Nombre de archivo: sla_completar_horas_cierre.py
# Ubicación de archivo: scripts/sla_completar_horas_cierre.py
# Descripción: Completa app.reclamos.horas_netas_cierre (columna P) desde el Excel de reclamos; dry-run por defecto

"""Completa la columna P de los reclamos ingeridos antes de P25 (2026-11-02).

Sólo escribe `horas_netas_cierre` donde está en NULL y el reclamo figura en el Excel; no toca ninguna
otra columna ni crea reclamos. Sin `--aplicar` hace lo mismo dentro de una transacción que se
revierte, así que el conteo es exacto. Es la misma operación que hace "SLA consumido" al re-subir un
par ya ingestado (`core/sla_consumo/persistencia.py::completar_horas_cierre`).

Correr DENTRO del contenedor `web` o `api` del entorno. El script entra por stdin, así que el Excel se
copia antes:

    docker cp "Reclamos.xlsx" lasfocasdev-web:/tmp/reclamos.xlsx
    docker exec -i -w /app -e PYTHONPATH=/app lasfocasdev-web \\
        python - --reclamos /tmp/reclamos.xlsx [--aplicar] < scripts/sla_completar_horas_cierre.py

El Excel tiene datos de clientes: borrarlo del contenedor al terminar.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if "__file__" in globals() and not __file__.startswith("<"):  # por stdin no hay archivo: usa PYTHONPATH
    ROOT_DIR = Path(__file__).resolve().parents[1]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import text

from core.sla_consumo.parser import parse_reclamos
from core.sla_consumo.persistencia import completar_horas_cierre
from db.session import engine


def _argumentos(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reclamos", required=True, type=Path, help="Excel de reclamos con la columna P")
    parser.add_argument("--aplicar", action="store_true", help="sin esta opción sólo cuenta (dry-run)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _argumentos(argv)
    reclamos = parse_reclamos(args.reclamos.read_bytes())
    with engine.connect() as conn:
        transaccion = conn.begin()
        sin_p_antes = conn.execute(text("SELECT count(*) FROM app.reclamos WHERE horas_netas_cierre IS NULL")).scalar_one()
        completados = completar_horas_cierre(conn, reclamos)
        sin_p_despues = conn.execute(
            text("SELECT count(*) FROM app.reclamos WHERE horas_netas_cierre IS NULL")).scalar_one()
        if args.aplicar:
            transaccion.commit()
        else:
            transaccion.rollback()
    modo = "APLICADO" if args.aplicar else "DRY-RUN"
    print(f"[{modo}] reclamos en el Excel={len(reclamos)} completados={completados} "
          f"sin columna P antes={sin_p_antes} después={sin_p_despues}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
