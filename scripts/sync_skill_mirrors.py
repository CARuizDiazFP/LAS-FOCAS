#!/usr/bin/env python3
# Nombre de archivo: sync_skill_mirrors.py
# Ubicación de archivo: scripts/sync_skill_mirrors.py
# Descripción: Propaga el cuerpo de las skills desde .agentes-comunes hacia los mirrors de .github, .claude, .gemini y .codex-skills, y verifica drift

"""Propagación determinista de skills a los mirrors por plataforma.

`.agentes-comunes/skills/<nombre>/SKILL.md` es la única fuente de verdad. Los mirrors
son artefactos derivados, y cada plataforma tiene su propia estructura de directorios:

| Plataforma | Ruta del mirror | Estructura |
|---|---|---|
| GitHub Copilot | `.github/skills/<n>/SKILL.md`            | igual a la fuente |
| Claude Code    | `.claude/skills/<n>/SKILL.md`            | igual a la fuente |
| Gemini CLI     | `.gemini/rules/skill-<n>.md`             | plana, un archivo por skill |
| OpenAI Codex   | `.codex-skills/skills/las-focas-<n>/SKILL.md` | prefijo `las-focas-` |

Por eso el cuerpo no se copia crudo: se aplican dos transformaciones **declaradas y
deterministas** (todo lo demás es copia fiel):

1. `rstrip` por línea — quita espacios al final. Los mirrors ya venían así y el
   whitespace final no aporta nada.
2. Reescritura de los enlaces relativos entre skills (`[texto](../<n>/SKILL.md)`) a la
   ruta que resuelve en cada plataforma. Sin esto, un enlace copiado tal cual apunta a
   un archivo inexistente en `.gemini/rules/` o en `.codex-skills/`.

Las menciones en prosa a rutas de otro entorno (por ejemplo `` `.github/skills/x/SKILL.md` ``
dentro de un párrafo) se dejan literales: son informativas, no navegación. Si están mal,
se corrigen en la fuente.

El frontmatter de cada mirror se **preserva** (cada plataforma tiene el suyo: `triggers`,
`globs`, `commands`, `metadata`). Si el mirror no existe, se genera uno mínimo derivado
del `name` y la `description` de la fuente.

Uso:
    python scripts/sync_skill_mirrors.py            # propaga (escribe)
    python scripts/sync_skill_mirrors.py --check    # verifica drift, sale 1 si hay
    python scripts/sync_skill_mirrors.py --skill <nombre>   # acota a una skill
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent) not in sys.path:  # pragma: no cover - inicialización
    sys.path.insert(0, str(SCRIPT_DIR.parent))

from scripts.agentes.consola import configurar_logging, emitir  # noqa: E402

FUENTE = Path(".agentes-comunes/skills")

RE_FRONTMATTER = re.compile(r"\A\s*---\n.*?\n---\n", re.DOTALL)
# Enlace markdown a otra skill desde la estructura de la fuente: [texto](../<nombre>/SKILL.md)
RE_ENLACE_SKILL = re.compile(r"\]\(\.\./([a-z0-9][a-z0-9-]*)/SKILL\.md\)")

logger = configurar_logging("sync_skill_mirrors")


@dataclass(frozen=True)
class Plataforma:
    """Cómo se materializa una skill en un entorno agéntico concreto."""

    clave: str
    #: Ruta del mirror, en función del nombre de la skill.
    ruta: object
    #: Reemplazo para los enlaces relativos entre skills.
    enlace: object
    #: Encabezado de 3 líneas + bloque de referencia previo al cuerpo.
    cabecera: object
    #: Si el frontmatter va antes (Codex) o después (resto) del encabezado.
    frontmatter_primero: bool = False


def _cabecera_github(nombre: str) -> str:
    return ""  # .github lo genera sync_agentes_comunes.sh copiando la fuente entera.


def _cabecera_claude(nombre: str, descripcion_fuente: str) -> str:
    return (
        "# Nombre de archivo: SKILL.md\n"
        f"# Ubicación de archivo: .claude/skills/{nombre}/SKILL.md\n"
        f"# Descripción: {descripcion_fuente} (mirror de "
        f".agentes-comunes/skills/{nombre}/SKILL.md — fuente de verdad)\n"
    )


def _cabecera_gemini(nombre: str, _descripcion: str) -> str:
    return (
        f"# Nombre de archivo: skill-{nombre}.md\n"
        f"# Ubicación de archivo: .gemini/rules/skill-{nombre}.md\n"
        f"# Descripción: Regla Gemini portable migrada desde .github/skills/{nombre}/SKILL.md\n"
    )


def _cabecera_codex(nombre: str, _descripcion: str) -> str:
    return (
        "# Nombre de archivo: SKILL.md\n"
        f"# Ubicación de archivo: .codex-skills/skills/las-focas-{nombre}/SKILL.md\n"
        f"# Descripción: Skill portable Codex migrada desde .github/skills/{nombre}/SKILL.md\n"
    )


PLATAFORMAS = (
    Plataforma(
        clave="claude",
        ruta=lambda n: Path(f".claude/skills/{n}/SKILL.md"),
        enlace=lambda n: f"](../{n}/SKILL.md)",
        cabecera=_cabecera_claude,
    ),
    Plataforma(
        clave="gemini",
        ruta=lambda n: Path(f".gemini/rules/skill-{n}.md"),
        enlace=lambda n: f"](skill-{n}.md)",
        cabecera=_cabecera_gemini,
    ),
    Plataforma(
        clave="codex",
        ruta=lambda n: Path(f".codex-skills/skills/las-focas-{n}/SKILL.md"),
        enlace=lambda n: f"](../las-focas-{n}/SKILL.md)",
        cabecera=_cabecera_codex,
        frontmatter_primero=True,
    ),
)

REFERENCIA = {
    "claude": lambda n: "",
    "gemini": lambda n: (
        f"# Regla Skill: {n}\n\n"
        f"> Fuente original: `.agentes-comunes/skills/{n}/SKILL.md`. Usar esta regla cuando "
        "Gemini/Codex IDE detecte los triggers o globs declarados.\n\n"
    ),
    "codex": lambda n: (
        f"# Skill portable: {n}\n\n"
        f"> Fuente original: `.agentes-comunes/skills/{n}/SKILL.md`. Copia portable generada "
        "porque `.codex/` está montado como solo lectura en esta sesión.\n\n"
    ),
}


# --------------------------------------------------------------------- parsing


def partes_fuente(ruta: Path) -> tuple[str, str, str]:
    """Devuelve ``(descripcion, frontmatter, cuerpo)`` de una skill fuente."""
    lineas = ruta.read_text(encoding="utf-8").splitlines(keepends=True)
    encabezado = "".join(lineas[:3])
    descripcion = ""
    for linea in encabezado.splitlines():
        if linea.startswith("# Descripción:"):
            descripcion = linea.split(":", 1)[1].strip()
    resto = "".join(lineas[3:])
    coincidencia = RE_FRONTMATTER.match(resto)
    frontmatter = coincidencia.group(0).strip().strip("-").strip("\n") if coincidencia else ""
    cuerpo = RE_FRONTMATTER.sub("", resto, count=1).strip("\n")
    return descripcion, frontmatter, cuerpo


def frontmatter_de(ruta: Path) -> str | None:
    """Extrae el frontmatter YAML existente de un mirror, si lo tiene."""
    if not ruta.is_file():
        return None
    texto = ruta.read_text(encoding="utf-8")
    coincidencia = re.search(r"^---\n(.*?)\n---\n", texto, re.DOTALL | re.MULTILINE)
    return coincidencia.group(1) if coincidencia else None


def transformar(cuerpo: str, plataforma: Plataforma) -> str:
    """Aplica las transformaciones declaradas para una plataforma."""
    cuerpo = RE_ENLACE_SKILL.sub(lambda m: plataforma.enlace(m.group(1)), cuerpo)
    return "\n".join(linea.rstrip() for linea in cuerpo.splitlines()).strip("\n")


def frontmatter_por_defecto(
    plataforma: Plataforma, nombre: str, frontmatter_fuente: str
) -> str:
    """Frontmatter mínimo para un mirror que todavía no existe."""
    descripcion = ""
    for linea in frontmatter_fuente.splitlines():
        if linea.startswith("description:"):
            descripcion = linea.split(":", 1)[1].strip().strip('"')
    disparadores = [nombre, *[p for p in nombre.split("-") if len(p) > 2]]
    if plataforma.clave == "gemini":
        return (
            f'name: "skill-{nombre}"\n'
            f'description: "{descripcion}"\n'
            f'source: ".agentes-comunes/skills/{nombre}/SKILL.md"\n'
            "triggers:\n"
            + "".join(f'  - "{t}"\n' for t in disparadores)
            + 'globs:\n  - "**/*"\ncommands:\n  []'
        )
    corta = descripcion if len(descripcion) <= 120 else descripcion[:117] + "..."
    return (
        f'name: "las-focas-{nombre}"\n'
        f'description: "{descripcion}"\n'
        "metadata:\n"
        f'  short-description: "{corta}"\n'
        f'  source: ".agentes-comunes/skills/{nombre}/SKILL.md"\n'
        "  triggers:\n"
        + "".join(f'    - "{t}"\n' for t in disparadores)
        + '  globs:\n    - "**/*"\n  commands:\n    []'
    )


def render(plataforma: Plataforma, nombre: str, ruta_fuente: Path) -> str:
    """Contenido completo que debe tener el mirror de esta skill."""
    descripcion, frontmatter_fuente, cuerpo = partes_fuente(ruta_fuente)
    destino = plataforma.ruta(nombre)
    frontmatter = frontmatter_de(destino)
    if frontmatter is None:
        frontmatter = (
            frontmatter_fuente
            if plataforma.clave == "claude"
            else frontmatter_por_defecto(plataforma, nombre, frontmatter_fuente)
        )
    cabecera = plataforma.cabecera(nombre, descripcion)
    referencia = REFERENCIA[plataforma.clave](nombre)
    bloque = transformar(cuerpo, plataforma)

    if plataforma.frontmatter_primero:
        return f"---\n{frontmatter}\n---\n\n{cabecera}\n{referencia}{bloque}\n"
    return f"{cabecera}\n---\n{frontmatter}\n---\n\n{referencia}{bloque}\n"


# ------------------------------------------------------------------ ejecución


def skills(raiz: Path, filtro: str | None = None) -> list[Path]:
    rutas = sorted(p for p in (raiz / FUENTE).glob("*/SKILL.md"))
    if filtro:
        rutas = [p for p in rutas if p.parent.name == filtro]
    return rutas


def procesar(raiz: Path, *, verificar: bool, filtro: str | None = None) -> list[str]:
    """Propaga (o verifica) todas las skills. Devuelve las rutas con diferencia."""
    diferencias: list[str] = []
    for ruta_fuente in skills(raiz, filtro):
        nombre = ruta_fuente.parent.name
        for plataforma in PLATAFORMAS:
            destino = raiz / plataforma.ruta(nombre)
            esperado = render(plataforma, nombre, ruta_fuente)
            actual = destino.read_text(encoding="utf-8") if destino.is_file() else None
            if actual == esperado:
                continue
            diferencias.append(str(plataforma.ruta(nombre)))
            if not verificar:
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_text(esperado, encoding="utf-8")
    return diferencias


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Propaga las skills de .agentes-comunes a los mirrors por plataforma."
    )
    parser.add_argument("--check", action="store_true", help="Sólo verificar drift (no escribe)")
    parser.add_argument("--skill", default=None, help="Acotar a una skill")
    args = parser.parse_args(argv)

    raiz = SCRIPT_DIR.parent
    if not (raiz / FUENTE).is_dir():
        logger.error("no existe %s", FUENTE)
        return 2

    diferencias = procesar(raiz, verificar=args.check, filtro=args.skill)

    if args.check:
        if diferencias:
            logger.error("drift detectado en %d mirror(s)", len(diferencias))
            for ruta in diferencias:
                emitir(f"DRIFT {ruta}")
            emitir("")
            emitir("Corregir con: python scripts/sync_skill_mirrors.py")
            return 1
        emitir("OK: mirrors por plataforma sincronizados con .agentes-comunes/skills")
        return 0

    if diferencias:
        for ruta in diferencias:
            emitir(f"actualizado {ruta}")
    emitir(f"OK: {len(diferencias)} mirror(s) actualizado(s)")
    return 0


if __name__ == "__main__":  # pragma: no cover - punto de entrada
    raise SystemExit(main())
