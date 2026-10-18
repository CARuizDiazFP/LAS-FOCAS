# Nombre de archivo: skill-libreoffice-convert.md
# Ubicación de archivo: .gemini/rules/skill-libreoffice-convert.md
# Descripción: Adaptador liviano (lazy loading) de .agentes-comunes/skills/libreoffice-convert/SKILL.md

---
name: "skill-libreoffice-convert"
description: "Usar cuando haya que convertir documentos con office_service o depurar flujos DOCX a PDF con LibreOffice headless"
source: ".agentes-comunes/skills/libreoffice-convert/SKILL.md"
triggers: ["libreoffice-convert", "habilidad", "conversi-n", "libreoffice", "convertir", "documentos", "office-service", "depurar", "flujos", "docx", "pdf", "headless"]
globs: ["office_service/**"]
---

# Regla Skill: libreoffice-convert (carga bajo demanda)

> Leer `.agentes-comunes/skills/libreoffice-convert/SKILL.md` completo **sólo** cuando la tarea active alguno de los `triggers` o `globs` de arriba; no precargarlo. Las skills locales prevalecen sobre Superpowers (`docs/superpowers/CATALOG.md`).
