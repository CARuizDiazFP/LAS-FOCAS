# Nombre de archivo: skill-secrets-rollout.md
# Ubicación de archivo: .gemini/rules/skill-secrets-rollout.md
# Descripción: Adaptador liviano (lazy loading) de .agentes-comunes/skills/secrets-rollout/SKILL.md

---
name: "skill-secrets-rollout"
description: "Usar cuando haya que migrar variables sensibles a Docker Secrets, agregar un secret nuevo a un servicio de Compose, o rotar un secret ya en uso (dev o prod) en LAS-FOCAS"
source: ".agentes-comunes/skills/secrets-rollout/SKILL.md"
triggers: ["secrets-rollout", "habilidad", "docker secrets", "rotar", "rotación", "db_password_v1", "postgres_password_file", "database_url", "las-focas"]
globs: ["deploy/**", ".secrets/**", ".env*", "core/config.py", "db/session.py"]
---

# Regla Skill: secrets-rollout (carga bajo demanda)

> Leer `.agentes-comunes/skills/secrets-rollout/SKILL.md` completo **sólo** cuando la tarea active alguno de los `triggers` o `globs` de arriba; no precargarlo. Las skills locales prevalecen sobre Superpowers (`docs/superpowers/CATALOG.md`).
