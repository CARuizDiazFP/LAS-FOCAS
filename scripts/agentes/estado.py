# Nombre de archivo: estado.py
# Ubicación de archivo: scripts/agentes/estado.py
# Descripción: Registro SQLite compartido de agentes, leases de recursos, handoffs y eventos de auditoría

"""Estado de coordinación multi-agente sobre SQLite.

La base vive bajo ``<git-common-dir>/las-focas-agents/agent_state.sqlite3`` (ver
``scripts/agentes/rutas.py``), por lo que es visible desde cualquier linked worktree
del mismo repositorio, sobrevive a los cambios de rama y **nunca** entra al historial
de Git.

Decisiones de implementación:

- ``journal_mode=WAL``: permite lecturas concurrentes mientras un agente escribe.
- ``busy_timeout``: un agente que encuentra la base tomada espera en vez de fallar.
- ``BEGIN IMMEDIATE`` en toda mutación de lease: el chequeo de propiedad y la
  escritura ocurren en la misma transacción de escritura, que es lo que hace atómico
  el ``acquire`` frente a dos agentes compitiendo por el mismo recurso.
- Todos los instantes se persisten como epoch UTC (``REAL``); el formateo legible es
  responsabilidad de la CLI.

PostgreSQL queda documentado como backend futuro para coordinación entre máquinas
distintas; para agentes locales sobre el mismo repositorio SQLite es suficiente y no
agrega dependencias ni servicios.
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

# TTL por defecto de un lease de recurso (minutos).
TTL_LEASE_MINUTOS = 30
# TTL por defecto de actividad de un agente antes de considerarlo stale (minutos).
TTL_AGENTE_MINUTOS = 120
# Espera máxima ante una base tomada por otro proceso (milisegundos).
BUSY_TIMEOUT_MS = 10_000

ESTADOS_AGENTE = (
    "starting",
    "active",
    "blocked",
    "handoff",
    "ready_to_merge",
    "integrating",
    "finished",
    "stale",
    "failed",
)

# Estados desde los que un agente inactivo puede pasar a ``stale``.
ESTADOS_VIVOS = ("starting", "active", "blocked", "ready_to_merge", "integrating")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS agentes (
    agent_id         TEXT PRIMARY KEY,
    task_id          TEXT NOT NULL,
    status           TEXT NOT NULL,
    branch           TEXT NOT NULL,
    worktree_path    TEXT NOT NULL,
    base_ref         TEXT NOT NULL DEFAULT '',
    base_sha         TEXT NOT NULL DEFAULT '',
    started_at       REAL NOT NULL,
    heartbeat_at     REAL NOT NULL,
    last_activity_at REAL NOT NULL,
    host             TEXT NOT NULL DEFAULT '',
    pid              INTEGER NOT NULL DEFAULT 0,
    notas            TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS leases (
    resource         TEXT PRIMARY KEY,
    owner_agent_id   TEXT NOT NULL,
    scope            TEXT NOT NULL DEFAULT '',
    status           TEXT NOT NULL DEFAULT 'active',
    acquired_at      REAL NOT NULL,
    heartbeat_at     REAL NOT NULL,
    lease_expires_at REAL NOT NULL,
    reason           TEXT NOT NULL DEFAULT '',
    host             TEXT NOT NULL DEFAULT '',
    pid              INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS handoffs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    from_agent    TEXT NOT NULL,
    to_agent      TEXT NOT NULL,
    resource      TEXT NOT NULL DEFAULT '',
    task          TEXT NOT NULL DEFAULT '',
    state         TEXT NOT NULL DEFAULT 'pendiente',
    next_action   TEXT NOT NULL DEFAULT '',
    blocked_on    TEXT NOT NULL DEFAULT '',
    branch        TEXT NOT NULL DEFAULT '',
    worktree_path TEXT NOT NULL DEFAULT '',
    last_commit   TEXT NOT NULL DEFAULT '',
    archivos      TEXT NOT NULL DEFAULT '',
    leases        TEXT NOT NULL DEFAULT '',
    created_at    REAL NOT NULL,
    accepted_at   REAL
);

CREATE TABLE IF NOT EXISTS eventos (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL NOT NULL,
    evento    TEXT NOT NULL,
    agent_id  TEXT NOT NULL DEFAULT '',
    resource  TEXT NOT NULL DEFAULT '',
    detalle   TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_eventos_ts ON eventos(ts);
CREATE INDEX IF NOT EXISTS idx_handoffs_to ON handoffs(to_agent, state);
"""


class ErrorEstado(RuntimeError):
    """Error genérico del registro de estado."""


class ConflictoLease(ErrorEstado):
    """El recurso pertenece a otro agente con lease vigente."""


class AgenteDesconocido(ErrorEstado):
    """El agente no está registrado en el estado compartido."""


def ahora() -> float:
    """Instante actual en epoch UTC (segundos)."""
    return time.time()


@dataclass
class Lease:
    resource: str
    owner_agent_id: str
    scope: str
    status: str
    acquired_at: float
    heartbeat_at: float
    lease_expires_at: float
    reason: str
    host: str
    pid: int

    def vencido(self, *, momento: float | None = None) -> bool:
        return (momento if momento is not None else ahora()) >= self.lease_expires_at

    def segundos_restantes(self, *, momento: float | None = None) -> int:
        return max(0, int(self.lease_expires_at - (momento if momento is not None else ahora())))


@dataclass
class Agente:
    agent_id: str
    task_id: str
    status: str
    branch: str
    worktree_path: str
    base_ref: str
    base_sha: str
    started_at: float
    heartbeat_at: float
    last_activity_at: float
    host: str
    pid: int
    notas: str

    def inactivo(self, *, ttl_minutos: int = TTL_AGENTE_MINUTOS, momento: float | None = None) -> bool:
        limite = (momento if momento is not None else ahora()) - ttl_minutos * 60
        return self.heartbeat_at < limite


@dataclass
class Handoff:
    id: int
    from_agent: str
    to_agent: str
    resource: str
    task: str
    state: str
    next_action: str
    blocked_on: str
    branch: str
    worktree_path: str
    last_commit: str
    archivos: str
    leases: str
    created_at: float
    accepted_at: float | None


class Registro:
    """Acceso al estado compartido. Instanciar con la ruta devuelta por ``rutas.contexto``."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._inicializar()

    # ------------------------------------------------------------------ conexión

    def _conectar(self) -> sqlite3.Connection:
        conexion = sqlite3.connect(str(self.db_path), timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None)
        conexion.row_factory = sqlite3.Row
        conexion.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        conexion.execute("PRAGMA journal_mode = WAL")
        conexion.execute("PRAGMA synchronous = NORMAL")
        conexion.execute("PRAGMA foreign_keys = ON")
        return conexion

    def _inicializar(self) -> None:
        with self._conectar() as conexion:
            conexion.executescript(ESQUEMA)

    @contextmanager
    def _escritura(self) -> Iterator[sqlite3.Connection]:
        """Transacción de escritura inmediata: serializa el check-then-write entre agentes."""
        conexion = self._conectar()
        try:
            conexion.execute("BEGIN IMMEDIATE")
            yield conexion
            conexion.execute("COMMIT")
        except BaseException:
            conexion.execute("ROLLBACK")
            raise
        finally:
            conexion.close()

    @contextmanager
    def _lectura(self) -> Iterator[sqlite3.Connection]:
        conexion = self._conectar()
        try:
            yield conexion
        finally:
            conexion.close()

    # -------------------------------------------------------------------- eventos

    def registrar_evento(
        self,
        evento: str,
        *,
        agent_id: str = "",
        resource: str = "",
        detalle: str = "",
        conexion: sqlite3.Connection | None = None,
    ) -> None:
        """Anota un evento de auditoría. Nunca debe recibir secretos en ``detalle``."""
        fila = (ahora(), evento, agent_id, resource, detalle)
        sentencia = "INSERT INTO eventos (ts, evento, agent_id, resource, detalle) VALUES (?, ?, ?, ?, ?)"
        if conexion is not None:
            conexion.execute(sentencia, fila)
            return
        with self._escritura() as nueva:
            nueva.execute(sentencia, fila)

    def eventos(self, *, limite: int = 50, agent_id: str | None = None) -> list[dict[str, Any]]:
        consulta = "SELECT * FROM eventos"
        parametros: list[Any] = []
        if agent_id:
            consulta += " WHERE agent_id = ?"
            parametros.append(agent_id)
        consulta += " ORDER BY id DESC LIMIT ?"
        parametros.append(limite)
        with self._lectura() as conexion:
            return [dict(fila) for fila in conexion.execute(consulta, parametros)]

    # -------------------------------------------------------------------- agentes

    def registrar_agente(
        self,
        agent_id: str,
        *,
        task_id: str,
        branch: str,
        worktree_path: str,
        base_ref: str = "",
        base_sha: str = "",
        status: str = "active",
        notas: str = "",
    ) -> Agente:
        """Alta o actualización idempotente de un agente.

        Si el agente ya existe conserva ``started_at`` y refresca el resto: volver a
        ejecutar ``start`` para la misma tarea no rompe el estado.
        """
        if status not in ESTADOS_AGENTE:
            raise ErrorEstado(f"estado de agente inválido: {status!r}")
        instante = ahora()
        with self._escritura() as conexion:
            existente = conexion.execute(
                "SELECT * FROM agentes WHERE agent_id = ?", (agent_id,)
            ).fetchone()
            started_at = existente["started_at"] if existente else instante
            conexion.execute(
                """
                INSERT INTO agentes (agent_id, task_id, status, branch, worktree_path, base_ref,
                                     base_sha, started_at, heartbeat_at, last_activity_at, host, pid, notas)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    task_id = excluded.task_id,
                    status = excluded.status,
                    branch = excluded.branch,
                    worktree_path = excluded.worktree_path,
                    base_ref = excluded.base_ref,
                    base_sha = excluded.base_sha,
                    heartbeat_at = excluded.heartbeat_at,
                    last_activity_at = excluded.last_activity_at,
                    host = excluded.host,
                    pid = excluded.pid,
                    notas = excluded.notas
                """,
                (
                    agent_id,
                    task_id,
                    status,
                    branch,
                    worktree_path,
                    base_ref,
                    base_sha,
                    started_at,
                    instante,
                    instante,
                    socket.gethostname(),
                    os.getpid(),
                    notas,
                ),
            )
            self.registrar_evento(
                "agent_started" if existente is None else "agent_updated",
                agent_id=agent_id,
                detalle=f"rama={branch} worktree={worktree_path} estado={status}",
                conexion=conexion,
            )
        agente = self.agente(agent_id)
        assert agente is not None  # recién insertado
        return agente

    def agente(self, agent_id: str) -> Agente | None:
        with self._lectura() as conexion:
            fila = conexion.execute("SELECT * FROM agentes WHERE agent_id = ?", (agent_id,)).fetchone()
        return Agente(**dict(fila)) if fila else None

    def agentes(self, *, estados: tuple[str, ...] | None = None) -> list[Agente]:
        consulta = "SELECT * FROM agentes"
        parametros: list[Any] = []
        if estados:
            marcadores = ",".join("?" for _ in estados)
            consulta += f" WHERE status IN ({marcadores})"
            parametros.extend(estados)
        consulta += " ORDER BY started_at ASC"
        with self._lectura() as conexion:
            return [Agente(**dict(fila)) for fila in conexion.execute(consulta, parametros)]

    def agente_por_worktree(self, worktree_path: str | Path) -> Agente | None:
        objetivo = str(Path(worktree_path).resolve())
        for agente in self.agentes():
            if str(Path(agente.worktree_path)) == objetivo:
                return agente
        return None

    def heartbeat_agente(self, agent_id: str, *, detalle: str = "") -> Agente:
        """Refresca el heartbeat y devuelve el agente. Falla si no está registrado."""
        with self._escritura() as conexion:
            fila = conexion.execute("SELECT * FROM agentes WHERE agent_id = ?", (agent_id,)).fetchone()
            if fila is None:
                raise AgenteDesconocido(f"el agente {agent_id!r} no está registrado")
            instante = ahora()
            nuevo_estado = "active" if fila["status"] == "stale" else fila["status"]
            conexion.execute(
                "UPDATE agentes SET heartbeat_at = ?, last_activity_at = ?, status = ? WHERE agent_id = ?",
                (instante, instante, nuevo_estado, agent_id),
            )
            self.registrar_evento("heartbeat", agent_id=agent_id, detalle=detalle, conexion=conexion)
        agente = self.agente(agent_id)
        assert agente is not None
        return agente

    def cambiar_estado(self, agent_id: str, status: str, *, detalle: str = "") -> Agente:
        if status not in ESTADOS_AGENTE:
            raise ErrorEstado(f"estado de agente inválido: {status!r}")
        with self._escritura() as conexion:
            fila = conexion.execute("SELECT * FROM agentes WHERE agent_id = ?", (agent_id,)).fetchone()
            if fila is None:
                raise AgenteDesconocido(f"el agente {agent_id!r} no está registrado")
            instante = ahora()
            conexion.execute(
                "UPDATE agentes SET status = ?, last_activity_at = ?, heartbeat_at = ? WHERE agent_id = ?",
                (status, instante, instante, agent_id),
            )
            self.registrar_evento(
                "agent_status_changed",
                agent_id=agent_id,
                detalle=f"{fila['status']} -> {status}. {detalle}".strip(),
                conexion=conexion,
            )
        agente = self.agente(agent_id)
        assert agente is not None
        return agente

    def olvidar_agente(self, agent_id: str, *, detalle: str = "") -> bool:
        """Elimina el registro del agente (no toca ramas ni worktrees)."""
        with self._escritura() as conexion:
            cursor = conexion.execute("DELETE FROM agentes WHERE agent_id = ?", (agent_id,))
            existia = cursor.rowcount > 0
            if existia:
                self.registrar_evento(
                    "agent_unregistered", agent_id=agent_id, detalle=detalle, conexion=conexion
                )
        return existia

    # --------------------------------------------------------------------- leases

    @staticmethod
    def _lease(fila: sqlite3.Row) -> Lease:
        return Lease(**dict(fila))

    def lease(self, resource: str) -> Lease | None:
        with self._lectura() as conexion:
            fila = conexion.execute("SELECT * FROM leases WHERE resource = ?", (resource,)).fetchone()
        return self._lease(fila) if fila else None

    def leases(self, resource: str | None = None) -> list[Lease]:
        consulta = "SELECT * FROM leases"
        parametros: list[Any] = []
        if resource is not None:
            consulta += " WHERE resource = ?"
            parametros.append(resource)
        consulta += " ORDER BY resource ASC"
        with self._lectura() as conexion:
            return [self._lease(fila) for fila in conexion.execute(consulta, parametros)]

    def leases_de(self, agent_id: str) -> list[Lease]:
        with self._lectura() as conexion:
            filas = conexion.execute(
                "SELECT * FROM leases WHERE owner_agent_id = ? ORDER BY resource ASC", (agent_id,)
            ).fetchall()
        return [self._lease(fila) for fila in filas]

    def adquirir(
        self,
        resource: str,
        agent_id: str,
        *,
        scope: str = "",
        reason: str = "",
        ttl_minutos: int = TTL_LEASE_MINUTOS,
        force: bool = False,
    ) -> Lease:
        """Adquiere el lease de un recurso de forma atómica.

        - Idempotente para el mismo dueño: conserva ``acquired_at`` y renueva la expiración.
        - Un lease vencido se toma sin ``force`` (se registra como recuperación).
        - Un lease vigente de otro agente sólo se roba con ``force`` explícito.
        """
        if not resource.strip():
            raise ErrorEstado("el recurso no puede ser vacío")
        instante = ahora()
        expira = instante + ttl_minutos * 60
        # El conflicto se propaga fuera de la transacción: lanzarlo adentro dispara el
        # ROLLBACK del context manager y se perdería el propio evento de auditoría.
        conflicto: ConflictoLease | None = None
        detalle_conflicto = ""

        with self._escritura() as conexion:
            fila = conexion.execute("SELECT * FROM leases WHERE resource = ?", (resource,)).fetchone()
            evento = "lock_acquired"
            acquired_at = instante
            if fila is not None:
                actual = self._lease(fila)
                if actual.owner_agent_id == agent_id and not actual.vencido(momento=instante):
                    acquired_at = actual.acquired_at
                    evento = "lock_reacquired"
                elif actual.vencido(momento=instante):
                    evento = "lock_expired_takeover"
                elif force:
                    evento = "lock_stolen"
                else:
                    restantes = actual.segundos_restantes(momento=instante)
                    detalle_conflicto = f"dueño={actual.owner_agent_id} restan={restantes}s"
                    conflicto = ConflictoLease(
                        f"el recurso {resource!r} pertenece al agente {actual.owner_agent_id!r} "
                        f"(motivo: {actual.reason or 'sin motivo declarado'}); "
                        f"el lease vence en {formatear_duracion(restantes)}"
                    )

            if conflicto is None:
                conexion.execute(
                    """
                    INSERT INTO leases (resource, owner_agent_id, scope, status, acquired_at, heartbeat_at,
                                        lease_expires_at, reason, host, pid)
                    VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(resource) DO UPDATE SET
                        owner_agent_id = excluded.owner_agent_id,
                        scope = excluded.scope,
                        status = 'active',
                        acquired_at = excluded.acquired_at,
                        heartbeat_at = excluded.heartbeat_at,
                        lease_expires_at = excluded.lease_expires_at,
                        reason = excluded.reason,
                        host = excluded.host,
                        pid = excluded.pid
                    """,
                    (
                        resource,
                        agent_id,
                        scope,
                        acquired_at,
                        instante,
                        expira,
                        reason,
                        socket.gethostname(),
                        os.getpid(),
                    ),
                )
                self.registrar_evento(
                    evento,
                    agent_id=agent_id,
                    resource=resource,
                    detalle=f"ttl={ttl_minutos}min motivo={reason}",
                    conexion=conexion,
                )
                self._tocar_agente(conexion, agent_id)

        if conflicto is not None:
            self.registrar_evento(
                "lock_conflict", agent_id=agent_id, resource=resource, detalle=detalle_conflicto
            )
            raise conflicto

        lease = self.lease(resource)
        assert lease is not None
        return lease

    def renovar(
        self,
        resource: str,
        agent_id: str,
        *,
        ttl_minutos: int = TTL_LEASE_MINUTOS,
    ) -> Lease:
        """Extiende un lease vigente propio. No resucita un lease ya vencido."""
        with self._escritura() as conexion:
            fila = conexion.execute("SELECT * FROM leases WHERE resource = ?", (resource,)).fetchone()
            if fila is None:
                raise ConflictoLease(f"el recurso {resource!r} no tiene un lease activo renovable")
            actual = self._lease(fila)
            if actual.owner_agent_id != agent_id:
                raise ConflictoLease(
                    f"el recurso {resource!r} pertenece al agente {actual.owner_agent_id!r}; "
                    "no puede renovarlo otro agente"
                )
            if actual.vencido():
                raise ConflictoLease(
                    f"el lease de {resource!r} venció; readquirirlo con 'acquire' tras verificar "
                    "el estado real del recurso (un heartbeat no revive un lease vencido)"
                )
            instante = ahora()
            conexion.execute(
                "UPDATE leases SET heartbeat_at = ?, lease_expires_at = ? WHERE resource = ?",
                (instante, instante + ttl_minutos * 60, resource),
            )
            self.registrar_evento(
                "lock_renewed", agent_id=agent_id, resource=resource, detalle=f"ttl={ttl_minutos}min",
                conexion=conexion,
            )
            self._tocar_agente(conexion, agent_id)
        lease = self.lease(resource)
        assert lease is not None
        return lease

    def liberar(self, resource: str, agent_id: str, *, force: bool = False) -> bool:
        """Libera un lease. Devuelve ``False`` si no existía (idempotente)."""
        with self._escritura() as conexion:
            fila = conexion.execute("SELECT * FROM leases WHERE resource = ?", (resource,)).fetchone()
            if fila is None:
                return False
            actual = self._lease(fila)
            if actual.owner_agent_id != agent_id and not force and not actual.vencido():
                raise ConflictoLease(
                    f"el recurso {resource!r} pertenece al agente {actual.owner_agent_id!r}; "
                    "usar --force sólo si se verificó que esa sesión terminó"
                )
            conexion.execute("DELETE FROM leases WHERE resource = ?", (resource,))
            self.registrar_evento(
                "lock_released",
                agent_id=agent_id,
                resource=resource,
                detalle="forzado" if actual.owner_agent_id != agent_id else "",
                conexion=conexion,
            )
        return True

    def liberar_todos(self, agent_id: str) -> list[str]:
        """Libera todos los leases propios de un agente (cierre de sesión)."""
        liberados: list[str] = []
        for lease in self.leases_de(agent_id):
            if self.liberar(lease.resource, agent_id):
                liberados.append(lease.resource)
        return liberados

    def limpiar_vencidos(self, *, dry_run: bool = False) -> list[Lease]:
        """Elimina leases vencidos. No toca ramas, worktrees ni archivos."""
        vencidos = [lease for lease in self.leases() if lease.vencido()]
        if dry_run:
            return vencidos
        with self._escritura() as conexion:
            for lease in vencidos:
                conexion.execute("DELETE FROM leases WHERE resource = ?", (lease.resource,))
                self.registrar_evento(
                    "lock_expired_cleanup",
                    agent_id=lease.owner_agent_id,
                    resource=lease.resource,
                    detalle="lease vencido eliminado",
                    conexion=conexion,
                )
        return vencidos

    def marcar_stale(
        self, *, ttl_minutos: int = TTL_AGENTE_MINUTOS, dry_run: bool = False
    ) -> list[Agente]:
        """Marca como ``stale`` a los agentes sin heartbeat dentro del TTL.

        Marcar stale es una señal, no una acción destructiva: no borra ramas, no
        elimina worktrees y no descarta cambios.
        """
        candidatos = [
            agente
            for agente in self.agentes(estados=ESTADOS_VIVOS)
            if agente.inactivo(ttl_minutos=ttl_minutos)
        ]
        if dry_run:
            return candidatos
        for agente in candidatos:
            self.cambiar_estado(
                agente.agent_id,
                "stale",
                detalle=f"sin heartbeat por más de {ttl_minutos} min",
            )
            self.registrar_evento("stale_detected", agent_id=agente.agent_id)
        return candidatos

    def _tocar_agente(self, conexion: sqlite3.Connection, agent_id: str) -> None:
        """Actualiza heartbeat del agente si está registrado (no falla si no lo está)."""
        instante = ahora()
        conexion.execute(
            "UPDATE agentes SET heartbeat_at = ?, last_activity_at = ? WHERE agent_id = ?",
            (instante, instante, agent_id),
        )

    # ------------------------------------------------------------------- handoffs

    def crear_handoff(
        self,
        *,
        from_agent: str,
        to_agent: str,
        task: str = "",
        resource: str = "",
        next_action: str = "",
        blocked_on: str = "",
        branch: str = "",
        worktree_path: str = "",
        last_commit: str = "",
        archivos: list[str] | None = None,
        leases: list[str] | None = None,
    ) -> Handoff:
        """Registra un handoff explícito. No cambia el ownership por sí solo."""
        instante = ahora()
        with self._escritura() as conexion:
            cursor = conexion.execute(
                """
                INSERT INTO handoffs (from_agent, to_agent, resource, task, state, next_action,
                                      blocked_on, branch, worktree_path, last_commit, archivos,
                                      leases, created_at, accepted_at)
                VALUES (?, ?, ?, ?, 'pendiente', ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    from_agent,
                    to_agent,
                    resource,
                    task,
                    next_action,
                    blocked_on,
                    branch,
                    worktree_path,
                    last_commit,
                    json.dumps(archivos or [], ensure_ascii=False),
                    json.dumps(leases or [], ensure_ascii=False),
                    instante,
                ),
            )
            handoff_id = int(cursor.lastrowid or 0)
            self.registrar_evento(
                "handoff_created",
                agent_id=from_agent,
                resource=resource,
                detalle=f"destino={to_agent} rama={branch} siguiente={next_action}",
                conexion=conexion,
            )
        handoff = self.handoff(handoff_id)
        assert handoff is not None
        return handoff

    def handoff(self, handoff_id: int) -> Handoff | None:
        with self._lectura() as conexion:
            fila = conexion.execute("SELECT * FROM handoffs WHERE id = ?", (handoff_id,)).fetchone()
        return Handoff(**dict(fila)) if fila else None

    def handoffs(self, *, to_agent: str | None = None, pendientes: bool = False) -> list[Handoff]:
        consulta = "SELECT * FROM handoffs"
        condiciones: list[str] = []
        parametros: list[Any] = []
        if to_agent:
            condiciones.append("to_agent = ?")
            parametros.append(to_agent)
        if pendientes:
            condiciones.append("state = 'pendiente'")
        if condiciones:
            consulta += " WHERE " + " AND ".join(condiciones)
        consulta += " ORDER BY id DESC"
        with self._lectura() as conexion:
            return [Handoff(**dict(fila)) for fila in conexion.execute(consulta, parametros)]

    def aceptar_handoff(self, handoff_id: int, to_agent: str) -> Handoff:
        """El agente destino acepta el handoff y toma la propiedad de los leases transferidos."""
        with self._escritura() as conexion:
            fila = conexion.execute("SELECT * FROM handoffs WHERE id = ?", (handoff_id,)).fetchone()
            if fila is None:
                raise ErrorEstado(f"no existe el handoff {handoff_id}")
            if fila["to_agent"] != to_agent:
                raise ErrorEstado(
                    f"el handoff {handoff_id} está dirigido a {fila['to_agent']!r}, no a {to_agent!r}"
                )
            if fila["state"] == "aceptado":
                return Handoff(**dict(fila))
            conexion.execute(
                "UPDATE handoffs SET state = 'aceptado', accepted_at = ? WHERE id = ?",
                (ahora(), handoff_id),
            )
            self.registrar_evento(
                "handoff_accepted",
                agent_id=to_agent,
                resource=fila["resource"],
                detalle=f"origen={fila['from_agent']} handoff={handoff_id}",
                conexion=conexion,
            )
        handoff = self.handoff(handoff_id)
        assert handoff is not None
        return handoff


def formatear_duracion(segundos: int) -> str:
    """Formatea una duración en ``NNmSSs`` legible para mensajes de error accionables."""
    segundos = max(0, int(segundos))
    minutos, resto = divmod(segundos, 60)
    if minutos >= 60:
        horas, minutos = divmod(minutos, 60)
        return f"{horas:02d}h{minutos:02d}m{resto:02d}s"
    return f"{minutos:02d}m{resto:02d}s"


def formatear_instante(epoch: float | None) -> str:
    """Formatea un epoch UTC como hora local legible."""
    if not epoch:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch))
