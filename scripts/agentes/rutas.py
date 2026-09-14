# Nombre de archivo: rutas.py
# Ubicación de archivo: scripts/agentes/rutas.py
# Descripción: Descubrimiento de repositorio, git-common-dir compartido y rutas de runtime agéntico

"""Resolución de rutas para la coordinación multi-agente.

El estado de coordinación **no** vive en el working tree ni en el historial de Git:
vive bajo el ``git-common-dir``, que todos los linked worktrees de un mismo
repositorio comparten. Eso garantiza que un agente parado en su propio worktree vea
exactamente el mismo registro que el checkout de control.

Todas las rutas devueltas son absolutas y resueltas: ``git rev-parse --git-common-dir``
puede devolver una ruta relativa al directorio actual (``.git`` en el checkout
principal), por lo que nunca se usa su salida cruda.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Subdirectorio de runtime dentro del git-common-dir. No pertenece al historial Git.
RUNTIME_DIRNAME = "las-focas-agents"
NOMBRE_BASE_ESTADO = "agent_state.sqlite3"

# Variables de entorno de override (documentadas en docs/arquitectura_agentes_worktrees.md).
ENV_DIR_WORKTREES = "LAS_FOCAS_WORKTREES_DIR"
ENV_DIR_RUNTIME = "LAS_FOCAS_AGENT_RUNTIME_DIR"

# Sufijo del directorio hermano que aloja los worktrees de agentes.
# Se evita el sufijo genérico "-worktrees" porque puede colisionar con directorios de
# worktrees creados a mano (o por otro usuario) fuera de este tooling.
SUFIJO_DIR_WORKTREES = "-agentes"


class ErrorRepositorio(RuntimeError):
    """No se pudo resolver un repositorio Git válido desde el directorio indicado."""


@dataclass(frozen=True)
class Contexto:
    """Rutas resueltas del entorno agéntico.

    Attributes:
        toplevel: raíz del working tree actual (el del agente, o el de control).
        git_common_dir: directorio Git compartido por todos los linked worktrees.
        control_toplevel: working tree del checkout principal (el no-linked).
        runtime_dir: directorio de estado runtime (fuera del historial Git).
        db_path: ruta de la base SQLite de coordinación.
        worktrees_dir: directorio donde se crean los worktrees de agentes.
    """

    toplevel: Path
    git_common_dir: Path
    control_toplevel: Path
    runtime_dir: Path
    db_path: Path
    worktrees_dir: Path


def _git(args: list[str], cwd: Path) -> str:
    """Ejecuta un comando Git de sólo lectura y devuelve su salida limpia."""
    proceso = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if proceso.returncode != 0:
        raise ErrorRepositorio(
            f"git {' '.join(args)} falló en {cwd}: {proceso.stderr.strip() or proceso.stdout.strip()}"
        )
    return proceso.stdout.strip()


def resolver_git_common_dir(cwd: Path) -> Path:
    """Devuelve el git-common-dir absoluto del repositorio que contiene ``cwd``."""
    try:
        salida = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd)
    except ErrorRepositorio:
        # Git < 2.31 no soporta --path-format; se resuelve la ruta relativa a mano.
        salida = _git(["rev-parse", "--git-common-dir"], cwd)
    ruta = Path(salida)
    if not ruta.is_absolute():
        ruta = (cwd / ruta).resolve()
    return ruta.resolve()


def resolver_control_toplevel(git_common_dir: Path) -> Path:
    """Devuelve el working tree del checkout principal (dueño del git-common-dir).

    En un repositorio no-bare el git-common-dir es ``<control>/.git``. Si el
    repositorio es bare (sin checkout principal), se devuelve el propio
    git-common-dir para que el llamador decida.
    """
    padre = git_common_dir.parent
    if git_common_dir.name == ".git" and padre.is_dir():
        return padre.resolve()
    return git_common_dir.resolve()


def directorio_runtime(git_common_dir: Path) -> Path:
    """Directorio de estado runtime compartido por todos los linked worktrees."""
    override = os.environ.get(ENV_DIR_RUNTIME)
    if override:
        return Path(override).expanduser().resolve()
    return (git_common_dir / RUNTIME_DIRNAME).resolve()


def directorio_worktrees(control_toplevel: Path) -> Path:
    """Directorio donde se materializan los worktrees de agentes.

    Por defecto es un directorio hermano del checkout de control
    (``<padre>/LAS-FOCAS-agentes``): queda fuera del árbol versionado, por lo que no
    ensucia ``git status`` ni obliga a mantener entradas de ``.gitignore``. Se puede
    reubicar con la variable ``LAS_FOCAS_WORKTREES_DIR``.
    """
    override = os.environ.get(ENV_DIR_WORKTREES)
    if override:
        return Path(override).expanduser().resolve()
    return (control_toplevel.parent / f"{control_toplevel.name}{SUFIJO_DIR_WORKTREES}").resolve()


def verificar_escritura(directorio: Path) -> None:
    """Valida que el directorio de worktrees sea utilizable antes de invocar a Git.

    Detecta el caso real de un directorio preexistente creado por otro usuario (por
    ejemplo con ``sudo``), donde ``git worktree add`` falla con un
    "Permission denied" difícil de interpretar.
    """
    objetivo = directorio if directorio.exists() else directorio.parent
    if objetivo.exists() and not os.access(objetivo, os.W_OK | os.X_OK):
        raise ErrorRepositorio(
            f"el directorio de worktrees {directorio} no es escribible "
            f"(bloquea {objetivo}). Corregir los permisos o elegir otra ubicación con "
            f"la variable {ENV_DIR_WORKTREES}=<ruta>."
        )


def contexto(cwd: Path | str | None = None) -> Contexto:
    """Resuelve el contexto completo de rutas desde ``cwd`` (por defecto, el actual)."""
    base = Path(cwd).resolve() if cwd is not None else Path.cwd().resolve()
    if not base.exists():
        raise ErrorRepositorio(f"el directorio {base} no existe")

    git_common_dir = resolver_git_common_dir(base)
    toplevel = Path(_git(["rev-parse", "--show-toplevel"], base)).resolve()
    control_toplevel = resolver_control_toplevel(git_common_dir)
    runtime_dir = directorio_runtime(git_common_dir)

    return Contexto(
        toplevel=toplevel,
        git_common_dir=git_common_dir,
        control_toplevel=control_toplevel,
        runtime_dir=runtime_dir,
        db_path=runtime_dir / NOMBRE_BASE_ESTADO,
        worktrees_dir=directorio_worktrees(control_toplevel),
    )
