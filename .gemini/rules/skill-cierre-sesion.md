# Nombre de archivo: skill-cierre-sesion.md
# Ubicación de archivo: .gemini/rules/skill-cierre-sesion.md
# Descripción: Adaptador liviano (lazy loading) de .agentes-comunes/skills/cierre-sesion/SKILL.md

---
name: "skill-cierre-sesion"
description: "Usar al finalizar una sesión de trabajo, sólo con declaración explícita de cierre, para generar una retrospectiva técnica, evaluar evolución agéntica del entorno y mergear automáticamente la rama efímera activa a dev"
source: ".agentes-comunes/skills/cierre-sesion/SKILL.md"
triggers: ["/cierre-sesion", "cierre-sesion", "Cerrar sesión", "Cerremos sesión", "cerrar sesion", "cerremos sesion"]
globs: ["docs/cierres/**", "docs/**", ".github/**", ".codex-skills/**", ".gemini/**"]
---

# Regla Skill: cierre-sesion (carga bajo demanda)

> Leer `.agentes-comunes/skills/cierre-sesion/SKILL.md` completo **sólo** cuando la tarea active alguno de los `triggers` o `globs` de arriba; no precargarlo. Las skills locales prevalecen sobre Superpowers (`docs/superpowers/CATALOG.md`).
