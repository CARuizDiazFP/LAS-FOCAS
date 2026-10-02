# Nombre de archivo: cromo_bajas_cables_fantasma.py
# Ubicación de archivo: scripts/cromo_bajas_cables_fantasma.py
# Descripción: Fix retroactivo de cables fantasma — alta de los cables que faltan, sus pelos por /inner y baja lógica de los que Cromo borró; dry-run exacto por defecto

"""Fix retroactivo del relevamiento `docs/relevamiento_cromo_cables_fantasma_2026-10-02.md`.

El orden importa y lo decidió el usuario (2026-10-02): en dev, 70 de los 244 cables que faltaban
eran justamente los que reemplazaron a los fantasmas. Dar de baja primero dejaba a sus servicios sin
cable vigente hasta la próxima ingesta.

1. **Alta**: cada clase de cable se lista en Cromo (`show=BASIC`) y los objetos sin fila local se
   piden uno por uno (última versión del linaje) y se procesan con el mismo código del barrido
   directo (`ingesta._procesar_cable_directo` / `_procesar_cable_tercero_directo`, que en 52/59/60
   ya trae tubos y pelos).
2. **Pelos**: `/inner` (`ingesta.fase_pelos_inner`) de los cables 51 vigentes que no tienen ningún
   pelo — los recién dados de alta y cualquiera que haya quedado igual. Idempotente: un corte entre
   1 y 2 se arregla volviendo a correr.
3. **Baja**: `bajas_service.conciliar_bajas_de_clase` con el mismo conjunto listado en 1: confirma
   cada candidato contra Cromo y aplica la baja lógica. Como los sucesores ya tienen pelos, la regla
   MANUAL ("se borra si el cable que lo reemplaza tiene el mismo servicio") ve la cobertura real.

**Dry-run exacto por defecto**: consulta Cromo de verdad y hace todas las escrituras dentro de una
transacción externa que al final se revierte. Con `--apply` se commitea por tanda.

Correr DENTRO del worker de Cromo del entorno; el script entra por stdin. Mientras `bajas_service`
no esté en la imagen desplegada, mandar el módulo adelante (su `from __future__` se filtra):

    { cat core/services/cromo/bajas_service.py; sed '/^from __future__/d' scripts/cromo_bajas_cables_fantasma.py; } \\
        | docker exec -i -w /app -e PYTHONPATH=/app lasfocasdev-cromo-worker python - [--apply --usuario X]

`--clases 51` acota las clases; `--sin-alta` / `--sin-inner` / `--sin-bajas` saltean un paso;
`--forzar` pasa por encima del tope de bajas por clase (`--tope`, default 300).
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

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.cromo import alias_service, ingesta
from core.services.cromo.client import CromoClient, CromoClientError
from core.services.cromo.config import get_cromo_config
from db.session import async_engine

if "estado_en_cromo" in globals():  # módulo concatenado adelante en el stdin (imagen sin desplegar)
    bajas = SimpleNamespace(**{n: globals()[n] for n in globals()["__all__"]})
else:
    from core.services.cromo import bajas_service as bajas

TIPO_CORRIDA = "MANUAL_BAJAS_CABLES_FANTASMA"
_TANDA = 50
_SQL_51_SIN_PELOS = text(
    "SELECT n_id FROM app.cromo_cables c WHERE vigente AND clase = 51 "
    "AND NOT EXISTS (SELECT 1 FROM app.cromo_pelos p WHERE p.cable_n_id = c.n_id) ORDER BY n_id"
)


def _log(mensaje: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {mensaje}", file=sys.stderr, flush=True)


async def _ultima_version(cliente: CromoClient, n_id: int) -> dict:
    """El objeto vigente del linaje: si `hist[]` dice que la versión pedida no es la última, se pide
    la última (trae `n_id` = linaje, que es lo que el parser usa como clave)."""
    obj = (await cliente.get_objeto(n_id)).get("response") or {}
    estado = bajas.estado_en_cromo(obj)
    if estado.id_ultima_version and estado.id_ultima_version != obj.get("id"):
        obj = (await cliente.get_objeto(estado.id_ultima_version)).get("response") or {}
    return obj


async def _alta(cliente, s, corrida, contadores, faltantes: dict[int, list[int]], alias, apply: bool) -> dict:
    resultado = {"pedidos": 0, "errores": 0, "borrados_en_cromo": 0}
    hechos = 0
    for clase, ids in faltantes.items():
        procesar = ingesta._procesar_cable_tercero_directo if clase in (52, 59, 60) else ingesta._procesar_cable_directo
        for n_id in ids:
            try:
                obj = await _ultima_version(cliente, n_id)
            except CromoClientError as exc:
                resultado["errores"] += 1
                await ingesta.registrar_evento(s, corrida.id, n_id, clase, "ERROR", f"alta: {exc}")
                continue
            if bajas.estado_en_cromo(obj).borrado:  # listado pero ya cerrado: no se da de alta
                resultado["borrados_en_cromo"] += 1
                continue
            await procesar(s, corrida.id, obj, contadores, alias_por_origen=alias)
            resultado["pedidos"] += 1
            hechos += 1
            if hechos % _TANDA == 0:
                ingesta.sincronizar_contadores(corrida, contadores)
                await s.commit()
                _log(f"alta: {hechos} cables")
    ingesta.sincronizar_contadores(corrida, contadores)
    await s.commit()
    return resultado


async def ejecutar(args: argparse.Namespace) -> dict:
    inicio = time.perf_counter()
    salida: dict = {"modo": "apply" if args.apply else "dry-run", "clases": {}}
    async with async_engine.connect() as conn:
        externa = None if args.apply else await conn.begin()
        try:
            async with AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False) as s, \
                    CromoClient(get_cromo_config()) as cliente:
                corrida = await ingesta.iniciar_corrida(
                    s, usuario=args.usuario, psize=0, max_paginas=None, clases=(),
                    params_extra={"tipo": TIPO_CORRIDA, "clases_cable": list(args.clases)},
                )
                contadores = ingesta.ContadoresCorrida()
                alias = await alias_service.cargar_alias_vigentes(s)

                vistos_por_clase: dict[int, set[int]] = {}
                faltantes: dict[int, list[int]] = {}
                for clase in args.clases:
                    vistos, linajes, conteo = await bajas.ids_en_cromo(cliente, clase, psize=args.psize)
                    vistos_por_clase[clase] = vistos
                    faltantes[clase] = await bajas.cables_faltantes(s, clase, linajes)
                    salida["clases"][clase] = {"count_cromo": conteo, "listados": len(linajes),
                                               "faltantes": len(faltantes[clase])}
                    _log(f"clase {clase}: listados={len(linajes)} faltantes={len(faltantes[clase])}")

                if not args.sin_alta:
                    salida["alta"] = await _alta(cliente, s, corrida, contadores, faltantes, alias, args.apply)
                    _log(f"alta: {salida['alta']}")

                if not args.sin_inner and 51 in args.clases:
                    sin_pelos = list((await s.execute(_SQL_51_SIN_PELOS)).scalars().all())
                    _log(f"/inner de {len(sin_pelos)} cables 51 sin pelos")
                    if sin_pelos:
                        r = await ingesta.fase_pelos_inner(
                            cliente, s, corrida, contadores, cables=sin_pelos, concurrencia=args.concurrencia
                        )
                        salida["inner"] = {"cables": len(sin_pelos), "ok": r.cables_ok, "error": r.cables_error,
                                           "pelos_nuevos": r.pelos_nuevos, "vinculos_creados": r.vinculos_creados}
                        _log(f"inner: {salida['inner']}")

                if not args.sin_bajas:
                    salida["bajas"] = {}
                    for clase in args.clases:
                        r = await bajas.conciliar_bajas_de_clase(
                            cliente, s, corrida.id, clase, vistos_por_clase[clase], forzar=args.forzar, tope=args.tope
                        )
                        salida["bajas"][clase] = {
                            "candidatos": r.candidatos, "bajas": r.bajas, "abortado": r.abortado,
                            "vivos_no_listados": r.vivos_no_listados, "errores": r.errores_confirmacion,
                            "pelos": r.pelos, "matches_retirados": r.matches_retirados,
                            "manual_retirados": r.manual_retirados, "manual_conservados": r.manual_conservados,
                        }
                        _log(f"bajas {clase}: {salida['bajas'][clase]}")

                abortado = any(v["abortado"] for v in salida.get("bajas", {}).values())
                corrida.estado = "OK" if contadores.errores == 0 and not abortado else "OK_CON_ERRORES"
                corrida.finalizada_at = datetime.now(timezone.utc)
                ingesta.sincronizar_contadores(corrida, contadores)
                await ingesta.registrar_evento(s, corrida.id, None, None, "RESUMEN", json.dumps(salida, default=str))
                await s.commit()
                salida["corrida_id"] = corrida.id if args.apply else None
        except BaseException:
            if externa is not None:
                await externa.rollback()
            raise
        if externa is not None:
            await externa.rollback()
    salida["duracion_s"] = round(time.perf_counter() - inicio, 1)
    return salida


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Escribir de verdad (sin esto, dry-run exacto)")
    parser.add_argument("--usuario", default="script_bajas_cables_fantasma")
    parser.add_argument("--clases", type=int, nargs="+", default=list(bajas.CLASES_CABLE))
    parser.add_argument("--psize", type=int, default=50)
    parser.add_argument("--concurrencia", type=int, default=4)
    parser.add_argument("--tope", type=int, default=bajas.TOPE_BAJAS_POR_CLASE)
    parser.add_argument("--forzar", action="store_true")
    parser.add_argument("--sin-alta", action="store_true")
    parser.add_argument("--sin-inner", action="store_true")
    parser.add_argument("--sin-bajas", action="store_true")
    args = parser.parse_args()
    salida = asyncio.run(ejecutar(args))
    print(json.dumps(salida, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
