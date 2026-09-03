---
name: "las-focas-cierre-sesion"
description: "Usar al finalizar una sesión de trabajo, sólo con declaración explícita de cierre, para generar una retrospectiva técnica, evaluar evolución agéntica del entorno y mergear automáticamente la rama efímera activa a dev"
metadata:
  short-description: "Usar al finalizar una sesión de trabajo, sólo con declaración explícita de cierre, para generar una retrospectiva técnica: tareas verif..."
  source: ".agentes-comunes/skills/cierre-sesion/SKILL.md"
  triggers:
    - "cierre-sesion"
    - "cierre"
    - "sesion"
    - "cierre de sesion"
    - "cerrar sesion"
    - "cerremos sesion"
    - "cierre chat"
    - "retrospectiva"
    - "habilidad"
    - "tareas"
    - "errores"
    - "bloqueos"
    - "soluciones"
    - "propuestas"
    - "prevencion"
    - "aceleracion"
    - "riesgo"
    - "auto-merge"
    - "skills"
    - "agentes"
    - "prompts"
  globs:
    - "docs/cierres/**"
    - "docs/**"
    - ".github/**"
    - ".codex-skills/**"
    - ".gemini/**"
  commands:
    []
---

# Nombre de archivo: SKILL.md
# Ubicación de archivo: .codex-skills/skills/las-focas-cierre-sesion/SKILL.md
# Descripción: Skill portable Codex migrada desde .github/skills/cierre-sesion/SKILL.md

# Skill portable: cierre-sesion

> Fuente original: `.agentes-comunes/skills/cierre-sesion/SKILL.md`. Copia portable generada porque `.codex/` está montado como solo lectura en esta sesión.

# Habilidad: Cierre de Sesión

Workflow invocable para analizar la conversación activa al finalizar el trabajo, extraer conocimiento
técnico factual que retroalimente el ecosistema de agentes del proyecto, y — como paso final —
integrar automáticamente la rama efímera de la sesión a `dev`.

## Cuándo usar

Usar esta skill sólo cuando el usuario declara explícitamente el fin de la sesión:

- invoca `/cierre-sesion` explícitamente, o
- escribe una frase inequívoca de cierre: "Cerrar sesión", "Cerremos sesión", "Cierre chat", "cierre
  de sesión", "terminamos la sesión", "este es el cierre del chat", "cerrá la sesión con una
  retrospectiva"

**No** activar por sólo nombrar la skill al pasar, completar una tarea, pedir estado o solicitar
documentación. Si un trigger heurístico dispara esta skill sin ese gate cumplido, no elaborar ni
persistir la retrospectiva: continuar la tarea normal e indicar en una línea que el cierre queda
reservado para cuando se declare explícitamente.

## Procedimiento

1. Confirmar el gate de activación. Si no se cumple, no continuar con los pasos siguientes.
2. Leer `AGENTS.md`, el historial disponible de la conversación activa, resultados de tool calls, el
   diff actual (`git status`/`git diff`) y la documentación de dominio afectada. Declarar cualquier
   límite de evidencia detectado (p.ej. contexto truncado por compactación automática).
3. Delimitar qué cambios son propios de esta sesión, cuáles son preexistentes del worktree y cuáles
   son acciones externas.
4. Contrastar cada tarea supuestamente terminada contra código, tests, logs, estado del sistema o
   documentación. Clasificarla como completada, parcial, bloqueada o no verificada.
5. Documentar errores, bloqueos o problemas post-implementación realmente enfrentados: síntoma, causa
   raíz confirmada o hipótesis explícita, impacto.
6. Detallar con precisión reutilizable la solución aplicada a cada error/bloqueo: archivo/componente,
   decisión técnica, validación ejecutada, condición que indicaría una regresión futura (o marcar sin
   resolver).
7. Revisar vigencia: corregir documentación desactualizada cuando la evidencia la contradiga. Corregir
   lógica fuera de la tarea principal sólo si está verificado y autorizado; si no, registrar como
   pendiente concreto.
8. Evaluar mejoras agénticas en dos carriles — prevención (obstáculos reales de esta sesión) y
   aceleración (pasos repetibles observados que agilizarían implementaciones similares futuras). Por
   cada candidata: evidencia, frecuencia esperada, beneficio, costo de mantenimiento y opción
   recomendada, prefiriendo ampliar una skill existente.
9. Determinar la fecha actual (`YYYY-MM-DD`).
10. Clasificar cada propuesta de evolución agéntica del paso 8 con esta tabla de riesgo (mismo patrón
    ya usado en `docker-cleanup/SKILL.md`, no se inventa taxonomía nueva):

    | Riesgo | Criterio | Acción |
    |---|---|---|
    | 🟢 Bajo | Agrega guardrail, corrige doc, amplía un skill existente sin tocar permisos de `main`/producción ni introducir un mecanismo de push/merge nuevo | Se implementa en este mismo cierre |
    | 🟡 Medio | Ídem, pero con superficie de cambio mayor (varios archivos/skills) o que toca un flujo ya en uso activo | Se implementa en este mismo cierre |
    | 🔴 Muy alto | Toca permisos sobre `main`/producción, debilita un guardrail existente, o introduce un mecanismo de push/merge automático nuevo no cubierto ya por una skill vigente | Se detiene el flujo (ver paso 11) |

11. **Compuerta de Riesgo**: si al menos una propuesta quedó clasificada 🔴, presentar su estado (qué
    cambiaría y por qué se clasificó así), preguntar explícitamente al usuario si se avanza, y
    **detener el flujo completo** (no continuar a los pasos 12-15) hasta recibir una respuesta. Si
    todas las propuestas son 🟢/🟡 o no hay propuestas, continuar sin pausas.
12. Implementar las propuestas 🟢/🟡 de evolución agéntica aprobadas (crear/editar skills, comandos o
    guardrails). Si la propuesta crea o edita un skill, seguir `superpowers:writing-skills` para su
    estructura y validación. Registrar con precisión qué archivos de gobernanza se tocaron y por qué
    — esto va en el reporte del paso 13, no sólo en el checklist final (mitiga que el mismo agente que
    propone sea quien clasifica su propio riesgo).
13. Crear o anexar `docs/cierres/YYYY-MM-DD.md` sin perder cierres previos del mismo día, con el
    reporte completo (tareas, errores/soluciones, evolución agéntica implementada/propuesta y su
    clasificación de riesgo, archivos de gobernanza tocados) y confirmar la ruta del archivo guardado.
14. **Flujo de Auto-Merge** — integrar la rama efímera activa de esta sesión a `dev`. Antes de
    cualquier operación: confirmar con `git branch --show-current` que la rama activa matchea
    `^(feat|fix|docs|chore|refactor|test)/` — si es `dev`, `main`, o no matchea el patrón,
    **DETENERSE inmediatamente** sin ejecutar ningún comando de este flujo (ni merge, ni push,
    ni borrado de rama), reportarlo en el checklist final, y no continuar. Recién con la rama
    efímera confirmada:
    ```bash
    git checkout <rama-efímera-actual>
    git fetch origin
    git merge origin/dev
    ```
    Si `git diff --name-only --diff-filter=U` devuelve archivos en conflicto: leer los marcadores
    `<<<<<<<`/`=======`/`>>>>>>>`, entender la lógica de ambos lados y resolver reescribiendo
    correctamente, luego `git add .`. El commit de fusión resultante debe documentar en su mensaje
    qué archivos tuvieron conflicto y el criterio de resolución aplicado (trazabilidad posterior, no
    es un gate de aprobación). Si no hubo conflictos, el merge es directo. Luego:
    ```bash
    git checkout dev
    git pull origin dev
    git merge <rama-efímera-actual>
    git push origin dev
    git branch -d <rama-efímera-actual>
    git push origin --delete <rama-efímera-actual>
    ```
    **Excepción**: si en esta misma sesión el usuario indicó explícitamente que esta rama debe
    diferirse (ej. ventana de mantenimiento — precedente real: `fix-baneos-hermanos-prod`), no forzar
    este flujo. Dejar la rama activa sin mergear, documentarlo en el checklist final, y sugerir
    `superpowers:finishing-a-development-branch` para cuando corresponda integrarla.
15. Mostrar **exclusivamente** este checklist al usuario (el reporte completo vive en
    `docs/cierres/YYYY-MM-DD.md`, no se reimprime en el chat):
    - Análisis retrospectivo completado
    - Evolución agéntica implementada/propuesta
    - Actualización de documentación
    - Merge a Dev
    - Final de sesión

## Referencias

- [Prompt asociado](../../prompts/cierre-sesion.prompt.md)
- Este flujo reemplaza a `superpowers:finishing-a-development-branch` específicamente para el cierre
  de sesión: el trigger de cierre ya constituye la decisión de integración explícita del usuario, por
  lo que no se invoca ese skill acá (evita volver a preguntar algo ya resuelto). Fuera de este flujo
  (rama deliberadamente diferida), `finishing-a-development-branch` sigue siendo la herramienta
  correcta. `superpowers:using-git-worktrees` es independiente (aislamiento de directorio, no ramas) y
  no se ve afectado por este flujo.
- `docker-cleanup/SKILL.md` — origen de la tabla de riesgo 🟢/🟡/🔴 reutilizada en el paso 10.

## Guardrails

1. Basarse únicamente en hechos verificables de la conversación activa; no inventar tareas, errores ni
   soluciones. Declarar límites de evidencia.
2. No proponer skills/agentes/prompts especulativos: prevención requiere un obstáculo real, aceleración
   requiere un paso repetible ya observado.
3. No crear ni modificar otras skills automáticamente salvo lo que resulte del paso 12 (evolución
   agéntica 🟢/🟡 ya evaluada) o solicitud expresa del usuario. Si se cataloga una skill nueva,
   verificar que tenga mirror en `.claude/skills/<nombre>/SKILL.md` para ser invocable por el tool
   `Skill`.
4. No sobrescribir cierres de sesión previos del mismo día; anexar como sección nueva.
5. No incluir secretos, tokens ni credenciales en el reporte.
6. El paso 14 (auto-merge) es un paso final propio de este skill, no una redefinición de
   `repo-updater`: los commits/push intermedios de la sesión sobre la rama efímera siguen siendo
   responsabilidad de `dev-workflow`/`repo-updater` durante el trabajo; este skill sólo integra el
   resultado final a `dev` al cerrar.
7. Sin declaración explícita de cierre del usuario, no elaborar ni persistir la retrospectiva ni
   ejecutar el auto-merge.
8. Ninguna propuesta de evolución agéntica clasificada 🔴 (muy alto riesgo) se implementa sin respuesta
   explícita del usuario — el flujo se detiene en el paso 11 hasta obtenerla.
9. El auto-merge del paso 14 es autónomo, incluida la resolución de conflictos, salvo que el usuario
   haya indicado explícitamente en la misma sesión que esa rama debe diferirse.
10. El commit de fusión del paso 14 documenta en su mensaje los archivos en conflicto (si los hubo) y
    el criterio de resolución aplicado.
11. Si hubo flujo recursivo SDD/superpowers durante la sesión, registrar métricas de ciclo y alertas
    según `docs/sdd_metricas_ciclo.md`.
12. El flujo de auto-merge nunca se ejecuta si la rama activa no matchea el patrón de rama efímera
    (`feat|fix|docs|chore|refactor|test`/...) — evita borrar o mutar `dev`/`main` por error si no
    se creó una rama efímera.

## Resultado esperado

- Reporte Markdown completo (tareas verificadas contra evidencia, errores/bloqueos, soluciones
  aplicadas, evolución agéntica con su clasificación de riesgo) guardado en
  `docs/cierres/YYYY-MM-DD.md`.
- Propuestas 🟢/🟡 de evolución agéntica implementadas; propuestas 🔴 detenidas hasta respuesta del
  usuario.
- Rama efímera de la sesión mergeada a `dev` y pusheada (o explícitamente diferida por pedido del
  usuario), rama efímera borrada tras el merge exitoso.
- Checklist final de 5 líneas mostrado al usuario en el chat.
