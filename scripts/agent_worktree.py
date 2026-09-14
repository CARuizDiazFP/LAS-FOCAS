#!/usr/bin/env python3
# Nombre de archivo: agent_worktree.py
# Ubicación de archivo: scripts/agent_worktree.py
# Descripción: CLI de ciclo de vida de agentes con worktree y rama propios (start/list/status/sync/ready/integrate/handoff/finish/cleanup/doctor)

"""Un agente = una tarea = una rama = un Git worktree.

Aísla físicamente el trabajo concurrente: cada agente recibe su propio working tree,
su propio index y su propia rama efímera. Un ``git switch``, un ``git add`` o un
commit de un agente no tocan el directorio de ningún otro.

El checkout principal queda reservado como **checkout de control/integración**:
permanece en ``dev`` y se usa para crear/eliminar worktrees, actualizar ``dev``,
inspeccionar el conjunto y coordinar. No es el working tree habitual de nadie.

El estado compartido (agentes, leases, handoffs, eventos) vive en
``<git-common-dir>/las-focas-agents/agent_state.sqlite3``, visible desde todos los
linked worktrees y fuera del historial de Git.

Uso típico:
    python scripts/agent_worktree.py start --agent claude-api --type feat --task busqueda-camaras
    python scripts/agent_worktree.py list
    python scripts/agent_worktree.py sync --agent claude-api
    python scripts/agent_worktree.py ready --agent claude-api
    python scripts/agent_worktree.py integrate --agent claude-api
    python scripts/agent_worktree.py cleanup --agent claude-api
    python scripts/agent_worktree.py doctor

Códigos de salida: 0 correcto, 1 conflicto/estado inválido, 2 error de uso o entorno.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent) not in sys.path:  # pragma: no cover - inicialización
    sys.path.insert(0, str(SCRIPT_DIR.parent))

from scripts.agentes import gitops, rutas  # noqa: E402
from scripts.agentes.consola import configurar_logging, emitir, emitir_json  # noqa: E402
from scripts.agentes.estado import (  # noqa: E402
    TTL_AGENTE_MINUTOS,
    Agente,
    ConflictoLease,
    ErrorEstado,
    Registro,
    formatear_instante,
)

# Recursos reservados del ciclo de vida Git (ver docs/arquitectura_agentes_worktrees.md).
RECURSO_LIFECYCLE = "git:worktree-lifecycle"
RECURSO_INTEGRACION = "git:integrate-dev"

# El lease de lifecycle sólo cubre el `git worktree add/remove`; se libera enseguida.
TTL_LIFECYCLE_MINUTOS = 5
TTL_INTEGRACION_MINUTOS = 20

RAMA_INTEGRACION = "dev"
REMOTO = "origin"

# Archivos/directorios locales del checkout de control que el worktree necesita para
# operar (todos ignorados por Git). Se enlazan, nunca se copian.
ENLACES_ENTORNO = (".venv", ".env", ".env.dev", ".secrets")

# Rutas que NO se enlazan automáticamente pero que igual deben quedar excluidas: se
# enlazan a mano y bajo demanda (ver la skill `agent-worktree`). `node_modules` es
# mutable y compartirlo entre worktrees puede romper instalaciones cruzadas, así que
# no se enlaza solo; pero cuando se lo enlaza para verificar el frontend, el symlink
# no debe ensuciar `git status` (guardrail 13 de `dev-workflow`, 2026-09-11).
EXCLUSIONES_ADICIONALES = ("web/frontend/node_modules",)

logger = configurar_logging("agent_worktree")


class ErrorCLI(RuntimeError):
    """Error de uso o de estado que la CLI reporta de forma accionable."""


# --------------------------------------------------------------------- contexto


class Entorno:
    """Contexto resuelto de una invocación: rutas + registro de estado."""

    def __init__(self, cwd: Path | None = None) -> None:
        self.ctx = rutas.contexto(cwd)
        self.registro = Registro(self.ctx.db_path)

    @property
    def control(self) -> Path:
        return self.ctx.control_toplevel

    def ruta_worktree(self, agent_id: str, task: str) -> Path:
        return self.ctx.worktrees_dir / f"{agent_id}-{task}"

    def agente(self, agent_id: str) -> Agente:
        agente = self.registro.agente(agent_id)
        if agente is None:
            raise ErrorCLI(
                f"el agente {agent_id!r} no está registrado. "
                "Iniciarlo con: agent_worktree.py start --agent <id> --type <tipo> --task <slug>"
            )
        return agente


# ----------------------------------------------------------------------- start


def _resolver_base(entorno: Entorno, base_pedida: str | None, *, fetch: bool) -> tuple[str, str]:
    """Devuelve ``(ref_base, sha)`` sincronizando la referencia remota de forma segura.

    ``git fetch`` sólo actualiza refs de seguimiento remoto: no toca ramas locales, ni
    el working tree, ni el index de ningún agente.
    """
    control = entorno.control
    if fetch and gitops.existe_remoto(REMOTO, control):
        try:
            gitops.fetch(control, REMOTO)
        except gitops.ErrorGit as exc:
            logger.warning("no se pudo hacer fetch de %s (se sigue con la referencia local): %s", REMOTO, exc)

    candidatas = [base_pedida] if base_pedida else [f"{REMOTO}/{RAMA_INTEGRACION}", RAMA_INTEGRACION]
    for candidata in candidatas:
        if candidata and gitops.existe_ref(candidata, control):
            return candidata, gitops.sha(candidata, control)

    raise ErrorCLI(
        f"no se encontró una referencia base válida ({', '.join(c for c in candidatas if c)}). "
        f"Verificar que exista la rama {RAMA_INTEGRACION!r} local o remota."
    )


def _enlazar_entorno(entorno: Entorno, destino: Path) -> list[str]:
    """Enlaza el venv y los archivos de entorno del checkout de control.

    Se usan symlinks y no copias: el venv no se duplica (espacio y deriva de versiones)
    y los secretos no se replican en disco. Todas las rutas enlazadas están ignoradas
    por Git, así que el symlink nunca se versiona.
    """
    gitops.asegurar_exclusiones(
        entorno.ctx.git_common_dir, ENLACES_ENTORNO + EXCLUSIONES_ADICIONALES
    )
    enlazados: list[str] = []
    for nombre in ENLACES_ENTORNO:
        origen = entorno.control / nombre
        enlace = destino / nombre
        if not origen.exists() or enlace.exists() or enlace.is_symlink():
            continue
        try:
            enlace.symlink_to(origen, target_is_directory=origen.is_dir())
            enlazados.append(nombre)
        except OSError as exc:  # pragma: no cover - depende del SO/permisos
            logger.warning("no se pudo enlazar %s: %s", nombre, exc)
    return enlazados


def comando_start(entorno: Entorno, args: argparse.Namespace) -> dict[str, object]:
    agent_id = gitops.validar_slug(args.agent, campo="agent_id")
    task = gitops.validar_slug(args.task, campo="task")
    tipo = gitops.validar_tipo(args.type)
    rama = gitops.nombre_rama(tipo, agent_id, task)
    destino = entorno.ruta_worktree(agent_id, task)
    control = entorno.control

    existente = entorno.registro.agente(agent_id)
    if existente is not None and existente.status not in ("finished", "failed"):
        if existente.task_id != task or existente.branch != rama:
            raise ErrorCLI(
                f"el agente {agent_id!r} ya está registrado en la tarea {existente.task_id!r} "
                f"(rama {existente.branch}, estado {existente.status}). "
                "Cerrarla con 'finish' o usar otro --agent: un agent_id sostiene una sola tarea activa."
            )
        worktree = gitops.worktree_de(Path(existente.worktree_path), control)
        if worktree is not None and Path(existente.worktree_path).is_dir():
            # Idempotente: mismo agente, misma tarea, worktree válido.
            entorno.registro.heartbeat_agente(agent_id, detalle="start idempotente")
            return {
                "agente": agent_id,
                "rama": existente.branch,
                "worktree": existente.worktree_path,
                "base": f"{existente.base_ref}@{existente.base_sha[:12]}" if existente.base_sha else "-",
                "estado": existente.status,
                "idempotente": True,
            }

    rutas.verificar_escritura(entorno.ctx.worktrees_dir)
    base_ref, base_sha = _resolver_base(entorno, args.base, fetch=not args.no_fetch)

    # El lease de lifecycle serializa sólo la creación del worktree/rama, no la tarea.
    entorno.registro.adquirir(
        RECURSO_LIFECYCLE,
        agent_id,
        reason=f"crear worktree {destino.name}",
        ttl_minutos=TTL_LIFECYCLE_MINUTOS,
    )
    try:
        if destino.exists() and any(destino.iterdir()):
            registrado = gitops.worktree_de(destino, control)
            if registrado is None:
                raise ErrorCLI(
                    f"la ruta {destino} ya existe y no está vacía, pero no es un worktree de este "
                    "repositorio. Revisarla a mano: esta herramienta no borra contenido ajeno."
                )

        if gitops.existe_rama_local(rama, control):
            worktree = None
            for candidato in gitops.listar_worktrees(control):
                if candidato.branch == rama:
                    worktree = candidato
                    break
            if worktree is not None:
                raise ErrorCLI(
                    f"la rama {rama!r} ya está checkouteada en {worktree.path}. "
                    "Git no permite la misma rama en dos worktrees: usar otro --task o continuar allí."
                )
            # La rama existe sin worktree (p.ej. recuperación tras una limpieza parcial).
            gitops.adjuntar_worktree(destino, rama, control)
            logger.info("rama %s preexistente: se adjuntó un worktree nuevo sin recrearla", rama)
        else:
            gitops.crear_worktree(destino, rama, base_ref, control)
    finally:
        entorno.registro.liberar(RECURSO_LIFECYCLE, agent_id)

    enlazados = _enlazar_entorno(entorno, destino)
    entorno.registro.registrar_agente(
        agent_id,
        task_id=task,
        branch=rama,
        worktree_path=str(destino),
        base_ref=base_ref,
        base_sha=base_sha,
        status="active",
        notas=args.notas or "",
    )
    entorno.registro.registrar_evento(
        "worktree_created",
        agent_id=agent_id,
        detalle=f"ruta={destino} rama={rama} base={base_ref}@{base_sha[:12]} enlaces={','.join(enlazados) or '-'}",
    )
    return {
        "agente": agent_id,
        "rama": rama,
        "worktree": str(destino),
        "base": f"{base_ref}@{base_sha[:12]}",
        "estado": "active",
        "enlaces": enlazados,
        "idempotente": False,
    }


# ------------------------------------------------------------- listado y estado


def _fila_agente(entorno: Entorno, agente: Agente) -> dict[str, object]:
    ruta = Path(agente.worktree_path)
    existe = ruta.is_dir()
    limpio: bool | None = None
    rama_real = ""
    if existe:
        try:
            limpio = gitops.esta_limpio(ruta)
            rama_real = gitops.rama_actual(ruta)
        except gitops.ErrorGit:
            limpio = None
    return {
        "agent_id": agente.agent_id,
        "task_id": agente.task_id,
        "status": agente.status,
        "branch": agente.branch,
        "branch_real": rama_real,
        "worktree_path": agente.worktree_path,
        "worktree_existe": existe,
        "worktree_limpio": limpio,
        "started_at": formatear_instante(agente.started_at),
        "heartbeat_at": formatear_instante(agente.heartbeat_at),
        "inactivo": agente.inactivo(),
        "leases": [lease.resource for lease in entorno.registro.leases_de(agente.agent_id)],
    }


def comando_list(entorno: Entorno, args: argparse.Namespace) -> list[dict[str, object]]:
    agentes = entorno.registro.agentes()
    if args.activos:
        agentes = [a for a in agentes if a.status not in ("finished", "failed")]
    return [_fila_agente(entorno, agente) for agente in agentes]


def comando_status(entorno: Entorno, args: argparse.Namespace) -> dict[str, object]:
    if args.agent:
        agente = entorno.agente(args.agent)
        datos = _fila_agente(entorno, agente)
        datos["ultimo_commit"] = (
            gitops.ultimo_commit(Path(agente.worktree_path))
            if Path(agente.worktree_path).is_dir()
            else ""
        )
        datos["eventos"] = entorno.registro.eventos(limite=10, agent_id=agente.agent_id)
        return datos

    control = entorno.control
    return {
        "control_worktree": str(control),
        "control_rama": gitops.rama_actual(control),
        "control_limpio": gitops.esta_limpio(control),
        "git_common_dir": str(entorno.ctx.git_common_dir),
        "estado_db": str(entorno.ctx.db_path),
        "worktrees_dir": str(entorno.ctx.worktrees_dir),
        "agentes": [_fila_agente(entorno, agente) for agente in entorno.registro.agentes()],
        "leases": [
            {
                "resource": lease.resource,
                "owner": lease.owner_agent_id,
                "vencido": lease.vencido(),
                "expira": formatear_instante(lease.lease_expires_at),
            }
            for lease in entorno.registro.leases()
        ],
        "handoffs_pendientes": [
            {"id": h.id, "de": h.from_agent, "para": h.to_agent, "tarea": h.task}
            for h in entorno.registro.handoffs(pendientes=True)
        ],
    }


# ------------------------------------------------------------ trabajo y sincro


def comando_heartbeat(entorno: Entorno, args: argparse.Namespace) -> dict[str, object]:
    agente = entorno.registro.heartbeat_agente(args.agent, detalle=args.detalle or "")
    for lease in entorno.registro.leases_de(args.agent):
        if not lease.vencido():
            entorno.registro.renovar(lease.resource, args.agent)
    return {"agent_id": agente.agent_id, "status": agente.status, "heartbeat_at": formatear_instante(agente.heartbeat_at)}


def comando_sync(entorno: Entorno, args: argparse.Namespace) -> dict[str, object]:
    """Incorpora ``origin/dev`` a la rama del agente dentro de SU worktree."""
    agente = entorno.agente(args.agent)
    ruta = Path(agente.worktree_path)
    if not ruta.is_dir():
        raise ErrorCLI(f"el worktree {ruta} no existe. Ejecutar 'doctor' para diagnosticar.")

    if not gitops.esta_limpio(ruta):
        raise ErrorCLI(
            f"el worktree {ruta} tiene cambios sin confirmar. Commitearlos antes de sincronizar: "
            "esta herramienta nunca hace stash, reset ni checkout destructivo."
        )

    if gitops.existe_remoto(REMOTO, ruta):
        gitops.fetch(ruta, REMOTO)
    referencia = (
        f"{REMOTO}/{RAMA_INTEGRACION}"
        if gitops.existe_ref(f"{REMOTO}/{RAMA_INTEGRACION}", ruta)
        else RAMA_INTEGRACION
    )
    resultado = gitops.merge(referencia, ruta)
    conflictos = gitops.archivos_en_conflicto(ruta)
    if resultado.returncode != 0:
        entorno.registro.cambiar_estado(
            args.agent, "blocked", detalle=f"conflicto al mergear {referencia}"
        )
        return {
            "agent_id": args.agent,
            "referencia": referencia,
            "resultado": "conflicto",
            "conflictos": conflictos,
            "detalle": (resultado.stdout + resultado.stderr).strip(),
        }
    entorno.registro.heartbeat_agente(args.agent, detalle=f"sync con {referencia}")
    return {
        "agent_id": args.agent,
        "referencia": referencia,
        "resultado": "ok",
        "detalle": resultado.stdout.strip(),
    }


def comando_ready(entorno: Entorno, args: argparse.Namespace) -> dict[str, object]:
    agente = entorno.agente(args.agent)
    ruta = Path(agente.worktree_path)
    if not ruta.is_dir():
        raise ErrorCLI(f"el worktree {ruta} no existe. Ejecutar 'doctor'.")
    if not gitops.esta_limpio(ruta):
        raise ErrorCLI(
            f"el worktree {ruta} no está limpio; confirmar o descartar los cambios antes de "
            "declararlo listo para integrar."
        )
    entorno.registro.cambiar_estado(args.agent, "ready_to_merge", detalle="validaciones locales OK")
    return {"agent_id": args.agent, "status": "ready_to_merge", "rama": agente.branch}


# ------------------------------------------------------------------ integración


def comando_integrate(entorno: Entorno, args: argparse.Namespace) -> dict[str, object]:
    """Integra la rama del agente a ``dev`` serializando sólo esa ventana."""
    agente = entorno.agente(args.agent)
    ruta = Path(agente.worktree_path)
    if not ruta.is_dir():
        raise ErrorCLI(f"el worktree {ruta} no existe. Ejecutar 'doctor'.")
    if not gitops.esta_limpio(ruta):
        raise ErrorCLI(f"el worktree {ruta} no está limpio: no se integra trabajo sin confirmar.")
    if not gitops.es_rama_efimera(agente.branch):
        raise ErrorCLI(
            f"la rama {agente.branch!r} no es una rama efímera válida; el flujo de integración "
            "no opera sobre dev/main."
        )

    if gitops.existe_remoto(REMOTO, ruta):
        gitops.fetch(ruta, REMOTO)
    referencia_dev = (
        f"{REMOTO}/{RAMA_INTEGRACION}"
        if gitops.existe_ref(f"{REMOTO}/{RAMA_INTEGRACION}", ruta)
        else RAMA_INTEGRACION
    )
    if not gitops.es_ancestro(referencia_dev, "HEAD", ruta):
        raise ErrorCLI(
            f"{referencia_dev} avanzó y no es ancestro de {agente.branch}. "
            f"Ejecutar primero: agent_worktree.py sync --agent {args.agent}"
        )

    # Ventana serializada: sólo un agente modifica dev a la vez.
    entorno.registro.adquirir(
        RECURSO_INTEGRACION,
        args.agent,
        reason=f"integrar {agente.branch} a {RAMA_INTEGRACION}",
        ttl_minutos=TTL_INTEGRACION_MINUTOS,
    )
    entorno.registro.cambiar_estado(args.agent, "integrating", detalle=f"integrando {agente.branch}")
    entorno.registro.registrar_evento(
        "integration_started", agent_id=args.agent, resource=RECURSO_INTEGRACION,
        detalle=f"rama={agente.branch}",
    )
    try:
        if not gitops.existe_remoto(REMOTO, ruta):
            raise ErrorCLI(
                f"no existe el remoto {REMOTO!r}; la integración requiere un remoto configurado."
            )
        empuje_rama = gitops.push(f"HEAD:refs/heads/{agente.branch}", ruta, REMOTO)
        if empuje_rama.returncode != 0:
            raise ErrorCLI(
                f"falló el push de la rama efímera: {(empuje_rama.stderr or empuje_rama.stdout).strip()}"
            )
        empuje_dev = gitops.push(f"HEAD:refs/heads/{RAMA_INTEGRACION}", ruta, REMOTO)
        if empuje_dev.returncode != 0:
            entorno.registro.cambiar_estado(
                args.agent, "blocked", detalle="push a dev rechazado (no fast-forward)"
            )
            raise ErrorCLI(
                f"{RAMA_INTEGRACION} avanzó durante la integración y el push fue rechazado. "
                f"Ejecutar 'sync --agent {args.agent}' y reintentar. "
                f"Detalle: {(empuje_dev.stderr or empuje_dev.stdout).strip()}"
            )

        sha_integrado = gitops.sha("HEAD", ruta)
        control_actualizado = _actualizar_control(entorno)
        entorno.registro.cambiar_estado(args.agent, "finished", detalle=f"integrado {sha_integrado[:12]}")
        entorno.registro.registrar_evento(
            "integration_completed",
            agent_id=args.agent,
            resource=RECURSO_INTEGRACION,
            detalle=f"rama={agente.branch} sha={sha_integrado[:12]}",
        )
        return {
            "agent_id": args.agent,
            "rama": agente.branch,
            "integrado_en": RAMA_INTEGRACION,
            "sha": sha_integrado,
            "control_actualizado": control_actualizado,
            "status": "finished",
        }
    finally:
        entorno.registro.liberar(RECURSO_INTEGRACION, args.agent)


def _actualizar_control(entorno: Entorno) -> str:
    """Deja el checkout de control al día con ``dev`` sin arriesgar trabajo local."""
    control = entorno.control
    try:
        if not gitops.esta_limpio(control):
            return "omitido: el checkout de control tiene cambios sin confirmar"
        if gitops.rama_actual(control) != RAMA_INTEGRACION:
            return f"omitido: el control no está en {RAMA_INTEGRACION}"
        if gitops.existe_remoto(REMOTO, control):
            gitops.fetch(control, REMOTO)
        resultado = gitops.ejecutar(
            ["merge", "--ff-only", f"{REMOTO}/{RAMA_INTEGRACION}"], control, check=False
        )
        if resultado.returncode != 0:
            return f"omitido: merge --ff-only rechazado ({resultado.stderr.strip()})"
        return f"actualizado a {gitops.sha('HEAD', control)[:12]}"
    except gitops.ErrorGit as exc:  # pragma: no cover - defensivo
        return f"omitido: {exc}"


# -------------------------------------------------------------------- handoffs


def comando_handoff(entorno: Entorno, args: argparse.Namespace) -> dict[str, object]:
    origen = entorno.agente(getattr(args, "from"))
    ruta = Path(origen.worktree_path)
    archivos = gitops.archivos_modificados(ruta) if ruta.is_dir() else []
    ultimo = gitops.ultimo_commit(ruta) if ruta.is_dir() else ""
    leases = [lease.resource for lease in entorno.registro.leases_de(origen.agent_id)]

    handoff = entorno.registro.crear_handoff(
        from_agent=origen.agent_id,
        to_agent=args.to,
        task=origen.task_id,
        resource=args.resource or "",
        next_action=args.next_action or args.reason or "",
        blocked_on=args.blocked_on or "",
        branch=origen.branch,
        worktree_path=origen.worktree_path,
        last_commit=ultimo,
        archivos=archivos,
        leases=leases,
    )
    entorno.registro.cambiar_estado(
        origen.agent_id, "handoff", detalle=f"handoff #{handoff.id} hacia {args.to}"
    )
    return {
        "handoff_id": handoff.id,
        "de": handoff.from_agent,
        "para": handoff.to_agent,
        "rama": handoff.branch,
        "worktree": handoff.worktree_path,
        "ultimo_commit": handoff.last_commit,
        "archivos_modificados": archivos,
        "leases": leases,
        "siguiente_accion": handoff.next_action,
        "bloqueado_por": handoff.blocked_on,
        "estado": handoff.state,
    }


def comando_accept_handoff(entorno: Entorno, args: argparse.Namespace) -> dict[str, object]:
    """El agente destino acepta el handoff y toma rama, worktree y leases."""
    pendientes = entorno.registro.handoffs(to_agent=args.agent, pendientes=True)
    if args.id is not None:
        elegido = next((h for h in pendientes if h.id == args.id), None)
        if elegido is None:
            raise ErrorCLI(f"no hay un handoff pendiente #{args.id} dirigido a {args.agent!r}")
    else:
        if not pendientes:
            raise ErrorCLI(f"no hay handoffs pendientes para {args.agent!r}")
        elegido = pendientes[0]

    handoff = entorno.registro.aceptar_handoff(elegido.id, args.agent)
    origen = entorno.registro.agente(handoff.from_agent)
    # El ownership se transfiere explícitamente: el agente origen deja de ser dueño.
    if origen is not None:
        entorno.registro.olvidar_agente(
            origen.agent_id, detalle=f"ownership transferido a {args.agent} vía handoff #{handoff.id}"
        )
    entorno.registro.registrar_agente(
        args.agent,
        task_id=handoff.task,
        branch=handoff.branch,
        worktree_path=handoff.worktree_path,
        status="active",
        notas=f"continúa handoff #{handoff.id}: {handoff.next_action}",
    )
    for recurso in _lista_json(handoff.leases):
        try:
            entorno.registro.adquirir(
                recurso, args.agent, reason=f"handoff #{handoff.id}", force=True
            )
        except ErrorEstado as exc:  # pragma: no cover - defensivo
            logger.warning("no se pudo transferir el lease %s: %s", recurso, exc)
    return {
        "handoff_id": handoff.id,
        "agent_id": args.agent,
        "rama": handoff.branch,
        "worktree": handoff.worktree_path,
        "siguiente_accion": handoff.next_action,
        "leases_transferidos": _lista_json(handoff.leases),
    }


def _lista_json(crudo: str) -> list[str]:
    try:
        valor = json.loads(crudo or "[]")
    except json.JSONDecodeError:  # pragma: no cover - defensivo
        return []
    return [str(item) for item in valor] if isinstance(valor, list) else []


# --------------------------------------------------------------- cierre/limpieza


def comando_finish(entorno: Entorno, args: argparse.Namespace) -> dict[str, object]:
    agente = entorno.agente(args.agent)
    liberados = entorno.registro.liberar_todos(args.agent)
    entorno.registro.cambiar_estado(args.agent, "finished", detalle=args.detalle or "")
    resultado: dict[str, object] = {
        "agent_id": args.agent,
        "status": "finished",
        "leases_liberados": liberados,
        "rama": agente.branch,
        "worktree": agente.worktree_path,
        "worktree_removido": False,
    }
    if args.cleanup:
        resultado.update(_limpiar(entorno, agente, borrar_rama=args.borrar_rama))
    return resultado


def comando_cleanup(entorno: Entorno, args: argparse.Namespace) -> dict[str, object]:
    if args.prune:
        salida = gitops.prune_worktrees(entorno.control)
        return {"prune": salida or "sin worktrees huérfanos"}
    agente = entorno.agente(args.agent)
    if agente.status not in ("finished", "failed"):
        raise ErrorCLI(
            f"el agente {args.agent!r} está en estado {agente.status!r}. "
            "Cerrarlo primero con 'finish' (o integrar con 'integrate'): no se elimina el "
            "worktree de un agente que puede seguir trabajando."
        )
    return {"agent_id": args.agent, **_limpiar(entorno, agente, borrar_rama=args.borrar_rama)}


def _limpiar(entorno: Entorno, agente: Agente, *, borrar_rama: bool) -> dict[str, object]:
    """Elimina el worktree sólo si está limpio. Nunca fuerza ni descarta trabajo."""
    ruta = Path(agente.worktree_path)
    control = entorno.control
    detalle: dict[str, object] = {"worktree_removido": False, "rama_borrada": False}

    if not ruta.is_dir():
        gitops.prune_worktrees(control)
        detalle["worktree_removido"] = True
        detalle["nota"] = "el directorio ya no existía; se hizo prune de la metadata"
        return detalle

    if not gitops.esta_limpio(ruta):
        detalle["nota"] = (
            f"el worktree {ruta} tiene cambios sin confirmar: NO se elimina. "
            "Confirmar o descartar manualmente y reintentar."
        )
        return detalle

    entorno.registro.adquirir(
        RECURSO_LIFECYCLE,
        agente.agent_id,
        reason=f"remover worktree {ruta.name}",
        ttl_minutos=TTL_LIFECYCLE_MINUTOS,
    )
    try:
        gitops.remover_worktree(ruta, control)
        detalle["worktree_removido"] = True
        entorno.registro.registrar_evento(
            "worktree_removed", agent_id=agente.agent_id, detalle=f"ruta={ruta}"
        )
        if borrar_rama:
            try:
                gitops.borrar_rama(agente.branch, control)
                detalle["rama_borrada"] = True
            except gitops.ErrorGit as exc:
                detalle["nota"] = (
                    f"worktree removido; la rama {agente.branch} NO se borró porque git la "
                    f"considera no integrada: {exc}"
                )
    finally:
        entorno.registro.liberar(RECURSO_LIFECYCLE, agente.agent_id)
    return detalle


# ----------------------------------------------------------------------- doctor


def comando_doctor(entorno: Entorno, args: argparse.Namespace) -> dict[str, object]:
    """Detecta inconsistencias entre registro, Git y disco. No corrige nada."""
    control = entorno.control
    hallazgos: list[dict[str, str]] = []
    worktrees = {wt.path: wt for wt in gitops.listar_worktrees(control)}
    registrados: set[Path] = set()

    for agente in entorno.registro.agentes():
        ruta = Path(agente.worktree_path)
        registrados.add(ruta)
        if agente.status in ("finished", "failed"):
            if ruta.is_dir():
                hallazgos.append(
                    {
                        "nivel": "info",
                        "agente": agente.agent_id,
                        "detalle": f"agente {agente.status} con worktree aún presente en {ruta}",
                        "accion": f"agent_worktree.py cleanup --agent {agente.agent_id}",
                    }
                )
            continue
        if not ruta.is_dir():
            hallazgos.append(
                {
                    "nivel": "alerta",
                    "agente": agente.agent_id,
                    "detalle": f"registro activo sin worktree en disco ({ruta})",
                    "accion": "verificar si la rama conserva commits y re-crear con 'start' o cerrar con 'finish'",
                }
            )
            continue
        worktree = worktrees.get(ruta)
        if worktree is None:
            hallazgos.append(
                {
                    "nivel": "alerta",
                    "agente": agente.agent_id,
                    "detalle": f"{ruta} existe pero Git no la reconoce como worktree",
                    "accion": "revisar manualmente; puede requerir 'git worktree prune' o re-crear",
                }
            )
            continue
        if worktree.branch and worktree.branch != agente.branch:
            hallazgos.append(
                {
                    "nivel": "alerta",
                    "agente": agente.agent_id,
                    "detalle": f"el worktree está en {worktree.branch!r} y el registro dice {agente.branch!r}",
                    "accion": "alinear la rama o actualizar el registro con 'start'",
                }
            )
        if worktree.locked:
            hallazgos.append(
                {
                    "nivel": "alerta",
                    "agente": agente.agent_id,
                    "detalle": f"worktree bloqueado por Git ({ruta})",
                    "accion": "git worktree unlock <ruta> tras verificar que nadie lo usa",
                }
            )
        if not gitops.existe_rama_local(agente.branch, control):
            hallazgos.append(
                {
                    "nivel": "alerta",
                    "agente": agente.agent_id,
                    "detalle": f"la rama {agente.branch} ya no existe localmente",
                    "accion": "no borrar nada: recuperar la rama desde el reflog o el remoto",
                }
            )
        if not gitops.esta_limpio(ruta):
            hallazgos.append(
                {
                    "nivel": "info",
                    "agente": agente.agent_id,
                    "detalle": f"worktree con cambios sin confirmar ({len(gitops.archivos_modificados(ruta))} rutas)",
                    "accion": "commitear antes de sync/integrate; la limpieza automática lo respeta",
                }
            )
        if agente.inactivo(ttl_minutos=args.agent_ttl_minutes):
            hallazgos.append(
                {
                    "nivel": "alerta",
                    "agente": agente.agent_id,
                    "detalle": f"sin heartbeat desde {formatear_instante(agente.heartbeat_at)}",
                    "accion": "marcar stale con 'agent_lock.py stale-cleanup'; NO borra rama ni worktree",
                }
            )
        if agente.status == "integrating":
            lease = entorno.registro.lease(RECURSO_INTEGRACION)
            if lease is None or lease.owner_agent_id != agente.agent_id:
                hallazgos.append(
                    {
                        "nivel": "alerta",
                        "agente": agente.agent_id,
                        "detalle": "quedó en 'integrating' sin sostener git:integrate-dev (integración interrumpida)",
                        "accion": "verificar si dev recibió el push y reintentar 'integrate'",
                    }
                )

    for ruta, worktree in worktrees.items():
        if ruta == control or ruta in registrados:
            continue
        if entorno.ctx.worktrees_dir in ruta.parents:
            hallazgos.append(
                {
                    "nivel": "alerta",
                    "agente": "-",
                    "detalle": f"worktree sin agente registrado: {ruta} (rama {worktree.branch or 'detached'})",
                    "accion": "registrar con 'start' usando el mismo agent/task, o retirarlo si quedó huérfano",
                }
            )

    for lease in entorno.registro.leases():
        if lease.vencido():
            hallazgos.append(
                {
                    "nivel": "info",
                    "agente": lease.owner_agent_id,
                    "detalle": f"lease vencido sobre {lease.resource}",
                    "accion": "agent_lock.py stale-cleanup",
                }
            )

    if not gitops.esta_limpio(control):
        hallazgos.append(
            {
                "nivel": "alerta",
                "agente": "-",
                "detalle": f"el checkout de control ({control}) tiene cambios sin confirmar",
                "accion": "el control se reserva para integración: mover el trabajo a un worktree de agente",
            }
        )
    rama_control = gitops.rama_actual(control)
    if rama_control != RAMA_INTEGRACION:
        hallazgos.append(
            {
                "nivel": "info",
                "agente": "-",
                "detalle": f"el checkout de control está en {rama_control or 'HEAD detached'}, no en {RAMA_INTEGRACION}",
                "accion": f"volver a {RAMA_INTEGRACION} cuando termine el trabajo en curso",
            }
        )

    if args.prune:
        gitops.prune_worktrees(control)

    return {
        "control": str(control),
        "git_common_dir": str(entorno.ctx.git_common_dir),
        "estado_db": str(entorno.ctx.db_path),
        "worktrees_dir": str(entorno.ctx.worktrees_dir),
        "hallazgos": hallazgos,
        "ok": not any(h["nivel"] == "alerta" for h in hallazgos),
    }


# -------------------------------------------------------------------------- CLI


def _parser_comun() -> argparse.ArgumentParser:
    """Flags globales aceptados tanto antes como después del subcomando.

    ``SUPPRESS`` evita que el subparser pise con ``False`` un flag ya activado en el
    parser padre: el atributo sólo existe si el usuario lo escribió.
    """
    comun = argparse.ArgumentParser(add_help=False)
    comun.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Salida en JSON")
    comun.add_argument(
        "--verbose", action="store_true", default=argparse.SUPPRESS, help="Diagnóstico detallado en stderr"
    )
    return comun


def construir_parser() -> argparse.ArgumentParser:
    comun = _parser_comun()
    parser = argparse.ArgumentParser(
        description="Ciclo de vida de agentes con worktree y rama propios (LAS-FOCAS).",
        parents=[comun],
    )
    sub = parser.add_subparsers(dest="comando", required=True)
    sub_kwargs = {"parents": [comun]}

    inicio = sub.add_parser("start", help="Crear rama efímera y worktree propios para un agente", **sub_kwargs)
    inicio.add_argument("--agent", required=True, help="Identificador único del agente (slug)")
    inicio.add_argument("--type", default="feat", help="Tipo de rama: feat|fix|docs|chore|refactor|test")
    inicio.add_argument("--task", required=True, help="Slug de la tarea (kebab-case)")
    inicio.add_argument("--base", default=None, help="Referencia base (por defecto origin/dev)")
    inicio.add_argument("--no-fetch", action="store_true", help="No sincronizar la base con el remoto")
    inicio.add_argument("--notas", default="", help="Nota libre para el registro")

    listar = sub.add_parser("list", help="Listar agentes registrados", **sub_kwargs)
    listar.add_argument("--activos", action="store_true", help="Sólo agentes no finalizados")

    estado_cmd = sub.add_parser("status", help="Estado global o de un agente", **sub_kwargs)
    estado_cmd.add_argument("--agent", default=None)

    latido = sub.add_parser("heartbeat", help="Registrar actividad del agente y renovar sus leases", **sub_kwargs)
    latido.add_argument("--agent", required=True)
    latido.add_argument("--detalle", default="")

    sincro = sub.add_parser("sync", help="Incorporar dev a la rama del agente dentro de su worktree", **sub_kwargs)
    sincro.add_argument("--agent", required=True)

    listo = sub.add_parser("ready", help="Marcar al agente como listo para integrar", **sub_kwargs)
    listo.add_argument("--agent", required=True)

    integrar = sub.add_parser("integrate", help="Integrar la rama del agente a dev (ventana serializada)", **sub_kwargs)
    integrar.add_argument("--agent", required=True)

    traspaso = sub.add_parser("handoff", help="Traspasar la tarea a otro agente conservando contexto", **sub_kwargs)
    traspaso.add_argument("--from", required=True, dest="from")
    traspaso.add_argument("--to", required=True)
    traspaso.add_argument("--reason", default="", help="Motivo del traspaso")
    traspaso.add_argument("--next-action", default="", help="Siguiente acción concreta")
    traspaso.add_argument("--blocked-on", default="", help="Bloqueo conocido")
    traspaso.add_argument("--resource", default="", help="Recurso asociado, si corresponde")

    aceptar = sub.add_parser("accept-handoff", help="Aceptar un handoff dirigido a este agente", **sub_kwargs)
    aceptar.add_argument("--agent", required=True)
    aceptar.add_argument("--id", type=int, default=None)

    terminar = sub.add_parser("finish", help="Cerrar el agente y liberar sus leases", **sub_kwargs)
    terminar.add_argument("--agent", required=True)
    terminar.add_argument("--detalle", default="")
    terminar.add_argument("--cleanup", action="store_true", help="Además, remover el worktree si está limpio")
    terminar.add_argument("--borrar-rama", action="store_true", help="Borrar la rama local con 'git branch -d'")

    limpieza = sub.add_parser("cleanup", help="Remover el worktree de un agente finalizado", **sub_kwargs)
    limpieza.add_argument("--agent", default=None)
    limpieza.add_argument("--borrar-rama", action="store_true")
    limpieza.add_argument("--prune", action="store_true", help="Sólo 'git worktree prune' (metadata huérfana)")

    medico = sub.add_parser("doctor", help="Diagnóstico de inconsistencias (no corrige nada)", **sub_kwargs)
    medico.add_argument("--agent-ttl-minutes", type=int, default=TTL_AGENTE_MINUTOS)
    medico.add_argument("--prune", action="store_true", help="Ejecutar 'git worktree prune' (seguro)")

    return parser


def _imprimir(comando: str, resultado: object) -> None:
    """Salida legible por humano de cada comando (el modo --json imprime la estructura)."""
    if comando == "start" and isinstance(resultado, dict):
        emitir(f"Agente:   {resultado['agente']}")
        emitir(f"Rama:     {resultado['rama']}")
        emitir(f"Worktree: {resultado['worktree']}")
        emitir(f"Base:     {resultado['base']}")
        emitir(f"Estado:   {resultado['estado']}")
        if resultado.get("idempotente"):
            emitir("Nota:     el agente ya existía con esta tarea; no se recreó nada.")
        elif resultado.get("enlaces"):
            emitir(f"Enlaces:  {', '.join(resultado['enlaces'])} (del checkout de control)")
        emitir("")
        emitir(f"Trabajar dentro de: cd {resultado['worktree']}")
        return

    if comando == "list" and isinstance(resultado, list):
        if not resultado:
            emitir("Sin agentes registrados")
            return
        emitir(f"{'AGENTE':<20} {'ESTADO':<14} {'RAMA':<44} {'WT':<4} LATIDO")
        for fila in resultado:
            marca = "ok" if fila["worktree_existe"] else "NO"
            emitir(
                f"{fila['agent_id']:<20} {fila['status']:<14} {fila['branch']:<44} {marca:<4} {fila['heartbeat_at']}"
            )
        return

    if comando == "doctor" and isinstance(resultado, dict):
        emitir(f"Control:        {resultado['control']}")
        emitir(f"git-common-dir: {resultado['git_common_dir']}")
        emitir(f"Estado:         {resultado['estado_db']}")
        emitir(f"Worktrees:      {resultado['worktrees_dir']}")
        hallazgos = resultado["hallazgos"]
        if not hallazgos:
            emitir("Sin inconsistencias detectadas.")
            return
        emitir("")
        for hallazgo in hallazgos:  # type: ignore[union-attr]
            emitir(f"[{hallazgo['nivel']}] {hallazgo['agente']}: {hallazgo['detalle']}")
            emitir(f"         → {hallazgo['accion']}")
        return

    if isinstance(resultado, dict):
        for clave, valor in resultado.items():
            if isinstance(valor, (list, dict)):
                emitir(f"{clave}: {valor if valor else '-'}")
            else:
                emitir(f"{clave}: {valor}")
        return

    emitir_json(resultado)


COMANDOS = {
    "start": comando_start,
    "list": comando_list,
    "status": comando_status,
    "heartbeat": comando_heartbeat,
    "sync": comando_sync,
    "ready": comando_ready,
    "integrate": comando_integrate,
    "handoff": comando_handoff,
    "accept-handoff": comando_accept_handoff,
    "finish": comando_finish,
    "cleanup": comando_cleanup,
    "doctor": comando_doctor,
}


def main(argv: list[str] | None = None) -> int:
    parser = construir_parser()
    args = parser.parse_args(argv)
    usar_json = getattr(args, "json", False)
    configurar_logging("agent_worktree", verboso=getattr(args, "verbose", False))

    if args.comando == "cleanup" and not args.prune and not args.agent:
        parser.error("cleanup requiere --agent o --prune")

    try:
        entorno = Entorno()
    except rutas.ErrorRepositorio as exc:
        logger.error("no se pudo resolver el repositorio: %s", exc)
        return 2

    try:
        resultado = COMANDOS[args.comando](entorno, args)
    except ConflictoLease as exc:
        logger.error("%s", exc)
        return 1
    except (ErrorCLI, ErrorEstado) as exc:
        logger.error("%s", exc)
        return 1
    except rutas.ErrorRepositorio as exc:
        logger.error("%s", exc)
        return 2
    except gitops.ErrorGit as exc:
        logger.error("%s", exc)
        return 2

    if usar_json:
        emitir_json(resultado)
    else:
        _imprimir(args.comando, resultado)
    return 0


if __name__ == "__main__":  # pragma: no cover - punto de entrada
    raise SystemExit(main())
