# Nombre de archivo: cromo_relevamiento_cables_fantasma.py
# Ubicación de archivo: scripts/cromo_relevamiento_cables_fantasma.py
# Descripción: Relevamiento de sólo lectura de cables vigentes en la base local que Cromo ya borró, con sucesores y cobertura de servicios

"""Relevamiento de cables "fantasma" (vigentes acá, borrados en Cromo). **No escribe nada**: sólo
`SELECT` en la base y `GET` a Cromo.

Pasos:
1. Barrido liviano (`show=BASIC`) de cada clase de cable: qué ids lista Cromo hoy.
2. Candidatos = cables vigentes locales de la clase que el barrido no vio.
3. Confirmación uno por uno con `GET /db/objects/{n_id}` (`bajas_service.estado_en_cromo`): un
   candidato que sigue vivo (p. ej. listado con otro id de versión) se informa aparte, nunca como
   fantasma.
4. Por fantasma: pelos, asignaciones por método, sucesores y cobertura de servicios.

Imprime el JSON del informe por stdout y el progreso por stderr. Correr DENTRO del worker de Cromo
del entorno. El contenedor no tiene `scripts/`: el script entra por stdin.

    docker exec -i -w /app -e PYTHONPATH=/app lasfocasdev-cromo-worker \\
        python - < scripts/cromo_relevamiento_cables_fantasma.py > relevamiento.json

Mientras `bajas_service` no esté en la imagen desplegada, mandar el módulo adelante en el mismo
stdin (el script lo detecta; su `from __future__` se filtra porque sólo vale al principio):

    { cat core/services/cromo/bajas_service.py; sed '/^from __future__/d' scripts/cromo_relevamiento_cables_fantasma.py; } \\
        | docker exec -i -w /app -e PYTHONPATH=/app lasfocasdev-cromo-worker python - > relevamiento.json

`--clases 51` acota las clases; `--n-id 9609095` salta el barrido y sólo confirma/detalla esos ids.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

if "__file__" in globals() and not __file__.startswith("<"):  # por stdin no hay archivo: usa PYTHONPATH
    ROOT_DIR = Path(__file__).resolve().parents[1]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy.ext.asyncio import AsyncSession

from core.services.cromo.client import CromoClient
from core.services.cromo.config import get_cromo_config
from db.session import async_engine

if "estado_en_cromo" in globals():  # módulo concatenado adelante en el stdin (imagen sin desplegar)
    bajas = SimpleNamespace(**{n: globals()[n] for n in globals()["__all__"]})
else:
    from core.services.cromo import bajas_service as bajas


def _log(mensaje: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {mensaje}", file=sys.stderr, flush=True)


async def relevar(args: argparse.Namespace) -> dict:
    inicio = time.perf_counter()
    informe: dict = {"generado_at": datetime.now(timezone.utc).isoformat(), "clases": {}, "fantasmas": [],
                     "vivos_no_listados": [], "errores_confirmacion": []}
    async with async_engine.connect() as conn:
        externa = await conn.begin()  # sólo lectura: se revierte siempre
        try:
            async with AsyncSession(bind=conn, join_transaction_mode="create_savepoint") as s, \
                    CromoClient(get_cromo_config()) as cliente:
                candidatos: list[int] = []
                if args.n_id:
                    candidatos = list(args.n_id)
                else:
                    for clase in args.clases:
                        t = time.perf_counter()
                        vistos, linajes, conteo = await bajas.ids_en_cromo(cliente, clase, psize=args.psize)
                        ausentes = await bajas.cables_ausentes(s, clase, vistos)
                        faltantes = await bajas.cables_faltantes(s, clase, linajes)
                        informe["clases"][clase] = {"count_cromo": conteo, "objetos_listados": len(linajes),
                                                    "candidatos": len(ausentes), "faltantes": len(faltantes),
                                                    "faltantes_ejemplos": faltantes[:50]}
                        _log(f"clase {clase}: cromo={conteo} listados={len(linajes)} candidatos={len(ausentes)} "
                             f"faltantes={len(faltantes)} ({time.perf_counter() - t:.0f}s)")
                        candidatos.extend(ausentes)

                _log(f"confirmando {len(candidatos)} candidatos contra Cromo")
                confirmados, vivos, errores = await bajas.confirmar_borrados(
                    cliente, candidatos, concurrencia=args.concurrencia
                )
                informe["vivos_no_listados"] = vivos
                informe["errores_confirmacion"] = [{"n_id": n, "error": e} for n, e in errores]

                ids_fantasma = [n for n, _ in confirmados]
                for n_id, vto in confirmados:
                    det = await bajas.detallar_fantasma(s, n_id, vto, ids_fantasma)
                    informe["fantasmas"].append(det.como_dict())
        finally:
            await externa.rollback()

    f = informe["fantasmas"]
    informe["resumen"] = {
        "duracion_s": round(time.perf_counter() - inicio, 1),
        "fantasmas": len(f),
        "fantasmas_con_servicios": sum(1 for x in f if x["servicios"]),
        "fantasmas_con_sucesor": sum(1 for x in f if x["sucesores"]),
        "pelos_a_dar_de_baja": sum(x["pelos"] for x in f),
        "matches_por_metodo": {m: sum(x["matches_por_metodo"].get(m, 0) for x in f)
                               for m in sorted({m for x in f for m in x["matches_por_metodo"]})},
        "fantasmas_con_manual": sum(1 for x in f if x["servicios_manual"]),
        "fantasmas_con_manual_sin_cobertura": sum(1 for x in f if x["manual_sin_cobertura"]),
        "fantasmas_con_servicios_sin_cobertura": sum(1 for x in f if x["servicios_sin_cobertura"]),
        "vivos_no_listados": len(informe["vivos_no_listados"]),
        "errores_confirmacion": len(informe["errores_confirmacion"]),
    }
    return informe


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clases", type=int, nargs="+", default=list(bajas.CLASES_CABLE))
    parser.add_argument("--n-id", type=int, nargs="+", help="Saltear el barrido y sólo confirmar/detallar estos ids")
    parser.add_argument("--psize", type=int, default=50)
    parser.add_argument("--concurrencia", type=int, default=4)
    args = parser.parse_args()
    informe = asyncio.run(relevar(args))
    json.dump(informe, sys.stdout, ensure_ascii=False, indent=1, default=str)
    _log(f"resumen: {json.dumps(informe['resumen'], ensure_ascii=False)}")


if __name__ == "__main__":
    main()
