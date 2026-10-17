# Nombre de archivo: skill-disk-analysis.md
# Ubicación de archivo: .gemini/rules/skill-disk-analysis.md
# Descripción: Adaptador liviano (lazy loading) de .agentes-comunes/skills/disk-analysis/SKILL.md

---
name: "skill-disk-analysis"
description: "Usar cuando haya que diagnosticar uso de disco, espacio consumido por Docker, logs, volúmenes o artefactos del proyecto"
source: ".agentes-comunes/skills/disk-analysis/SKILL.md"
triggers: ["disk-analysis", "habilidad", "an-lisis", "disco", "diagnosticar", "uso", "espacio", "consumido", "docker", "logs", "vol-menes", "artefactos"]
globs: ["Logs/**", "deploy/**", ".cache/**"]
---

# Regla Skill: disk-analysis (carga bajo demanda)

> Leer `.agentes-comunes/skills/disk-analysis/SKILL.md` completo **sólo** cuando la tarea active alguno de los `triggers` o `globs` de arriba; no precargarlo. Las skills locales prevalecen sobre Superpowers (`docs/superpowers/CATALOG.md`).
