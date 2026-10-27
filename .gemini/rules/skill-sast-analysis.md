# Nombre de archivo: skill-sast-analysis.md
# Ubicación de archivo: .gemini/rules/skill-sast-analysis.md
# Descripción: Adaptador liviano (lazy loading) de .agentes-comunes/skills/sast-analysis/SKILL.md

---
name: "skill-sast-analysis"
description: "Usar cuando haya que revisar código por validación de entradas, auth, SQL, subprocess, deserialización, logging sensible o superficie de ataque"
source: ".agentes-comunes/skills/sast-analysis/SKILL.md"
triggers: ["sast-analysis", "habilidad", "sast", "analysis", "c-digo", "validaci-n", "entradas", "auth", "sql", "subprocess", "deserializaci-n", "logging", "sensible", "superficie", "ataque"]
globs: ["api/**", "web/**", "core/**", "modules/**"]
---

# Regla Skill: sast-analysis (carga bajo demanda)

> Leer `.agentes-comunes/skills/sast-analysis/SKILL.md` completo **sólo** cuando la tarea active alguno de los `triggers` o `globs` de arriba; no precargarlo. Las skills locales prevalecen sobre Superpowers (`docs/superpowers/CATALOG.md`).
