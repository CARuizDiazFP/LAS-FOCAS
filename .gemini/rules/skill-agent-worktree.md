# Nombre de archivo: skill-agent-worktree.md
# Ubicación de archivo: .gemini/rules/skill-agent-worktree.md
# Descripción: Adaptador liviano (lazy loading) de .agentes-comunes/skills/agent-worktree/SKILL.md

---
name: "skill-agent-worktree"
description: "Usar al INICIAR cualquier tarea y ante cualquier señal de concurrencia (otra sesión activa, trabajo largo, subagentes). Crea el worktree y la rama propios del agente, define cuándo tomar un lease de recurso compartido y cómo integrar a dev sin pisar a nadie."
source: ".agentes-comunes/skills/agent-worktree/SKILL.md"
triggers: ["agent-worktree", "worktree", "agente", "concurrencia", "lease", "lock", "handoff", "aislamiento", "rama efimera", "integracion", "dev"]
globs: ["**/*"]
---

# Regla Skill: agent-worktree (carga bajo demanda)

> Leer `.agentes-comunes/skills/agent-worktree/SKILL.md` completo **sólo** cuando la tarea active alguno de los `triggers` o `globs` de arriba; no precargarlo. Las skills locales prevalecen sobre Superpowers (`docs/superpowers/CATALOG.md`).
