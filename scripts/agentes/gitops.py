# Nombre de archivo: gitops.py
# Ubicación de archivo: scripts/agentes/gitops.py
# Descripción: Operaciones Git y de worktrees encapsuladas para el tooling multi-agente

"""Capa Git del tooling agéntico.

Encapsula ``subprocess`` para que la CLI y el estado no manipulen comandos a mano.
Ninguna función de este módulo ejecuta operaciones destructivas implícitas: no hay
``reset --hard``, ``clean -fd``, ``checkout -- .``, ``restore .``, ``push --force``
ni ``worktree remove --force``. El borrado de un worktree exige que
``git status --porcelain`` esté vacío y es responsabilidad del llamador verificarlo.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Tipos de rama efímera admitidos por la política vigente de LAS-FOCAS.
TIPOS_RAMA = ("feat", "fix", "docs", "chore", "refactor", "test")
PATRON_RAMA_EFIMERA = re.compile(r"^(feat|fix|docs|chore|refactor|test)/.+")
PATRON_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ErrorGit(RuntimeError):
    """Un comando Git terminó con error."""


@dataclass(frozen=True)
class Worktree:
    path: Path
    head: str
    branch: str
    bare: bool
    detached: bool
    locked: bool


def ejecutar(args: list[str], cwd: Path | str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Ejecuta ``git <args>`` en ``cwd``. Lanza :class:`ErrorGit` si ``check`` y falla."""
    proceso = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if check and proceso.returncode != 0:
        detalle = proceso.stderr.strip() or proceso.stdout.strip()
        raise ErrorGit(f"git {' '.join(args)} falló ({proceso.returncode}): {detalle}")
    return proceso


def salida(args: list[str], cwd: Path | str) -> str:
    return ejecutar(args, cwd).stdout.strip()


# --------------------------------------------------------------------- consultas


def rama_actual(cwd: Path | str) -> str:
    return salida(["branch", "--show-current"], cwd)


def sha(ref: str, cwd: Path | str) -> str:
    return salida(["rev-parse", ref], cwd)


def existe_ref(ref: str, cwd: Path | str) -> bool:
    return ejecutar(["rev-parse", "--verify", "--quiet", ref], cwd, check=False).returncode == 0


def existe_rama_local(nombre: str, cwd: Path | str) -> bool:
    return existe_ref(f"refs/heads/{nombre}", cwd)


def existe_remoto(nombre: str, cwd: Path | str) -> bool:
    return nombre in ejecutar(["remote"], cwd, check=False).stdout.split()


def estado_porcelain(cwd: Path | str) -> str:
    return ejecutar(["status", "--porcelain"], cwd).stdout.strip()


def esta_limpio(cwd: Path | str) -> bool:
    """``True`` si el working tree no tiene cambios ni archivos sin trackear."""
    return estado_porcelain(cwd) == ""


def archivos_modificados(cwd: Path | str) -> list[str]:
    return [linea[3:] for linea in ejecutar(["status", "--porcelain"], cwd).stdout.splitlines() if linea]


def ultimo_commit(cwd: Path | str) -> str:
    proceso = ejecutar(["log", "-1", "--pretty=%h %s"], cwd, check=False)
    return proceso.stdout.strip() if proceso.returncode == 0 else ""


def es_ancestro(posible_ancestro: str, descendiente: str, cwd: Path | str) -> bool:
    proceso = ejecutar(
        ["merge-base", "--is-ancestor", posible_ancestro, descendiente], cwd, check=False
    )
    return proceso.returncode == 0


def commits_propios(base: str, cabeza: str, cwd: Path | str) -> int:
    proceso = ejecutar(["rev-list", "--count", f"{base}..{cabeza}"], cwd, check=False)
    return int(proceso.stdout.strip() or 0) if proceso.returncode == 0 else 0


def listar_worktrees(cwd: Path | str) -> list[Worktree]:
    """Parsea ``git worktree list --porcelain``."""
    crudo = ejecutar(["worktree", "list", "--porcelain"], cwd).stdout
    worktrees: list[Worktree] = []
    actual: dict[str, object] = {}
    for linea in crudo.splitlines() + [""]:
        if not linea.strip():
            if actual:
                worktrees.append(
                    Worktree(
                        path=Path(str(actual.get("worktree", ""))).resolve(),
                        head=str(actual.get("HEAD", "")),
                        branch=str(actual.get("branch", "")).replace("refs/heads/", ""),
                        bare=bool(actual.get("bare", False)),
                        detached=bool(actual.get("detached", False)),
                        locked=bool(actual.get("locked", False)),
                    )
                )
                actual = {}
            continue
        if " " in linea:
            clave, _, valor = linea.partition(" ")
            actual[clave] = valor
        else:
            actual[linea] = True
    return worktrees


def worktree_de(ruta: Path | str, cwd: Path | str) -> Worktree | None:
    objetivo = Path(ruta).resolve()
    for worktree in listar_worktrees(cwd):
        if worktree.path == objetivo:
            return worktree
    return None


# ------------------------------------------------------------------- mutaciones


def fetch(cwd: Path | str, remoto: str = "origin") -> None:
    ejecutar(["fetch", remoto, "--prune"], cwd)


def crear_worktree(ruta: Path, rama: str, base: str, cwd: Path | str) -> None:
    """Crea el worktree y la rama en una sola operación atómica de Git.

    ``git worktree add -b`` falla si la rama ya existe o si la ruta está ocupada;
    ese fallo es deseable: evita que dos agentes compartan rama por accidente.
    """
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ejecutar(["worktree", "add", "-b", rama, str(ruta), base], cwd)


def adjuntar_worktree(ruta: Path, rama: str, cwd: Path | str) -> None:
    """Crea un worktree sobre una rama que ya existe (recuperación / handoff)."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ejecutar(["worktree", "add", str(ruta), rama], cwd)


def remover_worktree(ruta: Path, cwd: Path | str) -> None:
    """Elimina un worktree. Nunca usa ``--force``: un worktree sucio debe fallar."""
    ejecutar(["worktree", "remove", str(ruta)], cwd)


MARCA_EXCLUSIONES = "# LAS-FOCAS agentes: enlaces de entorno de los worktrees (generado por scripts/agent_worktree.py)"


def asegurar_exclusiones(git_common_dir: Path, patrones: tuple[str, ...]) -> list[str]:
    """Garantiza que los enlaces de entorno queden ignorados en TODOS los worktrees.

    Escribe en ``<git-common-dir>/info/exclude``, que es compartido por todos los
    linked worktrees, no se versiona y —a diferencia de ``.gitignore``— no depende de
    la rama que tenga cada worktree checkouteada. Sin esto, un worktree creado desde
    una rama anterior al ajuste de ``.gitignore`` vería los symlinks ``.venv`` y
    ``.secrets`` como archivos sin trackear y nunca estaría "limpio".

    Es idempotente: sólo agrega los patrones que falten.
    """
    destino = git_common_dir / "info" / "exclude"
    destino.parent.mkdir(parents=True, exist_ok=True)
    existente = destino.read_text(encoding="utf-8") if destino.is_file() else ""
    presentes = {linea.strip() for linea in existente.splitlines()}
    # Los patrones se anclan a la raíz del worktree ("/.venv"), así que la comparación
    # de idempotencia debe hacerse sobre la forma ya anclada.
    faltantes = [patron for patron in patrones if f"/{patron}" not in presentes]
    if not faltantes:
        return []
    bloque = "" if existente.endswith("\n") or not existente else "\n"
    if MARCA_EXCLUSIONES not in existente:
        bloque += f"{MARCA_EXCLUSIONES}\n"
    bloque += "".join(f"/{patron}\n" for patron in faltantes)
    with destino.open("a", encoding="utf-8") as archivo:
        archivo.write(bloque)
    return faltantes


def prune_worktrees(cwd: Path | str) -> str:
    return ejecutar(["worktree", "prune", "-v"], cwd).stdout.strip()


def borrar_rama(nombre: str, cwd: Path | str) -> None:
    """Borra una rama local con ``-d`` (rechaza ramas no integradas). Nunca ``-D``."""
    ejecutar(["branch", "-d", nombre], cwd)


def merge(ref: str, cwd: Path | str, *, mensaje: str | None = None) -> subprocess.CompletedProcess[str]:
    args = ["merge", "--no-edit", ref]
    if mensaje:
        args = ["merge", "--no-ff", "-m", mensaje, ref]
    return ejecutar(args, cwd, check=False)


def archivos_en_conflicto(cwd: Path | str) -> list[str]:
    proceso = ejecutar(["diff", "--name-only", "--diff-filter=U"], cwd, check=False)
    return [linea for linea in proceso.stdout.splitlines() if linea.strip()]


def push(refspec: str, cwd: Path | str, remoto: str = "origin") -> subprocess.CompletedProcess[str]:
    """Push explícito por refspec. Nunca ``--force`` ni ``--force-with-lease``."""
    return ejecutar(["push", remoto, refspec], cwd, check=False)


# ------------------------------------------------------------------ validaciones


def validar_slug(valor: str, *, campo: str) -> str:
    if not PATRON_SLUG.match(valor):
        raise ErrorGit(
            f"{campo} inválido: {valor!r}. Usar minúsculas, dígitos y guiones "
            "(ej. 'busqueda-camaras')"
        )
    return valor


def validar_tipo(tipo: str) -> str:
    if tipo not in TIPOS_RAMA:
        raise ErrorGit(f"tipo de rama inválido: {tipo!r}. Válidos: {', '.join(TIPOS_RAMA)}")
    return tipo


def es_rama_efimera(rama: str) -> bool:
    return bool(PATRON_RAMA_EFIMERA.match(rama))


def nombre_rama(tipo: str, agent_id: str, task: str) -> str:
    """Construye ``<tipo>/<agent-id>-<task-slug>`` respetando la convención vigente."""
    return f"{validar_tipo(tipo)}/{agent_id}-{task}"
