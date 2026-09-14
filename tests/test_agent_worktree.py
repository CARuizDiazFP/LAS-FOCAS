# Nombre de archivo: test_agent_worktree.py
# Ubicación de archivo: tests/test_agent_worktree.py
# Descripción: Pruebas de aislamiento físico multi-agente por Git worktree, integración serializada a dev y diagnóstico

"""Pruebas del tooling de worktrees por agente.

Todas se ejecutan contra repositorios Git temporales creados en ``tmp_path`` con un
remoto *bare* local: no dependen de GitHub, de la red ni del repositorio real.
"""

from __future__ import annotations

import json
import shutil
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

    integrado_b = _correr_json(["integrate", "--agent", "codex-web"], capsys)
    assert integrado_b["status"] == "finished"
    assert gitops.es_ancestro(gitops.sha("HEAD", worktree_b), "origin/dev", control)


def test_integrate_se_bloquea_si_otro_agente_sostiene_la_ventana(
    control: Path, dos_agentes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    worktree_a, worktree_b = dos_agentes
    _configurar_identidad(worktree_b)
    _commit(worktree_b, "web/b.ts", "// B\n", "feat(web): trabajo de B")

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

    _correr_json(["integrate", "--agent", "claude-api"], capsys)
    capsys.readouterr()

    assert _correr(["integrate", "--agent", "codex-web"]) == 1
    assert "sync --agent codex-web" in capsys.readouterr().err


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

    assert set(resultado["enlaces"]) == {".venv", ".secrets", ".env.dev"}
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
