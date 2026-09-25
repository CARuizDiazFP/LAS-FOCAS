#!/usr/bin/env python3
# Nombre de archivo: agent_lock.py
# Ubicación de archivo: scripts/agent_lock.py
# Descripción: CLI de leases por recurso compartido entre agentes concurrentes (acquire/heartbeat/release/status/list/stale-cleanup)

"""Leases lógicos por recurso para agentes concurrentes de LAS-FOCAS.

El aislamiento físico del trabajo (working tree, index, rama) lo resuelve
``scripts/agent_worktree.py`` dándole a cada agente su propio Git worktree. Este
script resuelve el problema complementario: **los recursos realmente compartidos**,
que ningún worktree puede aislar.

No existe un lock global del repositorio durante el desarrollo normal. Dos agentes
editando ``api/foo.py`` y ``web/bar.vue`` en sus worktrees no necesitan ningún lease.
Los leases se reservan para recursos compartidos o peligrosos, por ejemplo:

    skill:docker-rebuild        agent:security          docs:AGENTS.md
    governance:claude           db:migrations           env:python-dependencies
    env:docker-compose          git:worktree-lifecycle  git:integrate-dev

Uso:
    python scripts/agent_lock.py acquire "db:migrations" --agent claude-db --reason "migración de inventario"
    python scripts/agent_lock.py heartbeat "db:migrations" --agent claude-db
    python scripts/agent_lock.py status "db:migrations"
    python scripts/agent_lock.py release "db:migrations" --agent claude-db
    python scripts/agent_lock.py list
    python scripts/agent_lock.py stale-cleanup --dry-run

Códigos de salida: 0 correcto, 1 conflicto de lease, 2 error de uso o de entorno.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent) not in sys.path:  # pragma: no cover - inicialización
    sys.path.insert(0, str(SCRIPT_DIR.parent))

from scripts.agentes import rutas  # noqa: E402
from scripts.agentes.consola import configurar_logging, emitir, emitir_json  # noqa: E402
from scripts.agentes.estado import (  # noqa: E402
    TTL_AGENTE_MINUTOS,
    TTL_LEASE_MINUTOS,
    ConflictoLease,
    ErrorEstado,
    Lease,
    Registro,
    formatear_duracion,
    formatear_instante,
)

# Recursos de referencia. La lista es orientativa: el recurso es un identificador
# lógico libre, pero se recomienda el formato "<clase>:<nombre>" para que el estado
# sea legible por cualquier agente.
RECURSOS_CONOCIDOS = (
    "skill:<nombre>",
    "agent:<nombre>",
    "docs:AGENTS.md",
    "governance:claude",
    "db:migrations",
    "env:python-dependencies",
    "env:docker-compose",
    "git:worktree-lifecycle",
    "git:integrate-dev",
)

logger = configurar_logging("agent_lock")


def _registro(cwd: Path | None = None) -> Registro:
    contexto = rutas.contexto(cwd)
    return Registro(contexto.db_path)


def _describir(lease: Lease) -> str:
    estado = "vencido" if lease.vencido() else f"vence en {formatear_duracion(lease.segundos_restantes())}"
    return (
        f"[{estado}] recurso={lease.resource} agente={lease.owner_agent_id} "
        f"scope={lease.scope or '-'} motivo={lease.reason or '-'} "
        f"expira={formatear_instante(lease.lease_expires_at)} host={lease.host} pid={lease.pid}"
    )


def _dict(lease: Lease) -> dict[str, object]:
    return {
        "resource": lease.resource,
        "owner_agent_id": lease.owner_agent_id,
        "scope": lease.scope,
        "status": "expired" if lease.vencido() else "active",
        "acquired_at": formatear_instante(lease.acquired_at),
        "heartbeat_at": formatear_instante(lease.heartbeat_at),
        "lease_expires_at": formatear_instante(lease.lease_expires_at),
        "segundos_restantes": lease.segundos_restantes(),
        "reason": lease.reason,
        "host": lease.host,
        "pid": lease.pid,
    }


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
        description="Leases por recurso compartido entre agentes concurrentes de LAS-FOCAS.",
        epilog="Recursos sugeridos: " + ", ".join(RECURSOS_CONOCIDOS),
        parents=[comun],
    )
    sub = parser.add_subparsers(dest="comando", required=True)
    sub_kwargs = {"parents": [comun]}

    adquirir = sub.add_parser("acquire", help="Adquirir el lease de un recurso", **sub_kwargs)
    adquirir.add_argument("resource")
    adquirir.add_argument("--agent", required=True, help="agent_id dueño del lease")
    adquirir.add_argument("--reason", default="", help="Motivo legible del bloqueo")
    adquirir.add_argument("--scope", default="", help="Ámbito opcional (ruta, módulo, submódulo)")
    adquirir.add_argument("--ttl-minutes", type=int, default=TTL_LEASE_MINUTOS)
    adquirir.add_argument(
        "--force",
        action="store_true",
        help="Robar un lease VIGENTE de otro agente. Sólo tras verificar que esa sesión terminó",
    )

    for nombre, ayuda in (("heartbeat", "Renovar el lease propio"), ("renew", "Alias de heartbeat")):
        renovar = sub.add_parser(nombre, help=ayuda, **sub_kwargs)
        renovar.add_argument("resource")
        renovar.add_argument("--agent", required=True)
        renovar.add_argument("--ttl-minutes", type=int, default=TTL_LEASE_MINUTOS)

    liberar = sub.add_parser("release", help="Liberar el lease de un recurso", **sub_kwargs)
    liberar.add_argument("resource")
    liberar.add_argument("--agent", required=True)
    liberar.add_argument("--force", action="store_true", help="Liberar un lease ajeno vigente")
    liberar.add_argument("--all", action="store_true", help="Liberar todos los leases del agente")

    estado_cmd = sub.add_parser("status", help="Ver el lease de un recurso", **sub_kwargs)
    estado_cmd.add_argument("resource", nargs="?")

    listar = sub.add_parser("list", help="Listar todos los leases registrados", **sub_kwargs)
    listar.add_argument("--agent", default=None, help="Filtrar por agente dueño")

    limpieza = sub.add_parser(
        "stale-cleanup",
        help="Eliminar leases vencidos y marcar agentes sin heartbeat como stale (no destructivo)",
        **sub_kwargs,
    )
    limpieza.add_argument("--agent-ttl-minutes", type=int, default=TTL_AGENTE_MINUTOS)
    limpieza.add_argument("--dry-run", action="store_true", help="Sólo informar, no modificar")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = construir_parser()
    args = parser.parse_args(argv)
    usar_json = getattr(args, "json", False)
    configurar_logging("agent_lock", verboso=getattr(args, "verbose", False))

    try:
        registro = _registro()
    except rutas.ErrorRepositorio as exc:
        logger.error("no se pudo resolver el repositorio: %s", exc)
        return 2

    try:
        if args.comando == "acquire":
            lease = registro.adquirir(
                args.resource,
                args.agent,
                scope=args.scope,
                reason=args.reason,
                ttl_minutos=args.ttl_minutes,
                force=args.force,
            )
            if usar_json:
                emitir_json(_dict(lease))
            else:
                emitir(_describir(lease))
            return 0

        if args.comando in ("heartbeat", "renew"):
            lease = registro.renovar(args.resource, args.agent, ttl_minutos=args.ttl_minutes)
            if usar_json:
                emitir_json(_dict(lease))
            else:
                emitir(_describir(lease))
            return 0

        if args.comando == "release":
            if args.all:
                liberados = registro.liberar_todos(args.agent)
                if usar_json:
                    emitir_json({"liberados": liberados})
                else:
                    emitir(
                        f"liberados {len(liberados)} leases de {args.agent}: {', '.join(liberados) or '-'}"
                    )
                return 0
            liberado = registro.liberar(args.resource, args.agent, force=args.force)
            if usar_json:
                emitir_json({"resource": args.resource, "liberado": liberado})
            else:
                emitir("liberado" if liberado else "no existía lease para ese recurso")
            return 0

        if args.comando in ("status", "list"):
            recurso = getattr(args, "resource", None)
            leases = registro.leases(recurso)
            agente_filtro = getattr(args, "agent", None)
            if agente_filtro:
                leases = [lease for lease in leases if lease.owner_agent_id == agente_filtro]
            if usar_json:
                emitir_json([_dict(lease) for lease in leases])
                return 0
            if not leases:
                emitir("Sin leases registrados" if recurso is None else "Sin lease para ese recurso")
                return 0
            for lease in leases:
                emitir(_describir(lease))
            return 0

        if args.comando == "stale-cleanup":
            vencidos = registro.limpiar_vencidos(dry_run=args.dry_run)
            stale = registro.marcar_stale(
                ttl_minutos=args.agent_ttl_minutes, dry_run=args.dry_run
            )
            resultado = {
                "dry_run": args.dry_run,
                "leases_vencidos": [lease.resource for lease in vencidos],
                "agentes_stale": [agente.agent_id for agente in stale],
            }
            if usar_json:
                emitir_json(resultado)
            else:
                prefijo = "[dry-run] " if args.dry_run else ""
                emitir(
                    f"{prefijo}leases vencidos: {', '.join(resultado['leases_vencidos']) or '-'}"
                )
                emitir(f"{prefijo}agentes marcados stale: {', '.join(resultado['agentes_stale']) or '-'}")
                if resultado["agentes_stale"]:
                    emitir(
                        "Un agente stale conserva su rama, su worktree y sus cambios: "
                        "revisar con 'agent_worktree.py doctor' antes de tocar nada."
                    )
            return 0

    except ConflictoLease as exc:
        logger.error("%s", exc)
        if usar_json:
            emitir_json({"error": "conflicto", "detalle": str(exc)})
        return 1
    except ErrorEstado as exc:
        logger.error("%s", exc)
        return 2

    parser.error(f"comando desconocido: {args.comando}")
    return 2


if __name__ == "__main__":  # pragma: no cover - punto de entrada
    raise SystemExit(main())
