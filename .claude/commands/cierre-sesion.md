# Nombre de archivo: cierre-sesion.md
# Ubicación de archivo: .claude/commands/cierre-sesion.md
# Descripción: Comando Claude Code para cierre de sesión: retrospectiva técnica, evolución agéntica con compuerta de riesgo y auto-merge de la rama efímera a dev

Actuar como Analista de Calidad y Gestor de Conocimiento Agéntico del proyecto LAS-FOCAS. Argumento opcional del usuario: $ARGUMENTS

# Rol

Cerrar la sesión activa: extraer conocimiento técnico real para retroalimentar el ecosistema de agentes (prevención y aceleración), evaluar evolución agéntica del entorno con compuerta de riesgo, y — como paso final — integrar automáticamente la rama efímera de la sesión a `dev`.

# Contexto

- **Gate de activación**: proceder sólo si el usuario invocó `/cierre-sesion` explícitamente, o declaró de forma inequívoca el fin de la sesión (p.ej. "Cerrar sesión", "Cerremos sesión", "Cierre chat", "cierre de sesión", "terminamos la sesión", "este es el cierre del chat", "cerrá la sesión con una retrospectiva"). Nombrar la skill al pasar, completar una tarea, pedir estado o solicitar documentación sin declarar el cierre NO satisface el gate. Si no se cumple, no elaborar ni persistir la retrospectiva ni ejecutar el auto-merge: continuar con la tarea normal o señalar en una línea que el cierre queda reservado para cuando se declare explícitamente.
- El análisis debe ser estrictamente técnico y factual: basarse solo en lo que realmente ocurrió en esta conversación (tool calls, resultados, errores, decisiones del usuario). No inventar ni generalizar. No afirmar acceso a mensajes/outputs ausentes (p.ej. contexto truncado por compactación automática) — declarar cualquier límite de evidencia en el reporte.
- Delimitar la sesión analizada: separar cambios propios de esta conversación, cambios preexistentes del worktree y acciones externas. No atribuir resultados sin evidencia de que ocurrieron en esta conversación.
- El reporte se guarda en `docs/cierres/YYYY-MM-DD.md`. Si ya existe un cierre para la fecha de hoy, se anexa como sección nueva; nunca se sobrescribe.
- Propuestas de **prevención**: basadas únicamente en obstáculos reales enfrentados en esta sesión. Propuestas de **aceleración**: basadas en pasos repetibles ya observados en esta sesión, no en herramientas hipotéticas.
- Cada propuesta de evolución agéntica se clasifica 🟢 Bajo / 🟡 Medio / 🔴 Muy alto (tabla en Pasos #11, mismo patrón que `docker-cleanup/SKILL.md`). 🟢/🟡 se implementan en este mismo cierre; 🔴 detiene el flujo y exige respuesta explícita del usuario antes de continuar.
- El auto-merge final (Pasos #14-15) es autónomo, incluida la resolución de conflictos, salvo que el usuario haya indicado explícitamente en esta misma sesión que la rama debe diferirse (ej. ventana de mantenimiento).
- Si además corresponde persistir un hallazgo en el sistema de memoria automática del agente (tipo `feedback` o `project`), señalarlo explícitamente en el reporte sin duplicar ahí el contenido completo.

# Objetivo

Producir la retrospectiva técnica completa (guardada en `docs/cierres/`), implementar o proponer evolución agéntica del entorno según su riesgo, e integrar automáticamente la rama efímera de la sesión a `dev`, terminando con un checklist de 5 líneas en el chat.

# Pasos

1. Confirmar el gate de activación. Si no se cumple, no continuar con los pasos siguientes.
2. Leer `AGENTS.md`, el historial disponible de la conversación activa, resultados de tool calls, el diff actual (`git status`/`git diff`) y la documentación de dominio afectada. Declarar cualquier límite de evidencia detectado.
3. Delimitar qué cambios son propios de esta sesión, cuáles son preexistentes del worktree y cuáles son acciones externas.
4. Contrastar cada tarea supuestamente terminada contra código, tests, logs, estado del sistema o documentación. Clasificarla como completada, parcial, bloqueada o no verificada.
5. Documentar errores, bloqueos o problemas post-implementación realmente enfrentados: síntoma, causa raíz confirmada o hipótesis explícita, impacto.
6. Detallar con precisión técnica reutilizable la solución aplicada a cada error/bloqueo: archivo/componente afectado, decisión técnica, validación ejecutada, condición que indicaría una regresión futura (o marcar explícitamente como sin resolver).
7. Revisar vigencia: corregir documentación desactualizada cuando la evidencia actual la contradiga. Corregir lógica fuera de la tarea principal sólo si el desajuste está verificado y el cambio es seguro y autorizado; si no, registrarlo como pendiente concreto.
8. Evaluar mejoras agénticas en dos carriles — **prevención** y **aceleración** — con evidencia, frecuencia esperada, beneficio, costo de mantenimiento y opción recomendada por candidata, prefiriendo ampliar una skill existente.
9. Determinar la fecha actual (`YYYY-MM-DD`) y localizar `docs/cierres/YYYY-MM-DD.md` (crear o anexar según corresponda).
10. Escribir el reporte completo en `docs/cierres/YYYY-MM-DD.md` con la "Estructura esperada del reporte" de abajo (no se muestra completo en el chat — ver Paso 15).
11. Clasificar cada propuesta de evolución agéntica del paso 8:

    | Riesgo | Criterio | Acción |
    |---|---|---|
    | 🟢 Bajo | Agrega guardrail, corrige doc, amplía un skill existente sin tocar permisos de `main`/producción ni introducir un mecanismo de push/merge nuevo | Se implementa en este mismo cierre |
    | 🟡 Medio | Ídem, pero con superficie de cambio mayor o que toca un flujo ya en uso activo | Se implementa en este mismo cierre |
    | 🔴 Muy alto | Toca permisos sobre `main`/producción, debilita un guardrail existente, o introduce un mecanismo de push/merge automático nuevo | Se detiene el flujo |

12. **Compuerta de Riesgo**: si hay al menos una propuesta 🔴, presentar su estado, preguntar si se avanza y **detener el flujo completo** (no continuar a los Pasos 13-15) hasta recibir respuesta explícita.
13. Implementar las propuestas 🟢/🟡 aprobadas. Si crean/editan un skill, seguir `superpowers:writing-skills`. Registrar en el reporte del Paso 10 qué archivos de gobernanza se tocaron y por qué.
14. **Flujo de Auto-Merge**. Antes de cualquier operación: confirmar con `git branch --show-current` que la rama activa matchea `^(feat|fix|docs|chore|refactor|test)/` — si es `dev`, `main`, o no matchea el patrón, **DETENERSE inmediatamente** sin ejecutar ningún comando de este flujo (ni merge, ni push, ni borrado de rama), reportarlo en el checklist final y no continuar. Recién con la rama efímera confirmada:
    ```bash
    git checkout <rama-efímera-actual>
    git fetch origin
    git merge origin/dev
    ```
    Si hay conflictos (`git diff --name-only --diff-filter=U`): leer marcadores `<<<<<<<`/`=======`/`>>>>>>>`, entender la lógica de ambos lados, resolver reescribiendo correctamente, `git add .`. El commit de fusión documenta en su mensaje qué archivos tuvieron conflicto y el criterio de resolución. Luego:
    ```bash
    git checkout dev
    git pull origin dev
    git merge <rama-efímera-actual>
    git push origin dev
    git branch -d <rama-efímera-actual>
    git push origin --delete <rama-efímera-actual>
    ```
    Excepción: si el usuario indicó explícitamente en esta sesión que la rama debe diferirse, no forzar — dejarla activa y documentarlo.
15. Mostrar **exclusivamente** este checklist en el chat:
    - Análisis retrospectivo completado
    - Evolución agéntica implementada/propuesta
    - Actualización de documentación
    - Merge a Dev
    - Final de sesión

# Estructura esperada del reporte (persistido en docs/cierres/YYYY-MM-DD.md)

```markdown
# Nombre de archivo: YYYY-MM-DD.md
# Ubicación de archivo: docs/cierres/YYYY-MM-DD.md
# Descripción: Cierre(s) de sesión técnica del YYYY-MM-DD

# Cierre de Sesión — YYYY-MM-DD

## Sesión HH:MM — [resumen corto del alcance]

### Contexto
- Alcance de la sesión analizada, evidencia consultada y límites de evidencia
- Cambios propios de esta sesión vs. preexistentes del worktree vs. externos

### Tareas verificadas
- [tarea]: [completada|parcial|bloqueada|no verificada] — [evidencia de contraste]

### Errores y bloqueos
- [síntoma]: [causa raíz confirmada o hipótesis explícita] — [impacto]

### Soluciones aplicadas
- [error asociado]: [fix técnico + archivo/comando] — [validación ejecutada] — [riesgo residual / condición de regresión]

### Mejoras de arquitectura agéntica propuestas

#### Prevención
- [control]: [obstáculo real] — [evidencia, frecuencia, beneficio, costo] — Riesgo: 🟢/🟡/🔴 — [implementada|propuesta]

#### Aceleración
- [skill/recurso]: [paso repetible observado] — [evidencia, frecuencia, beneficio, costo] — Riesgo: 🟢/🟡/🔴 — [implementada|propuesta]

### Archivos de gobernanza tocados (Paso 13)
- [archivo]: [qué cambió y por qué]

### Notas de actualización de documentación
- [archivo]: [inconsistencia encontrada y corregida]

### Auto-Merge
- Rama efímera: `<rama>` — [mergeada a dev / diferida por pedido del usuario]
- Conflictos: [ninguno | lista de archivos y criterio de resolución aplicado]

### Conocimiento a preservar
- [qué debería recordar una sesión futura sobre este trabajo]
```

# Criterios de Aceptación

- [ ] Reporte basado exclusivamente en hechos verificables; límites de evidencia declarados.
- [ ] Cada tarea clasificada (completada/parcial/bloqueada/no verificada).
- [ ] Cada propuesta de evolución agéntica tiene su clasificación de riesgo 🟢/🟡/🔴.
- [ ] Ninguna propuesta 🔴 se implementó sin respuesta explícita del usuario.
- [ ] `docs/cierres/YYYY-MM-DD.md` creado o actualizado sin perder cierres previos del mismo día.
- [ ] Auto-merge ejecutado (o explícitamente diferido) y documentado con su resultado.
- [ ] El chat muestra exclusivamente el checklist de 5 líneas, no el reporte completo.

# Reglas

1. No elaborar ni persistir la retrospectiva, ni ejecutar el auto-merge, sin que el usuario haya declarado explícitamente el cierre de la sesión.
2. No inventar tareas, errores, soluciones ni validaciones que no hayan ocurrido en esta conversación.
3. No proponer skills/agentes/prompts especulativos: prevención requiere un obstáculo real, aceleración requiere un paso repetible ya observado.
4. No crear ni modificar otras skills automáticamente salvo lo que resulte de la compuerta de riesgo (Paso 11-13) o solicitud expresa del usuario.
5. No sobrescribir cierres de sesión previos del mismo día; anexar.
6. No incluir secretos, tokens ni credenciales en el reporte.
7. Ninguna propuesta 🔴 se implementa sin respuesta explícita del usuario — el flujo se detiene en el Paso 12.
8. El auto-merge es autónomo (incluida resolución de conflictos) salvo instrucción explícita previa de diferir esa rama en la misma sesión.
9. Mantener todo el contenido en español técnico.
10. Si hubo flujo recursivo SDD/superpowers, registrar métricas de ciclo y alertas según `docs/sdd_metricas_ciclo.md`.
11. El flujo de auto-merge nunca se ejecuta si la rama activa no matchea el patrón de rama efímera (`feat|fix|docs|chore|refactor|test`/...) — evita borrar o mutar `dev`/`main` por error si no se creó una rama efímera.
