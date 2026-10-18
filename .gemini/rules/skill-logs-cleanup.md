# Nombre de archivo: skill-logs-cleanup.md
# Ubicación de archivo: .gemini/rules/skill-logs-cleanup.md
# Descripción: Adaptador liviano (lazy loading) de .agentes-comunes/skills/logs-cleanup/SKILL.md

---
name: "skill-logs-cleanup"
description: "Usar cuando haya que leer logs para diagnosticar, verificar que todos los servicios estén logueando, o limpiar Logs/ y logs de Docker sin perder evidencia"
source: ".agentes-comunes/skills/logs-cleanup/SKILL.md"
triggers: ["logs-cleanup", "habilidad", "limpieza", "logs", "limpiar", "contenedores", "perder", "informaci-n", "necesaria", "diagn-stico"]
globs: ["Logs/**", "logs/**", "deploy/**"]
---

# Regla Skill: logs-cleanup (carga bajo demanda)

> Leer `.agentes-comunes/skills/logs-cleanup/SKILL.md` completo **sólo** cuando la tarea active alguno de los `triggers` o `globs` de arriba; no precargarlo. Las skills locales prevalecen sobre Superpowers (`docs/superpowers/CATALOG.md`).
