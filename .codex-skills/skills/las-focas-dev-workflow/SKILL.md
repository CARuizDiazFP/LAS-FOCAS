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
7. Una rama efímera es un `git checkout -b`, no un worktree nuevo — para aislamiento de directorio usar `superpowers:using-git-worktrees` (mecanismo independiente y combinable). Preferir un worktree desde el arranque (no recién cuando ya hay un problema) si hay sospecha de sesión concurrente en el mismo checkout (verificable con `ListAgents`) — un `checkout -b` normal comparte `HEAD`/working directory con cualquier otra sesión activa; hallazgo real 2026-09-04 (ver `docs/cierres/2026-09-04.md`): un commit ajeno de otra sesión aterrizó por accidente en la rama efímera de esta tarea por ese motivo.

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
