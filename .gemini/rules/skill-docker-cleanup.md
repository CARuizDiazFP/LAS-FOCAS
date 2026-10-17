# Nombre de archivo: skill-docker-cleanup.md
# Ubicación de archivo: .gemini/rules/skill-docker-cleanup.md
# Descripción: Adaptador liviano (lazy loading) de .agentes-comunes/skills/docker-cleanup/SKILL.md

---
name: "skill-docker-cleanup"
description: "Usar cuando haya que limpiar imágenes, contenedores o build cache de Docker sin tocar volúmenes persistentes"
source: ".agentes-comunes/skills/docker-cleanup/SKILL.md"
triggers: ["docker-cleanup", "habilidad", "limpieza", "docker", "limpiar", "im-genes", "contenedores", "build", "cache", "tocar", "vol-menes", "persistentes"]
globs: ["deploy/**", "**/Dockerfile", "scripts/**"]
---

# Regla Skill: docker-cleanup (carga bajo demanda)

> Leer `.agentes-comunes/skills/docker-cleanup/SKILL.md` completo **sólo** cuando la tarea active alguno de los `triggers` o `globs` de arriba; no precargarlo. Las skills locales prevalecen sobre Superpowers (`docs/superpowers/CATALOG.md`).
