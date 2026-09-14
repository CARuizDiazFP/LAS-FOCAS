# Nombre de archivo: test_agent_lock.py
# Ubicación de archivo: tests/test_agent_lock.py
# Descripción: Pruebas del registro de leases por recurso entre agentes concurrentes (adquisición atómica, heartbeat, expiración y limpieza)

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from scripts.agentes.estado import (
    ConflictoLease,
    Registro,
    formatear_duracion,
)


@pytest.fixture()
def registro(tmp_path: Path) -> Registro:
    return Registro(tmp_path / "agent_state.sqlite3")


# ------------------------------------------------------------------ adquisición


def test_recursos_distintos_se_adquieren_en_simultaneo(registro: Registro) -> None:
    """Dos agentes trabajando sobre recursos distintos no se bloquean entre sí."""
    primero = registro.adquirir("db:migrations", "claude-db", reason="migración de inventario")
    segundo = registro.adquirir("env:docker-compose", "codex-infra", reason="recrear stack")

    assert primero.owner_agent_id == "claude-db"
    assert segundo.owner_agent_id == "codex-infra"
    assert {lease.resource for lease in registro.leases()} == {"db:migrations", "env:docker-compose"}


def test_mismo_recurso_rechaza_al_segundo_agente(registro: Registro) -> None:
    registro.adquirir("db:migrations", "claude-db", ttl_minutos=30)

    with pytest.raises(ConflictoLease) as excinfo:
        registro.adquirir("db:migrations", "codex-db", ttl_minutos=30)

    mensaje = str(excinfo.value)
    assert "claude-db" in mensaje
    assert "vence en" in mensaje


def test_acquire_es_idempotente_para_el_mismo_agente(registro: Registro) -> None:
    primero = registro.adquirir("skill:docker-rebuild", "claude-docker", ttl_minutos=30)
    segundo = registro.adquirir("skill:docker-rebuild", "claude-docker", ttl_minutos=30)

    assert primero.acquired_at == segundo.acquired_at
    assert segundo.lease_expires_at >= primero.lease_expires_at
    assert len(registro.leases()) == 1


def test_lease_vencido_se_puede_tomar_sin_force(registro: Registro) -> None:
    registro.adquirir("docs:AGENTS.md", "claude-docs", ttl_minutos=-1)

    lease = registro.adquirir("docs:AGENTS.md", "gemini-docs", ttl_minutos=30)

    assert lease.owner_agent_id == "gemini-docs"
    assert any(evento["evento"] == "lock_expired_takeover" for evento in registro.eventos())


def test_robar_lease_vigente_exige_force(registro: Registro) -> None:
    registro.adquirir("governance:claude", "claude-a", ttl_minutos=30)

    with pytest.raises(ConflictoLease):
        registro.adquirir("governance:claude", "claude-b", ttl_minutos=30)

    lease = registro.adquirir("governance:claude", "claude-b", ttl_minutos=30, force=True)
    assert lease.owner_agent_id == "claude-b"
    assert any(evento["evento"] == "lock_stolen" for evento in registro.eventos())


def test_conflicto_queda_auditado(registro: Registro) -> None:
    registro.adquirir("db:migrations", "claude-db")
    with pytest.raises(ConflictoLease):
        registro.adquirir("db:migrations", "codex-db")

    eventos = [evento["evento"] for evento in registro.eventos()]
    assert "lock_conflict" in eventos


# -------------------------------------------------------------------- heartbeat


def test_heartbeat_extiende_lease_vigente(registro: Registro) -> None:
    original = registro.adquirir("git:integrate-dev", "claude-api", ttl_minutos=1)

    renovado = registro.renovar("git:integrate-dev", "claude-api", ttl_minutos=60)

    assert renovado.acquired_at == original.acquired_at
    assert renovado.lease_expires_at > original.lease_expires_at


def test_heartbeat_no_revive_lease_vencido(registro: Registro) -> None:
    """Un heartbeat tardío no debe resucitar silenciosamente un lease ya expirado."""
    registro.adquirir("git:integrate-dev", "claude-api", ttl_minutos=-1)

    with pytest.raises(ConflictoLease) as excinfo:
        registro.renovar("git:integrate-dev", "claude-api", ttl_minutos=30)

    assert "venció" in str(excinfo.value)


def test_heartbeat_ajeno_es_rechazado(registro: Registro) -> None:
    registro.adquirir("db:migrations", "claude-db", ttl_minutos=30)

    with pytest.raises(ConflictoLease):
        registro.renovar("db:migrations", "codex-db", ttl_minutos=30)


# ---------------------------------------------------------------------- release


def test_release_propio_libera_el_recurso(registro: Registro) -> None:
    registro.adquirir("db:migrations", "claude-db")

    assert registro.liberar("db:migrations", "claude-db") is True
    assert registro.leases("db:migrations") == []


def test_release_de_lease_inexistente_es_idempotente(registro: Registro) -> None:
    assert registro.liberar("db:migrations", "claude-db") is False


def test_release_ajeno_vigente_exige_force(registro: Registro) -> None:
    registro.adquirir("db:migrations", "claude-db", ttl_minutos=30)

    with pytest.raises(ConflictoLease):
        registro.liberar("db:migrations", "codex-db")

    assert registro.liberar("db:migrations", "codex-db", force=True) is True


def test_release_all_libera_solo_los_propios(registro: Registro) -> None:
    registro.adquirir("db:migrations", "claude-db")
    registro.adquirir("docs:AGENTS.md", "claude-db")
    registro.adquirir("env:docker-compose", "codex-infra")

    liberados = registro.liberar_todos("claude-db")

    assert sorted(liberados) == ["db:migrations", "docs:AGENTS.md"]
    assert [lease.resource for lease in registro.leases()] == ["env:docker-compose"]


# ----------------------------------------------------------------- stale y TTL


def test_stale_cleanup_elimina_vencidos_y_conserva_vigentes(registro: Registro) -> None:
    registro.adquirir("docs:AGENTS.md", "claude-docs", ttl_minutos=-1)
    registro.adquirir("db:migrations", "claude-db", ttl_minutos=30)

    vencidos = registro.limpiar_vencidos()

    assert [lease.resource for lease in vencidos] == ["docs:AGENTS.md"]
    assert [lease.resource for lease in registro.leases()] == ["db:migrations"]


def test_stale_cleanup_dry_run_no_modifica(registro: Registro) -> None:
    registro.adquirir("docs:AGENTS.md", "claude-docs", ttl_minutos=-1)

    vencidos = registro.limpiar_vencidos(dry_run=True)

    assert len(vencidos) == 1
    assert len(registro.leases()) == 1


def test_agente_sin_heartbeat_se_marca_stale_sin_tocar_su_trabajo(registro: Registro) -> None:
    registro.registrar_agente(
        "claude-api",
        task_id="busqueda-camaras",
        branch="feat/claude-api-busqueda-camaras",
        worktree_path="/tmp/wt-a",
    )

    marcados = registro.marcar_stale(ttl_minutos=-1)

    assert [agente.agent_id for agente in marcados] == ["claude-api"]
    agente = registro.agente("claude-api")
    assert agente is not None
    assert agente.status == "stale"
    # Rama y worktree se conservan intactos: stale es una señal, no una acción destructiva.
    assert agente.branch == "feat/claude-api-busqueda-camaras"
    assert agente.worktree_path == "/tmp/wt-a"


def test_heartbeat_recupera_a_un_agente_stale(registro: Registro) -> None:
    registro.registrar_agente(
        "claude-api", task_id="t", branch="feat/claude-api-t", worktree_path="/tmp/wt-a"
    )
    registro.marcar_stale(ttl_minutos=-1)

    agente = registro.heartbeat_agente("claude-api")

    assert agente.status == "active"


# -------------------------------------------------------------- concurrencia


def test_acquire_concurrente_deja_un_unico_ganador(tmp_path: Path) -> None:
    """Diez hilos compitiendo por el mismo recurso: uno gana, el resto recibe conflicto."""
    db_path = tmp_path / "agent_state.sqlite3"
    Registro(db_path)  # crea el esquema antes de la contienda
    ganadores: list[str] = []
    conflictos: list[str] = []
    barrera = threading.Barrier(10)

    def competir(indice: int) -> None:
        propio = Registro(db_path)
        barrera.wait()
        try:
            propio.adquirir("db:migrations", f"agente-{indice}", ttl_minutos=30)
            ganadores.append(f"agente-{indice}")
        except ConflictoLease:
            conflictos.append(f"agente-{indice}")

    hilos = [threading.Thread(target=competir, args=(indice,)) for indice in range(10)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()

    assert len(ganadores) == 1
    assert len(conflictos) == 9
    leases = Registro(db_path).leases("db:migrations")
    assert len(leases) == 1
    assert leases[0].owner_agent_id == ganadores[0]


def test_estado_es_compartido_entre_conexiones(tmp_path: Path) -> None:
    """Dos instancias del registro (dos procesos/worktrees) ven el mismo estado."""
    db_path = tmp_path / "agent_state.sqlite3"
    Registro(db_path).adquirir("db:migrations", "claude-db", ttl_minutos=30)

    visto_desde_otro = Registro(db_path).lease("db:migrations")

    assert visto_desde_otro is not None
    assert visto_desde_otro.owner_agent_id == "claude-db"


# ---------------------------------------------------------------------- varios


def test_formatear_duracion_es_legible() -> None:
    assert formatear_duracion(512) == "08m32s"
    assert formatear_duracion(0) == "00m00s"
    assert formatear_duracion(-5) == "00m00s"
    assert formatear_duracion(3700) == "01h01m40s"


def test_handoff_conserva_contexto_y_transfiere_ownership(registro: Registro) -> None:
    registro.registrar_agente(
        "claude-api", task_id="endpoint", branch="feat/claude-api-endpoint", worktree_path="/tmp/wt-a"
    )
    handoff = registro.crear_handoff(
        from_agent="claude-api",
        to_agent="codex-api",
        task="endpoint",
        next_action="continuar implementación endpoint",
        blocked_on="falta definir el contrato de respuesta",
        branch="feat/claude-api-endpoint",
        worktree_path="/tmp/wt-a",
        last_commit="abc1234 feat(api): esqueleto",
        archivos=["api/app/routers/camaras.py"],
        leases=["db:migrations"],
    )

    assert handoff.state == "pendiente"
    aceptado = registro.aceptar_handoff(handoff.id, "codex-api")
    assert aceptado.state == "aceptado"
    assert aceptado.branch == "feat/claude-api-endpoint"
    assert aceptado.next_action == "continuar implementación endpoint"
    assert "handoff_created" in [evento["evento"] for evento in registro.eventos()]


def test_handoff_dirigido_a_otro_agente_no_puede_aceptarse(registro: Registro) -> None:
    handoff = registro.crear_handoff(from_agent="claude-api", to_agent="codex-api")

    with pytest.raises(Exception):
        registro.aceptar_handoff(handoff.id, "gemini-docs")
