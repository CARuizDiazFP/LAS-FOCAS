# Nombre de archivo: SKILL.md
# Ubicación de archivo: .github/skills/repo-update/SKILL.md
# Descripción: Alias legacy para redirigir solicitudes antiguas de actualización de repositorio hacia repo-updater

---
name: repo-update
description: "Usar solo cuando el pedido mencione el nombre legacy repo-update; redirige al workflow vigente repo-updater"
argument-hint: "Pedido legacy de actualización del repositorio"
---

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
