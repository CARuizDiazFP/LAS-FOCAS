# Nombre de archivo: skill-dependency-audit.md
# Ubicación de archivo: .gemini/rules/skill-dependency-audit.md
# Descripción: Adaptador liviano (lazy loading) de .agentes-comunes/skills/dependency-audit/SKILL.md

---
name: "skill-dependency-audit"
description: "Usar cuando haya que revisar requirements, package.json, pip-audit, npm audit y versiones expuestas a vulnerabilidades conocidas"
source: ".agentes-comunes/skills/dependency-audit/SKILL.md"
triggers: ["dependency-audit", "habilidad", "dependency", "audit", "requirements", "package", "json", "pip-audit", "npm", "versiones", "expuestas", "vulnerabilidades", "conocidas"]
globs: ["requirements*.txt", "**/requirements.txt", "web/frontend/package.json"]
---

# Regla Skill: dependency-audit (carga bajo demanda)

> Leer `.agentes-comunes/skills/dependency-audit/SKILL.md` completo **sólo** cuando la tarea active alguno de los `triggers` o `globs` de arriba; no precargarlo. Las skills locales prevalecen sobre Superpowers (`docs/superpowers/CATALOG.md`).
