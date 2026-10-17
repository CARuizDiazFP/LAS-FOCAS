# Nombre de archivo: skill-cromo-diagnostico-real.md
# Ubicación de archivo: .gemini/rules/skill-cromo-diagnostico-real.md
# Descripción: Adaptador liviano (lazy loading) de .agentes-comunes/skills/cromo-diagnostico-real/SKILL.md

---
name: "skill-cromo-diagnostico-real"
description: "Usar antes de escribir o confiar en código de parseo/ingesta de Cromo Red: valida contra la API o la DB real en vez de asumir que el diseño documentado describe el comportamiento actual"
source: ".agentes-comunes/skills/cromo-diagnostico-real/SKILL.md"
triggers: ["cromo-diagnostico-real", "cromo", "las-focas", "diagnostico", "parseo", "ingesta", "api", "validar", "diseno", "documentado"]
globs: ["core/services/cromo/**", "scripts/cromo_sonda.py", "scripts/cromo_backfill_geo.py"]
---

# Regla Skill: cromo-diagnostico-real (carga bajo demanda)

> Leer `.agentes-comunes/skills/cromo-diagnostico-real/SKILL.md` completo **sólo** cuando la tarea active alguno de los `triggers` o `globs` de arriba; no precargarlo. Las skills locales prevalecen sobre Superpowers (`docs/superpowers/CATALOG.md`).
