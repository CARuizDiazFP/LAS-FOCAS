# Nombre de archivo: repo-updater.prompt.md
# Ubicación de archivo: .github/prompts/repo-updater.prompt.md
# Descripción: Prompt para auditar trazabilidad, documentar cambios y ejecutar commit más push a main

---
name: Repo Updater
description: "Sincroniza cambios con main: audita diff, valida docs/PR y docs temáticas, genera commit técnico y hace push"
argument-hint: "Describe alcance o rama esperada, por ejemplo: validar cambios de api y docs antes de subir a main"
agent: "agent"
---

# Rol

Actuar como actualizador autónomo del repositorio LAS-FOCAS, usando directamente la CLI de `git` del sistema para validar trazabilidad, completar documentación faltante y sincronizar el estado local con la rama `main`.

# Contexto

- El repositorio exige que los cambios reales queden reflejados en `docs/PR/YYYY-MM-DD.md` y, si corresponde, en la documentación temática bajo `docs/`.
- La fecha del PR diario debe identificarse dinámicamente con la fecha actual del sistema en formato `YYYY-MM-DD`.
- Los commits deben ser técnicos, concisos y coherentes con el diff real.
- Si el cambio toca `.github/`, la documentación relacionada mínima es `docs/Mate_y_Ruta.md` además del PR diario.
- La rama objetivo por defecto es `main` y el push debe hacerse al remoto `origin`.

# Objetivo

Ejecutar el flujo completo de revisión, documentación, staging, commit y push, sin omitir la auditoría de trazabilidad entre el diff actual, el PR diario vigente y la documentación de `docs/`.

# Pasos

1. Inspeccionar el estado real del repositorio con CLI de `git`:
   ```bash
   git fetch origin main
   git status --short --branch
   git diff --stat
   git diff --cached --stat
   git diff --name-status
   git log --oneline origin/main..HEAD
   ```
2. Determinar la fecha actual y ubicar el archivo `docs/PR/YYYY-MM-DD.md`. Si no existe, crearlo con encabezado obligatorio de 3 líneas.
3. Analizar si el diff real ya está documentado en el PR diario vigente y en la documentación temática de `docs/`.
4. Si falta trazabilidad, actualizar antes de continuar:
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
5. Verificar que la documentación nueva o actualizada contraste con el estado actual del código. Si detectas información vieja o inconsistente, corregirla aunque no haya sido el foco principal del pedido.
6. Construir un mensaje de commit técnico, corto y semántico, derivado del diff real. Reglas mínimas:
   - usar scopes o módulos reales cuando aporten claridad
   - evitar mensajes genéricos como `update`, `misc`, `fix stuff` o equivalentes
   - reflejar el cambio dominante del diff
7. Ejecutar el flujo de versionado:
   ```bash
   git add .
   git commit -m "<mensaje_tecnico>"
   git push origin main
   ```
8. Si `git push` falla por divergencia, no hacer `push --force`. Explicar el bloqueo y, solo si es seguro y consistente con el estado local, preparar la resolución con `git pull --rebase origin main` antes de reintentar.
9. Entregar un cierre corto con:
   - archivos de documentación creados o actualizados
   - mensaje de commit usado
   - resultado del push
   - riesgos o pendientes reales

# Criterios de Aceptación

- [ ] Se inspeccionó el estado del repo con `git status` y `git diff`.
- [ ] Se identificó el PR diario correspondiente a la fecha actual.
- [ ] El diff quedó contrastado contra `docs/PR/` y contra la documentación relevante en `docs/`.
- [ ] Si faltaba documentación, se creó o actualizó antes del commit.
- [ ] El commit generado es técnico, conciso y describe el diff real.
- [ ] Se ejecutó `git add .`, `git commit` y `git push origin main`, o se dejó explicitado el bloqueo real.

# Reglas adicionales

1. No inventar validaciones, commits ni pushes que no hayan ocurrido.
2. No incluir secretos, tokens ni credenciales en la documentación ni en el commit.
3. No usar comandos destructivos como `git reset --hard` o `git push --force` sin pedido explícito.
4. Mantener todo el contenido en español técnico y concreto.