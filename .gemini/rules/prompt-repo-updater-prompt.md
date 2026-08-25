# Nombre de archivo: prompt-repo-updater-prompt.md
# Ubicación de archivo: .gemini/rules/prompt-repo-updater-prompt.md
# Descripción: Regla Gemini portable migrada desde .github/prompts/repo-updater.prompt.md
---
name: "prompt-repo-updater-prompt"
description: "Prompt migrado desde /home/support-focal-01/LAS-FOCAS/.github/prompts/repo-updater.prompt.md"
source: ".github/prompts/repo-updater.prompt.md"
triggers:
  - "rol"
  - "repo-updater-prompt"
  - "repo-updater"
  - "migrado"
  - "home"
  - "support-focal-01"
  - "las-focas"
  - "github"
  - "prompts"
globs:
  - "web/**"
  - "api/**"
  - "api_app/**"
  - "db/**"
  - "core/services/**"
  - "core/parsers/**"
  - "db/models/**"
  - "deploy/**"
  - ".env*"
  - "Keys/**"
  - ".github/workflows/**"
  - "bot_telegram/**"
  - "core/mcp/**"
  - "core/chatbot/**"
  - "docs/mcp.md"
  - "docs/chatbot.md"
  - "docs/**"
  - "AGENTS.md"
commands:
  []
---

# Regla Prompt: repo-updater.prompt

> Fuente original: `.github/prompts/repo-updater.prompt.md`. Usar como contrato reutilizable cuando el pedido coincida con esta automatización.

---
name: Repo Updater
description: "Sincroniza cambios con dev: audita diff, valida docs/PR y docs temáticas, genera commit técnico y hace push"
argument-hint: "Describe alcance o rama esperada, por ejemplo: validar cambios de api y docs antes de subir a dev"
agent: "agent"
---

# Rol

Actuar como actualizador autónomo del repositorio LAS-FOCAS, usando directamente la CLI de `git` del sistema para validar trazabilidad, completar documentación faltante y sincronizar el estado local con la rama `dev` (rama de trabajo habitual).

# Contexto

- El repositorio exige que los cambios reales queden reflejados en `docs/PR/YYYY-MM-DD.md` y, si corresponde, en la documentación temática bajo `docs/`.
- La fecha del PR diario debe identificarse dinámicamente con la fecha actual del sistema en formato `YYYY-MM-DD`.
- Los commits deben ser técnicos, concisos y coherentes con el diff real.
- Si el cambio toca `.github/`, la documentación relacionada mínima es `docs/Mate_y_Ruta.md` además del PR diario.
- La rama objetivo por defecto es `dev` y el push debe hacerse al remoto `origin`. Los merges a `main` solo se realizan mediante Pull Request revisado.
- El commit siempre se hace en el worktree real de `dev` — nunca en un worktree de prod ni en uno
  creado para una investigación o tarea aislada (regla dura, ver Reglas adicionales #5).

# Objetivo

Ejecutar el flujo completo de revisión, documentación, staging, commit y push, sin omitir la auditoría de trazabilidad entre el diff actual, el PR diario vigente y la documentación de `docs/`.

# Pasos

1. Confirmar el worktree/rama de destino ANTES de tocar nada: `git rev-parse --abbrev-ref HEAD` debe
   ser `dev`, y `git rev-parse --show-toplevel` debe ser el checkout real de trabajo, no un worktree
   aislado (de investigación, de un agente con aislamiento propio, o de prod). Regla dura, ver Reglas
   adicionales #5 — si no es `dev`, detenerse y avisar en vez de commitear ahí.
2. Inspeccionar el estado real del repositorio con CLI de `git`:
   ```bash
   git fetch origin dev
   git status --short --branch
   git diff --stat
   git diff --cached --stat
   git diff --name-status
   git log --oneline origin/dev..HEAD
   ```
3. Si el estado del repo mezcla archivos que esta tarea no tocó con archivos que sí (trabajo previo
   de otra sesión/tarea, sin commitear), no asumir "todo junto": preguntar cómo separar el commit.
   Ver Reglas adicionales #6 para la técnica de separación por hunk cuando un mismo archivo tiene
   cambios de ambos orígenes.
4. Determinar la fecha actual y ubicar el archivo `docs/PR/YYYY-MM-DD.md`. Si no existe, crearlo con encabezado obligatorio de 3 líneas.
5. Analizar si el diff real (el de este commit, según el paso 3) ya está documentado en el PR diario vigente y en la documentación temática de `docs/`.
6. Si falta trazabilidad, actualizar antes de continuar:
   - `docs/PR/YYYY-MM-DD.md`
   - documentación temática según el área impactada, por ejemplo:
     - `docs/api.md` para `api/` o `api_app/`
     - `docs/web.md` para `web/`
     - `docs/bot.md` para `bot_telegram/`
     - `docs/db.md` para `db/`
     - `docs/chatbot.md` y `docs/mcp.md` para `core/chatbot/` o `core/mcp/`
     - `docs/informes/` para `modules/informes_*`
     - `docs/Seguridad.md`, `docs/infra.md` o `docs/decisiones.md` si hay impacto operativo, de seguridad o de arquitectura
     - `docs/Mate_y_Ruta.md` si el cambio afecta `.github/`, prompts, skills o agentes
7. Verificar que la documentación nueva o actualizada contraste con el estado actual del código. Si detectas información vieja o inconsistente, corregirla aunque no haya sido el foco principal del pedido.
8. Construir un mensaje de commit técnico, corto y semántico, derivado del diff real de ESE commit. Reglas mínimas:
   - usar scopes o módulos reales cuando aporten claridad
   - evitar mensajes genéricos como `update`, `misc`, `fix stuff` o equivalentes
   - reflejar el cambio dominante del diff
9. Ejecutar el flujo de versionado (si el paso 3 determinó separar, repetir add+commit por cada cuerpo de trabajo antes del push):
   ```bash
   git add .   # o los archivos/hunks que correspondan a este commit, nunca a ciegas si hay mezcla
   git commit -m "<mensaje_tecnico>"
   git push origin dev
   ```
10. Si `git push` falla por divergencia, no hacer `push --force`. Explicar el bloqueo y, solo si es seguro y consistente con el estado local, preparar la resolución con `git pull --rebase origin dev` antes de reintentar.
11. Entregar un cierre corto con:
   - archivos de documentación creados o actualizados
   - mensaje(s) de commit usado(s)
   - resultado del push
   - riesgos o pendientes reales

# Criterios de Aceptación

- [ ] Se confirmó que el commit se hizo en el worktree/rama `dev` (nunca prod ni un worktree aislado).
- [ ] Se inspeccionó el estado del repo con `git status` y `git diff`.
- [ ] Si el estado mezclaba orígenes distintos, se preguntó cómo separar antes de commitear.
- [ ] Se identificó el PR diario correspondiente a la fecha actual.
- [ ] El diff quedó contrastado contra `docs/PR/` y contra la documentación relevante en `docs/`.
- [ ] Si faltaba documentación, se creó o actualizó antes del commit.
- [ ] El commit generado es técnico, conciso y describe el diff real.
- [ ] Se ejecutó `git add .`, `git commit` y `git push origin dev`, o se dejó explicitado el bloqueo real.

# Reglas adicionales

1. No inventar validaciones, commits ni pushes que no hayan ocurrido.
2. No incluir secretos, tokens ni credenciales en la documentación ni en el commit.
3. No usar comandos destructivos como `git reset --hard` o `git push --force` sin pedido explícito.
4. Mantener todo el contenido en español técnico y concreto.
5. **Regla dura (confirmada explícitamente por el usuario, 2026-08-25)**: siempre commitear en el
   worktree de `dev`, nunca en uno de prod ni en uno creado para una investigación o tarea aislada —
   los prompts e investigaciones de este proyecto usan siempre la rama `dev`.
6. Si el working tree mezcla trabajo de la tarea actual con trabajo previo sin commitear de otro
   origen, preguntar cómo separar en vez de `git add .` por default. Para un archivo compartido con
   hunks de ambos orígenes: extraer con `git diff -- <archivo>` los hunks propios (por número de
   línea y encabezado `@@`), armar un patch sólo con esos hunks, validar con
   `git apply --cached --check <patch>`, aplicar con `git apply --cached <patch>` (no toca el working
   tree), `git add` el resto de archivos 100% propios y commitear — el diff restante contra el nuevo
   `HEAD` queda listo para el otro commit sin trabajo manual adicional.
