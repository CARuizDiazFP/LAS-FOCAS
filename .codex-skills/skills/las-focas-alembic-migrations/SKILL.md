---
name: "las-focas-alembic-migrations"
description: "Usar cuando haya que crear, revisar o aplicar migraciones Alembic y validar cambios de esquema en la base de datos"
metadata:
  short-description: "Usar cuando haya que crear, revisar o aplicar migraciones Alembic y validar cambios de esquema en la base de datos"
  source: ".agentes-comunes/skills/alembic-migrations/SKILL.md"
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

# Nombre de archivo: SKILL.md
# Ubicación de archivo: .codex-skills/skills/las-focas-alembic-migrations/SKILL.md
# Descripción: Skill portable Codex migrada desde .github/skills/alembic-migrations/SKILL.md

# Skill portable: alembic-migrations

> Fuente original: `.agentes-comunes/skills/alembic-migrations/SKILL.md`. Copia portable generada porque `.codex/` está montado como solo lectura en esta sesión.

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
4. Si el cambio de esquema modifica el SIGNIFICADO de un campo/función ya existente y ampliamente
   consumido (no sólo agrega uno nuevo), grep-auditar TODOS los consumidores reales de ese campo/función
   en el repo — no sólo los que la tarea o el plan ya tocan — antes de dar el cambio por completo.
   Hallazgo real (2026-09-04, ver `docs/cierres/2026-09-04.md`): ampliar el significado de
   `tiene_baneo_activo` en `get_camara_estado_contexto()` fue correcto para sus consumidores previstos
   (badge web, listener de Slack), pero rompió silenciosamente `baneos_grupos_service.py` (panel admin
   de baneos activos), un consumidor preexistente nunca auditado por el plan de esa tarea — sólo lo
   detectó una revisión final de rama completa, no las revisiones acotadas por tarea.
