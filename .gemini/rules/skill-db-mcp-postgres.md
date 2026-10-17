# Nombre de archivo: skill-db-mcp-postgres.md
# Ubicación de archivo: .gemini/rules/skill-db-mcp-postgres.md
# Descripción: Adaptador liviano (lazy loading) de .agentes-comunes/skills/db-mcp-postgres/SKILL.md

---
name: "skill-db-mcp-postgres"
description: "Usar cuando haya que consultar PostgreSQL vía MCP para depurar infraestructura, revisar migraciones Alembic o auditar tablas del esquema app"
source: ".agentes-comunes/skills/db-mcp-postgres/SKILL.md"
triggers: ["db-mcp-postgres", "mcp", "postgresql", "las-focas", "consultar", "v-a", "depurar", "infraestructura", "migraciones", "alembic", "auditar", "tablas", "esquema", "app", "cromo"]
globs: ["db/**", "deploy/**"]
---

# Regla Skill: db-mcp-postgres (carga bajo demanda)

> Leer `.agentes-comunes/skills/db-mcp-postgres/SKILL.md` completo **sólo** cuando la tarea active alguno de los `triggers` o `globs` de arriba; no precargarlo. Las skills locales prevalecen sobre Superpowers (`docs/superpowers/CATALOG.md`).
