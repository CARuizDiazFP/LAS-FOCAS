# Nombre de archivo: SKILL.md
# Ubicación de archivo: .github/skills/repo-updater/SKILL.md
# Descripción: Skill para sincronizar el repositorio con validación documental, commit técnico y push a dev (rama de trabajo habitual)

---
name: repo-updater
description: "Usar cuando haya que auditar docs/PR y docs temáticas, preparar commit técnico con git y subir cambios a dev (rama de trabajo habitual)"
argument-hint: "Describe alcance o contexto, por ejemplo: sincronizar cambios de web y docs a main"
---

# Habilidad: Actualizador de Repositorio

Workflow invocable para validar trazabilidad, completar documentación faltante y ejecutar el flujo de `git` de punta a punta usando la CLI del sistema.

## Cuándo usar

Usar esta skill cuando el usuario pida:

- sincronizar cambios locales con `main`
- auditar si el diff quedó reflejado en `docs/PR/` y en la documentación de `docs/`
- generar commit técnico alineado al diff real
- hacer `git add`, `git commit` y `git push` sin omitir trazabilidad

## Procedimiento

1. Ejecutar inspección con CLI de git para comparar el estado local contra `dev`:
   - `git fetch origin dev`
   - `git status --short --branch`
   - `git diff --stat`
   - `git diff --cached --stat`
   - `git log --oneline origin/dev..HEAD`
2. Determinar la fecha actual en formato `YYYY-MM-DD` y localizar `docs/PR/YYYY-MM-DD.md`.
3. Mapear los archivos cambiados contra la documentación temática afectada dentro de `docs/`.
4. Si el diff no está documentado, actualizar primero el PR diario y luego la documentación temática correspondiente.
5. Generar un mensaje de commit técnico, breve y semántico a partir del diff real.
6. Ejecutar `git add .`, `git commit` y `git push origin dev`.

## Cobertura documental mínima

- `api/`, `api_app/` -> `docs/api.md`
- `web/` -> `docs/web.md`
- `bot_telegram/` -> `docs/bot.md`
- `db/` -> `docs/db.md`
- `core/chatbot/`, `core/mcp/` -> `docs/chatbot.md`, `docs/mcp.md`
- `modules/informes_*` -> `docs/informes/`
- `deploy/`, seguridad, secretos o exposición -> `docs/Seguridad.md`, `docs/infra.md`, `docs/decisiones.md` según aplique
- `.github/` y ecosistema agéntico -> `docs/Mate_y_Ruta.md` y PR diario vigente

## Referencias

- [Prompt asociado](../../prompts/repo-updater.prompt.md)
- [Prompt de PR diario](../../prompts/generar-pr-diario.prompt.md)

## Guardrails

1. Usar la CLI de `git` del sistema; no simular el flujo ni inventar resultados.
2. No commitear secretos, credenciales, binarios accidentales ni archivos temporales.
3. No omitir `docs/PR/YYYY-MM-DD.md` si hubo cambios reales en el workspace.
4. No redactar commits genéricos como "update" o "cambios varios"; el mensaje debe reflejar el diff real.
5. No hacer `push --force` ni comandos destructivos sin pedido explícito.

## Resultado esperado

- Diff auditado contra `main`.
- PR diario actual localizado o creado para la fecha vigente.
- Documentación temática alineada con los cambios.
- Commit técnico generado desde el diff real.
- Push exitoso a `origin/dev` o bloqueo explícito documentado.

> **Guardrail**: `git push origin main` está **prohibido** desde este skill. Los merges a `main` se realizan solo mediante Pull Request revisado desde `dev`.