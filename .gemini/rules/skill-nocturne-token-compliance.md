# Nombre de archivo: skill-nocturne-token-compliance.md
# Ubicación de archivo: .gemini/rules/skill-nocturne-token-compliance.md
# Descripción: Adaptador liviano (lazy loading) de .agentes-comunes/skills/nocturne-token-compliance/SKILL.md

---
name: "skill-nocturne-token-compliance"
description: "Usar antes de dar por cerrada cualquier tarea de UI/CSS en el SPA: audita colores hardcodeados fuera de tokens.css (vista + todo su árbol de imports) y define cómo verificar el resultado real cuando no hay navegador disponible en la sesión"
source: ".agentes-comunes/skills/nocturne-token-compliance/SKILL.md"
triggers: ["nocturne-token-compliance", "habilidad", "nocturne", "tokens", "tokens.css", "colores", "hardcodeados", "css", "frontend", "vue", "audita", "verificar", "las-focas"]
globs: ["web/frontend/src/**/*.vue", "web/frontend/src/**/*.css", "web/frontend/src/assets/styles/tokens.css"]
---

# Regla Skill: nocturne-token-compliance (carga bajo demanda)

> Leer `.agentes-comunes/skills/nocturne-token-compliance/SKILL.md` completo **sólo** cuando la tarea active alguno de los `triggers` o `globs` de arriba; no precargarlo. Las skills locales prevalecen sobre Superpowers (`docs/superpowers/CATALOG.md`).
