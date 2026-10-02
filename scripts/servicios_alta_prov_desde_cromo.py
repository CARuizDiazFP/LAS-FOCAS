# Nombre de archivo: servicios_alta_prov_desde_cromo.py
# Ubicación de archivo: scripts/servicios_alta_prov_desde_cromo.py
# Descripción: Da de alta desde PROV los servicios que Cromo asigna a pelos (at.62) y que no existen en app.servicios

"""Alta desde PROV de los servicios que Cromo asigna a un pelo y que LAS-FOCAS no conoce.

Hallazgo real (prod, 2026-10-01, después del barrido `/inner`): 47.437 vínculos de
`cromo_servicio_match` con método `ATRIBUTO_*` quedaron con `servicio_id` NULL. Son 15.238 números
que no existen en `app.servicios`, y en una muestra de 15 todos existían en PROV (ISI vigentes con
cliente, y bajas con su cadena de upgrade). Ej.: 120893 (pelo 2 de F-PE-AL-99), ISI de METROTEL.
La API v1 los omitía: `app.servicios` nació del Excel SLA y no tiene todos los servicios.

Por cada número candidato:

0. Si PROV lo da en un estado que no es un servicio (`OST REALIZADA`: IDs de red, confirmado por el
   usuario), no lo da de alta.
1. Si ya resuelve contra `app.servicios` (`_SQL_BUSCAR_SERVICIO`, el mismo de la ingesta Cromo), no
   hace nada: lo dio de alta un número anterior de la misma cadena.
2. Consulta PROV. Si algún ID de su cadena ya es un servicio nuestro, completa ESA fila con
   `ingerir_contexto_prov` (suma los IDs de la cadena como alias) en vez de duplicarla.
3. Si no, crea la fila (`origen_datos=INGEST_PROV`) y la completa con `ingerir_contexto_prov`: ID
   operativo según PROV, cliente, tipo, estado (las bajas quedan con su estado) y cadena.

Un commit por número con `--apply` (reanudable: repetir la corrida saltea lo ya dado de alta). Sin
`--apply` cada número se revierte; el resumen cuenta qué haría. Rate limit de PROV de `ProvConfig`
(5 req/s): ~50 min para ~15.000 números.

Después, en este orden (ver AGENTS.md, Gotchas):

    python scripts/servicios_fusionar_por_cadena_prov.py            # dry-run; luego --apply
    python scripts/cromo_pelos_snapshot.py conciliar --apply          # completa servicio_id de los vínculos

Uso, dentro del contenedor `api` del entorno (credenciales de PROV en /run/secrets):

    docker exec -i -w /app -e PYTHONPATH=/app <prefijo>-api python - --limite 200 < scripts/servicios_alta_prov_desde_cromo.py
    docker exec -i -w /app -e PYTHONPATH=/app <prefijo>-api python - --apply < scripts/servicios_alta_prov_desde_cromo.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path

if "__file__" in globals() and not __file__.startswith("<"):  # por stdin no hay archivo: usa PYTHONPATH
    ROOT_DIR = Path(__file__).resolve().parents[1]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from core.logging import setup_logging
from core.services.cromo.ingesta import _SQL_BUSCAR_SERVICIO
from core.services.prov.client import ProvClient, ProvClientError, ProvServicioNoEncontradoError
from core.services.prov.ingesta import ingerir_contexto_prov, parsear_contexto_prov
from db.models.infra import Servicio, ServicioOrigenDatos
from db.session import AsyncSessionLocal

logger = setup_logging("servicios_alta_prov_desde_cromo")

_SQL_CANDIDATOS = text(
    """
    SELECT servicio_numero, count(*) AS vinculos
    FROM app.cromo_servicio_match
    WHERE servicio_id IS NULL AND metodo LIKE 'ATRIBUTO%'
    GROUP BY servicio_numero
    ORDER BY count(*) DESC, servicio_numero
    """
)
_LIMITE_DRY_RUN = 200
# Estados comerciales de PROV que NO son un servicio: "OST REALIZADA" responde sin cliente, subproducto
# ni cadena (ej. 32200, 6886) y en Cromo el pelo dice "OS 32200 DWDM ARSAT…". El usuario confirmó
# (2026-10-01) que no son servicios válidos, probablemente IDs de red: no se dan de alta y el pelo
# queda `ocupado` sin servicio, como antes.
ESTADOS_NO_SERVICIO = frozenset({"OST REALIZADA"})


def _normalizar_contexto(contexto: dict, numero: str) -> dict:
    """Las bajas de PROV pueden venir sin `nro_servicio` (sólo `nro_servicio_original`, real en la
    muestra del 2026-10-01): sin él, el ID vigente quedaría vacío."""
    copia = dict(contexto)
    if not str(copia.get("nro_servicio") or "").strip():
        copia["nro_servicio"] = copia.get("nro_servicio_original") or numero
    return copia


async def _buscar(session, numero: str) -> int | None:
    fila = (await session.execute(_SQL_BUSCAR_SERVICIO, {"numero": numero})).first()
    return fila[0] if fila else None


async def _cargar(session, servicio_pk: int) -> Servicio:
    stmt = (
        select(Servicio)
        .options(selectinload(Servicio.historial_ids), selectinload(Servicio.equipos_ultima_milla))
        .where(Servicio.id == servicio_pk)
    )
    return (await session.execute(stmt)).scalars().one()


async def procesar_numero(session, cliente, numero: str) -> tuple[str, str | None]:
    """Devuelve `(resultado, estado_servicio)`; el caller hace commit o rollback."""
    if await _buscar(session, numero) is not None:
        return "ya_existia", None
    try:
        contexto = _normalizar_contexto(await cliente.obtener_contexto_servicio(numero), numero)
    except ProvServicioNoEncontradoError:
        return "no_existe_en_prov", None
    if str(contexto.get("estado_comercial") or "").strip().upper() in ESTADOS_NO_SERVICIO:
        return "omitido_no_es_servicio", None
    parseado = parsear_contexto_prov(contexto)
    cadena = {numero, parseado.nro_servicio_vigente, parseado.nro_servicio_original}
    cadena |= {e.numero_id for e in parseado.historial if e.numero_id}
    existente = None
    for otro in sorted(c for c in cadena if c):
        existente = await _buscar(session, otro)
        if existente is not None:
            break
    if existente is not None:
        servicio = await _cargar(session, existente)
        resultado = "completado_por_cadena"
    else:
        servicio = Servicio(
            servicio_id=numero,
            numero_primer_servicio=parseado.nro_servicio_original or numero,
            categoria=0,
            estado_servicio="DESCONOCIDO",
            origen_datos=ServicioOrigenDatos.INGEST_PROV,
            alias_ids=[],
        )
        session.add(servicio)
        await session.flush()
        servicio = await _cargar(session, servicio.id)
        resultado = "creado"
    await ingerir_contexto_prov(session, servicio, contexto)
    # El número que declara Cromo tiene que resolver contra esta fila aunque PROV no lo liste en la
    # cadena (ej. lo consultamos y PROV respondió por el vigente).
    identidades = {servicio.servicio_id, servicio.numero_primer_servicio, *(servicio.alias_ids or [])}
    if numero not in identidades:
        servicio.alias_ids = sorted({*(servicio.alias_ids or []), numero})
    await session.flush()
    return resultado, servicio.estado_servicio


async def main(args: argparse.Namespace) -> dict:
    inicio = time.perf_counter()
    async with AsyncSessionLocal() as session:
        candidatos = [(f.servicio_numero, f.vinculos) for f in (await session.execute(_SQL_CANDIDATOS)).all()]
    limite = args.limite if args.limite is not None else (None if args.apply else _LIMITE_DRY_RUN)
    if limite is not None:
        candidatos = candidatos[:limite]

    resultados: Counter = Counter()
    estados: Counter = Counter()
    vinculos_cubiertos = 0
    errores: list[str] = []
    async with ProvClient() as cliente:
        for indice, (numero, vinculos) in enumerate(candidatos, start=1):
            async with AsyncSessionLocal() as session:
                try:
                    resultado, estado = await procesar_numero(session, cliente, numero)
                    if args.apply:
                        await session.commit()
                    else:
                        await session.rollback()
                except ProvClientError as exc:
                    await session.rollback()
                    resultado, estado = "error_prov", None
                    errores.append(f"{numero}: {exc}")
                except Exception as exc:  # noqa: BLE001 - una corrida de miles no aborta por un número
                    await session.rollback()
                    resultado, estado = "error_ingesta", None
                    errores.append(f"{numero}: {exc!r}")
                    logger.exception("action=alta_prov_desde_cromo evento=error_ingesta numero=%s", numero)
            resultados[resultado] += 1
            if estado:
                estados[estado] += 1
            if resultado in ("creado", "completado_por_cadena"):
                vinculos_cubiertos += vinculos
            if indice % 250 == 0 or indice == len(candidatos):
                print(
                    f"{indice}/{len(candidatos)} {dict(resultados)} estados={dict(estados)} "
                    f"({time.perf_counter() - inicio:.0f}s)",
                    file=sys.stderr, flush=True,
                )
    return {
        "modo": "apply" if args.apply else "dry-run",
        "numeros": len(candidatos),
        "resultados": dict(resultados),
        "estados_servicio": dict(estados),
        "vinculos_cubiertos": vinculos_cubiertos,
        "errores": errores[:30],
        "duracion_s": round(time.perf_counter() - inicio, 1),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="escribe (sin esto: cada número se revierte)")
    parser.add_argument("--limite", type=int, help=f"máximo de números (default: todos con --apply, {_LIMITE_DRY_RUN} en dry-run)")
    args = parser.parse_args()
    resultado = asyncio.run(main(args))
    logger.info("action=alta_prov_desde_cromo %s", {k: v for k, v in resultado.items() if k != "errores"})
    print(json.dumps(resultado, ensure_ascii=False, indent=1))
