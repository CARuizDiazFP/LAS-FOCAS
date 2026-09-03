# Rama Efímera + Cierre de Sesión con Auto-Merge — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hacer obligatorio el Feature Branching Efímero (nunca commitear directo en `dev`/`main`) y dotar a `cierre-sesion` de evolución agéntica con compuerta de riesgo + un flujo de auto-merge autónomo que integra la rama efímera a `dev` al cerrar la sesión.

**Architecture:** Tres familias de skills concentran toda la escritura de git en el repo: `dev-workflow` (valida/crea la rama efímera), `repo-updater` (commitea/pushea sobre esa rama), `cierre-sesion` (integra esa rama a `dev` al final). Se edita cada fuente de verdad en `.agentes-comunes/skills/` y se propaga el mismo cambio a sus mirrors (`.github/skills/`, `.codex-skills/skills/`, `.gemini/rules/`, `.claude/skills/` o `.claude/commands/` según corresponda). Se cierra además un gap real preexistente: `dev-workflow` no tiene mirror en `.claude/skills/`, por lo que hoy no es invocable por el tool `Skill`.

**Tech Stack:** Archivos Markdown con frontmatter YAML (skills/comandos/prompts agénticos); sin código de aplicación ni tests automatizados — la verificación de cada tarea es por `grep`/`diff` contra el contenido esperado.

**Spec:** `docs/superpowers/specs/2026-09-03-rama-efimera-cierre-sesion-design.md`

## Global Constraints

- Convención de nombre de rama efímera: `<tipo>/<slug-kebab-case>`, `<tipo>` ∈ `feat|fix|docs|chore|refactor|test` (mismo vocabulario ya usado en mensajes de commit `<tipo>(módulo): descripción`).
- Prohibido commitear/pushear estando parado en `dev` o `main` — universal, sin excepciones (decisión confirmada por el usuario 2026-09-03).
- El guardrail de worktree de `repo-updater` ("nunca commitear en un worktree de prod/aislado", confirmado 2026-08-25) es ortogonal a este cambio y NO se modifica en su sustancia — sólo se re-redacta para no decir literalmente "debe ser `dev`".
- Push a `origin/main` sigue prohibido en todos los skills — esa prohibición no cambia en ningún archivo.
- Tabla de riesgo 🟢/🟡/🔴 de `cierre-sesion` reutiliza el patrón ya existente en `.agentes-comunes/skills/docker-cleanup/SKILL.md` — no se inventa taxonomía nueva.
- Triggers de `cierre-sesion` son **aditivos**: "Cerrar sesión"/"Cerremos sesión" se suman a los existentes ("Cierre chat", `/cierre-sesion`, etc.), nunca los reemplazan.
- Toda propuesta de evolución agéntica 🔴 (muy alto riesgo) detiene el flujo de `cierre-sesion` y exige respuesta explícita del usuario antes de continuar.
- Cada archivo modificable debe conservar el encabezado de 3 líneas (`# Nombre de archivo` / `# Ubicación de archivo` / `# Descripción`) por convención de `AGENTS.md`.

---

### Task 1: `dev-workflow` — fuente de verdad

**Files:**
- Modify: `.agentes-comunes/skills/dev-workflow/SKILL.md` (reescritura completa del cuerpo)

**Interfaces:**
- Produces: el texto exacto del nuevo paso 1 ("Verificar rama activa...") y paso 4 ("Commits y push...") de este skill — las Tareas 2, 4 y 6 lo citan como "la misma regla que en dev-workflow" y deben quedar consistentes con esta redacción.

- [ ] **Step 1: Reemplazar el contenido completo del archivo**

Reemplazar TODO el contenido de `.agentes-comunes/skills/dev-workflow/SKILL.md` por:

```markdown
# Nombre de archivo: SKILL.md
# Ubicación de archivo: .agentes-comunes/skills/dev-workflow/SKILL.md
# Descripción: Skill para garantizar que los agentes operen siempre sobre ramas efímeras derivadas de dev y el stack lasfocasdev, nunca sobre producción

---
name: dev-workflow
description: "Usar SIEMPRE antes de ejecutar cambios de código, commits, push, operaciones Docker o actualizaciones de repo. Valida rama efímera activa, stack correcto y restricciones del entorno dev."
argument-hint: "Contexto de la tarea, por ejemplo: implementar feature X en el módulo Y"
---

# Habilidad: Dev Workflow — Protocolo de Trabajo en Entorno Dev

Protocolo de validación y operación para garantizar que todos los cambios se realicen sobre una rama
efímera derivada del entorno de desarrollo aislado (`dev`), nunca directo sobre `dev` ni sobre
producción.

## Cuándo usar
Invocar esta skill **siempre** que el agente vaya a: modificar código/config/docs, ejecutar commits o push, operar Docker (up/build/exec/logs), actualizar el repo (repo-updater), crear/modificar migraciones Alembic, ejecutar tests que requieran DB.

## Procedimiento de validación (ejecutar en orden)

1. Verificar rama activa (`git branch --show-current`).
   - Si es una rama efímera vigente (prefijo `feat/`, `fix/`, `docs/`, `chore/`, `refactor/` o
     `test/`): continuar, es la rama de trabajo de esta tarea.
   - Si es `dev` o `main`: **está prohibido modificar código o commitear ahí**. Crear una rama
     efímera nueva desde el estado remoto de `dev` antes de cualquier cambio:
     ```bash
     git fetch origin
     git checkout -b <tipo>/<slug-kebab-case> origin/dev
     ```
     `<tipo>` = `feat|fix|docs|chore|refactor|test` según la naturaleza del cambio; `<slug>` describe
     la tarea en minúsculas y guiones (mismo criterio que ya se usa en `<tipo>(módulo): descripción`
     para mensajes de commit).
   - Si `dev` no existe en el remoto: crearla primero (`git checkout -b dev && git push -u origin dev`)
     y recién ahí crear la rama efímera.
   - Si ya existe una rama efímera vigente para esta misma tarea, reutilizarla — no crear ramas
     anidadas dentro de una sesión.
2. Verificar que `.env.dev` existe; si no, crearlo desde `deploy/env.dev.sample`.
3. Comandos Docker correctos en dev (tabla `start_dev.sh`, `docker-compose.dev.yml`, etc.). **NUNCA**
   usar `docker compose -f deploy/compose.yml` para pruebas/desarrollo.
4. **Commits y push** (siempre sobre la rama efímera activa, nunca sobre `dev`/`main`):
   ```bash
   git branch --show-current  # debe ser <tipo>/<slug>, nunca dev ni main
   git add .
   git commit -m "<tipo>(módulo): descripción técnica"
   git push -u origin HEAD     # NUNCA: git push origin dev ni git push origin main directamente
   ```
   La integración a `dev` ocurre exclusivamente vía `cierre-sesion` (flujo de auto-merge al cierre) o,
   para ramas deliberadamente diferidas (ej. ventana de mantenimiento), vía
   `superpowers:finishing-a-development-branch`.
5. Restricciones sobre archivos de producción (`deploy/compose.yml`, `.env`, secretos) — requieren aprobación explícita del Tech Lead; si se necesita, documentar en `docs/decisiones.md` y crear PR formal.

## Guardrails
1. No commitear ni pushear estando parado en `dev` o `main`. Todo trabajo ocurre en una rama efímera
   creada desde `origin/dev` (paso 1). Esta regla es universal — sin excepciones por tipo de tarea.
2. No hacer push a `origin/main` sin PR revisado que venga de `dev`.
3. No usar `--force` ni comandos destructivos sin pedido explícito del usuario.
4. No commitear `.env`, `.env.dev`, `Keys/`, `*.pem`, `*.key` ni binarios generados.
5. Si detectás que estás en `main`: no cherry-pickees a ciegas — crear la rama efímera desde
   `origin/dev` (paso 1) y evaluar si los cambios locales en `main` corresponden a esa tarea.
6. `git push origin main` está **prohibida** desde el agente salvo instrucción explícita y confirmación del usuario.
7. Una rama efímera es un `git checkout -b` dentro del mismo checkout de trabajo — **no** es un
   worktree nuevo. Para aislamiento real de directorio (ej. trabajo paralelo de subagentes) usar
   `superpowers:using-git-worktrees`, que es un mecanismo independiente y combinable (un worktree
   puede tener a su vez su propia rama efímera adentro).

## Relación con otras skills
`repo-updater` (audita/commitea sobre la rama efímera activa), `pytest-focas`, `alembic-migrations`,
`docker-rebuild`, `cierre-sesion` (único punto que integra la rama efímera a `dev`).

## Resultado esperado
Rama efímera confirmada (nunca `dev`/`main` en el momento de commitear), `.env.dev` presente, stack
`lasfocasdev` correcto, ningún cambio accidental en producción, push a `origin/<rama-efímera>`.
```

- [ ] **Step 2: Verificar el reemplazo**

Run:
```bash
grep -n "está prohibido modificar código o commitear ahí" .agentes-comunes/skills/dev-workflow/SKILL.md
grep -n "git push -u origin HEAD" .agentes-comunes/skills/dev-workflow/SKILL.md
grep -c "git push origin dev" .agentes-comunes/skills/dev-workflow/SKILL.md
```
Expected: las dos primeras devuelven una línea cada una; la tercera devuelve `0` (ya no debe quedar
ningún `git push origin dev` literal en el archivo).

- [ ] **Step 3: Commit**

```bash
git add .agentes-comunes/skills/dev-workflow/SKILL.md
git commit -m "feat(dev-workflow): rama efímera obligatoria, prohibido commit directo en dev/main"
```

---

### Task 2: `dev-workflow` — mirrors (`.github`, `.codex-skills`, `.gemini`, nuevo `.claude`)

**Files:**
- Modify: `.github/skills/dev-workflow/SKILL.md`
- Modify: `.codex-skills/skills/las-focas-dev-workflow/SKILL.md`
- Modify: `.gemini/rules/skill-dev-workflow.md`
- Create: `.claude/skills/dev-workflow/SKILL.md`

**Interfaces:**
- Consumes: el cuerpo final de la Tarea 1 (sección `# Habilidad: Dev Workflow —` en adelante, texto idéntico).

- [ ] **Step 1: `.github/skills/dev-workflow/SKILL.md`**

Reemplazar todo el archivo por el mismo contenido de la Tarea 1, cambiando únicamente la línea 2
(`# Ubicación de archivo: .github/skills/dev-workflow/SKILL.md`) y agregando a la línea 3 el sufijo
`" — mirror de .agentes-comunes/skills/dev-workflow/SKILL.md (fuente de verdad)"` (mismo patrón que
ya usa `.github/skills/repo-updater/SKILL.md`). El resto del cuerpo (frontmatter + `# Habilidad:` en
adelante) es idéntico byte a byte al de la Tarea 1.

- [ ] **Step 2: `.codex-skills/skills/las-focas-dev-workflow/SKILL.md`**

Reemplazar todo el archivo por:

```markdown
---
name: "las-focas-dev-workflow"
description: "Usar SIEMPRE antes de ejecutar cambios de código, commits, push, operaciones Docker o actualizaciones de repo. Valida rama efímera activa, stack correcto y restricciones del entorno dev."
metadata:
  short-description: "Usar SIEMPRE antes de ejecutar cambios de código, commits, push, operaciones Docker o actualizaciones de repo. Valida..."
  source: ".agentes-comunes/skills/dev-workflow/SKILL.md"
  triggers:
    - "dev-workflow"
    - "habilidad"
    - "dev"
    - "workflow"
    - "protocolo"
    - "trabajo"
    - "entorno"
    - "rama"
    - "efimera"
    - "siempre"
    - "antes"
    - "ejecutar"
    - "cambios"
    - "c-digo"
    - "commits"
    - "push"
    - "operaciones"
    - "docker"
    - "actualizaciones"
    - "repo"
  globs:
    - "**/*"
  commands:
    - |
      git branch --show-current
    - |
      git fetch origin
      git checkout -b <tipo>/<slug-kebab-case> origin/dev
      # Si dev no existe en el remoto:
      git checkout -b dev
      git push -u origin dev
    - |
      test -f .env.dev && echo "OK" || echo "FALTA .env.dev"
    - |
      cp deploy/env.dev.sample .env.dev
      echo "IMPORTANTE: Completar SLACK_BOT_TOKEN y SLACK_APP_TOKEN en .env.dev antes de continuar."
    - |
      # Siempre verificar rama antes de commitear
      git branch --show-current  # debe ser <tipo>/<slug>, nunca dev ni main

      git add .
      git commit -m "<tipo>(módulo): descripción técnica"
      git push -u origin HEAD     # NUNCA: git push origin dev ni git push origin main directamente
---

# Nombre de archivo: SKILL.md
# Ubicación de archivo: .codex-skills/skills/las-focas-dev-workflow/SKILL.md
# Descripción: Skill portable Codex migrada desde .github/skills/dev-workflow/SKILL.md

# Skill portable: dev-workflow

> Fuente original: `.agentes-comunes/skills/dev-workflow/SKILL.md`. Copia portable generada porque `.codex/` está montado como solo lectura en esta sesión.

# Habilidad: Dev Workflow — Protocolo de Trabajo en Entorno Dev

Protocolo de validación y operación para garantizar que todos los cambios se realicen sobre una rama
efímera derivada del entorno de desarrollo aislado (`dev`), nunca directo sobre `dev` ni sobre
producción.

## Cuándo usar

Invocar esta skill **siempre** que el agente vaya a:

- Modificar código fuente, configuración o documentación
- Ejecutar commits o push
- Operar el stack Docker (`up`, `build`, `exec`, `logs`)
- Actualizar el repositorio (invocar `repo-updater`)
- Crear o modificar migraciones Alembic
- Ejecutar tests que requieran la base de datos

## Procedimiento de validación (ejecutar en orden)

### 1. Verificar rama activa

```bash
git branch --show-current
```

- Si es una rama efímera vigente (`feat/*`, `fix/*`, `docs/*`, `chore/*`, `refactor/*`, `test/*`): continuar.
- Si devuelve `dev` o `main`: **está prohibido commitear ahí**. Crear una rama efímera antes de
  cualquier cambio:

```bash
git fetch origin
git checkout -b <tipo>/<slug-kebab-case> origin/dev
# Si dev no existe en el remoto:
git checkout -b dev
git push -u origin dev
```

### 2. Verificar que `.env.dev` existe

```bash
test -f .env.dev && echo "OK" || echo "FALTA .env.dev"
```

Si no existe, crear desde el sample:

```bash
cp deploy/env.dev.sample .env.dev
echo "IMPORTANTE: Completar SLACK_BOT_TOKEN y SLACK_APP_TOKEN en .env.dev antes de continuar."
```

### 3. Comandos Docker correctos en dev

| Operación | Comando correcto en dev |
|-----------|------------------------|
| Levantar stack | `./scripts/start_dev.sh` |
| Levantar sin rebuild | `./scripts/start_dev.sh --no-build` |
| Detener stack | `docker compose -f deploy/docker-compose.dev.yml down` |
| Ver logs | `docker compose -f deploy/docker-compose.dev.yml logs -f [servicio]` |
| Ejecutar comando en contenedor | `docker compose -f deploy/docker-compose.dev.yml exec <svc> <cmd>` |
| Clonar DB prod → dev | `./scripts/start_dev.sh --clone-db` |

> **NUNCA** usar `docker compose -f deploy/compose.yml` para pruebas o desarrollo. Ese archivo es exclusivo de producción.

### 4. Commits y push

```bash
# Siempre verificar rama antes de commitear
git branch --show-current  # debe ser <tipo>/<slug>, nunca dev ni main

git add .
git commit -m "<tipo>(módulo): descripción técnica"
git push -u origin HEAD     # NUNCA: git push origin dev ni git push origin main directamente
```

La integración a `dev` ocurre exclusivamente vía `cierre-sesion` (auto-merge) o, para ramas
deliberadamente diferidas, vía `superpowers:finishing-a-development-branch`.

### 5. Restricciones sobre archivos de producción

Los siguientes archivos **no deben modificarse** sin aprobación explícita del Tech Lead:

- `deploy/compose.yml`
- `.env` (en raíz del proyecto)
- Cualquier secreto o token de producción

Si el cambio requiere tocar producción, documentarlo en `docs/decisiones.md` y crear un PR formal.

## Guardrails

1. **No commitear ni pushear** estando parado en `dev` o `main`. Todo trabajo ocurre en una rama efímera creada desde `origin/dev`. Regla universal, sin excepciones.
2. **No hacer push a `origin/main`** sin PR revisado que venga de `dev`.
3. **No usar `--force`** ni comandos destructivos sin pedido explícito del usuario.
4. **No commitear** archivos `.env`, `.env.dev`, `Keys/`, `*.pem`, `*.key` ni binarios generados.
5. Si detectás que estás en `main`: crear la rama efímera desde `origin/dev` antes de proceder, no cherry-pickear a ciegas.
6. La operación `git push origin main` está **prohibida** desde el agente salvo instrucción explícita y confirmación del usuario.
7. Una rama efímera es un `git checkout -b`, no un worktree nuevo — para aislamiento de directorio usar `superpowers:using-git-worktrees` (mecanismo independiente y combinable).

## Relación con otras skills

| Skill | Cuándo invocar |
|-------|---------------|
| `repo-updater` | Para auditar y commitear cambios — pushea a la rama efímera activa |
| `pytest-focas` | Para correr tests — siempre en entorno dev |
| `alembic-migrations` | Para migraciones — ejecutar en contenedor `lasfocasdev-api` |
| `docker-rebuild` | Para rebuild selectivo — usar con compose dev |
| `cierre-sesion` | Único punto que integra la rama efímera a `dev` |

## Resultado esperado

- Rama efímera activa confirmada (nunca `dev`/`main` al commitear)
- `.env.dev` presente
- Stack correcto identificado (`lasfocasdev`)
- Ningún cambio accidental en archivos de producción
- Push apuntando a `origin/<rama-efímera>`
```

- [ ] **Step 3: `.gemini/rules/skill-dev-workflow.md`**

Leer el archivo actual primero. Aplicar el mismo patrón de frontmatter Gemini (`name`, `description`,
`source`, `triggers`, `globs`, `commands`) y banner `"> Fuente original: ..."` que ya tiene hoy, pero
con: (a) el bloque `commands:` actualizado al mismo contenido del Step 2 de esta tarea (los 5 bloques
de comandos, con el nuevo paso 1 de creación de rama y el nuevo paso 4 de push), (b) el cuerpo
(`# Habilidad: Dev Workflow —` en adelante) reemplazado por el mismo texto de la Tarea 1. Agregar
`"rama"` y `"efimera"` a la lista de `triggers` si no están.

- [ ] **Step 4: crear `.claude/skills/dev-workflow/SKILL.md`** (archivo nuevo — cierra el gap de que este skill hoy no es invocable por el tool `Skill`)

```markdown
# Nombre de archivo: SKILL.md
# Ubicación de archivo: .claude/skills/dev-workflow/SKILL.md
# Descripción: Habilidad para protocolo de rama efímera y entorno dev (mirror de .agentes-comunes/skills/dev-workflow/SKILL.md — fuente de verdad)

---
name: dev-workflow
description: "Usar SIEMPRE antes de ejecutar cambios de código, commits, push, operaciones Docker o actualizaciones de repo. Valida rama efímera activa, stack correcto y restricciones del entorno dev."
argument-hint: "Contexto de la tarea, por ejemplo: implementar feature X en el módulo Y"
---

# Habilidad: Dev Workflow — Protocolo de Trabajo en Entorno Dev

Protocolo de validación y operación para garantizar que todos los cambios se realicen sobre una rama
efímera derivada del entorno de desarrollo aislado (`dev`), nunca directo sobre `dev` ni sobre
producción.

## Cuándo usar
Invocar esta skill **siempre** que el agente vaya a: modificar código/config/docs, ejecutar commits o push, operar Docker (up/build/exec/logs), actualizar el repo (repo-updater), crear/modificar migraciones Alembic, ejecutar tests que requieran DB.

## Procedimiento de validación (ejecutar en orden)

1. Verificar rama activa (`git branch --show-current`).
   - Si es una rama efímera vigente (prefijo `feat/`, `fix/`, `docs/`, `chore/`, `refactor/` o
     `test/`): continuar, es la rama de trabajo de esta tarea.
   - Si es `dev` o `main`: **está prohibido modificar código o commitear ahí**. Crear una rama
     efímera nueva desde el estado remoto de `dev` antes de cualquier cambio:
     ```bash
     git fetch origin
     git checkout -b <tipo>/<slug-kebab-case> origin/dev
     ```
     `<tipo>` = `feat|fix|docs|chore|refactor|test` según la naturaleza del cambio; `<slug>` describe
     la tarea en minúsculas y guiones (mismo criterio que ya se usa en `<tipo>(módulo): descripción`
     para mensajes de commit).
   - Si `dev` no existe en el remoto: crearla primero (`git checkout -b dev && git push -u origin dev`)
     y recién ahí crear la rama efímera.
   - Si ya existe una rama efímera vigente para esta misma tarea, reutilizarla — no crear ramas
     anidadas dentro de una sesión.
2. Verificar que `.env.dev` existe; si no, crearlo desde `deploy/env.dev.sample`.
3. Comandos Docker correctos en dev (tabla `start_dev.sh`, `docker-compose.dev.yml`, etc.). **NUNCA**
   usar `docker compose -f deploy/compose.yml` para pruebas/desarrollo.
4. **Commits y push** (siempre sobre la rama efímera activa, nunca sobre `dev`/`main`):
   ```bash
   git branch --show-current  # debe ser <tipo>/<slug>, nunca dev ni main
   git add .
   git commit -m "<tipo>(módulo): descripción técnica"
   git push -u origin HEAD     # NUNCA: git push origin dev ni git push origin main directamente
   ```
   La integración a `dev` ocurre exclusivamente vía `cierre-sesion` (flujo de auto-merge al cierre) o,
   para ramas deliberadamente diferidas (ej. ventana de mantenimiento), vía
   `superpowers:finishing-a-development-branch`.
5. Restricciones sobre archivos de producción (`deploy/compose.yml`, `.env`, secretos) — requieren aprobación explícita del Tech Lead; si se necesita, documentar en `docs/decisiones.md` y crear PR formal.

## Guardrails
1. No commitear ni pushear estando parado en `dev` o `main`. Todo trabajo ocurre en una rama efímera
   creada desde `origin/dev` (paso 1). Esta regla es universal — sin excepciones por tipo de tarea.
2. No hacer push a `origin/main` sin PR revisado que venga de `dev`.
3. No usar `--force` ni comandos destructivos sin pedido explícito del usuario.
4. No commitear `.env`, `.env.dev`, `Keys/`, `*.pem`, `*.key` ni binarios generados.
5. Si detectás que estás en `main`: no cherry-pickees a ciegas — crear la rama efímera desde
   `origin/dev` (paso 1) y evaluar si los cambios locales en `main` corresponden a esa tarea.
6. `git push origin main` está **prohibida** desde el agente salvo instrucción explícita y confirmación del usuario.
7. Una rama efímera es un `git checkout -b` dentro del mismo checkout de trabajo — **no** es un
   worktree nuevo. Para aislamiento real de directorio (ej. trabajo paralelo de subagentes) usar
   `superpowers:using-git-worktrees`, que es un mecanismo independiente y combinable (un worktree
   puede tener a su vez su propia rama efímera adentro).

## Relación con otras skills
`repo-updater` (audita/commitea sobre la rama efímera activa), `pytest-focas`, `alembic-migrations`,
`docker-rebuild`, `cierre-sesion` (único punto que integra la rama efímera a `dev`).

## Resultado esperado
Rama efímera confirmada (nunca `dev`/`main` en el momento de commitear), `.env.dev` presente, stack
`lasfocasdev` correcto, ningún cambio accidental en producción, push a `origin/<rama-efímera>`.
```

- [ ] **Step 5: Verificar**

```bash
for f in .github/skills/dev-workflow/SKILL.md .codex-skills/skills/las-focas-dev-workflow/SKILL.md .gemini/rules/skill-dev-workflow.md .claude/skills/dev-workflow/SKILL.md; do
  echo "== $f =="; grep -c "está prohibido" "$f"; grep -c "git push -u origin HEAD" "$f"
done
ls .claude/skills/dev-workflow/SKILL.md
```
Expected: cada archivo devuelve al menos 1 para ambos greps; el `ls` confirma que el archivo nuevo existe.

- [ ] **Step 6: Commit**

```bash
git add .github/skills/dev-workflow/SKILL.md .codex-skills/skills/las-focas-dev-workflow/SKILL.md .gemini/rules/skill-dev-workflow.md .claude/skills/dev-workflow/SKILL.md
git commit -m "feat(dev-workflow): propaga rama efímera obligatoria a mirrors, agrega mirror .claude/skills"
```

---

### Task 3: `repo-updater` — fuente de verdad

**Files:**
- Modify: `.agentes-comunes/skills/repo-updater/SKILL.md`

**Interfaces:**
- Consumes: convención de rama efímera de la Tarea 1 (prefijos `feat/`, `fix/`, etc.).
- Produces: el texto exacto del nuevo paso 1 y paso 8 — la Tarea 4 lo replica en sus mirrors.

- [ ] **Step 1: Reemplazar el contenido completo del archivo**

Reemplazar TODO el contenido de `.agentes-comunes/skills/repo-updater/SKILL.md` por:

```markdown
# Nombre de archivo: SKILL.md
# Ubicación de archivo: .agentes-comunes/skills/repo-updater/SKILL.md
# Descripción: Skill para sincronizar el repositorio con validación documental, commit técnico y push a la rama efímera activa (la integración a dev es automática al cierre de sesión)

---
name: repo-updater
description: "Usar cuando haya que auditar docs/PR y docs temáticas, preparar commit técnico con git y subir cambios a la rama efímera activa (nunca dev/main directo — ver dev-workflow y cierre-sesion)"
argument-hint: "Describe alcance o contexto, por ejemplo: sincronizar cambios de web y docs en la rama efímera activa"
---

# Habilidad: Actualizador de Repositorio

Workflow invocable para validar trazabilidad, completar documentación faltante y ejecutar el flujo de `git` de punta a punta usando la CLI del sistema.

## Cuándo usar

Usar esta skill cuando el usuario pida:

- sincronizar cambios locales con la rama efímera activa (creada por `dev-workflow` — nunca `dev`, nunca `main`, nunca un worktree de prod)
- auditar si el diff quedó reflejado en `docs/PR/` y en la documentación de `docs/`
- generar commit técnico alineado al diff real
- hacer `git add`, `git commit` y `git push` sin omitir trazabilidad

## Procedimiento

1. Confirmar el worktree/rama de destino ANTES de tocar nada: `git rev-parse --abbrev-ref HEAD` debe
   ser una rama efímera activa (prefijo `feat/`, `fix/`, `docs/`, `chore/`, `refactor/` o `test/` —
   nunca `dev` ni `main`, ver `dev-workflow`), y `git rev-parse --show-toplevel` debe ser el checkout
   real de trabajo del proyecto, no un worktree aislado (de investigación, de un agente en
   `isolation: "worktree"`, o de prod). Ver guardrail 6 — esto es una regla dura, no una preferencia.
2. Ejecutar inspección con CLI de git para comparar el estado local contra `dev`:
   - `git fetch origin dev`
   - `git status --short --branch`
   - `git diff --stat`
   - `git diff --cached --stat`
   - `git log --oneline origin/dev..HEAD`
3. Si `git status` mezcla archivos que la sesión actual no tocó con archivos que sí (trabajo previo de
   otra sesión, sin commitear), no asumir "todo junto" ni "sólo lo mío": preguntarle al usuario cómo
   separar el commit. Ver guardrail 7 para la técnica de separación por hunk cuando un mismo archivo
   tiene cambios de ambos orígenes.
4. Determinar la fecha actual en formato `YYYY-MM-DD` y localizar `docs/PR/YYYY-MM-DD.md`.
5. Mapear los archivos cambiados (los que correspondan al commit que se está preparando, ver paso 3)
   contra la documentación temática afectada dentro de `docs/`.
6. Si el diff no está documentado, actualizar primero el PR diario y luego la documentación temática
   correspondiente.
7. Generar un mensaje de commit técnico, breve y semántico a partir del diff real de ESE commit (no
   de todo `git status` si el paso 3 determinó separar en varios).
8. Ejecutar `git add` (de los archivos/hunks que correspondan a este commit — nunca `git add .` a
   ciegas si el paso 3 detectó una mezcla), `git commit` y `git push -u origin HEAD` (empuja la rama
   efímera activa, cualquiera sea su nombre — nunca `git push origin dev` ni `git push origin main`).

## Cobertura documental mínima

- `api/`, `api_app/` -> `docs/api.md`
- `web/` -> `docs/web.md`
- `bot_telegram/` -> `docs/bot.md`
- `db/` -> `docs/db.md`
- `core/chatbot/`, `core/mcp/` -> `docs/chatbot.md`, `docs/mcp.md`
- `modules/informes_*` -> `docs/informes/`
- `deploy/`, seguridad, secretos o exposición -> `docs/Seguridad.md`, `docs/infra.md`, `docs/decisiones.md` según aplique
- `.github/` y ecosistema agéntico -> `docs/Mate_y_Ruta.md` y PR diario vigente

## Referencias

- [Prompt asociado](../../prompts/repo-updater.prompt.md)
- [Prompt de PR diario](../../prompts/generar-pr-diario.prompt.md)

## Guardrails

1. Usar la CLI de `git` del sistema; no simular el flujo ni inventar resultados.
2. No commitear secretos, credenciales, binarios accidentales ni archivos temporales.
3. No omitir `docs/PR/YYYY-MM-DD.md` si hubo cambios reales en el workspace.
4. No redactar commits genéricos como "update" o "cambios varios"; el mensaje debe reflejar el diff real.
5. No hacer `push --force` ni comandos destructivos sin pedido explícito.
6. **Regla dura, confirmada explícitamente por el usuario (2026-08-25)**: este skill siempre commitea
   en el worktree real de trabajo del proyecto — nunca en un worktree de prod, ni en uno creado para
   una investigación o tarea aislada (`superpowers:using-git-worktrees`, `isolation: "worktree"` de
   un agente, `EnterWorktree`). Los prompts e investigaciones de este proyecto usan siempre ese
   worktree (sobre una rama efímera, ver `dev-workflow`); si el directorio actual no es ese worktree,
   detenerse y decírselo al usuario en vez de commitear donde sea que se esté parado.
7. Si el working tree mezcla trabajo de la sesión actual con trabajo previo sin commitear de otro
   origen (otra sesión, otro agente), no bundlear todo en un commit por default: preguntar al usuario
   cómo separar (confirmado 2026-08-25: la opción preferida suele ser 2+ commits separados, uno por
   cuerpo de trabajo). Cuando un mismo archivo tiene hunks de ambos orígenes (ej. dos sesiones
   distintas editaron el mismo archivo de endpoints o el mismo `docs/decisiones.md`), separar así:
   1. `git diff -- <archivo>` y ubicar los encabezados `@@ -a,b +c,d @@` propios por número de línea.
   2. Armar un patch sólo con esos hunks (header `diff --git`/`index`/`---`/`+++` + los hunks elegidos).
   3. `git apply --cached --check <patch>` para validar ANTES de aplicar de verdad.
   4. `git apply --cached <patch>` — actualiza el índice sin tocar el working tree.
   5. Repetir para cada archivo compartido, `git add` el resto de archivos 100% propios, commitear.
   6. El diff restante contra el nuevo `HEAD` (para el/los otro(s) commit(s)) sale limpio solo, sin
      trabajo manual adicional.

## Resultado esperado

- Confirmado que el commit se hizo en el worktree real de trabajo, sobre una rama efímera (nunca
  prod ni un worktree aislado, nunca `dev`/`main` directo).
- Diff auditado contra `dev` (el estado remoto real, `origin/dev`).
- PR diario actual localizado o creado para la fecha vigente.
- Documentación temática alineada con los cambios.
- Commit(s) técnico(s) generado(s) desde el diff real — separados si el working tree mezclaba más de
  un origen de trabajo.
- Push exitoso a `origin/<rama-efímera-activa>` o bloqueo explícito documentado. La integración a
  `dev` es responsabilidad exclusiva de `cierre-sesion` (flujo de auto-merge).

> **Guardrail**: `git push origin main` está **prohibido** desde este skill. Los merges a `main` se realizan solo mediante Pull Request revisado desde `dev`.
```

- [ ] **Step 2: Verificar**

```bash
grep -n "git push -u origin HEAD" .agentes-comunes/skills/repo-updater/SKILL.md
grep -n "Regla dura, confirmada explícitamente por el usuario (2026-08-25)" .agentes-comunes/skills/repo-updater/SKILL.md
grep -c "git push origin dev$" .agentes-comunes/skills/repo-updater/SKILL.md
```
Expected: primeras dos devuelven 1 línea cada una (confirmando que el guardrail de worktree del
2026-08-25 se preservó); la tercera devuelve `0`.

- [ ] **Step 3: Commit**

```bash
git add .agentes-comunes/skills/repo-updater/SKILL.md
git commit -m "feat(repo-updater): push a la rama efímera activa en vez de dev directo"
```

---

### Task 4: `repo-updater` — mirrors (`.github` skill+prompt, `.claude` comando, `.gemini` x2, `.codex-skills`)

**Files:**
- Modify: `.github/skills/repo-updater/SKILL.md`
- Modify: `.claude/commands/repo-updater.md`
- Modify: `.github/prompts/repo-updater.prompt.md`
- Modify: `.gemini/rules/skill-repo-updater.md`
- Modify: `.gemini/rules/prompt-repo-updater-prompt.md`
- Modify: `.codex-skills/skills/las-focas-repo-updater/SKILL.md`

**Interfaces:**
- Consumes: el cuerpo final de la Tarea 3.

- [ ] **Step 1: `.github/skills/repo-updater/SKILL.md`**

Mismo contenido que la Tarea 3, cambiando sólo la línea 2 (`Ubicación de archivo`) y agregando el
sufijo de mirror ya existente en línea 3 ("— mirror de .agentes-comunes/skills/repo-updater/SKILL.md
(fuente de verdad)"), igual que hoy.

- [ ] **Step 2: `.claude/commands/repo-updater.md`**

Reemplazar todo el archivo por:

```markdown
# Nombre de archivo: repo-updater.md
# Ubicación de archivo: .claude/commands/repo-updater.md
# Descripción: Comando Claude Code para auditar trazabilidad, documentar cambios y hacer push a la rama efímera activa

Actuar como actualizador autónomo del repositorio LAS-FOCAS. Argumento opcional del usuario: $ARGUMENTS

# Rol

Validar trazabilidad entre el diff real, el PR diario vigente y la documentación temática. Completar documentación faltante y sincronizar el estado local con la rama efímera activa.

# Contexto

- El repositorio exige que los cambios reales queden reflejados en `docs/PR/YYYY-MM-DD.md` y, si corresponde, en la documentación temática bajo `docs/`.
- La fecha del PR diario debe identificarse dinámicamente con la fecha actual del sistema en formato `YYYY-MM-DD`.
- Los commits deben ser técnicos, concisos y coherentes con el diff real.
- Si el cambio toca `.github/` o `.claude/`, la documentación mínima es `docs/Mate_y_Ruta.md` además del PR diario.
- La rama objetivo es la rama efímera activa (`feat/`, `fix/`, `docs/`, `chore/`, `refactor/` o `test/`, creada por `dev-workflow`) — nunca `dev` ni `main` directo. La integración a `dev` es responsabilidad exclusiva de `cierre-sesion`.
- El commit siempre se hace en el worktree real de `dev` — nunca en un worktree de prod ni en uno
  creado para una investigación o tarea aislada (regla dura, ver Reglas #5).

# Pasos

1. Confirmar el worktree/rama de destino ANTES de tocar nada: `git rev-parse --abbrev-ref HEAD` debe
   ser una rama efímera activa (nunca `dev`, nunca `main` — ver `dev-workflow`), y
   `git rev-parse --show-toplevel` debe ser el checkout real de trabajo, no un worktree aislado (de
   investigación, de un agente en `isolation: "worktree"`, o de prod). Regla dura, ver Reglas #5 — si
   estás en `dev`/`main`, detenerse y avisar en vez de commitear ahí; usar `dev-workflow` para crear
   la rama efímera primero.
2. Inspeccionar el estado real del repositorio:
   ```bash
   git fetch origin dev
   git status --short --branch
   git diff --stat
   git diff --cached --stat
   git diff --name-status
   git log --oneline origin/dev..HEAD
   ```
3. Si `git status` mezcla archivos que esta sesión no tocó con archivos que sí (trabajo previo de
   otra sesión sin commitear), no asumir "todo junto": preguntar al usuario cómo separar el commit.
   Ver Reglas #6 para la técnica de separación por hunk cuando un mismo archivo tiene cambios de
   ambos orígenes.
4. Determinar la fecha actual y ubicar `docs/PR/YYYY-MM-DD.md`. Si no existe, crearlo con encabezado obligatorio de 3 líneas.
5. Analizar si el diff real (el de este commit, según el paso 3) ya está documentado en el PR diario y en la documentación temática de `docs/`.
6. Si falta trazabilidad, actualizar antes de continuar:
   - `docs/PR/YYYY-MM-DD.md`
   - documentación temática según el área impactada:
     - `docs/api.md` para `api/`
     - `docs/web.md` para `web/`
     - `docs/bot.md` para `bot_telegram/`
     - `docs/db.md` para `db/`
     - `docs/chatbot.md` y `docs/mcp.md` para `core/chatbot/` o `core/mcp/`
     - `docs/informes/` para `modules/informes_*`
     - `docs/Seguridad.md`, `docs/infra.md` o `docs/decisiones.md` si hay impacto operativo o de arquitectura
     - `docs/Mate_y_Ruta.md` si el cambio afecta `.github/`, `.claude/`, prompts, skills o agentes
7. Verificar que la documentación nueva o actualizada contraste con el estado actual del código. Corregir información vieja o inconsistente aunque no sea el foco principal.
8. Construir un mensaje de commit técnico y semántico derivado del diff real de ESE commit. Evitar `update`, `misc`, `fix stuff` o equivalentes.
9. Ejecutar el flujo de versionado (si el paso 3 determinó separar, repetir add+commit por cada cuerpo de trabajo antes del push):
   ```bash
   git add .   # o los archivos/hunks que correspondan a este commit, nunca a ciegas si hay mezcla
   git commit -m "<mensaje_tecnico>"
   git push -u origin HEAD   # NUNCA: git push origin dev ni git push origin main directamente
   ```
10. Si `git push` falla por divergencia, no hacer `push --force`. Explicar el bloqueo y, si es seguro, preparar resolución con `git pull --rebase origin <rama-efímera-activa>`.
11. Entregar un cierre corto: archivos actualizados, mensaje(s) de commit, resultado del push y riesgos o pendientes. Recordar que la integración a `dev` ocurre en `cierre-sesion`, no acá.

# Criterios de Aceptación

- [ ] Confirmado que el commit se hizo en el worktree real de trabajo, sobre una rama efímera (nunca prod ni un worktree aislado, nunca `dev`/`main` directo)
- [ ] Estado del repo inspeccionado con `git status` y `git diff`
- [ ] Si el working tree mezclaba orígenes distintos, se preguntó al usuario cómo separar antes de commitear
- [ ] PR diario correspondiente a la fecha actual identificado y actualizado
- [ ] Diff contrastado contra `docs/PR/` y documentación temática
- [ ] Commit(s) técnico(s) y conciso(s) que describe(n) el diff real
- [ ] `git push -u origin HEAD` ejecutado sobre la rama efímera activa, o bloqueo real documentado

# Reglas

1. No inventar validaciones, commits ni pushes que no hayan ocurrido.
2. No incluir secretos, tokens ni credenciales en documentación ni commits.
3. No usar `git reset --hard` ni `git push --force` sin pedido explícito.
4. Mantener todo el contenido en español técnico.
5. **Regla dura (confirmada explícitamente por el usuario, 2026-08-25)**: siempre commitear en el
   worktree real de trabajo del proyecto, nunca en uno de prod ni en uno creado para una investigación
   o tarea aislada (`superpowers:using-git-worktrees`, `isolation: "worktree"`, `EnterWorktree`) — los
   prompts e investigaciones de este proyecto usan siempre ese worktree, sobre una rama efímera.
6. Si el working tree mezcla trabajo de la sesión actual con trabajo previo sin commitear de otro
   origen, preguntar cómo separar en vez de `git add .` por default. Para un archivo compartido con
   hunks de ambos orígenes: extraer con `git diff -- <archivo>` los hunks propios (por número de
   línea y encabezado `@@`), armar un patch sólo con esos hunks, validar con
   `git apply --cached --check <patch>`, aplicar con `git apply --cached <patch>` (no toca el working
   tree), `git add` el resto de archivos 100% propios y commitear — el diff restante contra el nuevo
   `HEAD` queda listo para el otro commit sin trabajo manual adicional.
7. Nunca hacer `git push origin dev` ni `git push origin main` directamente desde este comando — la
   integración a `dev` es responsabilidad exclusiva de `cierre-sesion`.
```

- [ ] **Step 3: `.github/prompts/repo-updater.prompt.md`**

Aplicar al archivo actual (ya leído — 106 líneas) los mismos cambios semánticos que el Step 2: título
de la línea 3, "Rol" (línea 14: "...sincronizar el estado local con la rama efímera activa" en vez de
"con la rama `dev`"), bullet de "Contexto" línea 22 (reemplazar "La rama objetivo por defecto es `dev`
y el push debe hacerse al remoto `origin`" por "La rama objetivo es la rama efímera activa creada por
`dev-workflow` — nunca `dev`/`main` directo; la integración a `dev` es responsabilidad de
`cierre-sesion`"), paso 1 (línea 32-35: reemplazar "debe ser `dev`" por "debe ser una rama efímera
activa, nunca `dev`/`main`"), paso 9 (línea 67-72: `git push origin dev` → `git push -u origin HEAD`),
paso 10 (línea 73: `git pull --rebase origin dev` → `git pull --rebase origin <rama-efímera-activa>`),
Criterios de Aceptación línea 82 y 89 (mismo ajuste de "rama `dev`" → "rama efímera activa"), Reglas
adicionales línea 97-99 (igual que Reglas #5 del Step 2 de esta tarea).

- [ ] **Step 4: `.gemini/rules/skill-repo-updater.md`**

Leer el archivo actual primero para confirmar su formato exacto de frontmatter (Gemini usa
`name`/`source`/`triggers`/`globs`/`commands` + banner `"> Fuente original: ..."`, igual que
`.gemini/rules/skill-dev-workflow.md`). Aplicar el mismo cuerpo final de la Tarea 3 (el `# Habilidad:
Actualizador de Repositorio` completo), y si el archivo tiene un bloque `commands:` en el frontmatter,
actualizarlo para reflejar `git push -u origin HEAD` en vez de `git push origin dev`.

- [ ] **Step 5: `.gemini/rules/prompt-repo-updater-prompt.md`**

Leer el archivo actual primero. Aplicar los mismos cambios semánticos del Step 3 (mirror del prompt
`.github/prompts/repo-updater.prompt.md`), preservando el formato de frontmatter que ya tenga este
archivo específico.

- [ ] **Step 6: `.codex-skills/skills/las-focas-repo-updater/SKILL.md`**

Leer el archivo actual primero (mismo patrón de frontmatter Codex que
`.codex-skills/skills/las-focas-dev-workflow/SKILL.md`: `name`, `metadata.short-description`,
`metadata.source`, `metadata.triggers`, `metadata.globs`, `metadata.commands`). Reemplazar el cuerpo
por el mismo contenido final de la Tarea 3, y actualizar el bloque `commands:` para usar
`git push -u origin HEAD` en vez de `git push origin dev`. Agregar `"rama"` y `"efimera"` a `triggers`
si no están.

- [ ] **Step 7: Verificar**

```bash
for f in .github/skills/repo-updater/SKILL.md .claude/commands/repo-updater.md .github/prompts/repo-updater.prompt.md .gemini/rules/skill-repo-updater.md .gemini/rules/prompt-repo-updater-prompt.md .codex-skills/skills/las-focas-repo-updater/SKILL.md; do
  echo "== $f =="; grep -c "git push -u origin HEAD" "$f"; grep -c "git push origin dev" "$f"
done
```
Expected: primer grep ≥1 en cada archivo; segundo grep `0` en cada archivo (ningún push literal a dev
directo debe quedar).

- [ ] **Step 8: Commit**

```bash
git add .github/skills/repo-updater/SKILL.md .claude/commands/repo-updater.md .github/prompts/repo-updater.prompt.md .gemini/rules/skill-repo-updater.md .gemini/rules/prompt-repo-updater-prompt.md .codex-skills/skills/las-focas-repo-updater/SKILL.md
git commit -m "feat(repo-updater): propaga push a rama efímera a todos los mirrors"
```

---

### Task 5: `cierre-sesion` — fuente de verdad

**Files:**
- Modify: `.agentes-comunes/skills/cierre-sesion/SKILL.md`

**Interfaces:**
- Consumes: convención de rama efímera (Tarea 1); tabla de riesgo de `docker-cleanup/SKILL.md` (ya existente, no se modifica ese archivo).
- Produces: el texto exacto de los pasos 10-15 (evolución agéntica, compuerta de riesgo, auto-merge, checklist final) — las Tareas 6 lo replican en sus mirrors.

- [ ] **Step 1: Reemplazar el contenido completo del archivo**

Reemplazar TODO el contenido de `.agentes-comunes/skills/cierre-sesion/SKILL.md` por:

```markdown
# Nombre de archivo: SKILL.md
# Ubicación de archivo: .agentes-comunes/skills/cierre-sesion/SKILL.md
# Descripción: Skill de cierre de sesión — retrospectiva técnica, evolución agéntica con compuerta de riesgo y auto-merge autónomo de la rama efímera a dev

---
name: cierre-sesion
description: "Usar al finalizar una sesión de trabajo, sólo con declaración explícita de cierre, para generar una retrospectiva técnica, evaluar evolución agéntica del entorno y mergear automáticamente la rama efímera activa a dev"
argument-hint: "Palabra clave de cierre (ej. 'Cerrar sesión') o alcance/fecha"
---

# Habilidad: Cierre de Sesión

Workflow invocable para analizar la conversación activa al finalizar el trabajo, extraer conocimiento
técnico factual que retroalimente el ecosistema de agentes del proyecto, y — como paso final —
integrar automáticamente la rama efímera de la sesión a `dev`.

## Cuándo usar

Usar esta skill sólo cuando el usuario declara explícitamente el fin de la sesión:

- invoca `/cierre-sesion` explícitamente, o
- escribe una frase inequívoca de cierre: "Cerrar sesión", "Cerremos sesión", "Cierre chat", "cierre
  de sesión", "terminamos la sesión", "este es el cierre del chat", "cerrá la sesión con una
  retrospectiva"

**No** activar por sólo nombrar la skill al pasar, completar una tarea, pedir estado o solicitar
documentación. Si un trigger heurístico dispara esta skill sin ese gate cumplido, no elaborar ni
persistir la retrospectiva: continuar la tarea normal e indicar en una línea que el cierre queda
reservado para cuando se declare explícitamente.

## Procedimiento

1. Confirmar el gate de activación. Si no se cumple, no continuar con los pasos siguientes.
2. Leer `AGENTS.md`, el historial disponible de la conversación activa, resultados de tool calls, el
   diff actual (`git status`/`git diff`) y la documentación de dominio afectada. Declarar cualquier
   límite de evidencia detectado (p.ej. contexto truncado por compactación automática).
3. Delimitar qué cambios son propios de esta sesión, cuáles son preexistentes del worktree y cuáles
   son acciones externas.
4. Contrastar cada tarea supuestamente terminada contra código, tests, logs, estado del sistema o
   documentación. Clasificarla como completada, parcial, bloqueada o no verificada.
5. Documentar errores, bloqueos o problemas post-implementación realmente enfrentados: síntoma, causa
   raíz confirmada o hipótesis explícita, impacto.
6. Detallar con precisión reutilizable la solución aplicada a cada error/bloqueo: archivo/componente,
   decisión técnica, validación ejecutada, condición que indicaría una regresión futura (o marcar sin
   resolver).
7. Revisar vigencia: corregir documentación desactualizada cuando la evidencia la contradiga. Corregir
   lógica fuera de la tarea principal sólo si está verificado y autorizado; si no, registrar como
   pendiente concreto.
8. Evaluar mejoras agénticas en dos carriles — prevención (obstáculos reales de esta sesión) y
   aceleración (pasos repetibles observados que agilizarían implementaciones similares futuras). Por
   cada candidata: evidencia, frecuencia esperada, beneficio, costo de mantenimiento y opción
   recomendada, prefiriendo ampliar una skill existente.
9. Determinar la fecha actual (`YYYY-MM-DD`).
10. Clasificar cada propuesta de evolución agéntica del paso 8 con esta tabla de riesgo (mismo patrón
    ya usado en `docker-cleanup/SKILL.md`, no se inventa taxonomía nueva):

    | Riesgo | Criterio | Acción |
    |---|---|---|
    | 🟢 Bajo | Agrega guardrail, corrige doc, amplía un skill existente sin tocar permisos de `main`/producción ni introducir un mecanismo de push/merge nuevo | Se implementa en este mismo cierre |
    | 🟡 Medio | Ídem, pero con superficie de cambio mayor (varios archivos/skills) o que toca un flujo ya en uso activo | Se implementa en este mismo cierre |
    | 🔴 Muy alto | Toca permisos sobre `main`/producción, debilita un guardrail existente, o introduce un mecanismo de push/merge automático nuevo no cubierto ya por una skill vigente | Se detiene el flujo (ver paso 11) |

11. **Compuerta de Riesgo**: si al menos una propuesta quedó clasificada 🔴, presentar su estado (qué
    cambiaría y por qué se clasificó así), preguntar explícitamente al usuario si se avanza, y
    **detener el flujo completo** (no continuar a los pasos 12-15) hasta recibir una respuesta. Si
    todas las propuestas son 🟢/🟡 o no hay propuestas, continuar sin pausas.
12. Implementar las propuestas 🟢/🟡 de evolución agéntica aprobadas (crear/editar skills, comandos o
    guardrails). Si la propuesta crea o edita un skill, seguir `superpowers:writing-skills` para su
    estructura y validación. Registrar con precisión qué archivos de gobernanza se tocaron y por qué
    — esto va en el reporte del paso 13, no sólo en el checklist final (mitiga que el mismo agente que
    propone sea quien clasifica su propio riesgo).
13. Crear o anexar `docs/cierres/YYYY-MM-DD.md` sin perder cierres previos del mismo día, con el
    reporte completo (tareas, errores/soluciones, evolución agéntica implementada/propuesta y su
    clasificación de riesgo, archivos de gobernanza tocados) y confirmar la ruta del archivo guardado.
14. **Flujo de Auto-Merge** — integrar la rama efímera activa de esta sesión a `dev`:
    ```bash
    git checkout <rama-efímera-actual>
    git fetch origin
    git merge origin/dev
    ```
    Si `git diff --name-only --diff-filter=U` devuelve archivos en conflicto: leer los marcadores
    `<<<<<<<`/`=======`/`>>>>>>>`, entender la lógica de ambos lados y resolver reescribiendo
    correctamente, luego `git add .`. El commit de fusión resultante debe documentar en su mensaje
    qué archivos tuvieron conflicto y el criterio de resolución aplicado (trazabilidad posterior, no
    es un gate de aprobación). Si no hubo conflictos, el merge es directo. Luego:
    ```bash
    git checkout dev
    git pull origin dev
    git merge <rama-efímera-actual>
    git push origin dev
    git branch -d <rama-efímera-actual>
    git push origin --delete <rama-efímera-actual>
    ```
    **Excepción**: si en esta misma sesión el usuario indicó explícitamente que esta rama debe
    diferirse (ej. ventana de mantenimiento — precedente real: `fix-baneos-hermanos-prod`), no forzar
    este flujo. Dejar la rama activa sin mergear, documentarlo en el checklist final, y sugerir
    `superpowers:finishing-a-development-branch` para cuando corresponda integrarla.
15. Mostrar **exclusivamente** este checklist al usuario (el reporte completo vive en
    `docs/cierres/YYYY-MM-DD.md`, no se reimprime en el chat):
    - Análisis retrospectivo completado
    - Evolución agéntica implementada/propuesta
    - Actualización de documentación
    - Merge a Dev
    - Final de sesión

## Referencias

- [Prompt asociado](../../prompts/cierre-sesion.prompt.md)
- Este flujo reemplaza a `superpowers:finishing-a-development-branch` específicamente para el cierre
  de sesión: el trigger de cierre ya constituye la decisión de integración explícita del usuario, por
  lo que no se invoca ese skill acá (evita volver a preguntar algo ya resuelto). Fuera de este flujo
  (rama deliberadamente diferida), `finishing-a-development-branch` sigue siendo la herramienta
  correcta. `superpowers:using-git-worktrees` es independiente (aislamiento de directorio, no ramas) y
  no se ve afectado por este flujo.
- `docker-cleanup/SKILL.md` — origen de la tabla de riesgo 🟢/🟡/🔴 reutilizada en el paso 10.

## Guardrails

1. Basarse únicamente en hechos verificables de la conversación activa; no inventar tareas, errores ni
   soluciones. Declarar límites de evidencia.
2. No proponer skills/agentes/prompts especulativos: prevención requiere un obstáculo real, aceleración
   requiere un paso repetible ya observado.
3. No crear ni modificar otras skills automáticamente salvo lo que resulte del paso 12 (evolución
   agéntica 🟢/🟡 ya evaluada) o solicitud expresa del usuario. Si se cataloga una skill nueva,
   verificar que tenga mirror en `.claude/skills/<nombre>/SKILL.md` para ser invocable por el tool
   `Skill`.
4. No sobrescribir cierres de sesión previos del mismo día; anexar como sección nueva.
5. No incluir secretos, tokens ni credenciales en el reporte.
6. El paso 14 (auto-merge) es un paso final propio de este skill, no una redefinición de
   `repo-updater`: los commits/push intermedios de la sesión sobre la rama efímera siguen siendo
   responsabilidad de `dev-workflow`/`repo-updater` durante el trabajo; este skill sólo integra el
   resultado final a `dev` al cerrar.
7. Sin declaración explícita de cierre del usuario, no elaborar ni persistir la retrospectiva ni
   ejecutar el auto-merge.
8. Ninguna propuesta de evolución agéntica clasificada 🔴 (muy alto riesgo) se implementa sin respuesta
   explícita del usuario — el flujo se detiene en el paso 11 hasta obtenerla.
9. El auto-merge del paso 14 es autónomo, incluida la resolución de conflictos, salvo que el usuario
   haya indicado explícitamente en la misma sesión que esa rama debe diferirse.
10. El commit de fusión del paso 14 documenta en su mensaje los archivos en conflicto (si los hubo) y
    el criterio de resolución aplicado.
11. Si hubo flujo recursivo SDD/superpowers durante la sesión, registrar métricas de ciclo y alertas
    según `docs/sdd_metricas_ciclo.md`.

## Resultado esperado

- Reporte Markdown completo (tareas verificadas contra evidencia, errores/bloqueos, soluciones
  aplicadas, evolución agéntica con su clasificación de riesgo) guardado en
  `docs/cierres/YYYY-MM-DD.md`.
- Propuestas 🟢/🟡 de evolución agéntica implementadas; propuestas 🔴 detenidas hasta respuesta del
  usuario.
- Rama efímera de la sesión mergeada a `dev` y pusheada (o explícitamente diferida por pedido del
  usuario), rama efímera borrada tras el merge exitoso.
- Checklist final de 5 líneas mostrado al usuario en el chat.
```

- [ ] **Step 2: Verificar**

```bash
grep -n "Cerrar sesión.*Cerremos sesión\|Cerremos sesión" .agentes-comunes/skills/cierre-sesion/SKILL.md
grep -n "Compuerta de Riesgo" .agentes-comunes/skills/cierre-sesion/SKILL.md
grep -n "Flujo de Auto-Merge" .agentes-comunes/skills/cierre-sesion/SKILL.md
grep -n "Análisis retrospectivo completado" .agentes-comunes/skills/cierre-sesion/SKILL.md
grep -n "Cierre chat" .agentes-comunes/skills/cierre-sesion/SKILL.md
```
Expected: todas devuelven al menos 1 línea — la última (`Cierre chat`) confirma que el trigger viejo
sigue presente (aditivo, no reemplazado).

- [ ] **Step 3: Commit**

```bash
git add .agentes-comunes/skills/cierre-sesion/SKILL.md
git commit -m "feat(cierre-sesion): evolución agéntica con compuerta de riesgo + auto-merge autónomo a dev"
```

---

### Task 6: `cierre-sesion` — mirrors (`.github` skill+prompt, `.claude` skill+comando, `.gemini` x2, `.codex-skills`)

**Files:**
- Modify: `.github/skills/cierre-sesion/SKILL.md`
- Modify: `.claude/skills/cierre-sesion/SKILL.md`
- Modify: `.claude/commands/cierre-sesion.md`
- Modify: `.github/prompts/cierre-sesion.prompt.md`
- Modify: `.gemini/rules/skill-cierre-sesion.md`
- Modify: `.gemini/rules/prompt-cierre-sesion-prompt.md`
- Modify: `.codex-skills/skills/las-focas-cierre-sesion/SKILL.md`

**Interfaces:**
- Consumes: el cuerpo final de la Tarea 5.

- [ ] **Step 1: `.github/skills/cierre-sesion/SKILL.md`**

Mismo contenido que la Tarea 5, cambiando sólo la línea 2 y agregando el sufijo de mirror ya existente
en línea 3, igual que hoy.

- [ ] **Step 2: `.claude/skills/cierre-sesion/SKILL.md`**

Reemplazar todo el archivo (ya leído — formato: header propio con nota de mirror en línea 3, mismo
frontmatter plano `name/description/argument-hint`, sección "Referencias" con enlaces relativos a
`../../../.github/prompts/cierre-sesion.prompt.md` y `../../commands/cierre-sesion.md`) por el mismo
cuerpo de la Tarea 5, preservando ese formato de encabezado/Referencias propio de este mirror:

```markdown
# Nombre de archivo: SKILL.md
# Ubicación de archivo: .claude/skills/cierre-sesion/SKILL.md
# Descripción: Habilidad para retrospectiva técnica, evolución agéntica y auto-merge de cierre de sesión (mirror de .agentes-comunes/skills/cierre-sesion/SKILL.md — fuente de verdad)

---
name: cierre-sesion
description: "Usar al finalizar una sesión de trabajo, sólo con declaración explícita de cierre, para generar una retrospectiva técnica, evaluar evolución agéntica del entorno y mergear automáticamente la rama efímera activa a dev"
argument-hint: "Palabra clave de cierre (ej. 'Cerrar sesión') o alcance/fecha"
---

# Habilidad: Cierre de Sesión

Workflow invocable para analizar la conversación activa al finalizar el trabajo, extraer conocimiento
técnico factual que retroalimente el ecosistema de agentes del proyecto, y — como paso final —
integrar automáticamente la rama efímera de la sesión a `dev`.

## Cuándo usar

Usar esta skill sólo cuando el usuario declara explícitamente el fin de la sesión:

- invoca `/cierre-sesion` explícitamente, o
- escribe una frase inequívoca de cierre: "Cerrar sesión", "Cerremos sesión", "Cierre chat", "cierre
  de sesión", "terminamos la sesión", "este es el cierre del chat", "cerrá la sesión con una
  retrospectiva"

**No** activar por sólo nombrar la skill al pasar, completar una tarea, pedir estado o solicitar
documentación. Si un trigger heurístico dispara esta skill sin ese gate cumplido, no elaborar ni
persistir la retrospectiva: continuar la tarea normal e indicar en una línea que el cierre queda
reservado para cuando se declare explícitamente.

## Procedimiento

1. Confirmar el gate de activación. Si no se cumple, no continuar con los pasos siguientes.
2. Leer `AGENTS.md`, el historial disponible de la conversación activa, resultados de tool calls, el
   diff actual (`git status`/`git diff`) y la documentación de dominio afectada. Declarar cualquier
   límite de evidencia detectado (p.ej. contexto truncado por compactación automática).
3. Delimitar qué cambios son propios de esta sesión, cuáles son preexistentes del worktree y cuáles
   son acciones externas.
4. Contrastar cada tarea supuestamente terminada contra código, tests, logs, estado del sistema o
   documentación. Clasificarla como completada, parcial, bloqueada o no verificada.
5. Documentar errores, bloqueos o problemas post-implementación realmente enfrentados: síntoma, causa
   raíz confirmada o hipótesis explícita, impacto.
6. Detallar con precisión reutilizable la solución aplicada a cada error/bloqueo: archivo/componente,
   decisión técnica, validación ejecutada, condición que indicaría una regresión futura (o marcar sin
   resolver).
7. Revisar vigencia: corregir documentación desactualizada cuando la evidencia la contradiga. Corregir
   lógica fuera de la tarea principal sólo si está verificado y autorizado; si no, registrar como
   pendiente concreto.
8. Evaluar mejoras agénticas en dos carriles — prevención (obstáculos reales de esta sesión) y
   aceleración (pasos repetibles observados que agilizarían implementaciones similares futuras). Por
   cada candidata: evidencia, frecuencia esperada, beneficio, costo de mantenimiento y opción
   recomendada, prefiriendo ampliar una skill existente.
9. Determinar la fecha actual (`YYYY-MM-DD`).
10. Clasificar cada propuesta de evolución agéntica del paso 8 con esta tabla de riesgo (mismo patrón
    ya usado en `docker-cleanup/SKILL.md`, no se inventa taxonomía nueva):

    | Riesgo | Criterio | Acción |
    |---|---|---|
    | 🟢 Bajo | Agrega guardrail, corrige doc, amplía un skill existente sin tocar permisos de `main`/producción ni introducir un mecanismo de push/merge nuevo | Se implementa en este mismo cierre |
    | 🟡 Medio | Ídem, pero con superficie de cambio mayor (varios archivos/skills) o que toca un flujo ya en uso activo | Se implementa en este mismo cierre |
    | 🔴 Muy alto | Toca permisos sobre `main`/producción, debilita un guardrail existente, o introduce un mecanismo de push/merge automático nuevo no cubierto ya por una skill vigente | Se detiene el flujo (ver paso 11) |

11. **Compuerta de Riesgo**: si al menos una propuesta quedó clasificada 🔴, presentar su estado (qué
    cambiaría y por qué se clasificó así), preguntar explícitamente al usuario si se avanza, y
    **detener el flujo completo** (no continuar a los pasos 12-15) hasta recibir una respuesta. Si
    todas las propuestas son 🟢/🟡 o no hay propuestas, continuar sin pausas.
12. Implementar las propuestas 🟢/🟡 de evolución agéntica aprobadas (crear/editar skills, comandos o
    guardrails). Si la propuesta crea o edita un skill, seguir `superpowers:writing-skills` para su
    estructura y validación. Registrar con precisión qué archivos de gobernanza se tocaron y por qué
    — esto va en el reporte del paso 13, no sólo en el checklist final (mitiga que el mismo agente que
    propone sea quien clasifica su propio riesgo).
13. Crear o anexar `docs/cierres/YYYY-MM-DD.md` sin perder cierres previos del mismo día, con el
    reporte completo (tareas, errores/soluciones, evolución agéntica implementada/propuesta y su
    clasificación de riesgo, archivos de gobernanza tocados) y confirmar la ruta del archivo guardado.
14. **Flujo de Auto-Merge** — integrar la rama efímera activa de esta sesión a `dev`:
    ```bash
    git checkout <rama-efímera-actual>
    git fetch origin
    git merge origin/dev
    ```
    Si `git diff --name-only --diff-filter=U` devuelve archivos en conflicto: leer los marcadores
    `<<<<<<<`/`=======`/`>>>>>>>`, entender la lógica de ambos lados y resolver reescribiendo
    correctamente, luego `git add .`. El commit de fusión resultante debe documentar en su mensaje
    qué archivos tuvieron conflicto y el criterio de resolución aplicado (trazabilidad posterior, no
    es un gate de aprobación). Si no hubo conflictos, el merge es directo. Luego:
    ```bash
    git checkout dev
    git pull origin dev
    git merge <rama-efímera-actual>
    git push origin dev
    git branch -d <rama-efímera-actual>
    git push origin --delete <rama-efímera-actual>
    ```
    **Excepción**: si en esta misma sesión el usuario indicó explícitamente que esta rama debe
    diferirse (ej. ventana de mantenimiento — precedente real: `fix-baneos-hermanos-prod`), no forzar
    este flujo. Dejar la rama activa sin mergear, documentarlo en el checklist final, y sugerir
    `superpowers:finishing-a-development-branch` para cuando corresponda integrarla.
15. Mostrar **exclusivamente** este checklist al usuario (el reporte completo vive en
    `docs/cierres/YYYY-MM-DD.md`, no se reimprime en el chat):
    - Análisis retrospectivo completado
    - Evolución agéntica implementada/propuesta
    - Actualización de documentación
    - Merge a Dev
    - Final de sesión

## Referencias

- [Prompt asociado](../../../.github/prompts/cierre-sesion.prompt.md)
- [Comando Claude Code](../../commands/cierre-sesion.md)
- Este flujo reemplaza a `superpowers:finishing-a-development-branch` específicamente para el cierre
  de sesión: el trigger de cierre ya constituye la decisión de integración explícita del usuario, por
  lo que no se invoca ese skill acá. Fuera de este flujo (rama deliberadamente diferida),
  `finishing-a-development-branch` sigue siendo la herramienta correcta.

## Guardrails

1. Basarse únicamente en hechos verificables de la conversación activa; no inventar tareas, errores ni
   soluciones. Declarar límites de evidencia.
2. No proponer skills/agentes/prompts especulativos: prevención requiere un obstáculo real, aceleración
   requiere un paso repetible ya observado.
3. No crear ni modificar otras skills automáticamente salvo lo que resulte del paso 12 (evolución
   agéntica 🟢/🟡 ya evaluada) o solicitud expresa del usuario. Si se cataloga una skill nueva,
   verificar que tenga mirror en `.claude/skills/<nombre>/SKILL.md` para ser invocable por el tool
   `Skill`.
4. No sobrescribir cierres de sesión previos del mismo día; anexar como sección nueva.
5. No incluir secretos, tokens ni credenciales en el reporte.
6. El paso 14 (auto-merge) es un paso final propio de este skill, no una redefinición de
   `repo-updater`.
7. Sin declaración explícita de cierre del usuario, no elaborar ni persistir la retrospectiva ni
   ejecutar el auto-merge.
8. Ninguna propuesta de evolución agéntica clasificada 🔴 se implementa sin respuesta explícita del
   usuario — el flujo se detiene en el paso 11 hasta obtenerla.
9. El auto-merge del paso 14 es autónomo, incluida la resolución de conflictos, salvo instrucción
   explícita previa de diferir esa rama en la misma sesión.
10. El commit de fusión del paso 14 documenta en su mensaje los archivos en conflicto y el criterio de
    resolución aplicado.
11. Si hubo flujo recursivo SDD/superpowers durante la sesión, registrar métricas de ciclo y alertas
    según `docs/sdd_metricas_ciclo.md`.

## Resultado esperado

- Reporte Markdown completo guardado en `docs/cierres/YYYY-MM-DD.md`.
- Propuestas 🟢/🟡 de evolución agéntica implementadas; propuestas 🔴 detenidas hasta respuesta del
  usuario.
- Rama efímera de la sesión mergeada a `dev` y pusheada (o explícitamente diferida), borrada tras el
  merge exitoso.
- Checklist final de 5 líneas mostrado al usuario en el chat.
```

- [ ] **Step 3: `.claude/commands/cierre-sesion.md`**

Reemplazar todo el archivo (ya leído — 101 líneas) por:

```markdown
# Nombre de archivo: cierre-sesion.md
# Ubicación de archivo: .claude/commands/cierre-sesion.md
# Descripción: Comando Claude Code para cierre de sesión: retrospectiva técnica, evolución agéntica con compuerta de riesgo y auto-merge de la rama efímera a dev

Actuar como Analista de Calidad y Gestor de Conocimiento Agéntico del proyecto LAS-FOCAS. Argumento opcional del usuario: $ARGUMENTS

# Rol

Cerrar la sesión activa: extraer conocimiento técnico real para retroalimentar el ecosistema de agentes (prevención y aceleración), evaluar evolución agéntica del entorno con compuerta de riesgo, y — como paso final — integrar automáticamente la rama efímera de la sesión a `dev`.

# Contexto

- **Gate de activación**: proceder sólo si el usuario invocó `/cierre-sesion` explícitamente, o declaró de forma inequívoca el fin de la sesión (p.ej. "Cerrar sesión", "Cerremos sesión", "Cierre chat", "cierre de sesión", "terminamos la sesión", "este es el cierre del chat", "cerrá la sesión con una retrospectiva"). Nombrar la skill al pasar, completar una tarea, pedir estado o solicitar documentación sin declarar el cierre NO satisface el gate. Si no se cumple, no elaborar ni persistir la retrospectiva ni ejecutar el auto-merge: continuar con la tarea normal o señalar en una línea que el cierre queda reservado para cuando se declare explícitamente.
- El análisis debe ser estrictamente técnico y factual: basarse solo en lo que realmente ocurrió en esta conversación (tool calls, resultados, errores, decisiones del usuario). No inventar ni generalizar. No afirmar acceso a mensajes/outputs ausentes (p.ej. contexto truncado por compactación automática) — declarar cualquier límite de evidencia en el reporte.
- Delimitar la sesión analizada: separar cambios propios de esta conversación, cambios preexistentes del worktree y acciones externas. No atribuir resultados sin evidencia de que ocurrieron en esta conversación.
- El reporte se guarda en `docs/cierres/YYYY-MM-DD.md`. Si ya existe un cierre para la fecha de hoy, se anexa como sección nueva; nunca se sobrescribe.
- Propuestas de **prevención**: basadas únicamente en obstáculos reales enfrentados en esta sesión. Propuestas de **aceleración**: basadas en pasos repetibles ya observados en esta sesión, no en herramientas hipotéticas.
- Cada propuesta de evolución agéntica se clasifica 🟢 Bajo / 🟡 Medio / 🔴 Muy alto (tabla en Pasos #11, mismo patrón que `docker-cleanup/SKILL.md`). 🟢/🟡 se implementan en este mismo cierre; 🔴 detiene el flujo y exige respuesta explícita del usuario antes de continuar.
- El auto-merge final (Pasos #14-15) es autónomo, incluida la resolución de conflictos, salvo que el usuario haya indicado explícitamente en esta misma sesión que la rama debe diferirse (ej. ventana de mantenimiento).
- Si además corresponde persistir un hallazgo en el sistema de memoria automática del agente (tipo `feedback` o `project`), señalarlo explícitamente en el reporte sin duplicar ahí el contenido completo.

# Objetivo

Producir la retrospectiva técnica completa (guardada en `docs/cierres/`), implementar o proponer evolución agéntica del entorno según su riesgo, e integrar automáticamente la rama efímera de la sesión a `dev`, terminando con un checklist de 5 líneas en el chat.

# Pasos

1. Confirmar el gate de activación. Si no se cumple, no continuar con los pasos siguientes.
2. Leer `AGENTS.md`, el historial disponible de la conversación activa, resultados de tool calls, el diff actual (`git status`/`git diff`) y la documentación de dominio afectada. Declarar cualquier límite de evidencia detectado.
3. Delimitar qué cambios son propios de esta sesión, cuáles son preexistentes del worktree y cuáles son acciones externas.
4. Contrastar cada tarea supuestamente terminada contra código, tests, logs, estado del sistema o documentación. Clasificarla como completada, parcial, bloqueada o no verificada.
5. Documentar errores, bloqueos o problemas post-implementación realmente enfrentados: síntoma, causa raíz confirmada o hipótesis explícita, impacto.
6. Detallar con precisión técnica reutilizable la solución aplicada a cada error/bloqueo: archivo/componente afectado, decisión técnica, validación ejecutada, condición que indicaría una regresión futura (o marcar explícitamente como sin resolver).
7. Revisar vigencia: corregir documentación desactualizada cuando la evidencia actual la contradiga. Corregir lógica fuera de la tarea principal sólo si el desajuste está verificado y el cambio es seguro y autorizado; si no, registrarlo como pendiente concreto.
8. Evaluar mejoras agénticas en dos carriles — **prevención** y **aceleración** — con evidencia, frecuencia esperada, beneficio, costo de mantenimiento y opción recomendada por candidata, prefiriendo ampliar una skill existente.
9. Determinar la fecha actual (`YYYY-MM-DD`) y localizar `docs/cierres/YYYY-MM-DD.md` (crear o anexar según corresponda).
10. Escribir el reporte completo en `docs/cierres/YYYY-MM-DD.md` con la "Estructura esperada del reporte" de abajo (no se muestra completo en el chat — ver Paso 15).
11. Clasificar cada propuesta de evolución agéntica del paso 8:

    | Riesgo | Criterio | Acción |
    |---|---|---|
    | 🟢 Bajo | Agrega guardrail, corrige doc, amplía un skill existente sin tocar permisos de `main`/producción ni introducir un mecanismo de push/merge nuevo | Se implementa en este mismo cierre |
    | 🟡 Medio | Ídem, pero con superficie de cambio mayor o que toca un flujo ya en uso activo | Se implementa en este mismo cierre |
    | 🔴 Muy alto | Toca permisos sobre `main`/producción, debilita un guardrail existente, o introduce un mecanismo de push/merge automático nuevo | Se detiene el flujo |

12. **Compuerta de Riesgo**: si hay al menos una propuesta 🔴, presentar su estado, preguntar si se avanza y **detener el flujo completo** (no continuar a los Pasos 13-15) hasta recibir respuesta explícita.
13. Implementar las propuestas 🟢/🟡 aprobadas. Si crean/editan un skill, seguir `superpowers:writing-skills`. Registrar en el reporte del Paso 10 qué archivos de gobernanza se tocaron y por qué.
14. **Flujo de Auto-Merge**:
    ```bash
    git checkout <rama-efímera-actual>
    git fetch origin
    git merge origin/dev
    ```
    Si hay conflictos (`git diff --name-only --diff-filter=U`): leer marcadores `<<<<<<<`/`=======`/`>>>>>>>`, entender la lógica de ambos lados, resolver reescribiendo correctamente, `git add .`. El commit de fusión documenta en su mensaje qué archivos tuvieron conflicto y el criterio de resolución. Luego:
    ```bash
    git checkout dev
    git pull origin dev
    git merge <rama-efímera-actual>
    git push origin dev
    git branch -d <rama-efímera-actual>
    git push origin --delete <rama-efímera-actual>
    ```
    Excepción: si el usuario indicó explícitamente en esta sesión que la rama debe diferirse, no forzar — dejarla activa y documentarlo.
15. Mostrar **exclusivamente** este checklist en el chat:
    - Análisis retrospectivo completado
    - Evolución agéntica implementada/propuesta
    - Actualización de documentación
    - Merge a Dev
    - Final de sesión

# Estructura esperada del reporte (persistido en docs/cierres/YYYY-MM-DD.md)

```markdown
# Nombre de archivo: YYYY-MM-DD.md
# Ubicación de archivo: docs/cierres/YYYY-MM-DD.md
# Descripción: Cierre(s) de sesión técnica del YYYY-MM-DD

# Cierre de Sesión — YYYY-MM-DD

## Sesión HH:MM — [resumen corto del alcance]

### Contexto
- Alcance de la sesión analizada, evidencia consultada y límites de evidencia
- Cambios propios de esta sesión vs. preexistentes del worktree vs. externos

### Tareas verificadas
- [tarea]: [completada|parcial|bloqueada|no verificada] — [evidencia de contraste]

### Errores y bloqueos
- [síntoma]: [causa raíz confirmada o hipótesis explícita] — [impacto]

### Soluciones aplicadas
- [error asociado]: [fix técnico + archivo/comando] — [validación ejecutada] — [riesgo residual / condición de regresión]

### Mejoras de arquitectura agéntica propuestas

#### Prevención
- [control]: [obstáculo real] — [evidencia, frecuencia, beneficio, costo] — Riesgo: 🟢/🟡/🔴 — [implementada|propuesta]

#### Aceleración
- [skill/recurso]: [paso repetible observado] — [evidencia, frecuencia, beneficio, costo] — Riesgo: 🟢/🟡/🔴 — [implementada|propuesta]

### Archivos de gobernanza tocados (Paso 13)
- [archivo]: [qué cambió y por qué]

### Notas de actualización de documentación
- [archivo]: [inconsistencia encontrada y corregida]

### Auto-Merge
- Rama efímera: `<rama>` — [mergeada a dev / diferida por pedido del usuario]
- Conflictos: [ninguno | lista de archivos y criterio de resolución aplicado]

### Conocimiento a preservar
- [qué debería recordar una sesión futura sobre este trabajo]
```

# Criterios de Aceptación

- [ ] Reporte basado exclusivamente en hechos verificables; límites de evidencia declarados.
- [ ] Cada tarea clasificada (completada/parcial/bloqueada/no verificada).
- [ ] Cada propuesta de evolución agéntica tiene su clasificación de riesgo 🟢/🟡/🔴.
- [ ] Ninguna propuesta 🔴 se implementó sin respuesta explícita del usuario.
- [ ] `docs/cierres/YYYY-MM-DD.md` creado o actualizado sin perder cierres previos del mismo día.
- [ ] Auto-merge ejecutado (o explícitamente diferido) y documentado con su resultado.
- [ ] El chat muestra exclusivamente el checklist de 5 líneas, no el reporte completo.

# Reglas

1. No elaborar ni persistir la retrospectiva, ni ejecutar el auto-merge, sin que el usuario haya declarado explícitamente el cierre de la sesión.
2. No inventar tareas, errores, soluciones ni validaciones que no hayan ocurrido en esta conversación.
3. No proponer skills/agentes/prompts especulativos: prevención requiere un obstáculo real, aceleración requiere un paso repetible ya observado.
4. No crear ni modificar otras skills automáticamente salvo lo que resulte de la compuerta de riesgo (Paso 11-13) o solicitud expresa del usuario.
5. No sobrescribir cierres de sesión previos del mismo día; anexar.
6. No incluir secretos, tokens ni credenciales en el reporte.
7. Ninguna propuesta 🔴 se implementa sin respuesta explícita del usuario — el flujo se detiene en el Paso 12.
8. El auto-merge es autónomo (incluida resolución de conflictos) salvo instrucción explícita previa de diferir esa rama en la misma sesión.
9. Mantener todo el contenido en español técnico.
```

- [ ] **Step 4: `.github/prompts/cierre-sesion.prompt.md`**

Aplicar al archivo actual (ya leído — 107 líneas) los mismos cambios semánticos del Step 3: bullet de
Contexto (línea 18: agregar "Cerrar sesión"/"Cerremos sesión" a la lista de frases de cierre), agregar
un nuevo bullet de Contexto para la compuerta de riesgo y el auto-merge (igual al de Step 3), Pasos
9-11 (renombrar/insertar los pasos de clasificación de riesgo/compuerta/auto-merge/checklist, mismo
contenido que los Pasos 11-15 del Step 3), reemplazar "Presentar el reporte completo al usuario en el
chat" (línea 42) por la instrucción de mostrar sólo el checklist de 5 líneas, agregar la sección
"Auto-Merge" al "Formato del reporte" (línea 45-85, mismo bloque que el Step 3), agregar el criterio de
aceptación sobre el checklist de 5 líneas y sobre la compuerta de riesgo (líneas 87-96), agregar las
Reglas adicionales 7-8 del Step 3 (líneas 98-107).

- [ ] **Step 5: `.gemini/rules/skill-cierre-sesion.md`**

Leer el archivo actual primero (mismo formato Gemini que `skill-dev-workflow.md`: frontmatter
`name`/`source`/`triggers`/`globs`/`commands: []` + banner). Reemplazar el cuerpo por el mismo
contenido final de la Tarea 5/Step 2 de esta tarea (`# Habilidad: Cierre de Sesión` completo). Agregar
`"cerrar sesion"`, `"cerremos sesion"`, `"evolucion agentica"`, `"auto-merge"`, `"riesgo"` a `triggers`
si no están.

- [ ] **Step 6: `.gemini/rules/prompt-cierre-sesion-prompt.md`**

Leer el archivo actual primero. Aplicar los mismos cambios semánticos del Step 4 (mirror del prompt
`.github/prompts/cierre-sesion.prompt.md`), preservando el formato de frontmatter que ya tenga.

- [ ] **Step 7: `.codex-skills/skills/las-focas-cierre-sesion/SKILL.md`**

Leer el archivo actual primero (frontmatter Codex `name`/`metadata.short-description`/`metadata.source`
/`metadata.triggers`/`metadata.globs`/`metadata.commands: []`). Reemplazar el cuerpo por el mismo
contenido final de la Tarea 5. Agregar `"cerrar sesion"`, `"cerremos sesion"`, `"riesgo"`,
`"auto-merge"` a `triggers`. Este archivo hoy le falta el guardrail de métricas SDD (guardrail #11) que
sí tiene `.github/skills/cierre-sesion/SKILL.md` — al reemplazar el cuerpo completo por el de la Tarea
5, ese guardrail #11 queda incluido automáticamente (backfill del drift preexistente).

- [ ] **Step 8: Verificar**

```bash
for f in .github/skills/cierre-sesion/SKILL.md .claude/skills/cierre-sesion/SKILL.md .claude/commands/cierre-sesion.md .github/prompts/cierre-sesion.prompt.md .gemini/rules/skill-cierre-sesion.md .gemini/rules/prompt-cierre-sesion-prompt.md .codex-skills/skills/las-focas-cierre-sesion/SKILL.md; do
  echo "== $f =="
  grep -c "Cerremos sesión" "$f"
  grep -c "Compuerta de Riesgo\|compuerta de riesgo\|Compuerta de riesgo" "$f"
  grep -c "Auto-Merge\|auto-merge\|Auto-merge" "$f"
done
```
Expected: los 3 greps devuelven ≥1 en cada uno de los 7 archivos.

- [ ] **Step 9: Commit**

```bash
git add .github/skills/cierre-sesion/SKILL.md .claude/skills/cierre-sesion/SKILL.md .claude/commands/cierre-sesion.md .github/prompts/cierre-sesion.prompt.md .gemini/rules/skill-cierre-sesion.md .gemini/rules/prompt-cierre-sesion-prompt.md .codex-skills/skills/las-focas-cierre-sesion/SKILL.md
git commit -m "feat(cierre-sesion): propaga evolución agéntica + auto-merge a todos los mirrors"
```

---

### Task 7: Documentación (`docs/entorno_dev.md`, `AGENTS.md`, `CLAUDE.md`)

**Files:**
- Modify: `docs/entorno_dev.md`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: convención de rama efímera (Tarea 1), nuevo flujo de `cierre-sesion` (Tarea 5).

- [ ] **Step 1: `docs/entorno_dev.md` — leer primero las secciones "Modelo de ramas" y "Flujo de commits en rama dev"**

Leer el archivo completo (o al menos esas dos secciones + "Reglas del entorno dev para agentes") antes
de editar, para no perder contenido no relacionado con branching que viva en medio de esas secciones.

- [ ] **Step 2: Editar "Modelo de ramas"**

Reemplazar la fila de la tabla:
```
| `feature/xxx` | **Opcional**, para features largas. Mergear a `dev`, nunca directo a `main` | `lasfocasdev` |
```
por:
```
| `<tipo>/<slug>` | **Obligatoria** para todo cambio (`feat/`, `fix/`, `docs/`, `chore/`, `refactor/`, `test/`). Creada automáticamente por `dev-workflow` desde `origin/dev`; integrada a `dev` automáticamente por `cierre-sesion` al cerrar la sesión. Nunca commit directo en `dev`/`main`. | `lasfocasdev` |
```
Actualizar el diagrama ASCII inmediatamente arriba de la tabla, cambiando `feature/xxx` por
`<tipo>/<slug> (obligatoria)`.

- [ ] **Step 3: Editar "Flujo de commits en rama dev"**

Reescribir la secuencia de comandos documentada (hoy: `git checkout dev` → editar → `git add`/`commit`/
`git push origin dev`) por: `dev-workflow` crea/reutiliza la rama efímera desde `origin/dev` → editar →
`git add`/`commit`/`git push -u origin HEAD` sobre esa rama → `dev` sólo recibe el merge final vía
`cierre-sesion`. Renombrar la sección a "Flujo de commits en rama efímera" si el encabezado original
era literal sobre "rama dev".

- [ ] **Step 4: Editar "Reglas del entorno dev para agentes"**

Actualizar el resumen de guardrails para reflejar: rama efímera obligatoria, prohibido commit directo
en `dev`/`main`, integración automática vía `cierre-sesion`. Mantener sin cambios las reglas no
relacionadas con branching (compose dev, archivos de producción, push a `main` prohibido).

- [ ] **Step 5: `AGENTS.md` línea 33**

Reemplazar:
```
- Rama de trabajo habitual: `dev`. Push directo a `main` prohibido desde agentes; los merges a `main` se realizan únicamente por PR revisado.
```
por:
```
- Rama de trabajo: ramas efímeras `<tipo>/<slug>` creadas desde `origin/dev` (obligatorio — prohibido commitear directo en `dev`). La integración a `dev` es automática al cierre de sesión (`cierre-sesion`). Push directo a `main` prohibido desde agentes; los merges a `main` se realizan únicamente por PR revisado.
```

- [ ] **Step 6: `CLAUDE.md` — filas de comandos y skills**

Reemplazar:
```
| `/repo-updater` | Audita diff, actualiza docs/PR y docs temáticas, genera commit técnico y hace push a `dev` | alcance o contexto del cambio |
```
por:
```
| `/repo-updater` | Audita diff, actualiza docs/PR y docs temáticas, genera commit técnico y hace push a la rama efímera activa | alcance o contexto del cambio |
```

Reemplazar:
```
| `/cierre-sesion` | Retrospectiva técnica de la conversación activa: tareas, errores/bloqueos, soluciones y propuestas de skills/agentes/prompts, guardada en `docs/cierres/YYYY-MM-DD.md` | palabra clave "Cierre chat" o alcance/fecha |
```
por:
```
| `/cierre-sesion` | Retrospectiva técnica + evolución agéntica con compuerta de riesgo + auto-merge autónomo de la rama efímera a `dev`, guardada en `docs/cierres/YYYY-MM-DD.md` | palabra clave "Cerrar sesión"/"Cerremos sesión"/"Cierre chat" o alcance/fecha |
```

Reemplazar:
```
| `dev-workflow` | Validación obligatoria antes de cualquier cambio | Rama `dev`, compose dev, nunca push a `main` |
```
por:
```
| `dev-workflow` | Validación obligatoria antes de cualquier cambio | Rama efímera obligatoria por tarea (prohibido commit directo en dev/main), compose dev, nunca push a `main` |
```

Reemplazar:
```
| `repo-updater` | Commits técnicos a `dev` con auditoría de docs | Nunca `git push origin main` |
```
por:
```
| `repo-updater` | Commits técnicos a la rama efímera activa con auditoría de docs | Nunca `git push origin main` ni `git push origin dev` directo |
```

Reemplazar:
```
| `cierre-sesion` | Retrospectiva técnica de cierre de sesión: tareas verificadas contra evidencia, errores/soluciones y mejoras agénticas de prevención (obstáculos reales) y aceleración (pasos repetibles observados) | Requiere declaración explícita de cierre del usuario; basarse solo en hechos reales de la conversación activa; nunca inventar errores/soluciones |
```
por:
```
| `cierre-sesion` | Retrospectiva técnica + evolución agéntica con compuerta de riesgo (🔴 detiene y pregunta) + auto-merge autónomo de la rama efímera a `dev` (incluida resolución de conflictos) | Requiere declaración explícita de cierre; sin evidencia no se inventa; ninguna propuesta 🔴 se implementa sin respuesta del usuario |
```

- [ ] **Step 7: `CLAUDE.md` — corregir banner de mirrors stale**

Reemplazar el bloque:
```
> **Para que sean invocables por el `Skill` tool de Claude Code hace falta además un mirror en
> `.claude/skills/<nombre>/SKILL.md`** — no alcanza con existir en `.agentes-comunes/skills/`. Descubierto
> 2026-08-14: `Skill(skill="docker-rebuild")` falló con "Unknown skill" pese a estar catalogada acá,
> porque `.claude/skills/` no existía. `docker-rebuild` y `nocturne-token-compliance` tienen mirror
> hoy (esta última se creó ya con las 4 copias desde el arranque); el resto de la tabla de abajo
> **todavía no es invocable vía `/nombre-skill` o el tool `Skill` en este entorno** — hay que
> copiarla a `.claude/skills/` (mismo contenido que `.agentes-comunes/skills/`) antes de poder usarla así. Hasta
> entonces, seguir sus procedimientos manualmente vía Bash. Ver `docs/cierres/2026-08-14.md`.
```
por:
```
> **Para que sean invocables por el `Skill` tool de Claude Code hace falta además un mirror en
> `.claude/skills/<nombre>/SKILL.md`** — no alcanza con existir en `.agentes-comunes/skills/`. Descubierto
> 2026-08-14: `Skill(skill="docker-rebuild")` falló con "Unknown skill" pese a estar catalogada acá,
> porque `.claude/skills/` no existía. `docker-rebuild`, `nocturne-token-compliance`, `cierre-sesion`
> y `dev-workflow` tienen mirror hoy (2026-09-03: `dev-workflow` se agregó junto con el flujo de rama
> efímera obligatoria — antes no era invocable vía `Skill`); el resto de la tabla de abajo **todavía
> no es invocable vía `/nombre-skill` o el tool `Skill` en este entorno** — hay que copiarla a
> `.claude/skills/` (mismo contenido que `.agentes-comunes/skills/`) antes de poder usarla así. Hasta
> entonces, seguir sus procedimientos manualmente vía Bash. Ver `docs/cierres/2026-08-14.md`.
```

- [ ] **Step 8: Verificar**

```bash
grep -n "Obligatoria.*para todo cambio" docs/entorno_dev.md
grep -n "ramas efímeras" AGENTS.md
grep -n "auto-merge autónomo" CLAUDE.md
grep -n "dev-workflow.*tienen mirror hoy" CLAUDE.md
grep -c "Rama de trabajo habitual: \`dev\`\." AGENTS.md
```
Expected: primeras cuatro devuelven ≥1 línea; la última devuelve `0` (el texto viejo ya no debe estar).

- [ ] **Step 9: Commit**

```bash
git add docs/entorno_dev.md AGENTS.md CLAUDE.md
git commit -m "docs: refleja rama efímera obligatoria y nuevo flujo de cierre-sesion en entorno_dev/AGENTS/CLAUDE"
```

---

### Task 8: Verificación cruzada final + memoria

**Files:**
- (sin archivos nuevos — sólo verificación de todo lo anterior)

**Interfaces:**
- Consumes: el resultado de las Tareas 1-7 completas.

- [ ] **Step 1: Confirmar que no queda ningún push directo a dev/main en los 3 skills**

```bash
grep -rn "git push origin dev\b" .agentes-comunes/skills/dev-workflow .agentes-comunes/skills/repo-updater .agentes-comunes/skills/cierre-sesion .github/skills/dev-workflow .github/skills/repo-updater .github/skills/cierre-sesion .claude/skills/dev-workflow .claude/skills/cierre-sesion .claude/commands/repo-updater.md .claude/commands/cierre-sesion.md .codex-skills/skills/las-focas-dev-workflow .codex-skills/skills/las-focas-repo-updater .codex-skills/skills/las-focas-cierre-sesion .gemini/rules/skill-dev-workflow.md .gemini/rules/skill-repo-updater.md .gemini/rules/skill-cierre-sesion.md .gemini/rules/prompt-repo-updater-prompt.md .gemini/rules/prompt-cierre-sesion-prompt.md .github/prompts/repo-updater.prompt.md .github/prompts/cierre-sesion.prompt.md
```
Expected: **sin resultados** (exit code 1 de grep). Cualquier match es un archivo que quedó sin
actualizar — corregirlo antes de continuar.

- [ ] **Step 2: Confirmar que `.claude/skills/dev-workflow/SKILL.md` es invocable**

Invocar `Skill(skill="dev-workflow")` (tool `Skill`) y confirmar que carga el contenido de la Tarea 1
en vez de devolver "Unknown skill" — esto confirma que el gap real preexistente quedó cerrado.

- [ ] **Step 3: Diff de paridad fuente-de-verdad vs. mirrors**

Para cada skill, confirmar que el cuerpo sustantivo (desde `# Habilidad:` en adelante) es equivalente
entre la fuente de verdad y cada mirror — las únicas diferencias esperadas son de frontmatter/encabezado:

```bash
diff <(sed -n '/^# Habilidad:/,$p' .agentes-comunes/skills/dev-workflow/SKILL.md) <(sed -n '/^# Habilidad:/,$p' .github/skills/dev-workflow/SKILL.md)
diff <(sed -n '/^# Habilidad:/,$p' .agentes-comunes/skills/dev-workflow/SKILL.md) <(sed -n '/^# Habilidad:/,$p' .claude/skills/dev-workflow/SKILL.md)
diff <(sed -n '/^# Habilidad:/,$p' .agentes-comunes/skills/repo-updater/SKILL.md) <(sed -n '/^# Habilidad:/,$p' .github/skills/repo-updater/SKILL.md)
diff <(sed -n '/^# Habilidad:/,$p' .agentes-comunes/skills/cierre-sesion/SKILL.md) <(sed -n '/^# Habilidad:/,$p' .github/skills/cierre-sesion/SKILL.md)
diff <(sed -n '/^# Habilidad:/,$p' .agentes-comunes/skills/cierre-sesion/SKILL.md) <(sed -n '/^# Habilidad:/,$p' .claude/skills/cierre-sesion/SKILL.md)
```
Expected: sin diferencias (o únicamente diferencias ya esperadas y documentadas, ej. la sección
"Referencias" de `.claude/skills/cierre-sesion/SKILL.md` que agrega un link al comando Claude Code que
los demás mirrors no tienen). Cualquier otra diferencia debe corregirse.

- [ ] **Step 4: Actualizar memoria del agente (fuera del repo, no es un commit)**

Actualizar `feedback_push_dev_sin_preguntar.md` en el sistema de memoria: la autorización de push sin
preguntar sigue vigente pero retargeteada — pushes libres a la rama efímera activa, y el merge final a
`dev` vía `cierre-sesion` es autónomo (decisión confirmada 2026-09-03), nunca push directo a `dev`
desde fuera de ese flujo. Enlazar con una nueva memoria de tipo `project` que registre este rediseño
(rama efímera obligatoria + auto-merge en cierre-sesion) y actualizar `MEMORY.md`.

- [ ] **Step 5: Commit final si Step 3 requirió correcciones**

```bash
git status --short
# Si hubo correcciones:
git add -A
git commit -m "fix: ajustes de paridad entre fuente de verdad y mirrors tras verificación cruzada"
```

- [ ] **Step 6: Push de todos los commits de esta tarea**

```bash
git log --oneline origin/dev..HEAD
git push origin dev
```
Expected: todos los commits de las Tareas 1-7 (y el de Step 5 si aplicó) quedan reflejados en
`origin/dev`.
