# Nombre de archivo: repo-updater.md
# Ubicación de archivo: .claude/commands/repo-updater.md
# Descripción: Comando Claude Code para auditar trazabilidad, documentar cambios y hacer push a dev

Actuar como actualizador autónomo del repositorio LAS-FOCAS. Argumento opcional del usuario: $ARGUMENTS

# Rol

Validar trazabilidad entre el diff real, el PR diario vigente y la documentación temática. Completar documentación faltante y sincronizar el estado local con la rama `dev`.

# Contexto

- El repositorio exige que los cambios reales queden reflejados en `docs/PR/YYYY-MM-DD.md` y, si corresponde, en la documentación temática bajo `docs/`.
- La fecha del PR diario debe identificarse dinámicamente con la fecha actual del sistema en formato `YYYY-MM-DD`.
- Los commits deben ser técnicos, concisos y coherentes con el diff real.
- Si el cambio toca `.github/` o `.claude/`, la documentación mínima es `docs/Mate_y_Ruta.md` además del PR diario.
- La rama objetivo por defecto es `dev`. Push a `main` prohibido; solo vía PR revisado.

# Pasos

1. Inspeccionar el estado real del repositorio:
   ```bash
   git fetch origin dev
   git status --short --branch
   git diff --stat
   git diff --cached --stat
   git diff --name-status
   git log --oneline origin/dev..HEAD
   ```
2. Determinar la fecha actual y ubicar `docs/PR/YYYY-MM-DD.md`. Si no existe, crearlo con encabezado obligatorio de 3 líneas.
3. Analizar si el diff real ya está documentado en el PR diario y en la documentación temática de `docs/`.
4. Si falta trazabilidad, actualizar antes de continuar:
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
5. Verificar que la documentación nueva o actualizada contraste con el estado actual del código. Corregir información vieja o inconsistente aunque no sea el foco principal.
6. Construir un mensaje de commit técnico y semántico derivado del diff real. Evitar `update`, `misc`, `fix stuff` o equivalentes.
7. Ejecutar el flujo de versionado:
   ```bash
   git add .
   git commit -m "<mensaje_tecnico>"
   git push origin dev
   ```
8. Si `git push` falla por divergencia, no hacer `push --force`. Explicar el bloqueo y, si es seguro, preparar resolución con `git pull --rebase origin dev`.
9. Entregar un cierre corto: archivos actualizados, mensaje de commit, resultado del push y riesgos o pendientes.

# Criterios de Aceptación

- [ ] Estado del repo inspeccionado con `git status` y `git diff`
- [ ] PR diario correspondiente a la fecha actual identificado y actualizado
- [ ] Diff contrastado contra `docs/PR/` y documentación temática
- [ ] Commit técnico y conciso que describe el diff real
- [ ] `git push origin dev` ejecutado o bloqueo real documentado

# Reglas

1. No inventar validaciones, commits ni pushes que no hayan ocurrido.
2. No incluir secretos, tokens ni credenciales en documentación ni commits.
3. No usar `git reset --hard` ni `git push --force` sin pedido explícito.
4. Mantener todo el contenido en español técnico.
