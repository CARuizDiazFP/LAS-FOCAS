---
name: "las-focas-repo-update"
description: "Usar solo cuando el pedido mencione el nombre legacy repo-update; redirige al workflow vigente repo-updater"
metadata:
  short-description: "Usar solo cuando el pedido mencione el nombre legacy repo-update; redirige al workflow vigente repo-updater"
  source: ".github/skills/repo-update/SKILL.md"
  triggers:
    - "repo-update"
    - "habilidad"
    - "repo"
    - "update"
    - "legado"
    - "solo"
    - "pedido"
    - "mencione"
    - "nombre"
    - "legacy"
    - "redirige"
    - "workflow"
    - "vigente"
    - "repo-updater"
  globs:
    - "docs/**"
    - "AGENTS.md"
    - ".github/**"
    - ".codex-skills/**"
    - ".gemini/**"
  commands:
    []
---

# Nombre de archivo: SKILL.md
# Ubicación de archivo: .codex-skills/skills/las-focas-repo-update/SKILL.md
# Descripción: Skill portable Codex migrada desde .github/skills/repo-update/SKILL.md

# Skill portable: repo-update

> Fuente original: `.github/skills/repo-update/SKILL.md`. Copia portable generada porque `.codex/` está montado como solo lectura en esta sesión.

# Habilidad: Repo Update (Legado)

Alias de compatibilidad para no mantener dos workflows activos con reglas distintas.

## Estado

- Nombre vigente: `repo-updater`
- Skill vigente: `../repo-updater/SKILL.md`
- Prompt asociado: `../../prompts/repo-updater.prompt.md`

## Qué hacer

1. Reenviar la tarea al workflow `repo-updater`.
2. No duplicar reglas operativas en este archivo.
3. Mantener este alias solo para compatibilidad con pedidos viejos o memoria previa del usuario.

## Guardrails

1. No seguir manteniendo en paralelo instrucciones que contradigan `repo-updater`.
2. Si se actualiza el flujo principal, reflejarlo en `repo-updater`, no aquí.
