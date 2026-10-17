# Nombre de archivo: skill-alembic-migrations.md
# Ubicación de archivo: .gemini/rules/skill-alembic-migrations.md
# Descripción: Adaptador liviano (lazy loading) de .agentes-comunes/skills/alembic-migrations/SKILL.md

---
name: "skill-alembic-migrations"
description: "Usar cuando haya que crear, revisar o aplicar migraciones Alembic y validar cambios de esquema en la base de datos"
source: ".agentes-comunes/skills/alembic-migrations/SKILL.md"
triggers: ["alembic-migrations", "habilidad", "migraciones", "alembic", "crear", "aplicar", "validar", "cambios", "esquema", "base", "datos"]
globs: ["db/**", "db/alembic/**"]
---

# Regla Skill: alembic-migrations (carga bajo demanda)

> Leer `.agentes-comunes/skills/alembic-migrations/SKILL.md` completo **sólo** cuando la tarea active alguno de los `triggers` o `globs` de arriba; no precargarlo. Las skills locales prevalecen sobre Superpowers (`docs/superpowers/CATALOG.md`).
