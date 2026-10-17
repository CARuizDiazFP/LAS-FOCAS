# Nombre de archivo: skill-secret-detection.md
# Ubicación de archivo: .gemini/rules/skill-secret-detection.md
# Descripción: Adaptador liviano (lazy loading) de .agentes-comunes/skills/secret-detection/SKILL.md

---
name: "skill-secret-detection"
description: "Usar cuando haya que buscar credenciales expuestas, secretos en .env, llaves, tokens, compose, scripts o configuraciones sensibles"
source: ".agentes-comunes/skills/secret-detection/SKILL.md"
triggers: ["secret-detection", "habilidad", "secret", "detection", "buscar", "credenciales", "expuestas", "secretos", "env", "llaves", "tokens", "compose", "scripts", "configuraciones", "sensibles"]
globs: [".env*", "Keys/**", "deploy/**", ".github/workflows/**"]
---

# Regla Skill: secret-detection (carga bajo demanda)

> Leer `.agentes-comunes/skills/secret-detection/SKILL.md` completo **sólo** cuando la tarea active alguno de los `triggers` o `globs` de arriba; no precargarlo. Las skills locales prevalecen sobre Superpowers (`docs/superpowers/CATALOG.md`).
