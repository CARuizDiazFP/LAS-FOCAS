# Nombre de archivo: SKILL.md
# Ubicación de archivo: .github/skills/repo-updater/SKILL.md
# Descripción: Skill para sincronizar el repositorio con validación documental, commit técnico y push a la rama efímera activa (la integración a dev es automática al cierre de sesión) — mirror de .agentes-comunes/skills/repo-updater/SKILL.md (fuente de verdad)

---
name: repo-updater
description: "Usar cuando haya que auditar docs/PR y docs temáticas, preparar commit técnico con git y subir cambios a la rama efímera activa (nunca dev/main directo — ver dev-workflow y cierre-sesion)"
argument-hint: "Describe alcance o contexto, por ejemplo: sincronizar cambios de web y docs en la rama efímera activa"
---

# Habilidad: Actualizador de Repositorio

Workflow invocable para validar trazabilidad, completar documentación faltante y ejecutar el flujo de `git` de punta a punta usando la CLI del sistema.

## Cuándo usar

Usar esta skill cuando el usuario pida:

- sincronizar cambios locales con la rama efímera activa (creada por `dev-workflow` — nunca `dev`, nunca `main`, nunca un worktree de prod)
- auditar si el diff quedó reflejado en `docs/PR/` y en la documentación de `docs/`
- generar commit técnico alineado al diff real
- hacer `git add`, `git commit` y `git push` sin omitir trazabilidad

## Procedimiento

1. Confirmar el worktree/rama de destino ANTES de tocar nada: `git rev-parse --abbrev-ref HEAD` debe
   ser una rama efímera activa (prefijo `feat/`, `fix/`, `docs/`, `chore/`, `refactor/` o `test/` —
   nunca `dev` ni `main`, ver `dev-workflow`), y `git rev-parse --show-toplevel` debe ser el checkout
   real de trabajo del proyecto, no un worktree aislado (de investigación, de un agente en
   `isolation: "worktree"`, o de prod). Ver guardrail 6 — esto es una regla dura, no una preferencia.
2. Ejecutar inspección con CLI de git para comparar el estado local contra `dev`:
   - `git fetch origin dev`
   - `git status --short --branch`
   - `git diff --stat`
   - `git diff --cached --stat`
   - `git log --oneline origin/dev..HEAD`
3. Si `git status` mezcla archivos que la sesión actual no tocó con archivos que sí (trabajo previo de
   otra sesión, sin commitear), no asumir "todo junto" ni "sólo lo mío": preguntarle al usuario cómo
   separar el commit. Ver guardrail 7 para la técnica de separación por hunk cuando un mismo archivo
   tiene cambios de ambos orígenes.
4. Determinar la fecha actual en formato `YYYY-MM-DD` y localizar `docs/PR/YYYY-MM-DD.md`.
5. Mapear los archivos cambiados (los que correspondan al commit que se está preparando, ver paso 3)
   contra la documentación temática afectada dentro de `docs/`.
6. Si el diff no está documentado, actualizar primero el PR diario y luego la documentación temática
   correspondiente.
7. Generar un mensaje de commit técnico, breve y semántico a partir del diff real de ESE commit (no
   de todo `git status` si el paso 3 determinó separar en varios).
8. Ejecutar `git add` (de los archivos/hunks que correspondan a este commit — nunca `git add .` a
   ciegas si el paso 3 detectó una mezcla), `git commit` y `git push -u origin HEAD` (empuja la rama
   efímera activa, cualquiera sea su nombre — nunca hacer push directo a `dev` ni a `main`).

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
6. **Regla dura, confirmada explícitamente por el usuario (2026-08-25)**: este skill siempre commitea
   en el worktree real de trabajo del proyecto — nunca en un worktree de prod, ni en uno creado para
   una investigación o tarea aislada (`superpowers:using-git-worktrees`, `isolation: "worktree"` de
   un agente, `EnterWorktree`). Los prompts e investigaciones de este proyecto usan siempre ese
   worktree (sobre una rama efímera, ver `dev-workflow`); si el directorio actual no es ese worktree,
   detenerse y decírselo al usuario en vez de commitear donde sea que se esté parado.
7. Si el working tree mezcla trabajo de la sesión actual con trabajo previo sin commitear de otro
   origen (otra sesión, otro agente), no bundlear todo en un commit por default: preguntar al usuario
   cómo separar (confirmado 2026-08-25: la opción preferida suele ser 2+ commits separados, uno por
   cuerpo de trabajo). Cuando un mismo archivo tiene hunks de ambos orígenes (ej. dos sesiones
   distintas editaron el mismo archivo de endpoints o el mismo `docs/decisiones.md`), separar así:
   1. `git diff -- <archivo>` y ubicar los encabezados `@@ -a,b +c,d @@` propios por número de línea.
   2. Armar un patch sólo con esos hunks (header `diff --git`/`index`/`---`/`+++` + los hunks elegidos).
   3. `git apply --cached --check <patch>` para validar ANTES de aplicar de verdad.
   4. `git apply --cached <patch>` — actualiza el índice sin tocar el working tree.
   5. Repetir para cada archivo compartido, `git add` el resto de archivos 100% propios, commitear.
   6. El diff restante contra el nuevo `HEAD` (para el/los otro(s) commit(s)) sale limpio solo, sin
      trabajo manual adicional.

## Resultado esperado

- Confirmado que el commit se hizo en el worktree real de trabajo, sobre una rama efímera (nunca
  prod ni un worktree aislado, nunca `dev`/`main` directo).
- Diff auditado contra `dev` (el estado remoto real, `origin/dev`).
- PR diario actual localizado o creado para la fecha vigente.
- Documentación temática alineada con los cambios.
- Commit(s) técnico(s) generado(s) desde el diff real — separados si el working tree mezclaba más de
  un origen de trabajo.
- Push exitoso a `origin/<rama-efímera-activa>` o bloqueo explícito documentado. La integración a
  `dev` es responsabilidad exclusiva de `cierre-sesion` (flujo de auto-merge).

> **Guardrail**: `git push origin main` está **prohibido** desde este skill. Los merges a `main` se realizan solo mediante Pull Request revisado desde `dev`.
