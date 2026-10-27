# Nombre de archivo: cromo_retencion_eventos.py
# Ubicación de archivo: scripts/cromo_retencion_eventos.py
# Descripción: Retención manual de app.cromo_ingesta_eventos (default 90 días) y purga opcional de SIN_CAMBIOS históricos; dry-run por defecto

"""Aplica la retención de `core/services/cromo/retencion_eventos.py` a mano.

Hoy no hay ingestas periódicas (scheduler deshabilitado), así que no hay cron: se corre cuando haga
falta. Sin `--aplicar` sólo cuenta, por `accion`, lo que borraría. Con `--aplicar` borra por lotes
de ids con commit por lote.

Correr DENTRO del worker de Cromo del entorno (el host no tiene la config de la base):

    docker exec -i -w /app -e PYTHONPATH=/app lasfocasdev-cromo-worker \\
        python - --dias 90 [--incluir-sin-cambios] [--aplicar] < scripts/cromo_retencion_eventos.py

Si la imagen todavía no trae `retencion_eventos`, copiar `core/` del worktree a `/tmp/wt` del
contenedor y correr con `-w /tmp/wt -e PYTHONPATH=/tmp/wt` (skill `cromo-diagnostico-real`, regla 13).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

if "__file__" in globals() and not __file__.startswith("<"):  # por stdin no hay archivo: usa PYTHONPATH
    ROOT_DIR = Path(__file__).resolve().parents[1]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy.ext.asyncio import AsyncSession

from core.services.cromo import retencion_eventos
from db.session import async_engine


def _argumentos(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dias", type=int, default=retencion_eventos.DIAS_RETENCION)
    parser.add_argument(
        "--incluir-sin-cambios",
        action="store_true",
        help="borra también todos los SIN_CAMBIOS históricos, sin importar la edad",
    )
    parser.add_argument("--lote-ids", type=int, default=retencion_eventos.LOTE_IDS)
    parser.add_argument("--aplicar", action="store_true", help="sin esta opción sólo cuenta (dry-run)")
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    args = _argumentos(argv)
    corte = retencion_eventos.calcular_corte(args.dias)
    async with AsyncSession(async_engine, expire_on_commit=False) as sesion:
        if args.aplicar:
            resultado = await retencion_eventos.purgar_eventos(
                sesion, corte, incluir_sin_cambios=args.incluir_sin_cambios, lote_ids=args.lote_ids
            )
            por_accion = resultado.por_accion
        else:
            por_accion = await retencion_eventos.contar_purgables(
                sesion, corte, incluir_sin_cambios=args.incluir_sin_cambios
            )
    await async_engine.dispose()

    modo = "APLICADO" if args.aplicar else "DRY-RUN"
    print(f"[{modo}] corte={corte.isoformat()} dias={args.dias} incluir_sin_cambios={args.incluir_sin_cambios}")
    for accion, cantidad in por_accion.items():
        print(f"  {accion:<24} {cantidad:>9}")
    print(f"  {'TOTAL':<24} {sum(por_accion.values()):>9}")
    if args.aplicar:
        print(f"  borrados={resultado.borrados} lotes={resultado.lotes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
