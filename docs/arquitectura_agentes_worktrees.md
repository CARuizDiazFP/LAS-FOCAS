# Nombre de archivo: arquitectura_agentes_worktrees.md
# Ubicación de archivo: docs/arquitectura_agentes_worktrees.md
# Descripción: Arquitectura canónica de concurrencia multi-agente — aislamiento por Git worktree, leases por recurso, integración serializada y runtime compartido

# Arquitectura de concurrencia multi-agente (canónica)

> Este documento reemplaza como referencia operativa a
> [`docs/arquitectura_agent_awareness_2026-09-08.md`](arquitectura_agent_awareness_2026-09-08.md),
> que queda como el diseño original de la propuesta. Lo implementado y vigente es lo
> que está acá.

## 1. Problema

Varias sesiones agénticas (Claude Code, Codex, Gemini CLI, Copilot, scripts humanos)
trabajan sobre el mismo repositorio al mismo tiempo. Antes de esta implementación el
aislamiento era **sólo histórico**: cada tarea tenía su rama efímera, pero todas
compartían un único working tree. Eso produjo fricción real y documentada:

- `docs/cierres/2026-09-04.md`: un commit ajeno de otra sesión aterrizó en la rama
  efímera de esta tarea, simplemente porque era el `HEAD` activo del checkout.
- `docs/cierres/2026-09-07.md`: cinco procesos `claude` compartiendo el mismo checkout,
  con cambios de rama que ninguna sesión había iniciado.

Una rama no aísla un directorio. `git switch`, `git add`, `git stash` y `git status`
operan sobre el working tree y el index **compartidos**.

## 2. Cuatro capas distintas

El error conceptual a evitar es tratar todo como "el lock". Son cuatro problemas con
cuatro mecanismos:

| Capa | Qué aísla | Mecanismo | Alcance |
|---|---|---|---|
| **Aislamiento Git** | working tree, index, rama, `HEAD` | `git worktree` por agente | toda la tarea |
| **Lock de recurso** | artefactos compartidos que ningún worktree separa | lease en SQLite (`agent_lock.py`) | sólo mientras se toca ese recurso |
| **Serialización de integración** | la rama `dev` | lease `git:integrate-dev` | sólo la ventana de push a `dev` |
| **Lock de servicio/runtime** | Postgres, stack Docker, colas | `pg_advisory_xact_lock`, `env:docker-compose` | la operación puntual |

Son capas **complementarias**, no alternativas:

- Dos agentes editando `api/foo.py` y `web/bar.vue` **no necesitan ningún lease**: sus
  worktrees ya los separan físicamente.
- Dos agentes editando `AGENTS.md` **sí** necesitan un lease: el archivo es el mismo
  artefacto lógico aunque cada uno tenga su copia, y el conflicto aparecería recién en
  el merge.
- Dos agentes integrando a `dev` al mismo tiempo se serializan con
  `git:integrate-dev`; mientras uno integra, el otro **sigue desarrollando**.

**No existe un lock global sostenido durante toda la tarea.**

## 3. Topología

```
                    ┌─────────────────────────────┐
                    │  checkout de control        │
                    │  /home/.../LAS-FOCAS        │
                    │  rama: dev (permanente)     │
                    │  crear/quitar worktrees,    │
                    │  integrar, inspeccionar     │
                    └──────────────┬──────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        │                          │                          │
   worktree A                 worktree B                 worktree C
   LAS-FOCAS-agentes/         LAS-FOCAS-agentes/         LAS-FOCAS-agentes/
   claude-api-busqueda/       codex-web-mapa/            gemini-docs-agentes/
   feat/claude-api-busqueda   feat/codex-web-mapa        docs/gemini-docs-agentes
   working tree + index       working tree + index       working tree + index
   propios                    propios                    propios
        │                          │                          │
        └──────────────────────────┼──────────────────────────┘
                                   │
                     git-common-dir compartido
                     /home/.../LAS-FOCAS/.git
                                   │
                     .git/las-focas-agents/
                       agent_state.sqlite3
                                   │
         ┌─────────────┬───────────┴───────────┬─────────────┐
      agentes        leases                handoffs        eventos
   (estado, rama,  (recurso, dueño,      (origen→destino,  (auditoría
    worktree,       expiración,           rama, worktree,   append-only)
    heartbeat)      heartbeat)            next_action)
```

Rutas (deterministas, configurables por entorno):

| Elemento | Ruta por defecto | Override |
|---|---|---|
| Worktrees de agentes | `<padre-del-control>/LAS-FOCAS-agentes/<agent-id>-<task-slug>` | `LAS_FOCAS_WORKTREES_DIR` |
| Estado runtime | `<git-common-dir>/las-focas-agents/agent_state.sqlite3` | `LAS_FOCAS_AGENT_RUNTIME_DIR` |

Los worktrees viven **fuera** del árbol del repositorio: así no ensucian `git status`,
no requieren entradas nuevas en `.gitignore` y no hacen que pytest o ruff recorran
copias del proyecto.

El sufijo es `-agentes` y no `-worktrees` porque en esta máquina ya existía un
`LAS-FOCAS-worktrees/` creado por otro usuario (root, 2026-09-08) que bloqueaba la
escritura. `start` valida la escritura antes de invocar a Git y da un error accionable
con la variable de entorno a usar.

## 4. Por qué el estado va en el `git-common-dir`

Todos los linked worktrees de un repositorio comparten un único *common dir*
(`git rev-parse --git-common-dir`). Guardar ahí el estado cumple las cuatro
condiciones necesarias a la vez:

1. **No pertenece al historial Git**: nunca se commitea, nunca genera conflictos de
   merge, nunca aparece en un `git status`.
2. **Es visible desde todos los worktrees**: un agente parado en su propio directorio
   ve exactamente el mismo registro que el checkout de control.
3. **Sobrevive al cambio de rama**: no depende del contenido del working tree.
4. **Es único**: una base por repositorio, no una por worktree (una base por worktree
   no sería estado compartido, sería estado aislado — el problema opuesto).

`git rev-parse --git-common-dir` puede devolver una ruta **relativa** (`.git` en el
checkout principal). El tooling usa `--path-format=absolute` y, como respaldo para Git
anterior a 2.31, resuelve la ruta relativa contra el directorio actual.

### SQLite y no Redis/PostgreSQL

Para coordinación local alcanza la stdlib. La base usa:

- `journal_mode=WAL`: lecturas concurrentes mientras alguien escribe.
- `busy_timeout=10s`: un agente que encuentra la base tomada espera, no falla.
- `BEGIN IMMEDIATE` en toda mutación de lease: el chequeo de propiedad y la escritura
  ocurren dentro de la misma transacción de escritura. Eso es lo que hace atómico el
  `acquire` frente a dos agentes compitiendo (verificado con 10 hilos en
  `tests/test_agent_lock.py`: un ganador, nueve conflictos).

**PostgreSQL queda documentado como backend futuro opcional** para coordinar agentes
entre máquinas distintas (la base vive en el filesystem local, así que hoy no cruza
hosts). No se implementa porque agregaría un servicio y una dependencia para resolver
un problema que hoy no existe.

## 5. Modelo de estado

### `agentes`

| Campo | Sentido |
|---|---|
| `agent_id` | identidad única del agente (clave) |
| `task_id` | slug de la tarea en curso |
| `status` | ver máquina de estados |
| `branch`, `worktree_path` | rama y directorio propios |
| `base_ref`, `base_sha` | de dónde salió la rama |
| `started_at`, `heartbeat_at`, `last_activity_at` | ciclo de vida |
| `host`, `pid`, `notas` | diagnóstico |

Estados: `starting` → `active` → (`blocked` \| `handoff`) → `ready_to_merge` →
`integrating` → `finished`; más `stale` (sin heartbeat) y `failed`.

Un `agent_id` sostiene **una sola tarea activa**. Pedir una segunda es un error
explícito, no un reemplazo silencioso.

### `leases`

`resource`, `owner_agent_id`, `scope`, `status`, `acquired_at`, `heartbeat_at`,
`lease_expires_at`, `reason`, `host`, `pid`.

### `handoffs`

`from_agent`, `to_agent`, `resource`, `task`, `state`, `next_action`, `blocked_on`,
`branch`, `worktree_path`, `last_commit`, `archivos`, `leases`, `created_at`,
`accepted_at`.

### `eventos` (auditoría, append-only)

`agent_started`, `agent_updated`, `agent_status_changed`, `agent_unregistered`,
`worktree_created`, `worktree_removed`, `lock_acquired`, `lock_reacquired`,
`lock_renewed`, `lock_released`, `lock_conflict`, `lock_stolen`,
`lock_expired_takeover`, `lock_expired_cleanup`, `heartbeat`, `handoff_created`,
`handoff_accepted`, `integration_started`, `integration_completed`, `stale_detected`.

Ningún evento guarda secretos: se registran identificadores, recursos y motivos.

## 6. Recursos con lease

Un recurso es un identificador lógico, con formato sugerido `<clase>:<nombre>`:

| Recurso | Cuándo |
|---|---|
| `skill:<nombre>` | editar una skill compartida y sus mirrors |
| `agent:<nombre>` | editar la definición de un agente |
| `docs:AGENTS.md` | editar gobernanza raíz |
| `governance:claude` | editar `CLAUDE.md`, `.claude/commands/`, `.claude/skills/` |
| `db:migrations` | crear o aplicar migraciones Alembic |
| `env:python-dependencies` | instalar o cambiar dependencias del venv compartido |
| `env:docker-compose` | recrear, bajar o reconstruir el stack compartido |
| `git:worktree-lifecycle` | `git worktree add` / `remove` (se toma y se suelta enseguida) |
| `git:integrate-dev` | integrar a `dev` (única serialización global) |

No se toma un lease por archivo ordinario. El costo de coordinación se reserva para lo
que de verdad es compartido.

## 7. Ciclo de vida de una tarea

```
  dev actualizado (fetch)
        ↓
  registrar agente + crear rama efímera + crear worktree   ← git:worktree-lifecycle (segundos)
        ↓
  estado = active; el agente entra a SU worktree
        ↓
  editar / testear / commitear en su rama  ← sin ningún lease
  heartbeat periódico; leases sólo para recursos compartidos
        ↓
  sync: fetch + merge de origin/dev DENTRO de su worktree
  (los conflictos se resuelven ahí, sin tocar a nadie más)
        ↓
  ready: worktree limpio + validaciones → ready_to_merge
        ↓
  integrate  ← git:integrate-dev (ventana corta, exclusiva)
        ↓
  finished → cleanup (sólo si el worktree está limpio)
```

Mientras un agente integra, los demás siguen editando y commiteando sin interrupción.
Lo único serializado es la modificación de `dev`.

## 8. Seguridad Git

### Guardrail activo: hook `pre-commit`

La regla "prohibido commitear en `dev`" existía sólo en la documentación; nada lo
impedía técnicamente. `scripts/hooks/pre-commit` (instalable con
`scripts/instalar_hooks.sh`, que configura `core.hooksPath`) la hace efectiva:

| Situación | Efecto |
|---|---|
| Commit en `dev` o `main` | **bloqueado** |
| Rama fuera de `<tipo>/<slug>` | **bloqueado** |
| Commit en el checkout de control | aviso, no bloquea |
| Commit en el worktree de un agente | sin ruido |

El commit en el control se advierte pero no se bloquea a propósito: el bootstrap del
propio tooling y algunas tareas de mantenimiento ocurren legítimamente ahí. La salida de
emergencia es `git commit --no-verify`, deliberada y visible en el comando. Al vivir el
hook en el `git-common-dir`, una sola instalación cubre el control y todos los worktrees.

### Operaciones prohibidas

El tooling **nunca** ejecuta automáticamente `reset --hard`, `clean -fd`,
`checkout -- .`, `restore .`, `push --force` ni `worktree remove --force`.

- Un worktree con `git status --porcelain` no vacío **no se elimina**: se informa y se
  deja intacto.
- Las ramas se borran con `git branch -d` (rechaza lo no integrado), nunca con `-D`.
- Un agente `stale` conserva su rama, su worktree y sus cambios: `stale` es una señal,
  no una acción. La recuperación es conservadora y manual.
- Robar un lease vigente exige `--force` explícito y queda auditado como `lock_stolen`.
- Un heartbeat **no revive** un lease vencido: hay que readquirirlo tras verificar el
  estado real del recurso.

## 9. Entornos compartidos

Git worktree aísla el árbol de archivos; no aísla lo que vive fuera de él.

### Virtualenv Python

Cada worktree recibe un **symlink** a `.venv` del checkout de control: no se copia (no
se duplica espacio ni se produce deriva de versiones) y correr tests en paralelo
leyendo el mismo venv es seguro. **Instalar o cambiar dependencias** muta un recurso
compartido y requiere `env:python-dependencies`.

También se enlazan `.env`, `.env.dev` y `.secrets`, que resuelve el problema conocido
de `--env-file` y rutas relativas al levantar compose desde un worktree.

> **Trampa real (2026-09-14)**: `.gitignore` tenía `.venv*/` y `.secrets/` **con barra
> final**, y una barra final matchea sólo directorios. Un symlink es un archivo para
> Git, así que los enlaces aparecían como `??` y el worktree nunca estaba limpio, lo
> que bloqueaba `ready`, `integrate` y `cleanup`. Es el mismo problema que el
> guardrail 13 de `dev-workflow` había detectado para `node_modules` el 2026-09-11.
> Se corrigió en dos niveles: (a) patrones sin barra en `.gitignore`; (b) —y esto es
> lo que lo resuelve de raíz— el tooling escribe los patrones en
> `<git-common-dir>/info/exclude`, que es compartido por todos los worktrees, no se
> versiona y **no depende de la rama** que cada worktree tenga checkouteada (un
> worktree creado desde una rama vieja no tendría el `.gitignore` corregido).

### Docker Compose

**El stack de desarrollo es un recurso compartido y así se queda.** Recrearlo, bajarlo o
reconstruirlo afecta a todos los agentes: esas operaciones requieren
`env:docker-compose`.

Conviene ser preciso sobre por qué no se aísla por agente, porque la receta habitual
(`COMPOSE_PROJECT_NAME` distinto por sesión) **no funciona en este repositorio**:

- `deploy/docker-compose.dev.yml` fija `name: lasfocasdev`, y además cada servicio
  declara un `container_name:` explícito (`lasfocasdev-web`, `lasfocasdev-postgres`, …).
  Un `container_name` explícito **ignora** el prefijo del proyecto, así que dos stacks
  simultáneos colisionarían por nombre de contenedor, no sólo por puertos.
- Esos nombres no son un detalle interno: **467 menciones en 106 archivos** del repo
  (scripts, skills, documentación) hacen `docker exec lasfocasdev-<servicio> …`.

Aislar de verdad exigiría quitar los `container_name` fijos, parametrizar los puertos
publicados y actualizar esas 467 referencias. Es un cambio de infraestructura con su
propio riesgo, ajeno al problema de concurrencia agéntica: se decide aparte, no como
efecto colateral de esta arquitectura. Mientras tanto, el lease es la coordinación
correcta, y es suficiente: las operaciones destructivas sobre el stack son puntuales,
no continuas.

### Base de datos y Alembic

Dos agentes generando o aplicando migraciones contra el mismo entorno es peligroso:
requiere `db:migrations`. Esto es la contraparte agéntica del `pg_advisory_xact_lock`
que `core/services/camara_hierarchy_service.py` ya usa en la capa de negocio.

### Frontend: `node_modules` y `dist`

**No se enlazan automáticamente**: son mutables y un `npm install` o un `vite build`
cruzado rompería a otro agente. Cuando haga falta, se enlazan a mano; los patrones ya
están en `info/exclude`, así que el symlink no ensucia `git status` y no hay que
acordarse de borrarlo.

> **Consecuencia medida (2026-09-14)**: un worktree recién creado no tiene
> `web/frontend/dist`, y los tests que sirven el shell SPA
> (`test_web_admin.py::test_admin_paths_*`) fallan por eso. Comparando la suite completa
> entre el checkout de control y un worktree limpio sobre `origin/dev`: 32 vs 36 fallos,
> con **cero fallos nuevos** atribuibles al cambio — la diferencia son exactamente esos
> 4 tests. `start` avisa cuando faltan los artefactos, para que la ausencia no se
> confunda con una regresión.

## 10. Recuperación ante fallas

`agent_worktree.py doctor` detecta y **no corrige**:

| Situación | Detección |
|---|---|
| Proceso muerto / terminal cerrada | agente sin heartbeat dentro del TTL |
| Registro sin worktree en disco | ruta registrada que no existe |
| Worktree en disco sin registro | worktree dentro del directorio de agentes sin dueño |
| Rama y registro desalineados | la rama real del worktree difiere de la registrada |
| Rama eliminada | la rama registrada ya no existe (no se borra nada: recuperar por reflog) |
| Worktree bloqueado por Git | flag `locked` |
| Integración interrumpida | estado `integrating` sin sostener `git:integrate-dev` |
| Lease vencido olvidado | expiración pasada |
| Control sucio o fuera de `dev` | el checkout de control debe quedar libre para integrar |

`git worktree prune` (seguro: sólo limpia metadata de worktrees cuyo directorio ya no
existe) se ejecuta únicamente con `--prune` explícito.

Casos de recuperación cubiertos por el tooling:

- **Rama existente sin worktree**: `start` adjunta un worktree nuevo a la rama en vez
  de recrearla, conservando los commits (verificado en tests).
- **`git worktree add` fallido a mitad**: puede dejar la rama creada sin directorio; el
  siguiente `start` la detecta y la adjunta.
- **Integración rechazada por no-fast-forward**: el agente queda `blocked` con la
  instrucción exacta (`sync` y reintentar); no se fuerza nada.

## 11. Diferencia con Growen (evolución, no incompatibilidad)

`Growen` resolvió primero el problema de *Agent Awareness* con locks cooperativos en
JSON sobre un **único worktree físico**. Su propio
`docs/architecture/AGENT_ORCHESTRATION.md` deja el paso siguiente escrito como ítem 8
del plan de acción: *"Evaluar `git worktree add` por sesión para agentes que sí
necesiten paralelismo físico real (no sólo lógico) — propuesto, requiere decisión
explícita del equipo"*.

LAS-FOCAS implementa ese ítem 8 y ajusta las piezas en consecuencia:

| Aspecto | Growen (hoy) | LAS-FOCAS (implementado) |
|---|---|---|
| Aislamiento físico | uno solo: worktree compartido | uno por agente |
| Persistencia de estado | JSON por scope en `.agents/state/locks/` | SQLite transaccional en el git-common-dir |
| Cambio de rama | lock global `git-worktree` sostenido **toda la tarea** | innecesario: cada agente tiene su rama y su árbol |
| `git worktree add/remove` | — | `git:worktree-lifecycle`, tomado y soltado en segundos |
| Integración a `dev` | dentro del mismo lock global | `git:integrate-dev`, sólo la ventana de push |
| Estado del agente | no modelado | agentes, handoffs y eventos con máquina de estados |
| Handoff | informal, en documentos | registrado, con transferencia explícita de ownership |

El patrón de lease cooperativo con TTL, conflicto explícito, expiración recuperable y
`--force` auditado se conserva tal cual: es la parte que Growen ya tenía bien resuelta.

## 12. Herramientas

| Herramienta | Para qué |
|---|---|
| `scripts/agent_worktree.py` | ciclo de vida: `start`, `list`, `status`, `heartbeat`, `sync`, `ready`, `integrate`, `handoff`, `accept-handoff`, `finish`, `cleanup`, `doctor` |
| `scripts/agent_lock.py` | leases: `acquire`, `heartbeat`/`renew`, `release`, `status`, `list`, `stale-cleanup` |
| `scripts/agentes/` | capas internas: `rutas` (descubrimiento), `estado` (SQLite), `gitops` (Git), `consola` (salida/logging) |
| `scripts/sync_skill_mirrors.py` | propagación determinista de skills a los mirrors por plataforma; `--check` verifica drift |
| `scripts/hooks/pre-commit` + `scripts/instalar_hooks.sh` | guardrail activo de la política de ramas |

La lógica ejecutable vive en Python (capa neutral, stdlib únicamente, sin depender del
venv ni de la app). Las skills y los comandos de cada plataforma sólo indican **cuándo
y cómo** invocarla: no reimplementan el algoritmo en Markdown.

Cobertura: `tests/test_agent_lock.py` y `tests/test_agent_worktree.py` (56 pruebas)
corren contra repositorios Git temporales con remoto bare local — sin GitHub, sin red.

## 13. Referencias

- Skill operativa: `.agentes-comunes/skills/agent-worktree/SKILL.md`
- Política de ramas y validaciones previas: `.agentes-comunes/skills/dev-workflow/SKILL.md`
- Cierre e integración: `.agentes-comunes/skills/cierre-sesion/SKILL.md`
- Diseño original de la propuesta: `docs/arquitectura_agent_awareness_2026-09-08.md`
- Incidentes de concurrencia reales: `docs/cierres/2026-09-04.md`, `docs/cierres/2026-09-07.md`
