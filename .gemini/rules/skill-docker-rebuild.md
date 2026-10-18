# Nombre de archivo: skill-docker-rebuild.md
# Ubicación de archivo: .gemini/rules/skill-docker-rebuild.md
# Descripción: Adaptador liviano (lazy loading) de .agentes-comunes/skills/docker-rebuild/SKILL.md

---
name: "skill-docker-rebuild"
description: "Usar cuando haya que reconstruir servicios Docker, refrescar imágenes o verificar un rebuild selectivo de LAS-FOCAS"
source: ".agentes-comunes/skills/docker-rebuild/SKILL.md"
triggers: ["docker-rebuild", "habilidad", "docker", "rebuild", "reconstruir", "servicios", "refrescar", "im-genes", "verificar", "selectivo", "las-focas"]
globs: ["deploy/**", "**/Dockerfile", "scripts/**"]
---

# Regla Skill: docker-rebuild (carga bajo demanda)

> Leer `.agentes-comunes/skills/docker-rebuild/SKILL.md` completo **sólo** cuando la tarea active alguno de los `triggers` o `globs` de arriba; no precargarlo. Las skills locales prevalecen sobre Superpowers (`docs/superpowers/CATALOG.md`).
