# Nombre de archivo: __init__.py
# Ubicación de archivo: scripts/agentes/__init__.py
# Descripción: Paquete de coordinación multi-agente (rutas, estado SQLite y operaciones Git/worktree)

"""Capa neutral de coordinación multi-agente de LAS-FOCAS.

Separa tres responsabilidades para que cualquier plataforma agéntica (Claude Code,
Codex, Gemini CLI, Copilot o un humano con bash) use el mismo mecanismo:

- ``rutas``   : descubrimiento del repositorio, del ``git-common-dir`` compartido
                por todos los linked worktrees y del directorio de runtime.
- ``estado``  : registro SQLite de agentes, leases de recursos, handoffs y eventos.
- ``gitops``  : operaciones Git/worktree encapsuladas en ``subprocess``.

Las CLIs (``scripts/agent_lock.py`` y ``scripts/agent_worktree.py``) sólo orquestan
estas tres capas; no contienen lógica de dominio.
"""

from __future__ import annotations

__all__ = ["estado", "gitops", "rutas"]
