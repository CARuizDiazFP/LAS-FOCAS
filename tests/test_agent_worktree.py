# Nombre de archivo: test_agent_worktree.py
# Ubicación de archivo: tests/test_agent_worktree.py
# Descripción: Pruebas de aislamiento físico multi-agente por Git worktree (rama, puertos y .env.dev privados), limpieza segura, integración serializada a dev y diagnóstico

"""Pruebas del tooling de worktrees por agente.

Todas se ejecutan contra repositorios Git temporales creados en ``tmp_path`` con un
remoto *bare* local: no dependen de GitHub, de la red ni del repositorio real.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import stat
import subprocess
from pathlib import Path

import pytest

from scripts import agent_lock, agent_worktree
from scripts.agentes import gitops, rutas
from scripts.agentes.estado import Registro

# --------------------------------------------------------------------- helpers


def _git(args: list[str], cwd: Path) -> str:
    proceso = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True
    )
    return proceso.stdout.strip()


def _configurar_identidad(repo: Path) -> None:
    _git(["config", "user.email", "agente@las-focas.test"], repo)
    _git(["config", "user.name", "Agente de prueba"], repo)
    _git(["config", "commit.gpgsign", "false"], repo)


def _commit(repo: Path, archivo: str, contenido: str, mensaje: str) -> None:
    ruta = repo / archivo
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(contenido, encoding="utf-8")
    _git(["add", archivo], repo)
    _git(["commit", "-m", mensaje], repo)


@pytest.fixture(autouse=True)
def _puertos_siempre_libres(monkeypatch: pytest.MonkeyPatch) -> None:
    """La asignación de offsets no depende de qué escuche el host donde corren los tests."""
    monkeypatch.setattr(agent_worktree, "puerto_libre", lambda puerto: True)


@pytest.fixture()
def control(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Checkout de control con remoto local y rama ``dev`` publicada."""
    remoto = tmp_path / "remoto.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "dev", str(remoto)], check=True, capture_output=True
    )
    control_dir = tmp_path / "LAS-FOCAS"
    subprocess.run(
        ["git", "clone", str(remoto), str(control_dir)], check=True, capture_output=True
    )
    _configurar_identidad(control_dir)
    _commit(control_dir, "README.md", "# repo de prueba\n", "chore: commit inicial")
    _git(["push", "-u", "origin", "dev"], control_dir)
    monkeypatch.chdir(control_dir)
    return control_dir


def _correr(argv: list[str]) -> int:
    return agent_worktree.main(argv)


def _correr_json(argv: list[str], capsys: pytest.CaptureFixture[str]) -> dict:
    codigo = agent_worktree.main([*argv, "--json"])
    assert codigo == 0, capsys.readouterr().err
    salida = capsys.readouterr().out
    return json.loads(salida)


def _iniciar(agente: str, tarea: str, capsys: pytest.CaptureFixture[str], tipo: str = "feat") -> dict:
    return _correr_json(["start", "--agent", agente, "--type", tipo, "--task", tarea], capsys)


# --------------------------------------------------------------------- start


def test_start_crea_rama_worktree_y_registro(control: Path, capsys: pytest.CaptureFixture[str]) -> None:
    resultado = _iniciar("claude-api", "busqueda-camaras", capsys)

    assert resultado["rama"] == "feat/claude-api-busqueda-camaras"
    worktree = Path(resultado["worktree"])
    assert worktree.is_dir()
    assert worktree.name == "claude-api-busqueda-camaras"
    assert worktree.parent.name == "LAS-FOCAS-agentes"
    assert gitops.rama_actual(worktree) == "feat/claude-api-busqueda-camaras"
    assert resultado["base"].startswith("origin/dev@")
    assert resultado["estado"] == "active"

    registro = Registro(rutas.contexto(control).db_path)
    agente = registro.agente("claude-api")
    assert agente is not None and agente.status == "active"


def test_start_es_idempotente_para_la_misma_tarea(control: Path, capsys: pytest.CaptureFixture[str]) -> None:
    primero = _iniciar("claude-api", "busqueda-camaras", capsys)
    segundo = _iniciar("claude-api", "busqueda-camaras", capsys)

    assert segundo["idempotente"] is True
    assert segundo["worktree"] == primero["worktree"]
    assert len(gitops.listar_worktrees(control)) == 2  # control + un único worktree


def test_start_rechaza_una_segunda_tarea_para_el_mismo_agente(
    control: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _iniciar("claude-api", "busqueda-camaras", capsys)

    codigo = _correr(["start", "--agent", "claude-api", "--type", "feat", "--task", "otra-cosa"])

    assert codigo == 1
    assert "una sola tarea activa" in capsys.readouterr().err


def test_start_rechaza_una_rama_ya_checkouteada(control: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _iniciar("claude-api", "busqueda-camaras", capsys)

    # Otro agente pidiendo exactamente la misma rama: git no admite la misma rama en dos worktrees.
    codigo = _correr(
        ["start", "--agent", "claude-api", "--type", "feat", "--task", "busqueda-camaras", "--notas", "x"]
    )
    assert codigo == 0  # el mismo agente reingresa a su worktree (idempotente)

    registro = Registro(rutas.contexto(control).db_path)
    registro.olvidar_agente("claude-api")
    codigo = _correr(["start", "--agent", "codex-api", "--type", "feat", "--task", "busqueda-camaras"])
    assert codigo == 0  # rama distinta: feat/codex-api-busqueda-camaras
    assert gitops.existe_rama_local("feat/codex-api-busqueda-camaras", control)


def test_slug_invalido_es_rechazado_con_mensaje_accionable(
    control: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    codigo = _correr(["start", "--agent", "Claude API", "--type", "feat", "--task", "x"])

    assert codigo == 2
    assert "agent_id inválido" in capsys.readouterr().err


# ------------------------------------------------------- aislamiento real


@pytest.fixture()
def dos_agentes(control: Path, capsys: pytest.CaptureFixture[str]) -> tuple[Path, Path]:
    a = Path(_iniciar("claude-api", "tarea-a", capsys)["worktree"])
    b = Path(_iniciar("codex-web", "tarea-b", capsys)["worktree"])
    return a, b


def test_dos_agentes_activos_en_simultaneo(
    control: Path, dos_agentes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    worktree_a, worktree_b = dos_agentes

    agentes = _correr_json(["list"], capsys)
    estados = {fila["agent_id"]: fila["status"] for fila in agentes}
    assert estados == {"claude-api": "active", "codex-web": "active"}

    # Cada agente tiene su propia rama y su propio directorio.
    assert gitops.rama_actual(worktree_a) == "feat/claude-api-tarea-a"
    assert gitops.rama_actual(worktree_b) == "feat/codex-web-tarea-b"
    assert worktree_a != worktree_b
    rutas_worktrees = {wt.path for wt in gitops.listar_worktrees(control)}
    assert {control, worktree_a, worktree_b} <= rutas_worktrees


def test_edicion_y_staging_estan_aislados(control: Path, dos_agentes: tuple[Path, Path]) -> None:
    worktree_a, worktree_b = dos_agentes

    (worktree_a / "solo_de_a.txt").write_text("trabajo de A\n", encoding="utf-8")
    (worktree_b / "solo_de_b.txt").write_text("trabajo de B\n", encoding="utf-8")

    # git status aislado: cada uno ve únicamente lo suyo.
    assert gitops.archivos_modificados(worktree_a) == ["solo_de_a.txt"]
    assert gitops.archivos_modificados(worktree_b) == ["solo_de_b.txt"]
    # El checkout de control no ve ninguno de los dos.
    assert gitops.esta_limpio(control)

    # staging aislado: agregar en A no aparece en el index de B.
    _git(["add", "solo_de_a.txt"], worktree_a)
    assert _git(["diff", "--cached", "--name-only"], worktree_a) == "solo_de_a.txt"
    assert _git(["diff", "--cached", "--name-only"], worktree_b) == ""


def test_los_commits_estan_aislados(control: Path, dos_agentes: tuple[Path, Path]) -> None:
    worktree_a, worktree_b = dos_agentes
    _configurar_identidad(worktree_a)
    _configurar_identidad(worktree_b)

    _commit(worktree_a, "api/a.py", "# A\n", "feat(api): trabajo de A")
    _commit(worktree_b, "web/b.ts", "// B\n", "feat(web): trabajo de B")

    archivos_a = _git(["show", "--name-only", "--pretty=format:", "HEAD"], worktree_a).split()
    archivos_b = _git(["show", "--name-only", "--pretty=format:", "HEAD"], worktree_b).split()
    assert archivos_a == ["api/a.py"]
    assert archivos_b == ["web/b.ts"]

    # Ninguna rama contiene el commit de la otra.
    assert not gitops.es_ancestro(
        gitops.sha("HEAD", worktree_a), gitops.sha("HEAD", worktree_b), control
    )
    assert not (worktree_a / "web/b.ts").exists()
    assert not (worktree_b / "api/a.py").exists()
    # Y el control sigue limpio y en dev.
    assert gitops.esta_limpio(control)
    assert gitops.rama_actual(control) == "dev"


def test_cambiar_de_rama_en_un_worktree_no_afecta_al_otro(
    control: Path, dos_agentes: tuple[Path, Path]
) -> None:
    worktree_a, worktree_b = dos_agentes
    _configurar_identidad(worktree_a)
    _commit(worktree_a, "api/a.py", "# A\n", "feat(api): trabajo de A")

    _git(["switch", "-c", "feat/claude-api-rama-extra"], worktree_a)

    assert gitops.rama_actual(worktree_a) == "feat/claude-api-rama-extra"
    assert gitops.rama_actual(worktree_b) == "feat/codex-web-tarea-b"
    assert gitops.rama_actual(control) == "dev"


def test_el_estado_es_visible_desde_cualquier_worktree(
    control: Path, dos_agentes: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    worktree_a, worktree_b = dos_agentes

    # Un lease tomado desde el worktree de A se ve desde el de B y desde el control.
    monkeypatch.chdir(worktree_a)
    assert agent_lock.main(["acquire", "db:migrations", "--agent", "claude-api"]) == 0

    for lugar in (worktree_b, control):
        contexto = rutas.contexto(lugar)
        lease = Registro(contexto.db_path).lease("db:migrations")
        assert lease is not None and lease.owner_agent_id == "claude-api"
        # Todos resuelven el mismo git-common-dir y la misma base.
        assert contexto.git_common_dir == rutas.contexto(control).git_common_dir


def test_el_estado_runtime_no_se_versiona(control: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _iniciar("claude-api", "tarea-a", capsys)

    contexto = rutas.contexto(control)
    assert contexto.db_path.is_file()
    # Vive dentro del git-common-dir, no del working tree: git no lo ve.
    assert contexto.git_common_dir in contexto.db_path.parents
    assert gitops.esta_limpio(control)


# ------------------------------------------------------------------- leases


def test_recursos_distintos_no_bloquean_a_dos_agentes(
    control: Path, dos_agentes: tuple[Path, Path]
) -> None:
    assert agent_lock.main(["acquire", "db:migrations", "--agent", "claude-api"]) == 0
    assert agent_lock.main(["acquire", "env:docker-compose", "--agent", "codex-web"]) == 0


def test_el_mismo_recurso_se_rechaza_al_segundo_agente(
    control: Path, dos_agentes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    assert agent_lock.main(["acquire", "db:migrations", "--agent", "claude-api"]) == 0
    capsys.readouterr()

    assert agent_lock.main(["acquire", "db:migrations", "--agent", "codex-web"]) == 1
    assert "pertenece al agente 'claude-api'" in capsys.readouterr().err


def test_el_desarrollo_normal_no_toma_ningun_lease(
    control: Path, dos_agentes: tuple[Path, Path]
) -> None:
    """No hay lock global: crear worktrees y editar no deja leases retenidos."""
    worktree_a, worktree_b = dos_agentes
    (worktree_a / "a.txt").write_text("a\n", encoding="utf-8")
    (worktree_b / "b.txt").write_text("b\n", encoding="utf-8")

    assert Registro(rutas.contexto(control).db_path).leases() == []


# ------------------------------------------------------- integración serializada


def test_integracion_serializada_mientras_el_otro_agente_sigue_trabajando(
    control: Path, dos_agentes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    worktree_a, worktree_b = dos_agentes
    _configurar_identidad(worktree_a)
    _configurar_identidad(worktree_b)
    _commit(worktree_a, "api/a.py", "# A\n", "feat(api): trabajo de A")
    _commit(worktree_b, "web/b.ts", "// B\n", "feat(web): trabajo de B")

    # B deja además trabajo sin confirmar: no debe verse afectado por la integración de A.
    (worktree_b / "borrador.txt").write_text("en progreso\n", encoding="utf-8")

    listo = _correr_json(["ready", "--agent", "claude-api"], capsys)
    assert listo["status"] == "ready_to_merge"

    integrado = _correr_json(["integrate", "--agent", "claude-api"], capsys)
    assert integrado["integrado_en"] == "dev"
    assert integrado["status"] == "finished"

    # dev remoto avanzó con el trabajo de A y el control quedó al día.
    assert gitops.existe_ref("origin/dev", control)
    assert gitops.es_ancestro(gitops.sha("HEAD", worktree_a), "origin/dev", control)
    assert gitops.rama_actual(control) == "dev"

    # B siguió intacto durante toda la integración de A.
    assert gitops.rama_actual(worktree_b) == "feat/codex-web-tarea-b"
    assert (worktree_b / "borrador.txt").read_text(encoding="utf-8") == "en progreso\n"
    assert gitops.archivos_modificados(worktree_b) == ["borrador.txt"]
    assert not (worktree_b / "api/a.py").exists()

    # El lease de integración quedó liberado tras la ventana serializada.
    assert Registro(rutas.contexto(control).db_path).lease("git:integrate-dev") is None

    # B integra después: primero sincroniza dev en SU worktree y resuelve ahí.
    _git(["add", "borrador.txt"], worktree_b)
    _git(["commit", "-m", "chore(web): borrador"], worktree_b)
    sincronizado = _correr_json(["sync", "--agent", "codex-web"], capsys)
    assert sincronizado["resultado"] == "ok"
    assert (worktree_b / "api/a.py").exists()  # ya incorporó el trabajo de A

    # El sync movió el HEAD de B: el gate se corre sobre lo que realmente se integra.
    _correr_json(["ready", "--agent", "codex-web"], capsys)
    integrado_b = _correr_json(["integrate", "--agent", "codex-web"], capsys)
    assert integrado_b["status"] == "finished"
    assert gitops.es_ancestro(gitops.sha("HEAD", worktree_b), "origin/dev", control)


def test_integrate_actualiza_el_control_aunque_tenga_archivos_sin_trackear(
    control: Path, dos_agentes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Un archivo sin trackear en el control (p. ej. ``.claude/settings.json`` de la herramienta) no
    bloquea el ``merge --ff-only``: Git ya aborta solo si el merge fuera a pisarlo (real 2026-10-20,
    dos integraciones dejaron el control atrás de ``origin/dev``)."""
    worktree_a, _ = dos_agentes
    _configurar_identidad(worktree_a)
    _commit(worktree_a, "api/a.py", "# A\n", "feat(api): trabajo de A")
    (control / "local.json").write_text("{}\n", encoding="utf-8")

    _correr_json(["ready", "--agent", "claude-api"], capsys)
    integrado = _correr_json(["integrate", "--agent", "claude-api"], capsys)

    assert integrado["control_actualizado"].startswith("actualizado a ")
    assert gitops.sha("HEAD", control) == gitops.sha("HEAD", worktree_a)
    assert (control / "local.json").read_text(encoding="utf-8") == "{}\n"


def test_integrate_no_toca_el_control_con_cambios_trackeados(
    control: Path, dos_agentes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    worktree_a, _ = dos_agentes
    _configurar_identidad(worktree_a)
    _commit(worktree_a, "api/a.py", "# A\n", "feat(api): trabajo de A")
    previo = gitops.sha("HEAD", control)
    (control / "README.md").write_text("# editado en el control\n", encoding="utf-8")

    _correr_json(["ready", "--agent", "claude-api"], capsys)
    integrado = _correr_json(["integrate", "--agent", "claude-api"], capsys)

    assert integrado["control_actualizado"].startswith("omitido:")
    assert gitops.sha("HEAD", control) == previo


def test_integrate_se_bloquea_si_otro_agente_sostiene_la_ventana(
    control: Path, dos_agentes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    worktree_a, worktree_b = dos_agentes
    _configurar_identidad(worktree_b)
    _commit(worktree_b, "web/b.ts", "// B\n", "feat(web): trabajo de B")
    _correr_json(["ready", "--agent", "codex-web"], capsys)

    # A está integrando (sostiene el recurso serializado).
    Registro(rutas.contexto(control).db_path).adquirir(
        "git:integrate-dev", "claude-api", reason="integrando", ttl_minutos=20
    )
    capsys.readouterr()

    assert _correr(["integrate", "--agent", "codex-web"]) == 1
    assert "pertenece al agente 'claude-api'" in capsys.readouterr().err
    # B conserva su trabajo íntegro pese al rechazo.
    assert gitops.rama_actual(worktree_b) == "feat/codex-web-tarea-b"


def test_integrate_exige_sincronizar_si_dev_avanzo(
    control: Path, dos_agentes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    worktree_a, worktree_b = dos_agentes
    _configurar_identidad(worktree_a)
    _configurar_identidad(worktree_b)
    _commit(worktree_a, "api/a.py", "# A\n", "feat(api): trabajo de A")
    _commit(worktree_b, "web/b.ts", "// B\n", "feat(web): trabajo de B")
    _correr_json(["ready", "--agent", "claude-api"], capsys)
    _correr_json(["ready", "--agent", "codex-web"], capsys)

    _correr_json(["integrate", "--agent", "claude-api"], capsys)
    capsys.readouterr()

    assert _correr(["integrate", "--agent", "codex-web"]) == 1
    assert "sync --agent codex-web" in capsys.readouterr().err


# ------------------------------------------------------------ gate de calidad


def test_ready_con_gate_fallido_no_cambia_el_estado(
    control: Path, dos_agentes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    worktree_a, _ = dos_agentes
    _configurar_identidad(worktree_a)
    _commit(worktree_a, "api/a.py", "import os\n", "feat(api): import sin uso")
    capsys.readouterr()

    assert _correr(["ready", "--agent", "claude-api"]) == 1
    error = capsys.readouterr().err
    assert "el gate de calidad falló en 'lint'" in error
    assert "F401" in error

    agente = Registro(rutas.contexto(control).db_path).agente("claude-api")
    assert agente is not None and agente.status == "active"
    assert _correr(["integrate", "--agent", "claude-api"]) == 1


def test_ready_con_gate_ok_informa_el_resumen(
    control: Path, dos_agentes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    worktree_a, _ = dos_agentes
    _configurar_identidad(worktree_a)
    _commit(worktree_a, "api/a.py", "VALOR = 1\n", "feat(api): trabajo de A")

    listo = _correr_json(["ready", "--agent", "claude-api"], capsys)

    assert listo["gate"]["ok"] is True
    assert listo["gate"]["archivos"] == ["api/a.py"]
    assert listo["gate"]["sha"] == gitops.sha("HEAD", worktree_a)


def test_integrate_sin_ready_es_rechazado(
    control: Path, dos_agentes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    worktree_a, _ = dos_agentes
    _configurar_identidad(worktree_a)
    _commit(worktree_a, "api/a.py", "# A\n", "feat(api): trabajo de A")
    capsys.readouterr()

    assert _correr(["integrate", "--agent", "claude-api"]) == 1
    assert "ready --agent claude-api" in capsys.readouterr().err
    assert not gitops.es_ancestro(gitops.sha("HEAD", worktree_a), "origin/dev", control)


def test_integrate_rechaza_un_head_posterior_al_ready(
    control: Path, dos_agentes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    worktree_a, _ = dos_agentes
    _configurar_identidad(worktree_a)
    _commit(worktree_a, "api/a.py", "# A\n", "feat(api): trabajo de A")
    _correr_json(["ready", "--agent", "claude-api"], capsys)
    _commit(worktree_a, "api/a2.py", "# A2\n", "feat(api): commit después del ready")
    capsys.readouterr()

    assert _correr(["integrate", "--agent", "claude-api"]) == 1
    assert "cambió después de 'ready'" in capsys.readouterr().err


def test_sin_gate_exige_motivo_y_queda_auditado(
    control: Path, dos_agentes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    worktree_a, _ = dos_agentes
    _configurar_identidad(worktree_a)
    _commit(worktree_a, "api/a.py", "import os\n", "feat(api): import sin uso")
    capsys.readouterr()

    assert _correr(["ready", "--agent", "claude-api", "--sin-gate"]) == 1
    assert "--sin-gate exige --motivo" in capsys.readouterr().err

    listo = _correr_json(
        ["ready", "--agent", "claude-api", "--sin-gate", "--motivo", "hotfix de prod caído"], capsys
    )
    assert listo["gate"] == "salteado"

    registro = Registro(rutas.contexto(control).db_path)
    salteado = next(e for e in registro.eventos(agent_id="claude-api") if e["evento"] == "quality_gate_bypassed")
    assert salteado["detalle"] == f"{gitops.sha('HEAD', worktree_a)} | hotfix de prod caído"

    integrado = _correr_json(["integrate", "--agent", "claude-api"], capsys)
    assert integrado["status"] == "finished"


def test_integrate_rechaza_un_worktree_sucio(
    control: Path, dos_agentes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    worktree_a, _ = dos_agentes
    (worktree_a / "pendiente.txt").write_text("sin commitear\n", encoding="utf-8")

    assert _correr(["integrate", "--agent", "claude-api"]) == 1
    assert "no está limpio" in capsys.readouterr().err


# -------------------------------------------------------------- limpieza segura


def test_un_worktree_sucio_nunca_se_elimina(
    control: Path, dos_agentes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    worktree_a, _ = dos_agentes
    (worktree_a / "pendiente.txt").write_text("trabajo sin confirmar\n", encoding="utf-8")

    resultado = _correr_json(["finish", "--agent", "claude-api", "--cleanup"], capsys)

    assert resultado["worktree_removido"] is False
    assert "NO se elimina" in str(resultado["nota"])
    assert worktree_a.is_dir()
    assert (worktree_a / "pendiente.txt").is_file()


def test_worktree_limpio_y_finalizado_se_limpia(
    control: Path, dos_agentes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    worktree_a, worktree_b = dos_agentes

    _correr_json(["finish", "--agent", "claude-api"], capsys)
    resultado = _correr_json(["cleanup", "--agent", "claude-api"], capsys)

    assert resultado["worktree_removido"] is True
    assert not worktree_a.exists()
    # El worktree del otro agente sigue en pie.
    assert worktree_b.is_dir()
    assert gitops.rama_actual(worktree_b) == "feat/codex-web-tarea-b"


def test_cleanup_rechaza_un_agente_todavia_activo(
    control: Path, dos_agentes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    worktree_a, _ = dos_agentes

    assert _correr(["cleanup", "--agent", "claude-api"]) == 1
    assert "no se elimina el worktree" in capsys.readouterr().err
    assert worktree_a.is_dir()


def test_finish_libera_los_leases_propios(
    control: Path, dos_agentes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    registro = Registro(rutas.contexto(control).db_path)
    registro.adquirir("db:migrations", "claude-api", reason="x")

    resultado = _correr_json(["finish", "--agent", "claude-api"], capsys)

    assert resultado["leases_liberados"] == ["db:migrations"]
    assert registro.leases() == []


# ------------------------------------------------------------------- handoff


def test_handoff_conserva_rama_worktree_y_contexto(
    control: Path, dos_agentes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    worktree_a, _ = dos_agentes
    _configurar_identidad(worktree_a)
    _commit(worktree_a, "api/a.py", "# A\n", "feat(api): esqueleto del endpoint")
    (worktree_a / "api/pendiente.py").write_text("# TODO\n", encoding="utf-8")
    Registro(rutas.contexto(control).db_path).adquirir("db:migrations", "claude-api", reason="x")

    traspaso = _correr_json(
        [
            "handoff",
            "--from",
            "claude-api",
            "--to",
            "codex-api",
            "--next-action",
            "continuar implementación endpoint",
            "--blocked-on",
            "falta contrato de respuesta",
        ],
        capsys,
    )

    assert traspaso["rama"] == "feat/claude-api-tarea-a"
    assert traspaso["worktree"] == str(worktree_a)
    assert "esqueleto del endpoint" in traspaso["ultimo_commit"]
    assert traspaso["archivos_modificados"] == ["api/pendiente.py"]
    assert traspaso["leases"] == ["db:migrations"]
    assert traspaso["siguiente_accion"] == "continuar implementación endpoint"
    assert traspaso["bloqueado_por"] == "falta contrato de respuesta"

    registro = Registro(rutas.contexto(control).db_path)
    assert registro.agente("claude-api").status == "handoff"  # type: ignore[union-attr]

    aceptado = _correr_json(["accept-handoff", "--agent", "codex-api"], capsys)
    assert aceptado["rama"] == "feat/claude-api-tarea-a"
    assert aceptado["leases_transferidos"] == ["db:migrations"]
    # El ownership se transfirió de forma explícita, no silenciosa.
    nuevo = registro.agente("codex-api")
    assert nuevo is not None and nuevo.worktree_path == str(worktree_a)
    assert registro.lease("db:migrations").owner_agent_id == "codex-api"  # type: ignore[union-attr]
    assert registro.agente("claude-api") is None


# -------------------------------------------------------------------- doctor


def test_doctor_no_reporta_alertas_en_un_entorno_sano(
    control: Path, dos_agentes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    diagnostico = _correr_json(["doctor"], capsys)

    assert diagnostico["ok"] is True


def test_doctor_detecta_un_worktree_borrado_a_mano(
    control: Path, dos_agentes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    worktree_a, _ = dos_agentes
    shutil.rmtree(worktree_a)

    diagnostico = _correr_json(["doctor"], capsys)

    assert diagnostico["ok"] is False
    detalles = " ".join(h["detalle"] for h in diagnostico["hallazgos"])
    assert "registro activo sin worktree en disco" in detalles


def test_doctor_detecta_un_worktree_sin_agente_registrado(
    control: Path, dos_agentes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    registro = Registro(rutas.contexto(control).db_path)
    registro.olvidar_agente("codex-web")

    diagnostico = _correr_json(["doctor"], capsys)

    detalles = " ".join(h["detalle"] for h in diagnostico["hallazgos"])
    assert "worktree sin agente registrado" in detalles


def test_doctor_detecta_integracion_interrumpida(
    control: Path, dos_agentes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    registro = Registro(rutas.contexto(control).db_path)
    registro.cambiar_estado("claude-api", "integrating", detalle="simulación de corte")

    diagnostico = _correr_json(["doctor"], capsys)

    detalles = " ".join(h["detalle"] for h in diagnostico["hallazgos"])
    assert "integración interrumpida" in detalles


def test_doctor_no_modifica_nada(
    control: Path, dos_agentes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    worktree_a, worktree_b = dos_agentes
    (worktree_a / "pendiente.txt").write_text("sin confirmar\n", encoding="utf-8")

    _correr_json(["doctor"], capsys)

    assert (worktree_a / "pendiente.txt").is_file()
    assert worktree_b.is_dir()
    assert gitops.rama_actual(worktree_a) == "feat/claude-api-tarea-a"


# ------------------------------------------------------ recuperación y stale


def test_un_agente_stale_conserva_rama_worktree_y_cambios(
    control: Path, dos_agentes: tuple[Path, Path]
) -> None:
    worktree_a, _ = dos_agentes
    (worktree_a / "pendiente.txt").write_text("trabajo a medio hacer\n", encoding="utf-8")
    registro = Registro(rutas.contexto(control).db_path)

    registro.marcar_stale(ttl_minutos=-1)

    assert registro.agente("claude-api").status == "stale"  # type: ignore[union-attr]
    assert worktree_a.is_dir()
    assert (worktree_a / "pendiente.txt").is_file()
    assert gitops.existe_rama_local("feat/claude-api-tarea-a", control)


def test_start_recupera_un_registro_perdido_sin_borrar_la_rama(
    control: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Registro incompleto + rama existente: se re-adjunta el worktree, no se recrea la rama."""
    primero = _iniciar("claude-api", "tarea-a", capsys)
    worktree = Path(primero["worktree"])
    _configurar_identidad(worktree)
    _commit(worktree, "api/a.py", "# A\n", "feat(api): trabajo previo")
    sha_previo = gitops.sha("HEAD", worktree)

    # Simula una limpieza a medias: se retira el worktree pero la rama sobrevive.
    gitops.remover_worktree(worktree, control)
    Registro(rutas.contexto(control).db_path).olvidar_agente("claude-api")
    assert gitops.existe_rama_local("feat/claude-api-tarea-a", control)

    recuperado = _iniciar("claude-api", "tarea-a", capsys)

    assert Path(recuperado["worktree"]).is_dir()
    assert gitops.sha("HEAD", Path(recuperado["worktree"])) == sha_previo


def test_heartbeat_renueva_los_leases_del_agente(
    control: Path, dos_agentes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    registro = Registro(rutas.contexto(control).db_path)
    original = registro.adquirir("db:migrations", "claude-api", ttl_minutos=1)

    _correr_json(["heartbeat", "--agent", "claude-api"], capsys)

    renovado = registro.lease("db:migrations")
    assert renovado is not None and renovado.lease_expires_at >= original.lease_expires_at


def test_start_falla_con_mensaje_util_si_el_directorio_no_es_escribible(
    control: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Caso real: el directorio de worktrees existe y pertenece a otro usuario."""
    import os

    if os.geteuid() == 0:  # pragma: no cover - root ignora los permisos de escritura
        pytest.skip("root puede escribir en cualquier directorio")

    bloqueado = tmp_path / "bloqueado"
    bloqueado.mkdir()
    bloqueado.chmod(0o500)
    monkeypatch.setenv(rutas.ENV_DIR_WORKTREES, str(bloqueado))
    try:
        codigo = _correr(["start", "--agent", "claude-api", "--type", "feat", "--task", "tarea-a"])
        assert codigo == 2
        error = capsys.readouterr().err
        assert "no es escribible" in error
        assert rutas.ENV_DIR_WORKTREES in error
    finally:
        bloqueado.chmod(0o700)


def test_logs_del_worktree_apunta_a_los_del_checkout_de_control(
    control: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Un `docker compose up` desde el worktree monta `../Logs/dev` relativo al worktree.

    Regresión real (2026-09-30): el stack dev se levantó desde un worktree que después se cerró, y
    web, cromo_worker y slack_baneo_worker quedaron escribiendo en `Logs/dev` de una carpeta borrada.
    Con el enlace, el montaje resuelve al `Logs/` del checkout de control y sobrevive al cleanup.
    """
    (control / "Logs" / "dev").mkdir(parents=True)
    (control / ".gitignore").write_text("Logs/\n", encoding="utf-8")
    _git(["add", ".gitignore"], control)
    _git(["commit", "-m", "chore: ignorar logs"], control)

    resultado = _iniciar("claude-api", "tarea-logs", capsys)
    worktree = Path(resultado["worktree"])

    assert "Logs" in resultado["enlaces"]
    assert (worktree / "Logs").is_symlink()
    assert (worktree / "Logs" / "dev").resolve() == (control / "Logs" / "dev").resolve()
    assert gitops.esta_limpio(worktree), gitops.estado_porcelain(worktree)


def test_los_enlaces_de_entorno_no_ensucian_el_worktree(
    control: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """El venv y los secretos enlazados quedan ignorados sin importar la rama base.

    Regresión real (2026-09-14): ``.gitignore`` usaba patrones con barra final
    (``.venv*/``, ``.secrets/``) que no matchean un symlink, y el worktree quedaba
    permanentemente sucio, bloqueando ready/integrate/cleanup.
    """
    (control / ".venv").mkdir()
    (control / ".venv" / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
    (control / ".secrets").mkdir()
    (control / ".env.dev").write_text("CLAVE=valor\n", encoding="utf-8")
    # .gitignore con los mismos patrones que tenía el repo cuando se detectó el bug.
    (control / ".gitignore").write_text(".venv*/\n.secrets/\n.env\n.env.*\n", encoding="utf-8")
    _git(["add", ".gitignore"], control)
    _git(["commit", "-m", "chore: ignorar entornos"], control)

    resultado = _iniciar("claude-api", "tarea-a", capsys)
    worktree = Path(resultado["worktree"])

    assert set(resultado["enlaces"]) == {".venv", ".secrets"}
    # `.env.dev` ya no es symlink: es una copia privada con los puertos del agente.
    assert resultado["copias_privadas"] == [".env.dev"]
    assert not (worktree / ".env.dev").is_symlink()
    assert (worktree / ".venv").is_symlink()
    assert (worktree / ".venv" / "pyvenv.cfg").is_file()  # el venv se reutiliza, no se copia
    assert gitops.esta_limpio(worktree), gitops.estado_porcelain(worktree)


def test_asegurar_exclusiones_es_idempotente(control: Path) -> None:
    comun = rutas.contexto(control).git_common_dir

    primero = gitops.asegurar_exclusiones(comun, (".venv", ".secrets"))
    segundo = gitops.asegurar_exclusiones(comun, (".venv", ".secrets"))

    assert primero == [".venv", ".secrets"]
    assert segundo == []
    contenido = (comun / "info" / "exclude").read_text(encoding="utf-8")
    assert contenido.count("/.venv") == 1


def test_start_avisa_si_faltan_artefactos_de_build(
    control: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Un worktree nuevo no hereda los artefactos de build ignorados por Git.

    Hallazgo real (2026-09-14): los tests que sirven el shell SPA necesitan
    ``web/frontend/dist/index.html``; en un worktree recién creado no existe y los
    fallos parecen una regresión del cambio en curso. El aviso evita ese triage erróneo.
    """
    dist = control / "web" / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text('<div id="app"></div>', encoding="utf-8")
    (control / ".gitignore").write_text("web/frontend/dist/\n", encoding="utf-8")
    _git(["add", ".gitignore"], control)
    _git(["commit", "-m", "chore: ignorar dist"], control)

    resultado = _iniciar("claude-web", "tarea-web", capsys)

    assert resultado["artefactos_build_faltantes"] == ["web/frontend/dist"]
    assert not (Path(resultado["worktree"]) / "web" / "frontend" / "dist").exists()
    assert gitops.esta_limpio(Path(resultado["worktree"]))


def test_cleanup_olvidar_retira_el_registro_solo_si_el_worktree_ya_no_esta(
    control: Path, dos_agentes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    worktree_a, _ = dos_agentes
    (worktree_a / "pendiente.txt").write_text("sin confirmar\n", encoding="utf-8")
    _correr_json(["finish", "--agent", "claude-api"], capsys)

    # Worktree sucio: no se elimina, y por lo tanto tampoco se retira el registro.
    assert _correr(["cleanup", "--agent", "claude-api", "--olvidar"]) == 1
    assert "sigue presente" in capsys.readouterr().err
    registro = Registro(rutas.contexto(control).db_path)
    assert registro.agente("claude-api") is not None

    (worktree_a / "pendiente.txt").unlink()
    resultado = _correr_json(["cleanup", "--agent", "claude-api", "--olvidar"], capsys)

    assert resultado["worktree_removido"] is True
    assert resultado["registro_retirado"] is True
    assert registro.agente("claude-api") is None
    assert registro.agente("codex-web") is not None  # el otro agente no se toca


# ------------------------------------------------- puertos y .env.dev privados


def test_puertos_agente_es_determinista() -> None:
    assert agent_worktree.puertos_agente(3) == {
        "api": 8014,
        "web": 8093,
        "vite": 5176,
        "office": 8023,
        "nlp_intent": 8033,
    }


def test_start_asigna_offsets_distintos_a_agentes_simultaneos(
    control: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    primero = _iniciar("claude-api", "tarea-a", capsys)
    segundo = _iniciar("codex-web", "tarea-b", capsys)

    assert primero["offset"] == 1
    assert segundo["offset"] == 2
    assert set(primero["puertos"].values()).isdisjoint(segundo["puertos"].values())


def test_start_evita_offsets_cuyos_puertos_se_solapan_con_otro_agente(
    control: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """api(8011+10) == office(8020+1): comparar sólo el offset no alcanza."""
    _correr_json(["start", "--agent", "claude-api", "--task", "tarea-a", "--offset", "10"], capsys)

    assert _correr(["start", "--agent", "codex-web", "--task", "tarea-b", "--offset", "1"]) == 1
    assert "se solapan" in capsys.readouterr().err
    # Un offset rechazado no deja un worktree ni una rama huérfanos.
    assert not (control.parent / "LAS-FOCAS-agentes" / "codex-web-tarea-b").exists()
    assert not gitops.existe_rama_local("feat/codex-web-tarea-b", control)
    automatico = _iniciar("codex-web", "tarea-b", capsys)
    assert automatico["offset"] not in (1, 10)


def test_start_salta_offsets_con_puertos_ocupados_en_el_host(
    control: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent_worktree, "puerto_libre", lambda puerto: puerto != 8012)

    resultado = _iniciar("claude-api", "tarea-a", capsys)

    assert resultado["offset"] == 2


def test_start_rechaza_un_offset_fuera_de_rango(
    control: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _correr(["start", "--agent", "claude-api", "--task", "tarea-a", "--offset", "91"]) == 1
    assert "entre 1 y 90" in capsys.readouterr().err


def test_un_agente_finalizado_libera_su_offset(
    control: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _iniciar("claude-api", "tarea-a", capsys)
    _correr_json(["finish", "--agent", "claude-api"], capsys)

    assert _iniciar("codex-web", "tarea-b", capsys)["offset"] == 1


def test_env_dev_privada_sobrescribe_puertos_sin_tocar_el_control(
    control: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    original = "POSTGRES_DB=focas\nAPI_PORT=9999\n# comentario\n"
    (control / ".env.dev").write_text(original, encoding="utf-8")
    (control / ".gitignore").write_text(".env\n.env.*\n", encoding="utf-8")
    _git(["add", ".gitignore"], control)
    _git(["commit", "-m", "chore: ignorar env"], control)

    resultado = _iniciar("claude-api", "tarea-a", capsys)
    privada = Path(resultado["worktree"]) / ".env.dev"
    contenido = privada.read_text(encoding="utf-8")

    assert "POSTGRES_DB=focas" in contenido
    assert "API_PORT=9999" not in contenido
    assert "API_PORT=8012" in contenido
    assert "LAS_FOCAS_AGENT_WORKTREE=1" in contenido
    assert "LAS_FOCAS_PORT_OFFSET=1" in contenido
    assert "VITE_API_BASE_URL=http://127.0.0.1:8012" in contenido
    assert stat.S_IMODE(privada.stat().st_mode) == 0o600
    # Editar la copia del agente no contamina el control ni a otros worktrees.
    privada.write_text(contenido + "SOLO_ESTE_AGENTE=1\n", encoding="utf-8")
    assert (control / ".env.dev").read_text(encoding="utf-8") == original
    assert gitops.esta_limpio(Path(resultado["worktree"]))


def test_env_dev_privada_no_imprime_su_contenido(
    control: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (control / ".env.dev").write_text("POSTGRES_PASSWORD=Dev_secreto_no_mostrar\n", encoding="utf-8")

    codigo = _correr(["start", "--agent", "claude-api", "--task", "tarea-a"])

    salida = capsys.readouterr()
    assert codigo == 0
    assert "Dev_secreto_no_mostrar" not in salida.out + salida.err


def test_start_escribe_metadata_del_worktree_ignorada_por_git(
    control: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    resultado = _iniciar("claude-api", "tarea-a", capsys)
    worktree = Path(resultado["worktree"])

    datos = json.loads((worktree / ".agent-worktree.json").read_text(encoding="utf-8"))

    assert datos == {
        "agent_id": "claude-api",
        "task_id": "tarea-a",
        "branch": "feat/claude-api-tarea-a",
        "offset": 1,
        "ports": agent_worktree.puertos_agente(1),
    }
    assert gitops.esta_limpio(worktree)


def test_start_idempotente_conserva_el_offset(
    control: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    primero = _iniciar("claude-api", "tarea-a", capsys)
    segundo = _iniciar("claude-api", "tarea-a", capsys)

    assert segundo["idempotente"] is True
    assert segundo["offset"] == primero["offset"]


def test_status_y_list_exponen_offset_y_puertos(
    control: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _iniciar("claude-api", "tarea-a", capsys)

    fila = _correr_json(["status", "--agent", "claude-api"], capsys)
    listado = json.loads(
        (agent_worktree.main(["list", "--json"]), capsys.readouterr().out)[1]
    )

    assert fila["port_offset"] == 1
    assert fila["puertos"]["api"] == 8012
    assert listado[0]["port_offset"] == 1


def test_el_registro_migra_una_base_sin_port_offset(tmp_path: Path) -> None:
    """Una base creada antes de la columna nueva se migra al abrirla, sin perder filas."""
    db = tmp_path / "agent_state.sqlite3"
    conexion = sqlite3.connect(db)
    conexion.executescript(
        """
        CREATE TABLE agentes (
            agent_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, status TEXT NOT NULL,
            branch TEXT NOT NULL, worktree_path TEXT NOT NULL, base_ref TEXT NOT NULL DEFAULT '',
            base_sha TEXT NOT NULL DEFAULT '', started_at REAL NOT NULL, heartbeat_at REAL NOT NULL,
            last_activity_at REAL NOT NULL, host TEXT NOT NULL DEFAULT '',
            pid INTEGER NOT NULL DEFAULT 0, notas TEXT NOT NULL DEFAULT ''
        );
        INSERT INTO agentes VALUES ('viejo', 't', 'active', 'feat/viejo-t', '/x', '', '', 1, 1, 1, '', 0, '');
        """
    )
    conexion.commit()
    conexion.close()

    registro = Registro(db)
    Registro(db)  # idempotente: reabrir no vuelve a alterar la tabla

    agente = registro.agente("viejo")
    assert agente is not None and agente.port_offset == 0


# ----------------------------------------- cleanup: procesos e ignorados no runtime


def test_cleanup_aborta_si_hay_ignorados_que_no_son_runtime(
    control: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (control / ".gitignore").write_text("*.docx\n__pycache__/\n", encoding="utf-8")
    _git(["add", ".gitignore"], control)
    _git(["commit", "-m", "chore: ignorar docx"], control)
    _git(["push", "origin", "dev"], control)
    worktree = Path(_iniciar("claude-api", "tarea-a", capsys)["worktree"])
    (worktree / "informe_generado.docx").write_bytes(b"PK")
    (worktree / "scripts" / "__pycache__").mkdir(parents=True)
    (worktree / "scripts" / "__pycache__" / "x.pyc").write_bytes(b"\0")
    _correr_json(["finish", "--agent", "claude-api"], capsys)

    assert _correr(["cleanup", "--agent", "claude-api"]) == 1
    error = capsys.readouterr().err
    assert "informe_generado.docx" in error
    assert "__pycache__" not in error
    assert (worktree / "informe_generado.docx").is_file()

    (worktree / "informe_generado.docx").unlink()
    resultado = _correr_json(["cleanup", "--agent", "claude-api"], capsys)
    assert resultado["worktree_removido"] is True


def test_cleanup_descarta_el_workspace_sdd(control: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`.superpowers/` (ledgers y reportes del flujo con subagentes) es scratch de la sesión: no
    bloquea el cleanup. Real 2026-10-21/22: lo trabó en 4 worktrees y hubo que borrarlo a mano."""
    (control / ".gitignore").write_text(".superpowers/\n", encoding="utf-8")
    _git(["add", ".gitignore"], control)
    _git(["commit", "-m", "chore: ignorar superpowers"], control)
    _git(["push", "origin", "dev"], control)
    worktree = Path(_iniciar("claude-api", "tarea-a", capsys)["worktree"])
    ledger = worktree / ".superpowers" / "sdd" / "plan-x" / "progress.md"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("# ledger\n", encoding="utf-8")
    _correr_json(["finish", "--agent", "claude-api"], capsys)

    resultado = _correr_json(["cleanup", "--agent", "claude-api"], capsys)

    assert resultado["worktree_removido"] is True


def test_cleanup_descarta_el_runtime_conocido(
    control: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (control / ".env.dev").write_text("X=1\n", encoding="utf-8")
    (control / ".venv").mkdir()
    worktree = Path(_iniciar("claude-api", "tarea-a", capsys)["worktree"])
    assert (worktree / ".agent-worktree.json").is_file()
    _correr_json(["finish", "--agent", "claude-api"], capsys)

    resultado = _correr_json(["cleanup", "--agent", "claude-api"], capsys)

    assert resultado["worktree_removido"] is True
    assert (control / ".venv").is_dir()  # se borró el symlink, no el venv del control
    assert (control / ".env.dev").read_text(encoding="utf-8") == "X=1\n"


def test_cleanup_aborta_si_hay_un_proceso_vivo_dentro_del_worktree(
    control: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    worktree = Path(_iniciar("claude-api", "tarea-a", capsys)["worktree"])
    _correr_json(["finish", "--agent", "claude-api"], capsys)
    servidor = subprocess.Popen(["sleep", "60"], cwd=str(worktree))
    try:
        assert _correr(["cleanup", "--agent", "claude-api"]) == 1
        error = capsys.readouterr().err
        assert f"sleep[{servidor.pid}]" in error
        assert worktree.is_dir()
    finally:
        servidor.kill()
        servidor.wait()

    assert _correr_json(["cleanup", "--agent", "claude-api"], capsys)["worktree_removido"] is True


def test_procesos_en_worktree_excluye_a_la_propia_cli(control: Path, capsys) -> None:
    worktree = Path(_iniciar("claude-api", "tarea-a", capsys)["worktree"])
    previo = Path.cwd()
    os.chdir(worktree)
    try:
        assert agent_worktree.procesos_en_worktree(worktree) == []
    finally:
        os.chdir(previo)


def test_el_registro_tolera_columnas_futuras(tmp_path: Path) -> None:
    """Una columna agregada por una versión más nueva no rompe a esta versión."""
    db = tmp_path / "agent_state.sqlite3"
    registro = Registro(db)
    registro.registrar_agente("a", task_id="t", branch="feat/a-t", worktree_path="/x")
    conexion = sqlite3.connect(db)
    conexion.execute("ALTER TABLE agentes ADD COLUMN columna_del_futuro TEXT DEFAULT ''")
    conexion.execute("ALTER TABLE leases ADD COLUMN columna_del_futuro TEXT DEFAULT ''")
    conexion.commit()
    conexion.close()
    registro.adquirir("db:migrations", "a")

    assert registro.agente("a") is not None
    assert [lease.resource for lease in registro.leases()] == ["db:migrations"]
