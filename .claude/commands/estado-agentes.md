# Nombre de archivo: estado-agentes.md
# Ubicación de archivo: .claude/commands/estado-agentes.md
# Descripción: Comando Claude Code para inspeccionar agentes activos, worktrees, leases y handoffs, y diagnosticar inconsistencias

Muestra el estado de coordinación multi-agente del repositorio. Argumento opcional: $ARGUMENTS (`doctor` para diagnóstico, un `agent_id` para el detalle de un agente, o vacío para el panorama completo).

## Objetivo

Responder, con evidencia y sin adivinar: qué agentes están activos, en qué rama y worktree, qué recursos están tomados y por quién, qué handoffs quedaron pendientes y qué inconsistencias existen entre el registro, Git y el disco.

## Flujo de trabajo

1. **Panorama general**:
   ```bash
   python scripts/agent_worktree.py status
   python scripts/agent_worktree.py list
   python scripts/agent_lock.py list
   git worktree list
   ```

2. **Detalle de un agente** (si el argumento trae un `agent_id`):
   ```bash
   python scripts/agent_worktree.py status --agent <agent-id>
   python scripts/agent_lock.py list --agent <agent-id>
   ```
   Incluye últimos eventos de auditoría y último commit de su rama.

3. **Diagnóstico** (si el argumento es `doctor`, o si el paso 1 muestra algo raro):
   ```bash
   python scripts/agent_worktree.py doctor
   python scripts/agent_lock.py stale-cleanup --dry-run
   ```

4. **Sesiones fuera del registro**: complementar con `ListAgents` y `ps aux | grep claude`. Una sesión puede estar activa sin haberse registrado en el tooling; el registro no la inventa.

5. **Reportar** en el chat: agentes y su estado, leases vigentes y vencidos, handoffs pendientes, hallazgos del `doctor` con su acción sugerida. Si no hay nada anómalo, decirlo en una línea.

## Guardrails

- Este comando es de **sólo lectura y diagnóstico**. `doctor` no corrige nada.
- No ejecutar `stale-cleanup` sin `--dry-run` salvo que el usuario lo pida: eliminar leases vencidos es seguro, pero marcar agentes como `stale` cambia estado compartido.
- Un agente `stale` **no** autoriza a borrar su rama, su worktree ni sus cambios. Informar, no actuar.
- Nunca liberar con `--force` el lease de otro agente sin confirmación explícita del usuario y evidencia de que esa sesión terminó.

## Resultado esperado

Cuadro claro del estado concurrente del repositorio, con acciones sugeridas para cada inconsistencia y ninguna modificación de estado no solicitada.
