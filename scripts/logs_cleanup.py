# Nombre de archivo: logs_cleanup.py
# Ubicación de archivo: scripts/logs_cleanup.py
# Descripción: Rotación por renombre, retención y truncado seguro de Logs/ con los servicios corriendo; reporte por defecto

"""Limpieza de `Logs/` que se puede correr con los servicios en marcha.

Los servicios escriben con `core/logging.py::BufferedAppendFileHandler`, que abre, escribe y cierra
el archivo en cada volcado (cada ~2 s). Por eso nada queda bloqueado y se puede:

- **rotar por renombre**: `x.log` → `x.log.YYYYMMDD-HHMMSS`. El volcado siguiente crea un `x.log`
  nuevo en la misma ruta. Sin `copytruncate`: no se pierde ni se duplica nada.
- **borrar rotados** más viejos que `--dias`, y los más viejos hasta respetar `--max-total-mb`.
- **truncar** un archivo en uso (`--truncar`): sin offset guardado, no quedan huecos.

Por defecto sólo informa. `--apply` ejecuta. Guardrail (skill `logs-cleanup`): no rota, trunca ni
borra un archivo con un `ERROR`/`CRITICAL` en los últimos `--ventana-error-min` minutos, salvo con
`--forzar`. Con eso no se pierde la evidencia de un incidente en curso.

Los logs de Docker (`docker logs`) no se tocan acá: los rota el driver `json-file` con `max-size`
(anchor `x-logging` de los compose). No necesita `sudo`.

    python scripts/logs_cleanup.py                  # reporte de Logs/ (incluye Logs/dev/)
    python scripts/logs_cleanup.py --apply
    python scripts/logs_cleanup.py --apply --truncar Logs/dev/web.log
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
_MB = 1024 * 1024
_REGEX_ROTADO = re.compile(r"\.log\.(\d{8}-\d{6}|\d+)$")
_REGEX_ERROR = re.compile(r"level=(ERROR|CRITICAL)\b")
_FORMATO_FECHA_LOG = "%Y-%m-%d %H:%M:%S"
_BLOQUE_BYTES = 256 * 1024


@dataclass
class Plan:
    rotar: list[Path] = field(default_factory=list)
    borrar: list[Path] = field(default_factory=list)
    truncar: list[Path] = field(default_factory=list)
    protegidos: list[tuple[Path, str]] = field(default_factory=list)


def _es_rotado(ruta: Path) -> bool:
    return bool(_REGEX_ROTADO.search(ruta.name))


def _lineas_desde_el_final(ruta: Path):
    """Líneas del archivo de la última a la primera, leyendo de a `_BLOQUE_BYTES` (nunca entero)."""
    with open(ruta, "rb") as archivo:
        archivo.seek(0, os.SEEK_END)
        posicion, resto = archivo.tell(), b""
        while posicion > 0:
            leer = min(_BLOQUE_BYTES, posicion)
            posicion -= leer
            archivo.seek(posicion)
            partes = (archivo.read(leer) + resto).split(b"\n")
            resto = partes.pop(0)  # puede ser media línea: se completa con el bloque anterior
            for linea in reversed(partes):
                yield linea.decode("utf-8", "replace")
        if resto:
            yield resto.decode("utf-8", "replace")


def _tiene_error_reciente(ruta: Path, ventana_min: float, ahora: float) -> bool:
    """¿Hay una línea ERROR/CRITICAL con timestamp dentro de la ventana?

    Recorre desde el final y corta en la primera línea fechada más vieja que la ventana: en un log
    muy activo el error de hace 5 minutos puede estar a varios MB del final.
    """
    limite = ahora - ventana_min * 60
    try:
        for linea in _lineas_desde_el_final(ruta):
            try:
                momento = datetime.strptime(linea[:19], _FORMATO_FECHA_LOG).timestamp()
            except ValueError:
                continue
            if momento < limite:
                return False
            if _REGEX_ERROR.search(linea):
                return True
    except OSError:
        return False
    return False


def armar_plan(
    carpeta: Path,
    *,
    max_mb: float,
    dias: float,
    max_total_mb: float,
    truncar: list[Path],
    ventana_error_min: float,
    forzar: bool,
    ahora: float | None = None,
) -> Plan:
    ahora = ahora or time.time()
    plan = Plan()
    archivos = sorted(p for p in carpeta.rglob("*") if p.is_file() and (p.suffix == ".log" or _es_rotado(p)))

    evaluados: dict[Path, bool] = {}

    def protegido(ruta: Path) -> bool:
        if ruta not in evaluados:
            evaluados[ruta] = not forzar and _tiene_error_reciente(ruta, ventana_error_min, ahora)
            if evaluados[ruta]:
                plan.protegidos.append((ruta, f"ERROR en los últimos {ventana_error_min:g} min"))
        return evaluados[ruta]

    for ruta in truncar:
        if ruta.exists() and not protegido(ruta):
            plan.truncar.append(ruta)

    activos = [p for p in archivos if not _es_rotado(p)]
    rotados = [p for p in archivos if _es_rotado(p)]
    for ruta in activos:
        if ruta in plan.truncar or ruta.stat().st_size <= max_mb * _MB:
            continue
        if not protegido(ruta):
            plan.rotar.append(ruta)

    limite_edad = ahora - dias * 86400
    plan.borrar = [p for p in rotados if p.stat().st_mtime < limite_edad]

    # Tope total: tras rotar/borrar, si Logs/ sigue por encima, se borran los rotados más viejos.
    # Los recién rotados cuentan como rotados (siguen ocupando disco hasta el próximo pase).
    restantes = sorted((p for p in rotados if p not in plan.borrar), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in archivos if p not in plan.borrar and p not in plan.truncar)
    while total > max_total_mb * _MB and restantes:
        viejo = restantes.pop(0)
        plan.borrar.append(viejo)
        total -= viejo.stat().st_size
    return plan


def aplicar(plan: Plan) -> list[tuple[Path, str]]:
    """Ejecuta el plan. Devuelve lo que no se pudo hacer, sin cortar el resto.

    Real (2026-09-30): `office.log` lo crea el usuario de la imagen de office (UID 1000), no el dueño de
    Logs/; si el archivo no es escribible por grupo, truncarlo desde el host da `PermissionError`.
    Rotar y borrar sólo necesitan permiso sobre la carpeta.
    """
    sello = datetime.now().strftime("%Y%m%d-%H%M%S")
    fallidos: list[tuple[Path, str]] = []

    def intentar(ruta: Path, accion) -> None:
        try:
            accion()
        except OSError as exc:
            fallidos.append((ruta, str(exc)))

    for ruta in plan.rotar:
        intentar(ruta, lambda r=ruta: r.rename(r.with_name(f"{r.name}.{sello}")))
    for ruta in plan.truncar:
        intentar(ruta, lambda r=ruta: os.truncate(r, 0))
    for ruta in plan.borrar:
        intentar(ruta, lambda r=ruta: r.unlink(missing_ok=True))
    return fallidos


def _mb(ruta: Path) -> str:
    try:
        return f"{ruta.stat().st_size / _MB:8.1f} MB"
    except OSError:
        return "       ? MB"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--carpeta", type=Path, default=RAIZ / "Logs", help="default: Logs/ de este checkout (con dev/)")
    parser.add_argument("--apply", action="store_true", help="ejecutar (sin esto: sólo reporte)")
    parser.add_argument("--max-mb", type=float, default=50, help="rotar archivos activos que superen este tamaño")
    parser.add_argument("--dias", type=float, default=14, help="borrar rotados más viejos que esto")
    parser.add_argument("--max-total-mb", type=float, default=500, help="tope total de la carpeta")
    parser.add_argument("--truncar", type=Path, action="append", default=[], help="archivo a vaciar (repetible)")
    parser.add_argument("--ventana-error-min", type=float, default=10, help="protege archivos con ERROR reciente")
    parser.add_argument("--forzar", action="store_true", help="ignorar la protección por ERROR reciente")
    args = parser.parse_args()

    carpeta = args.carpeta.resolve()
    if not carpeta.is_dir():
        print(f"No existe la carpeta {carpeta}", file=sys.stderr)
        return 1
    truncar = [p.resolve() for p in args.truncar]
    fuera = [p for p in truncar if carpeta not in p.parents]
    if fuera:
        print(f"--truncar fuera de {carpeta}: {fuera}", file=sys.stderr)
        return 1

    plan = armar_plan(
        carpeta, max_mb=args.max_mb, dias=args.dias, max_total_mb=args.max_total_mb,
        truncar=truncar, ventana_error_min=args.ventana_error_min, forzar=args.forzar,
    )
    total = sum(p.stat().st_size for p in carpeta.rglob("*") if p.is_file())
    print(f"{'APLICANDO' if args.apply else 'REPORTE'} {carpeta} — total {total / _MB:.1f} MB")
    for titulo, rutas in (("rotar", plan.rotar), ("truncar", plan.truncar), ("borrar", plan.borrar)):
        for ruta in rutas:
            print(f"  {titulo:8} {_mb(ruta)}  {ruta.relative_to(carpeta)}")
    for ruta, motivo in plan.protegidos:
        print(f"  {'protegido':8} {_mb(ruta)}  {ruta.relative_to(carpeta)} ({motivo}; --forzar para ignorarlo)")
    if not (plan.rotar or plan.truncar or plan.borrar):
        print("  nada que hacer")
    if args.apply:
        fallidos = aplicar(plan)
        for ruta, error in fallidos:
            print(f"  FALLÓ    {ruta.relative_to(carpeta)}: {error}", file=sys.stderr)
        return 1 if fallidos else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
