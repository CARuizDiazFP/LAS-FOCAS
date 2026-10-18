# Nombre de archivo: skill-baneo-qa-real.md
# Ubicación de archivo: .gemini/rules/skill-baneo-qa-real.md
# Descripción: Adaptador liviano (lazy loading) de .agentes-comunes/skills/baneo-qa-real/SKILL.md

---
name: "skill-baneo-qa-real"
description: "Usar antes de ejecutar create_ban/lift_ban o cualquier prueba de cascada de estado de Camara contra datos reales (lasfocasdev-*) — resuelve el blast radius real y cómo revertir con precisión si algo sale mal"
source: ".agentes-comunes/skills/baneo-qa-real/SKILL.md"
triggers: ["baneo-qa-real", "baneo", "las-focas", "cascada", "camara", "botella", "proteccion", "lift_ban", "create_ban", "qa"]
globs: ["core/services/protection_service.py", "core/services/camara_estado_service.py", "core/services/camara_hierarchy_service.py", "core/services/botellas_unificadas_service.py", "tests/test_protection_service.py"]
---

# Regla Skill: baneo-qa-real (carga bajo demanda)

> Leer `.agentes-comunes/skills/baneo-qa-real/SKILL.md` completo **sólo** cuando la tarea active alguno de los `triggers` o `globs` de arriba; no precargarlo. Las skills locales prevalecen sobre Superpowers (`docs/superpowers/CATALOG.md`).
