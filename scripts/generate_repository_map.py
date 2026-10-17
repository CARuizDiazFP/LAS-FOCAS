#!/usr/bin/env python3
# Nombre de archivo: generate_repository_map.py
# Ubicación de archivo: scripts/generate_repository_map.py
# Descripción: Genera y verifica docs/REPOSITORY_MAP.md a partir del manifiesto config/repository-map.json

"""Mapa canónico del repositorio (punto de entrada antes de cualquier búsqueda global).

``config/repository-map.json`` declara los dominios (``roots``, ``entrypoints``, ``docs``,
``tests``, ``commands``, ``exclusions``); este script lo renderiza a un Markdown compacto
(``max_output_bytes``, 8 KiB) para que un agente ubique dónde buscar sin indexar todo el árbol.

El archivo generado lleva un comentario HTML con metadatos:

- ``source_commit`` y ``generated_at_utc``: informativos, no participan del ``--check``.
- ``manifest_sha256``: hash del manifiesto; si cambia, el mapa está vencido.

``--check`` falla (código 1) si alguna ruta declarada no existe, si el mapa supera el tope de
bytes, o si el archivo en disco difiere de lo que generaría el manifiesto actual.

Uso:
    python scripts/generate_repository_map.py --write
    python scripts/generate_repository_map.py --check
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
MANIFIESTO = Path("config/repository-map.json")

CAMPOS_VALIDADOS = ("roots", "entrypoints", "docs", "tests")
CAMPOS_DOMINIO = (*CAMPOS_VALIDADOS, "commands", "exclusions")
ETIQUETAS = {
    "roots": "Raíces",
    "entrypoints": "Entradas",
    "docs": "Docs",
    "tests": "Tests",
    "commands": "Comandos",
    "exclusions": "No indexar",
}
RE_METADATA = re.compile(r"\A<!-- repository-map: (?P<datos>\{.*?\}) -->\n", re.DOTALL)


class ErrorMapa(RuntimeError):
    """Manifiesto inválido o mapa desactualizado."""


def cargar_manifiesto(raiz: Path) -> tuple[dict, str]:
    """Devuelve ``(manifiesto, sha256)`` validando la estructura mínima."""
    ruta = raiz / MANIFIESTO
    if not ruta.is_file():
        raise ErrorMapa(f"no existe {MANIFIESTO}")
    crudo = ruta.read_bytes()
    try:
        datos = json.loads(crudo)
    except json.JSONDecodeError as exc:
        raise ErrorMapa(f"{MANIFIESTO} no es JSON válido: {exc}") from exc
    for clave in ("title", "output", "max_output_bytes", "domains"):
        if clave not in datos:
            raise ErrorMapa(f"{MANIFIESTO}: falta la clave {clave!r}")
    vistos: set[str] = set()
    for dominio in datos["domains"]:
        for clave in ("id", "title", "summary", *CAMPOS_DOMINIO):
            if clave not in dominio:
                raise ErrorMapa(f"{MANIFIESTO}: el dominio {dominio.get('id', '?')!r} no declara {clave!r}")
        if dominio["id"] in vistos:
            raise ErrorMapa(f"{MANIFIESTO}: dominio duplicado {dominio['id']!r}")
        vistos.add(dominio["id"])
    return datos, hashlib.sha256(crudo).hexdigest()


def rutas_faltantes(raiz: Path, manifiesto: dict) -> list[str]:
    """Rutas declaradas (no exclusiones ni comandos) que no existen; un glob debe matchear algo."""
    faltantes: list[str] = []
    for dominio in manifiesto["domains"]:
        for campo in CAMPOS_VALIDADOS:
            for ruta in dominio[campo]:
                if any(c in ruta for c in "*?["):
                    existe = bool(glob.glob(str(raiz / ruta)))
                else:
                    existe = (raiz / ruta).exists()
                if not existe:
                    faltantes.append(f"{dominio['id']}.{campo}: {ruta}")
    return faltantes


def _lista(valores: list[str]) -> str:
    return ", ".join(f"`{v}`" for v in valores)


def render_cuerpo(manifiesto: dict) -> str:
    """Markdown del mapa sin la línea de metadatos (es lo que compara ``--check``)."""
    lineas = [
        "# Nombre de archivo: REPOSITORY_MAP.md",
        f"# Ubicación de archivo: {manifiesto['output']}",
        "# Descripción: Mapa canónico del repositorio por dominio (generado; no editar a mano)",
        "",
        f"# {manifiesto['title']}",
        "",
        f"> Generado desde `{MANIFIESTO}` con `python scripts/generate_repository_map.py --write`.",
        "> **Leer antes de cualquier búsqueda global**: identificar el dominio de la tarea y buscar",
        "> sólo dentro de sus raíces. Un dominio por contexto (context-splitting).",
        "",
    ]
    if manifiesto.get("global_exclusions"):
        lineas += [f"No indexar nunca: {_lista(manifiesto['global_exclusions'])}.", ""]
    for dominio in manifiesto["domains"]:
        lineas += [f"## `{dominio['id']}` — {dominio['title']}", "", dominio["summary"], ""]
        for campo in CAMPOS_DOMINIO:
            if dominio[campo]:
                lineas.append(f"- {ETIQUETAS[campo]}: {_lista(dominio[campo])}")
        lineas.append("")
    return "\n".join(lineas).rstrip("\n") + "\n"


def _commit_actual(raiz: Path) -> str:
    try:
        proceso = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"], cwd=raiz, capture_output=True, text=True, check=True
        )
        return proceso.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def render(raiz: Path, manifiesto: dict, sha_manifiesto: str) -> str:
    metadata = {
        "source_commit": _commit_actual(raiz),
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "manifest_sha256": sha_manifiesto,
    }
    return f"<!-- repository-map: {json.dumps(metadata)} -->\n" + render_cuerpo(manifiesto)


def separar_metadata(texto: str) -> tuple[dict, str]:
    coincidencia = RE_METADATA.match(texto)
    if not coincidencia:
        return {}, texto
    try:
        datos = json.loads(coincidencia.group("datos"))
    except json.JSONDecodeError:
        datos = {}
    return datos, texto[coincidencia.end() :]


def verificar(raiz: Path) -> list[str]:
    """Hallazgos que hacen fallar ``--check`` (lista vacía = mapa vigente)."""
    manifiesto, sha_manifiesto = cargar_manifiesto(raiz)
    hallazgos = [f"ruta inexistente: {r}" for r in rutas_faltantes(raiz, manifiesto)]
    salida = raiz / manifiesto["output"]
    if not salida.is_file():
        return [*hallazgos, f"no existe {manifiesto['output']}: generarlo con --write"]
    texto = salida.read_text(encoding="utf-8")
    metadata, cuerpo = separar_metadata(texto)
    if len(texto.encode("utf-8")) > int(manifiesto["max_output_bytes"]):
        hallazgos.append(
            f"{manifiesto['output']} pesa {len(texto.encode('utf-8'))} bytes "
            f"(tope {manifiesto['max_output_bytes']})"
        )
    if not metadata:
        hallazgos.append(f"{manifiesto['output']} no tiene el comentario de metadatos")
    elif metadata.get("manifest_sha256") != sha_manifiesto:
        hallazgos.append(f"{manifiesto['output']} se generó con otro manifiesto: regenerar con --write")
    if cuerpo != render_cuerpo(manifiesto):
        hallazgos.append(f"{manifiesto['output']} difiere de lo generado: regenerar con --write")
    return hallazgos


def escribir(raiz: Path) -> Path:
    manifiesto, sha_manifiesto = cargar_manifiesto(raiz)
    faltantes = rutas_faltantes(raiz, manifiesto)
    if faltantes:
        raise ErrorMapa("rutas inexistentes en el manifiesto: " + "; ".join(faltantes))
    contenido = render(raiz, manifiesto, sha_manifiesto)
    tamano = len(contenido.encode("utf-8"))
    if tamano > int(manifiesto["max_output_bytes"]):
        raise ErrorMapa(f"el mapa pesaría {tamano} bytes (tope {manifiesto['max_output_bytes']}): acortar el manifiesto")
    salida = raiz / manifiesto["output"]
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(contenido, encoding="utf-8")
    return salida


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Genera o verifica docs/REPOSITORY_MAP.md")
    modo = parser.add_mutually_exclusive_group(required=True)
    modo.add_argument("--write", action="store_true", help="Regenerar el mapa")
    modo.add_argument("--check", action="store_true", help="Verificar que el mapa esté vigente")
    parser.add_argument("--root", type=Path, default=RAIZ, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    raiz = args.root.resolve()
    try:
        if args.write:
            salida = escribir(raiz)
            print(f"OK: {salida.relative_to(raiz)} regenerado")
            return 0
        hallazgos = verificar(raiz)
    except ErrorMapa as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if hallazgos:
        for hallazgo in hallazgos:
            print(f"ERROR: {hallazgo}", file=sys.stderr)
        return 1
    print("OK: mapa del repositorio vigente")
    return 0


if __name__ == "__main__":  # pragma: no cover - punto de entrada
    raise SystemExit(main())
