# Nombre de archivo: skill-repo-update.md
# Ubicación de archivo: .gemini/rules/skill-repo-update.md
# Descripción: Adaptador liviano (lazy loading) de .agentes-comunes/skills/repo-update/SKILL.md

---
name: "skill-repo-update"
description: "Usar solo cuando el pedido mencione el nombre legacy repo-update; redirige al workflow vigente repo-updater"
source: ".agentes-comunes/skills/repo-update/SKILL.md"
triggers: ["repo-update", "habilidad", "repo", "update", "legado", "solo", "pedido", "mencione", "nombre", "legacy", "redirige", "workflow", "vigente", "repo-updater"]
globs: ["docs/**", "AGENTS.md", ".github/**", ".codex-skills/**", ".gemini/**"]
---

# Regla Skill: repo-update (carga bajo demanda)

> Leer `.agentes-comunes/skills/repo-update/SKILL.md` completo **sólo** cuando la tarea active alguno de los `triggers` o `globs` de arriba; no precargarlo. Las skills locales prevalecen sobre Superpowers (`docs/superpowers/CATALOG.md`).
