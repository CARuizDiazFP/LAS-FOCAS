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
