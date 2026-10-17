# Nombre de archivo: skill-skill-generator.md
# Ubicación de archivo: .gemini/rules/skill-skill-generator.md
# Descripción: Adaptador liviano (lazy loading) de .agentes-comunes/skills/skill-generator/SKILL.md

---
name: "skill-skill-generator"
description: "Usar cuando haya que crear o evolucionar skills meta-agénticas con stack SPA/API moderno, seguridad obligatoria y reglas anti-legacy"
source: ".agentes-comunes/skills/skill-generator/SKILL.md"
triggers: ["skill-generator", "habilidad", "generador", "skills", "crear", "evolucionar", "spa", "seguridad", "anti-legacy", "meta-agentico"]
globs: [".github/skills/**", ".github/agents/**", ".github/prompts/**", ".codex-skills/**", ".gemini/rules/**"]
---

# Regla Skill: skill-generator (carga bajo demanda)

> Leer `.agentes-comunes/skills/skill-generator/SKILL.md` completo **sólo** cuando la tarea active alguno de los `triggers` o `globs` de arriba; no precargarlo. Las skills locales prevalecen sobre Superpowers (`docs/superpowers/CATALOG.md`).
