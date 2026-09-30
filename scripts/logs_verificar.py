# Nombre de archivo: logs_verificar.py
# Ubicación de archivo: scripts/logs_verificar.py
# Descripción: Verifica que cada contenedor del stack tenga su colecta de logs (archivo en Logs/ + rotación de docker logs)

"""Chequea la colecta de logs de cada contenedor del stack (dev o prod) y sale con código 1 si falla alguno.

Por contenedor en ejecución del proyecto compose:

1. **Rotación de `docker logs`**: driver `json-file` o `local` con `max-size` (anchor `x-logging` de
   los compose). Aplica a todos, incluidos postgres/redis/docker-socket-proxy/pgadmin, que sólo
   loguean a stdout.
2. **Archivo propio** (sólo servicios Python): `Logs/<archivo>` (prod) o `Logs/dev/<archivo>` (dev)
   existe y fue escrito después de que arrancó el contenedor. `core/logging.py` escribe
   `action=logging evento=inicio` al arrancar, así que un servicio sano lo cumple aunque no haya
   tenido tráfico.

Corre en el host, sin dependencias fuera de la stdlib:

    python scripts/logs_verificar.py --entorno dev
    python scripts/logs_verificar.py --entorno prod --json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PROYECTOS = {"prod": "lasfocas", "dev": "lasfocasdev"}
CARPETAS = {"prod": RAIZ / "Logs", "dev": RAIZ / "Logs" / "dev"}

# Servicio compose → archivo que escribe con core/logging.py (o office_service/app/logging_setup.py).
ARCHIVO_POR_SERVICIO = {
    "api": "api.log",
    "web": "web.log",
    "nlp_intent": "nlp_intent.log",
    "bot": "bot.log",
    "office": "office.log",
    "repetitividad_worker": "repetitividad_worker.log",
    "slack_baneo_worker": "slack_baneo_worker.log",
    "cromo_worker": "cromo_worker.log",
    "botellas_recalculo_worker": "botellas_recalculo_worker.log",
}
# Margen entre el arranque del contenedor y la primera escritura (buffer de 2 s + import de la app).
_MARGEN_SEGUNDOS = 5


def _docker(*args: str) -> str:
    return subprocess.run(["docker", *args], check=True, capture_output=True, text=True).stdout


def _contenedores(proyecto: str) -> list[dict]:
    ids = _docker("ps", "-q", "--filter", f"label=com.docker.compose.project={proyecto}").split()
    return json.loads(_docker("inspect", *ids)) if ids else []


def _parsear_fecha(valor: str) -> float:
    # Docker da nanosegundos ("2026-09-30T18:14:39.21844897Z"); fromisoformat acepta hasta micro.
    base, _, resto = valor.rstrip("Z").partition(".")
    return datetime.fromisoformat(f"{base}.{(resto + '000000')[:6]}+00:00").timestamp()


def verificar(entorno: str, carpeta: Path | None = None) -> list[dict]:
    carpeta = carpeta or CARPETAS[entorno]
    resultados = []
    for c in _contenedores(PROYECTOS[entorno]):
        servicio = c["Config"]["Labels"].get("com.docker.compose.service", c["Name"].lstrip("/"))
        log_config = c["HostConfig"].get("LogConfig") or {}
        problemas = []
        if log_config.get("Type") not in ("json-file", "local") or not (log_config.get("Config") or {}).get("max-size"):
            problemas.append(f"docker logs sin rotación (driver={log_config.get('Type')}, config={log_config.get('Config')})")
        archivo = ARCHIVO_POR_SERVICIO.get(servicio)
        ruta = carpeta / archivo if archivo else None
        if ruta is not None:
            if not ruta.exists():
                problemas.append(f"no existe {ruta}")
            else:
                arranque = _parsear_fecha(c["State"]["StartedAt"])
                if ruta.stat().st_mtime + _MARGEN_SEGUNDOS < arranque:
                    problemas.append(f"{ruta} no se escribió desde que arrancó el contenedor")
        resultados.append(
            {
                "servicio": servicio,
                "contenedor": c["Name"].lstrip("/"),
                "archivo": str(ruta) if ruta else None,
                "ok": not problemas,
                "problemas": problemas,
            }
        )
    return sorted(resultados, key=lambda r: r["servicio"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--entorno", choices=sorted(PROYECTOS), default="dev")
    parser.add_argument("--json", action="store_true", help="salida JSON en vez de tabla")
    parser.add_argument(
        "--carpeta", type=Path,
        help="carpeta de logs montada por el stack (default: Logs/ o Logs/dev/ de este checkout)",
    )
    args = parser.parse_args()

    resultados = verificar(args.entorno, args.carpeta)
    if not resultados:
        print(f"No hay contenedores en ejecución del proyecto {PROYECTOS[args.entorno]}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(resultados, ensure_ascii=False, indent=1))
    else:
        for r in resultados:
            estado = "OK " if r["ok"] else "FALLA"
            print(f"{estado} {r['servicio']:28} {r['archivo'] or '(sólo docker logs)'}")
            for problema in r["problemas"]:
                print(f"      - {problema}")
    return 0 if all(r["ok"] for r in resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
