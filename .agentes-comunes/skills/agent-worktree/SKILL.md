# Nombre de archivo: SKILL.md
# Ubicación de archivo: .agentes-comunes/skills/agent-worktree/SKILL.md
# Descripción: Skill de trabajo concurrente multi-agente — worktree y rama propios por agente, leases por recurso compartido e integración serializada a dev

---
name: agent-worktree
description: "Usar al INICIAR cualquier tarea y ante cualquier señal de concurrencia (otra sesión activa, trabajo largo, subagentes). Crea el worktree y la rama propios del agente, define cuándo tomar un lease de recurso compartido y cómo integrar a dev sin pisar a nadie."
argument-hint: "agent-id y tarea, por ejemplo: claude-api / busqueda-camaras"
---

# Habilidad: Agent Worktree — trabajo concurrente aislado

Varias sesiones agénticas (Claude Code, Codex, Gemini CLI, Copilot, scripts humanos)
pueden trabajar sobre LAS-FOCAS al mismo tiempo. Esta skill define **cómo** hacerlo sin
que un `git switch`, un staging o un commit de un agente afecte físicamente a otro.

La lógica ejecutable vive en `scripts/agent_worktree.py` y `scripts/agent_lock.py`
(Python stdlib, sin dependencias, sin venv obligatorio). Esta skill sólo indica cuándo
y cómo invocarlos. La arquitectura completa está en
`docs/arquitectura_agentes_worktrees.md`.

## Regla central

```
un agente = una tarea = una rama = un Git worktree
```

- El **checkout principal es el checkout de control**: queda en `dev` y se usa para
  crear/quitar worktrees, integrar e inspeccionar. No se trabaja ahí.
- Cada agente edita, testea y commitea **dentro de su propio worktree**.
- **No hay lock global.** Dos agentes tocando archivos distintos no toman ningún lease.

## Cuándo usar

Invocar **al inicio** de cualquier tarea que vaya a modificar el repositorio, y
obligatoriamente si: hay otra sesión activa (verificable con `ListAgents` o
`ps aux | grep claude`), la tarea es larga (SDD, migraciones, subagentes), o va a tocar
gobernanza/skills/migraciones/Docker.

## Procedimiento

### 1. Averiguar si ya se está dentro de un worktree de agente

```bash
python scripts/agent_worktree.py status            # panorama completo
python scripts/agent_worktree.py list              # agentes registrados
git rev-parse --show-toplevel                      # ¿dónde estoy parado?
```

Si el `toplevel` coincide con el `worktree_path` de un agente registrado, continuar ahí.
Si se está en el checkout de control, **no empezar a editar**: crear el workspace.

### 2. Crear el workspace propio

```bash
python scripts/agent_worktree.py start \
  --agent claude-api --type feat --task busqueda-camaras
```

Devuelve agente, rama (`feat/claude-api-busqueda-camaras`), ruta del worktree, base
(`origin/dev@<sha>`) y estado. Es idempotente para la misma tarea: repetirlo no recrea
nada. Un `agent_id` sostiene **una sola tarea activa**.

Elegir un `agent_id` que identifique plataforma y dominio (`claude-api`, `codex-web`,
`gemini-docs`). Ambos argumentos son slugs kebab-case.

El worktree recibe symlinks a `.venv`, `.env`, `.env.dev` y `.secrets` del checkout de
control (no se copian), y el tooling registra los patrones en
`<git-common-dir>/info/exclude` para que esos enlaces no ensucien `git status`.

Después: `cd <ruta-del-worktree>` y trabajar ahí.

### 3. Trabajar

- Editar, testear y commitear normalmente en la rama propia. **Sin leases.**
- Registrar actividad de tanto en tanto (también renueva los leases propios):
  ```bash
  python scripts/agent_worktree.py heartbeat --agent claude-api
  ```
- Tomar un lease **sólo** al tocar un recurso compartido:
  ```bash
  python scripts/agent_lock.py acquire "db:migrations" \
    --agent claude-api --reason "migración de inventario"
  # ... trabajo ...
  python scripts/agent_lock.py release "db:migrations" --agent claude-api
  ```

| Recurso | Cuándo tomarlo |
|---|---|
| `skill:<nombre>` | editar una skill y propagar sus mirrors |
| `agent:<nombre>` | editar la definición de un agente |
| `docs:AGENTS.md` | editar gobernanza raíz |
| `governance:claude` | editar `CLAUDE.md`, `.claude/commands/`, `.claude/skills/` |
| `db:migrations` | crear o aplicar migraciones Alembic |
| `env:python-dependencies` | instalar o cambiar dependencias del venv compartido |
| `env:docker-compose` | recrear, bajar o reconstruir el stack compartido |

Si el `acquire` devuelve conflicto (código 1), **no sobrescribir**: esperar, trabajar en
otra parte de la tarea, o pedir handoff. El mensaje indica dueño y tiempo restante.

### 4. Preparar la integración

```bash
python scripts/agent_worktree.py sync  --agent claude-api   # trae origin/dev a la rama
# resolver conflictos DENTRO del worktree propio; volver a validar
pytest -q                                                    # o el subconjunto pertinente
scripts/check_no_plaintext_secrets.sh
scripts/sync_agentes_comunes.sh && scripts/check_skill_mirror_drift.sh   # si se tocaron skills
python scripts/agent_worktree.py ready --agent claude-api    # exige worktree limpio
```

### 5. Integrar (ventana serializada)

```bash
python scripts/agent_worktree.py integrate --agent claude-api
```

Toma `git:integrate-dev`, publica la rama, hace fast-forward de `dev`, actualiza el
checkout de control y libera el lease. **Mientras un agente integra, los demás siguen
desarrollando**: lo único serializado es la escritura sobre `dev`.

Si `dev` avanzó, el push es rechazado por Git y el comando lo informa: volver a `sync` y
reintentar. En el cierre de sesión, este paso lo ejecuta `cierre-sesion`.

### 6. Cerrar y limpiar

```bash
python scripts/agent_worktree.py finish  --agent claude-api   # libera leases propios
python scripts/agent_worktree.py cleanup --agent claude-api --borrar-rama
```

`cleanup` elimina el worktree **sólo si está limpio**; si tiene cambios sin confirmar lo
informa y lo deja intacto.

### 7. Handoff (traspaso a otro agente)

```bash
python scripts/agent_worktree.py handoff \
  --from claude-api --to codex-api \
  --next-action "continuar implementación del endpoint" \
  --blocked-on "falta definir el contrato de respuesta"

python scripts/agent_worktree.py accept-handoff --agent codex-api
```

Conserva rama, worktree, último commit, archivos modificados, leases y bloqueo conocido.
El ownership **no** cambia hasta que el destino lo acepta explícitamente.

### 8. Diagnóstico

```bash
python scripts/agent_worktree.py doctor
python scripts/agent_lock.py stale-cleanup --dry-run
```

`doctor` detecta registros sin worktree, worktrees sin registro, ramas desalineadas,
worktrees bloqueados, agentes sin heartbeat, integraciones interrumpidas, leases vencidos
y un checkout de control sucio o fuera de `dev`. **Sólo diagnostica: no corrige.**

## Guardrails

1. **Nunca** ejecutar automáticamente `git reset --hard`, `git clean -fd`,
   `git checkout -- .`, `git restore .`, `git push --force` ni
   `git worktree remove --force` sobre trabajo no demostrado como descartable.
2. Un worktree con `git status --porcelain` no vacío **no se elimina**. Confirmar o
   descartar a mano primero.
3. Nunca borrar la rama de otro agente si tiene commits no integrados. Las ramas se
   borran con `git branch -d` (rechaza lo no integrado), jamás con `-D`.
4. Un agente `stale` (sin heartbeat dentro del TTL) **conserva** rama, worktree y
   cambios: `stale` es una señal, no una acción. Inspeccionar antes de tocar nada.
5. Un `heartbeat` no revive un lease vencido: readquirirlo con `acquire` tras verificar
   el estado real del recurso.
6. Robar un lease vigente exige `--force` explícito y sólo tras confirmar que la otra
   sesión terminó. Queda auditado como `lock_stolen`.
7. No trabajar en el checkout de control ni dejarlo fuera de `dev`: se reserva para
   integración y coordinación.
8. No tomar leases para archivos ordinarios. El costo de coordinación se reserva para
   recursos que ningún worktree puede aislar.
9. El estado runtime (`<git-common-dir>/las-focas-agents/`) **no se versiona nunca** y no
   debe contener secretos.
10. `node_modules` **no** se enlaza automáticamente (es mutable y un `npm install`
    cruzado rompería a otro agente). Para verificar el frontend desde un worktree,
    enlazarlo a mano según el guardrail 13 de `dev-workflow`; el patrón ya está en
    `info/exclude`, así que el symlink no ensucia `git status`.

## Relación con otras skills

- `dev-workflow`: validaciones previas, política de ramas efímeras y stack dev. Esta
  skill aporta el **aislamiento físico** que `dev-workflow` recomienda; son
  complementarias, no alternativas.
- `cierre-sesion`: ejecuta la integración final usando `ready`/`integrate`/`cleanup` de
  esta misma herramienta. No duplicar ese flujo acá.
- `superpowers:using-git-worktrees`: mecanismo genérico de worktrees. Para trabajo
  agéntico coordinado en LAS-FOCAS usar **esta** skill, que además registra estado,
  leases y auditoría compartidos.

## Resultado esperado

Agente registrado y `active`, con rama y worktree propios; trabajo aislado del resto de
las sesiones; leases tomados sólo sobre recursos compartidos y liberados al terminar;
integración a `dev` serializada; worktree eliminado únicamente si quedó limpio.
