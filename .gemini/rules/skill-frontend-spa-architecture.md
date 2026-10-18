# Nombre de archivo: skill-frontend-spa-architecture.md
# Ubicación de archivo: .gemini/rules/skill-frontend-spa-architecture.md
# Descripción: Adaptador liviano (lazy loading) de .agentes-comunes/skills/frontend-spa-architecture/SKILL.md

---
name: "skill-frontend-spa-architecture"
description: "Usar SIEMPRE antes de agregar, modificar o mover rutas, vistas o componentes en el frontend SPA de LAS-FOCAS. Valida el entry point activo, el router unificado y advierte sobre archivos huérfanos conocidos."
source: ".agentes-comunes/skills/frontend-spa-architecture/SKILL.md"
triggers: ["frontend-spa-architecture", "spa", "router", "ruta", "rutas", "vue-router", "admin", "vista", "vistas", "componente", "entry-point", "index.html", "main.ts", "src/router", "admin/router", "RouterLink", "RouterView", "children", "path-match", "huerfano", "ingesta", "camaras", "frontend"]
globs: ["web/frontend/src/router/**", "web/frontend/src/admin/**", "web/frontend/src/views/**", "web/frontend/index.html", "web/frontend/vite.config.ts"]
---

# Regla Skill: frontend-spa-architecture (carga bajo demanda)

> Leer `.agentes-comunes/skills/frontend-spa-architecture/SKILL.md` completo **sólo** cuando la tarea active alguno de los `triggers` o `globs` de arriba; no precargarlo. Las skills locales prevalecen sobre Superpowers (`docs/superpowers/CATALOG.md`).
