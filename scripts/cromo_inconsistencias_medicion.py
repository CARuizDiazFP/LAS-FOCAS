# Nombre de archivo: cromo_inconsistencias_medicion.py
# Ubicación de archivo: scripts/cromo_inconsistencias_medicion.py
# Descripción: Medición del detector de inconsistencias de Cromo en modo reporte (no escribe nada):
# conteos por tipo y revisión, caso testigo y muestra validada contra Cromo en vivo

"""Corre `inconsistencias_cromo.detectar(aplicar=False)` y valida una muestra contra Cromo.

No escribe nada en la base: el detector en modo reporte sólo crea y borra dos tablas temporales.
Las únicas llamadas a Cromo son GET (`/db/objects/{id}`): las confirmaciones de las islas
candidatas (con tope `--max-confirmaciones`) y la validación de la muestra.

Correr DENTRO del contenedor del worker de Cromo del entorno (tiene la config de Cromo y la
`DATABASE_URL`). El contenedor no tiene `scripts/`: el script entra por stdin. Si la imagen todavía
no trae el servicio, se le pasa el archivo con `--modulo`:

    docker cp core/services/cromo/inconsistencias_cromo.py lasfocasdev-cromo-worker:/tmp/inc.py
    docker exec -i -w /app -e PYTHONPATH=/app lasfocasdev-cromo-worker \\
        python - --modulo /tmp/inc.py --muestra 5 < scripts/cromo_inconsistencias_medicion.py

    # Sin llamadas a Cromo (todo lo candidato queda MANUAL por falla cerrada)
    docker exec -i ... python - --sin-vivo < scripts/cromo_inconsistencias_medicion.py
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import random
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Any

_FUSION_TESTIGO_BOTELLA = 10234797  # cámara 10238011 (versión), isla confirmada el 2026-10-17


def _cargar_servicio(ruta: str | None):
    nombre = "core.services.cromo.inconsistencias_cromo"
    if ruta:
        spec = importlib.util.spec_from_file_location(nombre, ruta)
        modulo = importlib.util.module_from_spec(spec)
        sys.modules[nombre] = modulo
        spec.loader.exec_module(modulo)
        return modulo
    from core.services.cromo import inconsistencias_cromo

    return inconsistencias_cromo


async def _validar_en_vivo(inc, cliente, caso, ahora) -> dict[str, Any]:
    """Para cada cable del caso, cuántos extremos tiene hoy en Cromo su versión vigente."""
    ev = caso.evidencia
    if caso.tipo == inc.TIPO_ISLA_FUSION:
        cables = [c["n_id"] for c in ev.get("cables", [])]
        versiones = {c["n_id"]: c.get("version_id") for c in ev.get("cables", [])}
    elif caso.tipo == inc.TIPO_CABLE_SIN_EXTREMO:
        cables = [ev["cable"]["n_id"]]
        versiones = {ev["cable"]["n_id"]: ev["cable"].get("version_id")}
    else:
        cables = [c["n_id"] for c in ev.get("cables", [])][:6]
        versiones = {}
    salida = {}
    for n_id in cables:
        cable = inc.CableLocal(
            n_id=n_id, nombre=None, clase=None, version_id=versiones.get(n_id),
            extremo_a_n_id=None, extremo_a_clase=None, extremo_b_n_id=None, extremo_b_clase=None,
        )
        try:
            conf = await inc.confirmar_cable_en_vivo(cliente, cable, ahora=ahora)
            salida[n_id] = {"extremos": conf.extremos, "ids": list(conf.ids_extremos), "borrado": conf.borrado}
        except Exception as exc:  # noqa: BLE001 - es un reporte
            salida[n_id] = {"error": str(exc)[:200]}
    return salida


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--modulo", help="ruta al .py del servicio si la imagen no lo trae")
    parser.add_argument("--sin-vivo", action="store_true", help="no confirma nada contra Cromo")
    parser.add_argument("--max-confirmaciones", type=int, default=None)
    parser.add_argument("--muestra", type=int, default=5, help="casos por tipo a validar en vivo (0 = ninguno)")
    parser.add_argument("--semilla", type=int, default=20261017)
    parser.add_argument("--json", action="store_true", help="imprime el resumen como JSON")
    args = parser.parse_args()

    inc = _cargar_servicio(args.modulo)
    from sqlalchemy import text

    from core.services.cromo.client import CromoClient
    from core.services.cromo.config import get_cromo_config
    from db.session import AsyncSessionLocal

    ahora = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as sesion:
        corrida = (
            await sesion.execute(
                text(
                    "SELECT id, estado FROM app.cromo_ingesta_corridas "
                    "WHERE params ->> 'modo' = 'SOLO_ODF' ORDER BY id DESC LIMIT 1"
                )
            )
        ).first()
        print(f"Última corrida SOLO_ODF: {tuple(corrida) if corrida else None}", file=sys.stderr)
        if args.sin_vivo:
            resumen = await inc.detectar(sesion, cliente=None, aplicar=False, ahora=ahora, max_confirmaciones=0)
            cliente_muestra = None
        else:
            async with CromoClient(config=get_cromo_config()) as cliente:
                resumen = await inc.detectar(
                    sesion, cliente=cliente, aplicar=False, ahora=ahora,
                    max_confirmaciones=args.max_confirmaciones,
                )
                muestras = {}
                if args.muestra:
                    azar = random.Random(args.semilla)
                    for tipo in inc.TIPOS:
                        del_tipo = [c for c in resumen.casos if c.tipo == tipo]
                        elegidos = azar.sample(del_tipo, min(args.muestra, len(del_tipo)))
                        muestras[tipo] = [
                            {
                                "objeto_n_id": c.objeto_n_id,
                                "nombre": c.nombre,
                                "revision": c.revision,
                                "motivo": c.evidencia.get("motivo"),
                                "pelos_en_uso": len(c.pelos),
                                "vivo": await _validar_en_vivo(inc, cliente, c, ahora),
                            }
                            for c in elegidos
                        ]
                cliente_muestra = muestras

    motivos = Counter((c.tipo, c.revision, c.evidencia.get("motivo")) for c in resumen.casos)
    testigo = [
        c for c in resumen.casos
        if c.tipo == inc.TIPO_ISLA_FUSION and c.evidencia["contenedor"]["n_id"] == _FUSION_TESTIGO_BOTELLA
    ]
    testigo_elemento = [
        c for c in resumen.casos
        if c.tipo == inc.TIPO_ELEMENTO_ISLA and c.objeto_n_id == _FUSION_TESTIGO_BOTELLA
    ]
    salida = {
        "resumen": resumen.a_dict(),
        "motivos": [
            {"tipo": t, "revision": r, "motivo": m, "casos": n}
            for (t, r, m), n in sorted(motivos.items())
        ],
        "pelos_en_uso_por_tipo": {
            t: len({p for c in resumen.casos if c.tipo == t for p in c.pelos}) for t in inc.TIPOS
        },
        "servicios_por_tipo": {
            t: len({s for c in resumen.casos if c.tipo == t for s in c.evidencia.get("servicios", [])})
            for t in inc.TIPOS
        },
        "testigo_10234797": {
            "isla_fusion": {f"{r}/{m}": n for (r, m), n in Counter((c.revision, c.evidencia.get("motivo")) for c in testigo).items()},
            "isla_fusion_casos": len(testigo),
            "confirmaciones": testigo[0].evidencia.get("confirmaciones") if testigo else None,
            "elemento_isla": [
                {"revision": c.revision, "motivo": c.evidencia.get("motivo"), "pelos": len(c.pelos)}
                for c in testigo_elemento
            ],
        },
        "muestra": cliente_muestra,
    }
    if args.json:
        print(json.dumps(salida, indent=2, ensure_ascii=False, default=str))
    else:
        print(json.dumps(salida["resumen"], indent=2, ensure_ascii=False))
        for fila in salida["motivos"]:
            print(f"{fila['tipo']:<18} {fila['revision']:<7} {fila['motivo']:<32} {fila['casos']}")
        print(json.dumps({k: salida[k] for k in ("pelos_en_uso_por_tipo", "servicios_por_tipo", "testigo_10234797")},
                         indent=2, ensure_ascii=False, default=str))
        if salida["muestra"]:
            print(json.dumps(salida["muestra"], indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
