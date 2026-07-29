# Nombre de archivo: skill-alembic-migrations.md
# Ubicación de archivo: .gemini/rules/skill-alembic-migrations.md
# Descripción: Regla Gemini portable migrada desde .github/skills/alembic-migrations/SKILL.md
---
name: "skill-alembic-migrations"
description: "Usar cuando haya que crear, revisar o aplicar migraciones Alembic y validar cambios de esquema en la base de datos"
source: ".github/skills/alembic-migrations/SKILL.md"
triggers:
  - "alembic-migrations"
  - "habilidad"
  - "migraciones"
  - "alembic"
  - "crear"
  - "aplicar"
  - "validar"
  - "cambios"
  - "esquema"
  - "base"
  - "datos"
globs:
  - "db/**"
  - "db/alembic/**"
commands:
  []
---

# Regla Skill: alembic-migrations

> Fuente original: `.github/skills/alembic-migrations/SKILL.md`. Usar esta regla cuando Gemini/Codex IDE detecte los triggers o globs declarados.

# Habilidad: Migraciones Alembic

Guía breve para crear, validar y aplicar migraciones Alembic sin sobrecargar el contexto base.

## Cuándo usar

- cuando haya cambios de esquema en `db/models/`
- cuando se necesite crear una migración manual o autogenerada
- cuando haga falta revisar rollback, SQL generado o troubleshooting Alembic

## Procedimiento

1. Revisar estado actual de migraciones.
2. Elegir `autogenerate` o migración manual.
3. Implementar `upgrade()` y `downgrade()`.
4. Validar con `--sql` y aplicar solo si corresponde.
5. Actualizar `docs/db.md` o PR diario cuando el cambio tenga impacto visible.

## Referencias

- [Recetas y operaciones comunes](./references/recetas.md)
- [Prompt de migración](../../prompts/migracion-alembic.prompt.md)

## Guardrails

1. Toda migración debe preservar datos salvo advertencia explícita.
2. Toda migración debe incluir `downgrade()` salvo excepción justificada.
3. Revisar SQL antes de aplicar cambios delicados en entornos reales.
