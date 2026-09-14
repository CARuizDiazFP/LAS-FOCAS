# Nombre de archivo: handoff-agente.md
# Ubicación de archivo: .claude/commands/handoff-agente.md
# Descripción: Comando Claude Code para traspasar una tarea a otro agente conservando rama, worktree, leases y contexto de continuidad

Traspasa la tarea en curso a otro agente sin perder continuidad. Argumento opcional: $ARGUMENTS (por ejemplo: `claude-api → codex-api: continuar el endpoint`, o `aceptar` para tomar un handoff dirigido a esta sesión).

## Objetivo

Dejar registrado, de forma que otra sesión pueda retomar sin reconstruir contexto: qué rama y worktree se estaban usando, cuál fue el último commit, qué archivos quedaron modificados, qué leases estaban tomados, cuál es el siguiente paso concreto y qué está bloqueando.

## Flujo de trabajo

### Emitir un handoff

1. Verificar el estado real antes de traspasar:
   ```bash
   python scripts/agent_worktree.py status --agent <agent-id-origen>
   ```
2. Commitear lo que sea commiteable en la rama propia. Lo que quede sin confirmar viaja en el handoff como lista de archivos, pero no se pierde ni se descarta.
3. Emitir el traspaso:
   ```bash
   python scripts/agent_worktree.py handoff \
     --from <agent-id-origen> --to <agent-id-destino> \
     --next-action "<siguiente paso concreto>" \
     --blocked-on "<bloqueo conocido, si lo hay>"
   ```
   El agente origen pasa a estado `handoff`. **El ownership no cambia todavía.**
4. Informar al usuario el id del handoff y su contenido (rama, worktree, último commit, archivos modificados, leases, siguiente acción, bloqueo).

### Aceptar un handoff

1. Ver lo pendiente para esta sesión:
   ```bash
   python scripts/agent_worktree.py status
   ```
2. Aceptarlo explícitamente:
   ```bash
   python scripts/agent_worktree.py accept-handoff --agent <agent-id-destino>
   ```
   Recién ahí se transfieren la tarea, el worktree, la rama y los leases; el agente origen deja de figurar como dueño.
3. Entrar al worktree heredado y continuar desde `next_action`.

## Guardrails

- El ownership **nunca** cambia de forma silenciosa: se emite y se acepta, en dos pasos explícitos.
- No borrar el worktree ni la rama del agente origen al emitir un handoff: el destino los necesita tal cual.
- No emitir un handoff para "liberar" un recurso que se quiere tomar. Si hay un lease ajeno vigente, esperar o pedirlo, no traspasarse la tarea a uno mismo.
- Si el destino no existe todavía como sesión, el handoff queda pendiente en el registro: es su propósito, no un error.
- Un handoff no reemplaza el cierre de sesión. Si la tarea terminó, corresponde `/cierre-sesion`, no un traspaso.

## Resultado esperado

Handoff registrado con continuidad completa (rama, worktree, último commit, archivos, leases, siguiente acción, bloqueo) y, al aceptarse, ownership transferido de forma explícita y auditada.
