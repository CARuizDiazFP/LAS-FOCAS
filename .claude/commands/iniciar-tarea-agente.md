# Nombre de archivo: iniciar-tarea-agente.md
# Ubicación de archivo: .claude/commands/iniciar-tarea-agente.md
# Descripción: Comando Claude Code para crear el worktree y la rama efímera propios del agente antes de empezar a trabajar

Prepara el workspace aislado de esta sesión antes de tocar el repositorio. Argumento opcional: $ARGUMENTS (por ejemplo: `claude-api feat busqueda-camaras`, o una descripción de la tarea de la que derivar el slug).

## Objetivo

Garantizar que esta sesión trabaje en **su propio Git worktree y su propia rama efímera**, sin compartir working tree, index ni `HEAD` con ninguna otra sesión agéntica.

La lógica vive en `scripts/agent_worktree.py`; la skill `agent-worktree` tiene el procedimiento completo y los guardrails. Este comando sólo orquesta.

## Flujo de trabajo

1. **Averiguar dónde está parada la sesión**:
   ```bash
   python scripts/agent_worktree.py status
   git rev-parse --show-toplevel
   ```
   Si el `toplevel` ya coincide con el `worktree_path` de un agente registrado y activo, informarlo y **no crear nada**: continuar ahí.

2. **Elegir identidad y tarea** (del argumento, o derivadas del pedido del usuario):
   - `agent_id`: plataforma + dominio, en kebab-case (`claude-api`, `claude-web`, `claude-docs`).
   - `type`: `feat|fix|docs|chore|refactor|test`.
   - `task`: slug kebab-case de la tarea.
   Si el argumento no alcanza para decidirlos sin ambigüedad, preguntar al usuario en una línea antes de crear nada.

3. **Crear el workspace**:
   ```bash
   python scripts/agent_worktree.py start --agent <agent-id> --type <tipo> --task <task-slug>
   ```
   Es idempotente para la misma tarea. Un `agent_id` sostiene una sola tarea activa: si ya tiene otra, el comando lo rechaza con el motivo.

4. **Confirmar el resultado al usuario** con las cinco líneas que devuelve el tooling (agente, rama, worktree, base, estado) y la ruta a la que hay que entrar.

5. **Trabajar dentro del worktree** a partir de ese momento: todas las lecturas, ediciones, tests y commits de la tarea ocurren con esa ruta como raíz. El checkout principal queda reservado para control e integración.

6. Registrar actividad periódicamente durante tareas largas:
   ```bash
   python scripts/agent_worktree.py heartbeat --agent <agent-id>
   ```

## Guardrails

- No empezar a editar en el checkout de control. Si ya hay ediciones ahí, informarlo antes de crear el worktree (mover trabajo entre árboles es decisión del usuario, no automática).
- No tomar leases (`agent_lock.py`) para archivos ordinarios: sólo para recursos compartidos (`db:migrations`, `docs:AGENTS.md`, `skill:<nombre>`, `env:docker-compose`, `env:python-dependencies`, `governance:claude`).
- Si `start` falla por permisos del directorio de worktrees, el error indica la variable `LAS_FOCAS_WORKTREES_DIR` a usar: no crear directorios con `sudo`.
- Nunca borrar ni forzar nada para "hacer lugar": `git worktree remove --force`, `reset --hard` y `branch -D` están prohibidos.

## Resultado esperado

Agente registrado y `active`, con rama `<tipo>/<agent-id>-<task-slug>` y worktree propios, listo para trabajar en paralelo con otras sesiones sin interferencia física.
