# Nombre de archivo: test_hook_pre_commit.py
# Ubicación de archivo: tests/test_hook_pre_commit.py
# Descripción: Pruebas del hook pre-commit que bloquea commits en dev/main y en ramas fuera de la convención

"""El hook se ejecuta de verdad contra repositorios Git temporales.

Verifica la política que hasta ahora sólo existía en la documentación: ningún commit
directo sobre `dev` o `main`, y ninguna rama fuera de `<tipo>/<slug>`.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
HOOK = RAIZ / "scripts" / "hooks" / "pre-commit"


def _git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=check
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Repositorio con el hook instalado tal como lo haría instalar_hooks.sh."""
    destino = tmp_path / "repo"
    destino.mkdir()
    _git(["init", "-b", "dev"], destino)
    _git(["config", "user.email", "agente@las-focas.test"], destino)
    _git(["config", "user.name", "Agente"], destino)
    _git(["config", "commit.gpgsign", "false"], destino)

    hooks = destino / "scripts" / "hooks"
    hooks.mkdir(parents=True)
    shutil.copy(HOOK, hooks / "pre-commit")
    (hooks / "pre-commit").chmod(0o755)
    _git(["config", "core.hooksPath", "scripts/hooks"], destino)

    (destino / "README.md").write_text("# repo\n", encoding="utf-8")
    _git(["add", "."], destino)
    # El commit inicial va con --no-verify: en dev el hook (correctamente) lo bloquearía.
    _git(["commit", "--no-verify", "-m", "chore: inicial"], destino)
    return destino


def _intentar_commit(repo: Path, archivo: str, mensaje: str) -> subprocess.CompletedProcess[str]:
    (repo / archivo).write_text("contenido\n", encoding="utf-8")
    _git(["add", archivo], repo)
    return _git(["commit", "-m", mensaje], repo, check=False)


def test_bloquea_commit_directo_en_dev(repo: Path) -> None:
    resultado = _intentar_commit(repo, "a.txt", "feat: algo")

    assert resultado.returncode != 0
    assert "BLOQUEADO: commit directo sobre 'dev'" in resultado.stderr
    assert "agent_worktree.py start" in resultado.stderr


def test_bloquea_commit_directo_en_main(repo: Path) -> None:
    _git(["switch", "-c", "main"], repo)

    resultado = _intentar_commit(repo, "a.txt", "feat: algo")

    assert resultado.returncode != 0
    assert "BLOQUEADO: commit directo sobre 'main'" in resultado.stderr


def test_permite_commit_en_rama_efimera(repo: Path) -> None:
    _git(["switch", "-c", "feat/claude-api-busqueda"], repo)

    resultado = _intentar_commit(repo, "a.txt", "feat(api): algo")

    assert resultado.returncode == 0, resultado.stderr
    assert _git(["log", "-1", "--pretty=%s"], repo).stdout.strip() == "feat(api): algo"


@pytest.mark.parametrize("tipo", ["feat", "fix", "docs", "chore", "refactor", "test"])
def test_acepta_todos_los_tipos_de_rama_validos(repo: Path, tipo: str) -> None:
    _git(["switch", "-c", f"{tipo}/agente-tarea"], repo)

    resultado = _intentar_commit(repo, f"{tipo}.txt", f"{tipo}: algo")

    assert resultado.returncode == 0, resultado.stderr


def test_bloquea_una_rama_fuera_de_la_convencion(repo: Path) -> None:
    _git(["switch", "-c", "mi-rama-suelta"], repo)

    resultado = _intentar_commit(repo, "a.txt", "feat: algo")

    assert resultado.returncode != 0
    assert "no sigue la convención" in resultado.stderr


def test_no_verify_es_la_salida_de_emergencia(repo: Path) -> None:
    (repo / "a.txt").write_text("contenido\n", encoding="utf-8")
    _git(["add", "a.txt"], repo)

    resultado = _git(["commit", "--no-verify", "-m", "chore: excepción"], repo, check=False)

    assert resultado.returncode == 0


def test_avisa_pero_no_bloquea_en_el_checkout_de_control(repo: Path, tmp_path: Path) -> None:
    """En el control el commit sigue: el bootstrap del tooling ocurre legítimamente ahí."""
    _git(["switch", "-c", "feat/claude-bootstrap"], repo)

    resultado = _intentar_commit(repo, "a.txt", "feat: bootstrap")

    assert resultado.returncode == 0, resultado.stderr
    assert "AVISO: estás commiteando en el checkout de control" in resultado.stderr


def test_no_avisa_dentro_del_worktree_de_un_agente(repo: Path, tmp_path: Path) -> None:
    worktree = tmp_path / "wt-agente"
    _git(["worktree", "add", "-b", "feat/claude-api-tarea", str(worktree)], repo)

    (worktree / "a.txt").write_text("contenido\n", encoding="utf-8")
    _git(["add", "a.txt"], worktree)
    resultado = _git(["commit", "-m", "feat(api): trabajo aislado"], worktree, check=False)

    assert resultado.returncode == 0, resultado.stderr
    assert "checkout de control" not in resultado.stderr
