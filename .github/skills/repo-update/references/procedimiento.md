# Nombre de archivo: procedimiento.md
# Ubicación de archivo: .github/skills/repo-update/references/procedimiento.md
# Descripción: Referencia legacy para redirigir el procedimiento de repo-update al workflow vigente repo-updater

# Procedimiento Legacy de Repo Update

Este archivo se conserva solo por compatibilidad histórica.

## Workflow vigente

- Skill principal: `../../repo-updater/SKILL.md`
- Prompt principal: `../../../prompts/repo-updater.prompt.md`

## Qué hacer si aparece una referencia vieja a `repo-update`

1. Reenviar la tarea a `repo-updater`.
2. Ejecutar el flujo actual con auditoría de `docs/PR/YYYY-MM-DD.md` y de la documentación temática en `docs/`.
3. No reintroducir desde aquí instrucciones duplicadas o divergentes.

## Notas

- El alias legacy existe para mantener compatibilidad con nombres anteriores.
- El flujo canónico de commit y push vive en `repo-updater`.
- Si el workflow principal cambia, actualizar solo `repo-updater`.