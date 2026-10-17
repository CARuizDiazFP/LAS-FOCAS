# Nombre de archivo: CATALOG.md
# Ubicación de archivo: docs/superpowers/CATALOG.md
# Descripción: Índice de una línea por skill de Superpowers y precedencia frente a las skills locales (lazy loading)

# Catálogo de Superpowers (lazy loading)

Índice mínimo: **no** cargar los manifiestos completos de Superpowers en memoria. Leer el
`SKILL.md` de una skill sólo cuando su disparador aplica a la tarea en curso.

| Skill | Cargar cuando… |
|---|---|
| `brainstorming` | se diseña algo nuevo y el alcance todavía no está definido |
| `writing-plans` | hay una spec y la tarea tiene varios pasos antes de tocar código |
| `executing-plans` | se ejecuta un plan propio sin subagentes |
| `subagent-driven-development` | se ejecuta un plan con tareas independientes vía subagentes |
| `dispatching-parallel-agents` | hay 2+ tareas independientes sin estado compartido |
| `test-driven-development` | se implementa una feature o un fix con tests primero |
| `systematic-debugging` | aparece un bug, un test rojo o un comportamiento inesperado |
| `verification-before-completion` | antes de declarar algo terminado, verde o arreglado |
| `requesting-code-review` | se cierra una tarea grande y conviene una revisión |
| `receiving-code-review` | llegan hallazgos de review que hay que validar antes de aplicar |
| `using-git-worktrees` | se necesita aislamiento de directorio (ver precedencia) |
| `finishing-a-development-branch` | una rama terminada se integra fuera del cierre de sesión |
| `writing-skills` | se crea o edita una skill |
| `using-superpowers` | inicio de sesión (la inyecta el propio plugin) |
| `diagnosing-superpowers` | una sesión con Superpowers salió mal y se busca el porqué (sólo plugin de Claude Code) |

## Precedencia

Las skills de `.agentes-comunes/skills/` **prevalecen siempre** sobre Superpowers. Superpowers
aporta el método; la skill local fija el cómo en este repositorio.

| Superpowers | Prevalece la local | Motivo |
|---|---|---|
| `using-git-worktrees` | `agent-worktree` | worktree registrado, leases, puertos propios y `.env.dev` privada |
| `finishing-a-development-branch` | `cierre-sesion` | el trigger de cierre ya autoriza la integración a `dev` |
| `test-driven-development`, `verification-before-completion` | `pytest-focas` | pruebas focales hacia `dev`; regresión completa sólo en deploy |
| `writing-skills` | `skill-generator` / `crear-skill` | stack, seguridad y mirrors (`scripts/sync_agentes_comunes.sh`) obligatorios |
| `subagent-driven-development` | `docs/politica_recursion_sdd.md` | corte de rondas de review sin hallazgos nuevos |

Antes de cualquier búsqueda global en el repo, leer `docs/REPOSITORY_MAP.md`.
