# Nombre de archivo: 2026-09-03-rama-efimera-cierre-sesion-design.md
# Ubicación de archivo: docs/superpowers/specs/2026-09-03-rama-efimera-cierre-sesion-design.md
# Descripción: Spec de diseño — Feature Branching Efímero obligatorio + Flujo Secuencial de Cierre de Sesión con auto-merge autónomo a dev

# Feature Branching Efímero + Cierre de Sesión con Auto-Merge

## Contexto y motivación

El flujo actual (`dev-workflow`, `repo-updater`) prescribe commit y push directos sobre `dev`. Esto
funciona con un solo agente a la vez, pero genera conflictos cuando varios agentes trabajan en
paralelo sobre el mismo checkout. `cierre-sesion` hoy es puramente retrospectivo (escribe
`docs/cierres/YYYY-MM-DD.md`, nunca toca git en escritura).

Este documento define dos cambios acoplados:

1. **Feature Branching Efímero** (obligatorio, sin excepciones): todo trabajo ocurre en una rama
   nueva creada desde `origin/dev`, nunca directo sobre `dev`/`main`.
2. **Flujo Secuencial de Cierre de Sesión**: `cierre-sesion` pasa a incluir, además de la
   retrospectiva existente, una compuerta de riesgo para auto-evolución del entorno y un flujo de
   auto-merge autónomo (incluida resolución de conflictos) que integra la rama efímera a `dev`.

## Decisiones ya confirmadas por el usuario (2026-09-03)

- **Auto-merge**: autonomía total. Ante conflictos reales, el agente lee los marcadores
  (`<<<<<<<`/`=======`/`>>>>>>>`), entiende la lógica y resuelve reescribiendo, sin checkpoint humano
  en ningún punto del merge/push a `dev`.
- **Alcance de ramas efímeras**: universal, sin excepciones — ningún skill/agente commitea directo
  en `dev`.
- **Triggers de cierre-sesion**: aditivos — "Cerrar sesión"/"Cerremos sesión" se suman a los triggers
  existentes ("Cierre chat", `/cierre-sesion`, etc.), no los reemplazan.
- **Evolución agéntica de riesgo bajo/medio**: se implementa en la misma sesión, sin paso de revisión
  separado, pero el reporte final debe listar explícitamente qué archivos de gobernanza se tocaron
  (mitiga el conflicto de interés de que el mismo agente clasifica su propio riesgo).

## Alcance real (qué toca, qué no)

Sólo tres familias de skills hacen escritura de git hoy: `dev-workflow` (valida y centraliza la regla
de rama), `repo-updater` (ejecuta el commit/push real), `cierre-sesion` (pasa a hacer el merge final).
El resto de los skills (migracion-alembic, nuevo-modulo, docker-cleanup, etc.) no commitean por sí
mismos — dependen de que el agente invoque `dev-workflow`/`repo-updater` para eso. Por lo tanto
"universal, sin excepciones" se logra centralizando la regla en estas tres familias, sin tocar cada
skill individualmente.

### Archivos a modificar

**`dev-workflow`** (fuente de verdad + mirrors, 5 archivos):
- `.agentes-comunes/skills/dev-workflow/SKILL.md` (fuente de verdad)
- `.github/skills/dev-workflow/SKILL.md`
- `.codex-skills/skills/las-focas-dev-workflow/SKILL.md` (incluye bloque `commands:` en frontmatter)
- `.gemini/rules/skill-dev-workflow.md` (incluye bloque `commands:` en frontmatter)
- `.claude/skills/dev-workflow/SKILL.md` — **nuevo**, no existe hoy; cierra un gap real (el skill no es
  invocable por el tool `Skill` de Claude Code actualmente)

**`cierre-sesion`** (fuente de verdad + mirrors + comando, 6 archivos):
- `.agentes-comunes/skills/cierre-sesion/SKILL.md` (fuente de verdad)
- `.github/skills/cierre-sesion/SKILL.md`
- `.codex-skills/skills/las-focas-cierre-sesion/SKILL.md` (backfillear guardrail de métricas SDD que
  falta hoy vs. `.github`, drift preexistente)
- `.gemini/rules/skill-cierre-sesion.md` (mismo backfill)
- `.claude/skills/cierre-sesion/SKILL.md` (ya existe; backfill del mismo guardrail)
- `.claude/commands/cierre-sesion.md`
- `.github/prompts/cierre-sesion.prompt.md` (prompt referenciado desde "Referencias" del skill)

**`repo-updater`** (fuente de verdad + mirrors, 6 archivos):
- `.agentes-comunes/skills/repo-updater/SKILL.md` (fuente de verdad)
- `.github/skills/repo-updater/SKILL.md`
- `.claude/commands/repo-updater.md`
- `.github/prompts/repo-updater.prompt.md`
- `.gemini/rules/skill-repo-updater.md`
- `.gemini/rules/prompt-repo-updater-prompt.md`
- `.codex-skills/skills/las-focas-repo-updater/SKILL.md`

**Docs** (3 archivos):
- `docs/entorno_dev.md` — sección "Modelo de ramas" y "Flujo de commits en rama dev"
- `AGENTS.md` — línea 33 (convención de rama de trabajo)
- `CLAUDE.md` — filas de guardrail de `dev-workflow`/`cierre-sesion`/`repo-updater` en las tablas de
  comandos y skills, y el banner de "Skills Disponibles" (stale: dice que sólo `docker-rebuild` y
  `nocturne-token-compliance` tienen mirror en `.claude/skills/`, pero `cierre-sesion` ya lo tiene hoy
  en disco — corregir independientemente de esta tarea)

Total: ~22 archivos.

## Diseño detallado

### 1. Convención de nombres y ciclo de vida de la rama efímera

`<tipo>/<slug-kebab-case>`, con `<tipo>` tomado del mismo vocabulario ya usado en mensajes de commit
(`feat|fix|docs|chore|refactor|test`). Se crea una sola vez por tarea/sesión (si ya se está parado en
una rama que matchea el patrón, se reutiliza — no se anidan ramas). Se borra (local y remoto) recién
después de que `cierre-sesion` la mergea exitosamente a `dev`.

### 2. `dev-workflow` — nuevo paso 1 y paso 4

Reemplaza la verificación binaria `dev` vs. `main` por:

```
1. Verificar rama activa (`git branch --show-current`).
   - Si es una rama efímera vigente (`feat/*`, `fix/*`, `docs/*`, `chore/*`, `refactor/*`, `test/*`):
     continuar, es la rama de trabajo de esta tarea.
   - Si es `dev` o `main`: está PROHIBIDO modificar código o commitear ahí. Crear una rama efímera
     nueva desde el estado remoto de dev:
     git fetch origin
     git checkout -b <tipo>/<slug> origin/dev
   - Si `dev` no existe en el remoto: crearla primero (git checkout -b dev && git push -u origin dev)
     y luego la rama efímera desde ahí.
```

```
4. Commits y push (siempre sobre la rama efímera activa, nunca sobre dev/main):
   git branch --show-current  # debe ser <tipo>/<slug>, nunca dev ni main
   git add .
   git commit -m "<tipo>(módulo): descripción técnica"
   git push -u origin HEAD    # NUNCA: git push origin dev ni git push origin main directamente
   La integración a dev ocurre exclusivamente vía cierre-sesion (auto-merge) o, para ramas
   deliberadamente diferidas (ej. ventana de mantenimiento), vía superpowers:finishing-a-development-branch.
```

Guardrails: agregar prohibición explícita de commit/push estando parado en `dev`/`main`; agregar nota
de que una rama efímera es un `git checkout -b` dentro del mismo checkout (no un worktree) — para
aislamiento de directorio real se usa `superpowers:using-git-worktrees`, mecanismo independiente y
combinable. Mantener intacta la prohibición de push a `main`.

### 3. `repo-updater` — redirección de push, guardrail de worktree intacto

Paso 1 (verificación de destino): cambia "`git rev-parse --abbrev-ref HEAD` debe ser `dev`" por "debe
ser una rama efímera activa (no `dev`, no `main`) creada según `dev-workflow`". El guardrail 6 (regla
dura confirmada 2026-08-25: nunca commitear en un worktree de prod/aislado) queda **sin cambios** — es
sobre el worktree (directorio), no sobre la rama, y es ortogonal a este cambio.

Paso de push: `git push origin dev` → `git push -u origin HEAD` (empuja la rama efímera activa,
cualquiera sea su nombre, sin necesidad de interpolar el nombre a mano). Actualizar toda mención de
"push a dev" en la descripción del skill/comando a "push a la rama efímera activa (la integración a
`dev` es automática al cierre de sesión)".

### 4. `cierre-sesion` — flujo secuencial completo

Procedimiento renumerado (pasos 1-9 = retrospectiva existente, sin cambios de fondo):

```
10. Evaluar mejoras agénticas (evolución) y clasificar cada propuesta con la tabla de riesgo:
    🟢 Bajo / 🟡 Medio: agrega guardrail, corrige doc, amplía un skill existente sin tocar permisos
       de main/producción ni introducir un mecanismo de push/merge nuevo.
    🔴 Muy alto: toca permisos sobre main/prod, debilita un guardrail existente, o introduce un
       mecanismo de push/merge automático nuevo no cubierto por este mismo documento.
    (Tabla reutiliza el patrón ya existente en docker-cleanup/SKILL.md, no se inventa taxonomía nueva.)

11. Compuerta de Riesgo: si hay al menos una propuesta 🔴, presentar su estado, preguntar si se
    avanza y DETENER el flujo completo (no continuar a los pasos 12-15) hasta recibir respuesta
    explícita. Si todas las propuestas son 🟢/🟡 o no hay propuestas, continuar.

12. Implementar las propuestas 🟢/🟡. Registrar con precisión qué archivos de gobernanza se tocaron
    y por qué (mitigación del conflicto de interés: el mismo agente que propone clasifica el riesgo).

13. Actualización de Documentación: escribir/anexar docs/cierres/YYYY-MM-DD.md con el reporte
    completo (igual que hoy) + la lista explícita de archivos tocados en el paso 12. También
    corregir cualquier documentación desactualizada encontrada, sea o no de esta sesión.

14. Flujo de Auto-Merge (nuevo):
    git checkout <rama-efímera-actual>
    git fetch origin
    git merge origin/dev
    # Si hay conflictos (git diff --name-only --diff-filter=U):
    #   leer marcadores <<<<<<<//=======//>>>>>>>, entender la lógica de ambos lados, resolver
    #   reescribiendo correctamente, git add .
    #   El commit de fusión debe documentar en su mensaje qué archivos tuvieron conflicto y el
    #   criterio de resolución aplicado (trazabilidad, no es un gate).
    git checkout dev
    git pull origin dev
    git merge <rama-efímera-actual>
    git push origin dev
    git branch -d <rama-efímera-actual>; git push origin --delete <rama-efímera-actual>
    Excepción: si en esta misma sesión el usuario indicó explícitamente que la rama debe diferirse
    (ej. ventana de mantenimiento, precedente real: fix-baneos-hermanos-prod), NO forzar el merge —
    dejar la rama activa, documentarlo en el checklist final, y sugerir
    superpowers:finishing-a-development-branch para cuando corresponda integrarla.

15. Output Final: imprimir EXCLUSIVAMENTE este checklist (reemplaza la exhibición completa del
    reporte en el chat — el reporte completo íntegro sigue viviendo en docs/cierres/YYYY-MM-DD.md):
    - Análisis retrospectivo completado
    - Evolución agéntica implementada/propuesta
    - Actualización de documentación
    - Merge a Dev
    - Final de sesión
```

Triggers (paso "Cuándo usar"): agregar "Cerrar sesión" / "Cerremos sesión" a la lista existente
("Cierre chat", `/cierre-sesion`, etc.) — aditivo, no reemplaza.

Guardrails: mantener 1-7 existentes, con ajuste al guardrail "no mezclar con repo-updater" para
aclarar que sigue siendo válido para el mid-sesión (repo-updater sigue siendo responsable de la
auditoría de diff/PR/doc temática y de los pushes intermedios a la rama efímera) — el auto-merge de
cierre-sesion es un paso final distinto, no una redefinición de repo-updater. Agregar:
- Ninguna propuesta 🔴 se implementa sin respuesta explícita del usuario (compuerta de riesgo).
- El auto-merge es autónomo (incluida resolución de conflictos) salvo instrucción explícita previa
  de diferir esa rama en la misma sesión.
- El commit de fusión documenta en su mensaje los archivos en conflicto y el criterio de resolución.

### 5. Coexistencia con Superpowers (tarea adicional del usuario)

- **`finishing-a-development-branch`**: su patrón es presentar un menú de 3 opciones y esperar la
  decisión de integración humana. Para el flujo de `cierre-sesion`, el propio trigger ("Cerrar
  sesión"/"Cerremos sesión") ya es esa decisión de integración explícita — por diseño, `cierre-sesion`
  NO invoca este skill (se documenta como supersesión deliberada, para no volver a preguntar algo ya
  resuelto). Fuera de `cierre-sesion` (rama deliberadamente diferida) sigue siendo la herramienta
  correcta, sin cambios.
- **`using-git-worktrees`**: gobierna aislamiento de directorio, no ramas dentro del mismo checkout.
  Sin conflicto — se documenta la distinción en `dev-workflow` para que no se confundan ambos
  mecanismos.
- **`writing-skills`**: cuando el paso 12 (evolución agéntica) cree o edite un skill, debe seguirse
  `superpowers:writing-skills` para el CÓMO (estructura, validación) — `cierre-sesion` sólo gobierna
  el CUÁNDO y la compuerta de riesgo, no reemplaza esa skill.

### 6. Docs

- `docs/entorno_dev.md`: "Modelo de ramas" — `feature/xxx` deja de ser "opcional" y pasa a
  "obligatoria, creada automáticamente por dev-workflow, integrada a dev por cierre-sesion".
  "Flujo de commits en rama dev" — reescribir para describir creación de rama + push a la rama
  efímera, con nota de que `dev` sólo recibe merges vía `cierre-sesion`.
- `AGENTS.md` línea 33: reflejar rama efímera obligatoria + integración automática al cierre.
- `CLAUDE.md`: actualizar filas de guardrail de las 3 skills en ambas tablas; corregir el banner de
  mirrors de `.claude/skills/` (agregar `dev-workflow`, corregir que `cierre-sesion` ya estaba
  mirrado antes de esta tarea).

## Riesgos y mitigaciones ya decididas

- **Merge conflictivo mal resuelto sin revisión humana**: riesgo aceptado explícitamente por el
  usuario (autonomía total). Mitigación incluida: el commit de fusión documenta qué se resolvió y
  cómo, para auditoría posterior aunque no haya gate en el momento.
- **Rama efímera abandonada** (sesión que nunca cierra formalmente): no se resuelve en este diseño
  (YAGNI) — el precedente real (`fix-baneos-hermanos-prod`) ya muestra que una rama sin mergear queda
  simplemente visible en `git branch -a` para retomar manualmente o vía
  `finishing-a-development-branch`.
