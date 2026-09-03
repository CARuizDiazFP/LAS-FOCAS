# Nombre de archivo: repo-updater.md
# Ubicación de archivo: .claude/commands/repo-updater.md
# Descripción: Comando Claude Code para auditar trazabilidad, documentar cambios y hacer push a la rama efímera activa

Actuar como actualizador autónomo del repositorio LAS-FOCAS. Argumento opcional del usuario: $ARGUMENTS

# Rol

Validar trazabilidad entre el diff real, el PR diario vigente y la documentación temática. Completar documentación faltante y sincronizar el estado local con la rama efímera activa.

# Contexto

- El repositorio exige que los cambios reales queden reflejados en `docs/PR/YYYY-MM-DD.md` y, si corresponde, en la documentación temática bajo `docs/`.
- La fecha del PR diario debe identificarse dinámicamente con la fecha actual del sistema en formato `YYYY-MM-DD`.
- Los commits deben ser técnicos, concisos y coherentes con el diff real.
- Si el cambio toca `.github/` o `.claude/`, la documentación mínima es `docs/Mate_y_Ruta.md` además del PR diario.
- La rama objetivo es la rama efímera activa (`feat/`, `fix/`, `docs/`, `chore/`, `refactor/` o `test/`, creada por `dev-workflow`) — nunca `dev` ni `main` directo. La integración a `dev` es responsabilidad exclusiva de `cierre-sesion`.
- El commit siempre se hace en el worktree real de trabajo del proyecto — nunca en un worktree de prod ni en uno
  creado para una investigación o tarea aislada (regla dura, ver Reglas #5).

# Pasos

1. Confirmar el worktree/rama de destino ANTES de tocar nada: `git rev-parse --abbrev-ref HEAD` debe
   ser una rama efímera activa (nunca `dev`, nunca `main` — ver `dev-workflow`), y
   `git rev-parse --show-toplevel` debe ser el checkout real de trabajo, no un worktree aislado (de
   investigación, de un agente en `isolation: "worktree"`, o de prod). Regla dura, ver Reglas #5 — si
   estás en `dev`/`main`, detenerse y avisar en vez de commitear ahí; usar `dev-workflow` para crear
   la rama efímera primero.
2. Inspeccionar el estado real del repositorio:
   ```bash
   git fetch origin dev
   git status --short --branch
   git diff --stat
   git diff --cached --stat
   git diff --name-status
   git log --oneline origin/dev..HEAD
   ```
3. Si `git status` mezcla archivos que esta sesión no tocó con archivos que sí (trabajo previo de
   otra sesión sin commitear), no asumir "todo junto": preguntar al usuario cómo separar el commit.
   Ver Reglas #6 para la técnica de separación por hunk cuando un mismo archivo tiene cambios de
   ambos orígenes.
4. Determinar la fecha actual y ubicar `docs/PR/YYYY-MM-DD.md`. Si no existe, crearlo con encabezado obligatorio de 3 líneas.
5. Analizar si el diff real (el de este commit, según el paso 3) ya está documentado en el PR diario y en la documentación temática de `docs/`.
6. Si falta trazabilidad, actualizar antes de continuar:
   - `docs/PR/YYYY-MM-DD.md`
   - documentación temática según el área impactada:
     - `docs/api.md` para `api/`
     - `docs/web.md` para `web/`
     - `docs/bot.md` para `bot_telegram/`
     - `docs/db.md` para `db/`
     - `docs/chatbot.md` y `docs/mcp.md` para `core/chatbot/` o `core/mcp/`
     - `docs/informes/` para `modules/informes_*`
     - `docs/Seguridad.md`, `docs/infra.md` o `docs/decisiones.md` si hay impacto operativo o de arquitectura
     - `docs/Mate_y_Ruta.md` si el cambio afecta `.github/`, `.claude/`, prompts, skills o agentes
7. Verificar que la documentación nueva o actualizada contraste con el estado actual del código. Corregir información vieja o inconsistente aunque no sea el foco principal.
8. Construir un mensaje de commit técnico y semántico derivado del diff real de ESE commit. Evitar `update`, `misc`, `fix stuff` o equivalentes.
9. Ejecutar el flujo de versionado (si el paso 3 determinó separar, repetir add+commit por cada cuerpo de trabajo antes del push):
   ```bash
   git add .   # o los archivos/hunks que correspondan a este commit, nunca a ciegas si hay mezcla
   git commit -m "<mensaje_tecnico>"
   git push -u origin HEAD   # NUNCA: hacer push directo a dev ni a main
   ```
10. Si `git push` falla por divergencia, no hacer `push --force`. Explicar el bloqueo y, si es seguro, preparar resolución con `git pull --rebase origin <rama-efímera-activa>`.
11. Entregar un cierre corto: archivos actualizados, mensaje(s) de commit, resultado del push y riesgos o pendientes. Recordar que la integración a `dev` ocurre en `cierre-sesion`, no acá.

# Criterios de Aceptación

- [ ] Confirmado que el commit se hizo en el worktree real de trabajo, sobre una rama efímera (nunca prod ni un worktree aislado, nunca `dev`/`main` directo)
- [ ] Estado del repo inspeccionado con `git status` y `git diff`
- [ ] Si el working tree mezclaba orígenes distintos, se preguntó al usuario cómo separar antes de commitear
- [ ] PR diario correspondiente a la fecha actual identificado y actualizado
- [ ] Diff contrastado contra `docs/PR/` y documentación temática
- [ ] Commit(s) técnico(s) y conciso(s) que describe(n) el diff real
- [ ] `git push -u origin HEAD` ejecutado sobre la rama efímera activa, o bloqueo real documentado

# Reglas

1. No inventar validaciones, commits ni pushes que no hayan ocurrido.
2. No incluir secretos, tokens ni credenciales en documentación ni commits.
3. No usar `git reset --hard` ni `git push --force` sin pedido explícito.
4. Mantener todo el contenido en español técnico.
5. **Regla dura (confirmada explícitamente por el usuario, 2026-08-25)**: siempre commitear en el
   worktree real de trabajo del proyecto, nunca en uno de prod ni en uno creado para una investigación
   o tarea aislada (`superpowers:using-git-worktrees`, `isolation: "worktree"`, `EnterWorktree`) — los
   prompts e investigaciones de este proyecto usan siempre ese worktree, sobre una rama efímera.
6. Si el working tree mezcla trabajo de la sesión actual con trabajo previo sin commitear de otro
   origen, preguntar cómo separar en vez de `git add .` por default. Para un archivo compartido con
   hunks de ambos orígenes: extraer con `git diff -- <archivo>` los hunks propios (por número de
   línea y encabezado `@@`), armar un patch sólo con esos hunks, validar con
   `git apply --cached --check <patch>`, aplicar con `git apply --cached <patch>` (no toca el working
   tree), `git add` el resto de archivos 100% propios y commitear — el diff restante contra el nuevo
   `HEAD` queda listo para el otro commit sin trabajo manual adicional.
7. Nunca hacer push directo a `dev` ni a `main` desde este comando — la
   integración a `dev` es responsabilidad exclusiva de `cierre-sesion`.
