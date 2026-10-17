# Nombre de archivo: skill-temp-cleanup.md
# Ubicación de archivo: .gemini/rules/skill-temp-cleanup.md
# Descripción: Adaptador liviano (lazy loading) de .agentes-comunes/skills/temp-cleanup/SKILL.md

---
name: "skill-temp-cleanup"
description: "Usar cuando haya que limpiar archivos temporales, __pycache__, bytecode o caches de desarrollo del repo"
source: ".agentes-comunes/skills/temp-cleanup/SKILL.md"
triggers: ["temp-cleanup", "habilidad", "limpieza", "temporales", "limpiar", "pycache", "bytecode", "caches", "desarrollo", "repo"]
globs: ["**/__pycache__/**", ".pytest_cache/**", ".mypy_cache/**", ".ruff_cache/**", "tmp/**"]
---

# Regla Skill: temp-cleanup (carga bajo demanda)

> Leer `.agentes-comunes/skills/temp-cleanup/SKILL.md` completo **sólo** cuando la tarea active alguno de los `triggers` o `globs` de arriba; no precargarlo. Las skills locales prevalecen sobre Superpowers (`docs/superpowers/CATALOG.md`).
