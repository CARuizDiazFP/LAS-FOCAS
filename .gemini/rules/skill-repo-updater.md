# Nombre de archivo: skill-repo-updater.md
# Ubicación de archivo: .gemini/rules/skill-repo-updater.md
# Descripción: Adaptador liviano (lazy loading) de .agentes-comunes/skills/repo-updater/SKILL.md

---
name: "skill-repo-updater"
description: "Usar cuando haya que auditar docs/PR y docs temáticas, preparar commit técnico con git y subir cambios a la rama efímera activa (nunca dev/main directo — ver dev-workflow y cierre-sesion)"
source: ".agentes-comunes/skills/repo-updater/SKILL.md"
triggers: ["repo-updater", "habilidad", "actualizador", "repositorio", "auditar", "docs", "tem-ticas", "preparar", "commit", "t-cnico", "git", "subir", "cambios", "dev", "rama", "trabajo", "efimera"]
globs: ["docs/**", "AGENTS.md", ".github/**", ".codex-skills/**", ".gemini/**"]
---

# Regla Skill: repo-updater (carga bajo demanda)

> Leer `.agentes-comunes/skills/repo-updater/SKILL.md` completo **sólo** cuando la tarea active alguno de los `triggers` o `globs` de arriba; no precargarlo. Las skills locales prevalecen sobre Superpowers (`docs/superpowers/CATALOG.md`).
