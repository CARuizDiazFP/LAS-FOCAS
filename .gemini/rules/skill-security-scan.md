# Nombre de archivo: skill-security-scan.md
# Ubicación de archivo: .gemini/rules/skill-security-scan.md
# Descripción: Adaptador liviano (lazy loading) de .agentes-comunes/skills/security-scan/SKILL.md

---
name: "skill-security-scan"
description: "Usar cuando haya que ejecutar una revisión integral de seguridad, correlacionar secretos, dependencias, SAST y proponer mitigaciones"
source: ".agentes-comunes/skills/security-scan/SKILL.md"
triggers: ["security-scan", "habilidad", "security", "scan", "ejecutar", "revisi-n", "integral", "seguridad", "correlacionar", "secretos", "dependencias", "sast", "proponer", "mitigaciones"]
globs: [".env*", "Keys/**", "deploy/**", ".github/workflows/**", "api/**", "web/**"]
---

# Regla Skill: security-scan (carga bajo demanda)

> Leer `.agentes-comunes/skills/security-scan/SKILL.md` completo **sólo** cuando la tarea active alguno de los `triggers` o `globs` de arriba; no precargarlo. Las skills locales prevalecen sobre Superpowers (`docs/superpowers/CATALOG.md`).
