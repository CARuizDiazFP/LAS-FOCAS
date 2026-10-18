#!/usr/bin/env python3
# Nombre de archivo: audit_agentic_environment.py
# Ubicación de archivo: scripts/audit_agentic_environment.py
# Descripción: Auditor determinista de los contratos del entorno agéntico (gobernanza, skills, mirrors, mapa, exclusiones y estado de agentes)

"""Auditoría integral y determinista del entorno agéntico de LAS-FOCAS.

Complementa a ``scripts/check_skill_mirror_drift.sh`` (que sólo mira mirrors) verificando
los contratos obligatorios de gobernanza. Cada hallazgo es una línea ``nivel:código:detalle``:

- ``error:*`` hace salir con código 1 (contrato roto).
- ``warning:stale_lease:*`` / ``warning:stale_agent:*`` son avisos no bloqueantes sobre el
  estado compartido de agentes (se leen en modo sólo lectura: el auditor nunca escribe ni
  migra ``agent_state.sqlite3``).

Uso:
    python scripts/audit_agentic_environment.py          # exit 0 si pasa, 1 si falla
    python scripts/audit_agentic_environment.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:  # pragma: no cover - inicialización
    sys.path.insert(0, str(RAIZ))

from scripts import generate_repository_map, sync_skill_mirrors  # noqa: E402

ARCHIVOS_OBLIGATORIOS = (
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    "docs/REPOSITORY_MAP.md",
    "docs/superpowers/CATALOG.md",
    ".copilotignore",
    ".geminiignore",
    ".cursorignore",
    ".aiderignore",
)
ARCHIVOS_IGNORE = (".geminiignore", ".copilotignore", ".cursorignore", ".aiderignore")
PATRONES_IGNORE_OBLIGATORIOS = (".venv/", "Logs/", "*.log", ".secrets/", ".env*", "web/frontend/node_modules/")

CIERRE_SESION = Path(".agentes-comunes/skills/cierre-sesion/SKILL.md")
# Marcadores textuales del contrato de cierre-sesion: (código, texto requerido).
CONTRATO_CIERRE = (
    ("trigger_cerrar", "`Cerrar sesión`"),
    ("trigger_cerremos", "`Cerremos sesión`"),
    ("trigger_comando", "`/cierre-sesion`"),
    ("triggers_unicos", "únicos\ntriggers directos"),
    ("compuerta_riesgo", "**Compuerta de Riesgo**"),
    ("riesgo_muy_alto", "🔴 Muy alto"),
    ("pruebas_focales", "pruebas focales"),
    ("recursos_efimeros", "lasfocas.session=<agent-id>"),
    ("limpieza_worktree", "agent_worktree.py cleanup"),
)
# La lista de viñetas que sigue a "únicos triggers directos" debe ser exactamente ésta.
TRIGGERS_CIERRE = frozenset({"/cierre-sesion", "Cerrar sesión", "Cerremos sesión"})

TTL_AGENTE_SEGUNDOS = 120 * 60
ESTADOS_VIVOS = ("starting", "active", "blocked", "ready_to_merge", "integrating")


# ------------------------------------------------------------------ chequeos


def chequear_archivos(raiz: Path) -> list[str]:
    return [f"error:missing_file:{ruta}" for ruta in ARCHIVOS_OBLIGATORIOS if not (raiz / ruta).is_file()]


def chequear_ignores(raiz: Path) -> list[str]:
    hallazgos: list[str] = []
    for nombre in ARCHIVOS_IGNORE:
        ruta = raiz / nombre
        if not ruta.is_file():
            continue  # ya reportado por chequear_archivos
        lineas = {linea.strip() for linea in ruta.read_text(encoding="utf-8").splitlines()}
        for patron in PATRONES_IGNORE_OBLIGATORIOS:
            if patron not in lineas:
                hallazgos.append(f"error:ignore_pattern_missing:{nombre}:{patron}")
    return hallazgos


def chequear_mapa(raiz: Path) -> list[str]:
    try:
        return [f"error:repository_map:{h}" for h in generate_repository_map.verificar(raiz)]
    except generate_repository_map.ErrorMapa as exc:
        return [f"error:repository_map:{exc}"]


def chequear_frontmatter_skills(raiz: Path) -> list[str]:
    hallazgos: list[str] = []
    for ruta in sync_skill_mirrors.skills(raiz):
        nombre = ruta.parent.name
        _, frontmatter, _ = sync_skill_mirrors.partes_fuente(ruta)
        if not frontmatter:
            hallazgos.append(f"error:skill_frontmatter_missing:{nombre}")
            continue
        declarado = sync_skill_mirrors.valor_escalar(frontmatter, "name")
        if not declarado:
            hallazgos.append(f"error:skill_frontmatter_name:{nombre}:falta name")
        elif declarado != nombre:
            hallazgos.append(f"error:skill_frontmatter_name:{nombre}:name={declarado!r} no coincide con el directorio")
        if not sync_skill_mirrors.valor_escalar(frontmatter, "description"):
            hallazgos.append(f"error:skill_frontmatter_description:{nombre}")
    return hallazgos


def chequear_cierre_sesion(raiz: Path) -> list[str]:
    ruta = raiz / CIERRE_SESION
    if not ruta.is_file():
        return [f"error:cierre_sesion_missing:{CIERRE_SESION}"]
    texto = ruta.read_text(encoding="utf-8")
    hallazgos = [f"error:cierre_sesion_contract:{codigo}" for codigo, marcador in CONTRATO_CIERRE if marcador not in texto]
    declarados = triggers_cierre(texto)
    if declarados != TRIGGERS_CIERRE:
        sobrantes = sorted(declarados - TRIGGERS_CIERRE)
        faltantes = sorted(TRIGGERS_CIERRE - declarados)
        hallazgos.append(
            f"error:cierre_sesion_triggers:sobrantes={sobrantes} faltantes={faltantes}"
        )
    return hallazgos


def triggers_cierre(texto: str) -> set[str]:
    """Viñetas `` - `trigger` `` inmediatamente posteriores a "únicos triggers directos"."""
    indice = texto.find("triggers directos")
    if indice < 0:
        return set()
    triggers: set[str] = set()
    for linea in texto[indice:].splitlines()[1:]:
        vineta = re.match(r"^- `([^`]+)`$", linea.strip())
        if vineta:
            triggers.add(vineta.group(1))
        elif triggers:
            break  # terminó el bloque de viñetas
        elif linea.strip():
            break  # texto antes de cualquier viñeta: no hay lista
    return triggers


def chequear_mirrors(raiz: Path) -> list[str]:
    hallazgos = [f"error:mirror_drift:{ruta}" for ruta in sync_skill_mirrors.procesar(raiz, verificar=True)]
    # Claude Code, Codex y Agent Skills sólo leen name/description si el archivo empieza con `---`.
    for plataforma in sync_skill_mirrors.PLATAFORMAS:
        if not plataforma.frontmatter_primero:
            continue
        for fuente in sync_skill_mirrors.skills(raiz):
            mirror = raiz / plataforma.ruta(fuente.parent.name)
            if mirror.is_file() and not mirror.read_text(encoding="utf-8").startswith("---\n"):
                hallazgos.append(f"error:mirror_frontmatter_not_first:{plataforma.ruta(fuente.parent.name)}")
    for ruta in sorted((raiz / ".gemini/rules").glob("skill-*.md")):
        lineas = len(ruta.read_text(encoding="utf-8").splitlines())
        if lineas > sync_skill_mirrors.MAX_LINEAS_ADAPTADOR:
            hallazgos.append(
                f"error:gemini_adapter_too_long:{ruta.relative_to(raiz)}:{lineas} líneas "
                f"(tope {sync_skill_mirrors.MAX_LINEAS_ADAPTADOR})"
            )
    return hallazgos


def ruta_estado(raiz: Path) -> Path | None:
    """``<git-common-dir>/las-focas-agents/agent_state.sqlite3`` o ``None`` fuera de un repo."""
    try:
        comun = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=raiz,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return Path(comun) / "las-focas-agents" / "agent_state.sqlite3"


def chequear_estado(db: Path | None, *, momento: float | None = None) -> list[str]:
    """Avisos (no bloqueantes) de leases vencidos y agentes sin heartbeat. Sólo lectura."""
    if db is None or not db.is_file():
        return []
    instante = momento if momento is not None else time.time()
    hallazgos: list[str] = []
    try:
        conexion = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            for recurso, dueno in conexion.execute(
                "SELECT resource, owner_agent_id FROM leases WHERE lease_expires_at <= ? ORDER BY resource",
                (instante,),
            ):
                hallazgos.append(f"warning:stale_lease:{recurso}:{dueno}")
            marcadores = ",".join("?" for _ in ESTADOS_VIVOS)
            for agente, estado in conexion.execute(
                f"SELECT agent_id, status FROM agentes WHERE status = 'stale' "
                f"OR (status IN ({marcadores}) AND heartbeat_at < ?) ORDER BY agent_id",
                (*ESTADOS_VIVOS, instante - TTL_AGENTE_SEGUNDOS),
            ):
                hallazgos.append(f"warning:stale_agent:{agente}:{estado}")
        finally:
            conexion.close()
    except sqlite3.Error as exc:
        hallazgos.append(f"warning:agent_state_unreadable:{exc}")
    return hallazgos


def chequear_comandos_claude(raiz: Path) -> list[str]:
    """Los comandos slash necesitan frontmatter primero con `description` (si no, Claude Code
    muestra la primera línea, "# Nombre de archivo: ...", como descripción)."""
    hallazgos: list[str] = []
    for ruta in sorted((raiz / ".claude/commands").glob("*.md")):
        texto = ruta.read_text(encoding="utf-8")
        frontmatter = texto.split("\n---\n", 1)[0] if texto.startswith("---\n") else ""
        if not sync_skill_mirrors.valor_escalar(frontmatter.removeprefix("---\n"), "description"):
            hallazgos.append(f"error:command_description_missing:{ruta.relative_to(raiz)}")
    return hallazgos


CHEQUEOS = (
    chequear_archivos,
    chequear_comandos_claude,
    chequear_ignores,
    chequear_mapa,
    chequear_frontmatter_skills,
    chequear_cierre_sesion,
    chequear_mirrors,
)


def auditar(raiz: Path, *, db: Path | None = None) -> list[str]:
    hallazgos: list[str] = []
    for chequeo in CHEQUEOS:
        hallazgos.extend(chequeo(raiz))
    hallazgos.extend(chequear_estado(db if db is not None else ruta_estado(raiz)))
    return hallazgos


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audita los contratos del entorno agéntico de LAS-FOCAS")
    parser.add_argument("--json", action="store_true", help="Salida en JSON")
    parser.add_argument("--root", type=Path, default=RAIZ, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    hallazgos = auditar(args.root.resolve())
    errores = [h for h in hallazgos if h.startswith("error:")]
    if args.json:
        print(json.dumps({"ok": not errores, "hallazgos": hallazgos}, ensure_ascii=False, indent=2))
    else:
        for hallazgo in hallazgos:
            print(hallazgo, file=sys.stderr if hallazgo.startswith("error:") else sys.stdout)
        avisos = len(hallazgos) - len(errores)
        print(f"{'FALLA' if errores else 'OK'}: {len(errores)} error(es), {avisos} aviso(s)")
    return 1 if errores else 0


if __name__ == "__main__":  # pragma: no cover - punto de entrada
    raise SystemExit(main())
