# Nombre de archivo: skill-dev-workflow.md
# Ubicación de archivo: .gemini/rules/skill-dev-workflow.md
# Descripción: Adaptador liviano (lazy loading) de .agentes-comunes/skills/dev-workflow/SKILL.md

---
name: "skill-dev-workflow"
description: "Usar SIEMPRE antes de ejecutar cambios de código, commits, push, operaciones Docker o actualizaciones de repo. Valida rama efímera activa, stack correcto y restricciones del entorno dev."
source: ".agentes-comunes/skills/dev-workflow/SKILL.md"
triggers: ["dev-workflow", "habilidad", "dev", "workflow", "protocolo", "trabajo", "entorno", "rama", "efimera", "siempre", "antes", "ejecutar", "cambios", "c-digo", "commits", "push", "operaciones", "docker", "actualizaciones", "repo"]
globs: ["**/*"]
---

# Regla Skill: dev-workflow (carga bajo demanda)

> Leer `.agentes-comunes/skills/dev-workflow/SKILL.md` completo **sólo** cuando la tarea active alguno de los `triggers` o `globs` de arriba; no precargarlo. Las skills locales prevalecen sobre Superpowers (`docs/superpowers/CATALOG.md`).
