# Nombre de archivo: skill-cromo-inventario.md
# Ubicación de archivo: .gemini/rules/skill-cromo-inventario.md
# Descripción: Adaptador liviano (lazy loading) de .agentes-comunes/skills/cromo-inventario/SKILL.md

---
name: "skill-cromo-inventario"
description: "Usar para consultar, explotar o construir features sobre los datos de infraestructura FO ya ingeridos desde Cromo Red (app.cromo_*) — no para tocar la ingesta en sí"
source: ".agentes-comunes/skills/cromo-inventario/SKILL.md"
triggers: ["cromo-inventario", "cromo", "las-focas", "consultar", "explotar", "construir", "features", "infraestructura", "ingeridos", "inventario", "app"]
globs: ["core/services/cromo/**", "db/models/cromo.py", "docs/modulo_ingesta_cromo.md"]
---

# Regla Skill: cromo-inventario (carga bajo demanda)

> Leer `.agentes-comunes/skills/cromo-inventario/SKILL.md` completo **sólo** cuando la tarea active alguno de los `triggers` o `globs` de arriba; no precargarlo. Las skills locales prevalecen sobre Superpowers (`docs/superpowers/CATALOG.md`).
