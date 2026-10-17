# Nombre de archivo: skill-pytest-focas.md
# Ubicación de archivo: .gemini/rules/skill-pytest-focas.md
# Descripción: Adaptador liviano (lazy loading) de .agentes-comunes/skills/pytest-focas/SKILL.md

---
name: "skill-pytest-focas"
description: "Usar cuando haya que ejecutar pytest, escribir tests, preparar fixtures o revisar cobertura en LAS-FOCAS"
source: ".agentes-comunes/skills/pytest-focas/SKILL.md"
triggers: ["pytest-focas", "habilidad", "pytest", "ejecutar", "escribir", "tests", "preparar", "fixtures", "cobertura", "las-focas"]
globs: ["tests/**", "pytest.ini"]
---

# Regla Skill: pytest-focas (carga bajo demanda)

> Leer `.agentes-comunes/skills/pytest-focas/SKILL.md` completo **sólo** cuando la tarea active alguno de los `triggers` o `globs` de arriba; no precargarlo. Las skills locales prevalecen sobre Superpowers (`docs/superpowers/CATALOG.md`).
