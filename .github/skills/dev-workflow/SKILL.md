# Nombre de archivo: SKILL.md
# Ubicación de archivo: .github/skills/dev-workflow/SKILL.md
# Descripción: Skill para garantizar que los agentes operen siempre sobre la rama dev y el stack lasfocasdev

---
name: dev-workflow
description: "Usar SIEMPRE antes de ejecutar cambios de código, commits, push, operaciones Docker o actualizaciones de repo. Valida rama activa, stack correcto y restricciones del entorno dev."
argument-hint: "Contexto de la tarea, por ejemplo: implementar feature X en el módulo Y"
---

# Habilidad: Dev Workflow — Protocolo de Trabajo en Entorno Dev

Protocolo de validación y operación para garantizar que todos los cambios se realicen sobre el entorno de desarrollo aislado (`dev`), nunca sobre producción.

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

- Si devuelve `dev`: continuar.
- Si devuelve `main` o cualquier otra rama: **detener y cambiar a `dev`** antes de hacer cualquier cambio:

```bash
git checkout dev
# Si dev no existe:
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
git branch --show-current  # debe decir: dev

git add .
git commit -m "<tipo>(módulo): descripción técnica"
git push origin dev         # NUNCA: git push origin main
```

### 5. Restricciones sobre archivos de producción

Los siguientes archivos **no deben modificarse** sin aprobación explícita del Tech Lead:

- `deploy/compose.yml`
- `.env` (en raíz del proyecto)
- Cualquier secreto o token de producción

Si el cambio requiere tocar producción, documentarlo en `docs/decisiones.md` y crear un PR formal.

## Guardrails

1. **No hacer push a `origin/main`** sin PR revisado que venga de `dev`.
2. **No usar `--force`** ni comandos destructivos sin pedido explícito del usuario.
3. **No commitear** archivos `.env`, `.env.dev`, `Keys/`, `*.pem`, `*.key` ni binarios generados.
4. Si detectás que estás en `main`: crear una rama `dev` local, cherry-pick de los cambios y borrar el estado local de `main` antes de proceder.
5. La operación `git push origin main` está **prohibida** desde el agente salvo instrucción explícita y confirmación del usuario.

## Relación con otras skills

| Skill | Cuándo invocar |
|-------|---------------|
| `repo-updater` | Para auditar y commitear cambios — ya apunta a `dev` por defecto |
| `pytest-focas` | Para correr tests — siempre en entorno dev |
| `alembic-migrations` | Para migraciones — ejecutar en contenedor `lasfocasdev-api` |
| `docker-rebuild` | Para rebuild selectivo — usar con compose dev |

## Resultado esperado

- Rama activa confirmada como `dev`
- `.env.dev` presente
- Stack correcto identificado (`lasfocasdev`)
- Ningún cambio accidental en archivos de producción
- Push apuntando a `origin/dev`
