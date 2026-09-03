# Nombre de archivo: cierre-sesion.prompt.md
# Ubicación de archivo: .github/prompts/cierre-sesion.prompt.md
# Descripción: Prompt para retrospectiva técnica de cierre de sesión: tareas verificadas, errores, soluciones, evolución agéntica con compuerta de riesgo y auto-merge de la rama efímera a dev

---
name: Cierre de Sesión
description: "Analiza la conversación activa y genera una retrospectiva técnica: tareas verificadas contra evidencia, errores/bloqueos, soluciones aplicadas y mejoras agénticas de prevención y aceleración"
argument-hint: "Opcional: alcance o fecha, por ejemplo: cierre de la sesión de hoy sobre ingesta Cromo"
agent: "agent"
---

# Rol

Actuar como Analista de Calidad y Gestor de Conocimiento Agéntico del proyecto LAS-FOCAS. Cerrar la sesión activa extrayendo conocimiento técnico real para retroalimentar el ecosistema de agentes, tanto para evitar errores/dificultades futuras como para acelerar futuras implementaciones similares.

# Contexto

- **Gate de activación**: proceder sólo si el usuario invocó `/cierre-sesion` explícitamente, o declaró de forma inequívoca el fin de la sesión (p.ej. "Cerrar sesión", "Cerremos sesión", "Cierre chat", "cierre de sesión", "terminamos la sesión", "este es el cierre del chat", "cerrá la sesión con una retrospectiva"). Nombrar la skill al pasar, completar una tarea, pedir estado o solicitar documentación sin declarar el cierre NO satisface el gate. Si no se cumple, no elaborar ni persistir la retrospectiva: continuar con la tarea normal o señalar en una línea que el cierre queda reservado para cuando se declare explícitamente.
- El análisis debe basarse exclusivamente en lo que realmente ocurrió en la conversación activa: tool calls ejecutadas, resultados obtenidos, errores reales, decisiones del usuario. No inventar ni generalizar. No afirmar acceso a mensajes/outputs ausentes (p.ej. contexto truncado por compactación automática de la conversación) — declarar cualquier límite de evidencia en el reporte.
- Delimitar la sesión analizada: separar cambios propios de esta conversación, cambios preexistentes del worktree (frecuente en este repo: suele haber ramas con trabajo en curso de otras sesiones) y acciones externas. No atribuir resultados sin evidencia de que ocurrieron en esta conversación.
- El reporte se persiste en `docs/cierres/YYYY-MM-DD.md`. Si ya existe un cierre para la fecha (otra sesión el mismo día), se agrega como sección nueva con marca de tiempo, sin duplicar ni sobrescribir cierres previos.
- Propuestas de **prevención**: basadas únicamente en obstáculos/errores/retrabajo reales de esta sesión. Propuestas de **aceleración**: basadas en pasos repetibles ya observados en esta sesión que agilizarían implementaciones similares futuras, no en herramientas hipotéticas sin caso de uso — aunque esta sesión no haya tenido fricción.
- Cada propuesta de evolución agéntica se clasifica 🟢 Bajo / 🟡 Medio / 🔴 Muy alto (tabla en Pasos #11, mismo patrón que `docker-cleanup/SKILL.md`). 🟢/🟡 se implementan en este mismo cierre; 🔴 detiene el flujo y exige respuesta explícita del usuario antes de continuar.
- El auto-merge final (Pasos #14-15) es autónomo, incluida la resolución de conflictos, salvo que el usuario haya indicado explícitamente en esta misma sesión que la rama debe diferirse (ej. ventana de mantenimiento).
- Si además corresponde persistir un hallazgo en el sistema de memoria automática del agente (tipo `feedback` o `project`), señalarlo explícitamente en el reporte sin duplicar ahí el contenido completo.

# Objetivo

Producir un reporte Markdown estructurado que documente, contrastado contra evidencia real, el estado de las tareas, los errores/soluciones, y dos carriles de mejora agéntica —prevención y aceleración— con su clasificación de riesgo, dejándolo guardado en `docs/cierres/`, e integrar automáticamente la rama efímera de la sesión a `dev`.

# Pasos

1. Confirmar el gate de activación. Si no se cumple, no continuar con los pasos siguientes.
2. Leer `AGENTS.md`, el historial disponible de la conversación activa, resultados de tool calls, el diff actual (`git status`/`git diff`) y la documentación de dominio afectada. Declarar cualquier límite de evidencia detectado.
3. Delimitar qué cambios son propios de esta sesión, cuáles son preexistentes del worktree y cuáles son acciones externas.
4. Contrastar cada tarea supuestamente terminada contra código, tests, logs, estado del sistema o documentación. Clasificarla como completada, parcial, bloqueada o no verificada.
5. Documentar errores, bloqueos o problemas post-implementación realmente enfrentados (no hipotéticos): síntoma, causa raíz confirmada o hipótesis explícita, impacto.
6. Detallar, con precisión técnica reutilizable, la solución aplicada a cada error/bloqueo: archivo/componente afectado, decisión técnica, validación ejecutada, condición que indicaría una regresión futura (o marcar explícitamente como sin resolver).
7. Revisar vigencia: corregir documentación desactualizada cuando la evidencia actual la contradiga. Corregir lógica fuera de la tarea principal sólo si el desajuste está verificado y el cambio es seguro y autorizado; si no, registrarlo como pendiente concreto sin afirmar que quedó resuelto.
8. Evaluar mejoras agénticas en dos carriles — **prevención** (obstáculos reales de esta sesión) y **aceleración** (pasos repetibles observados que agilizarían implementaciones similares futuras). Para cada candidata: evidencia, frecuencia esperada, beneficio, costo de mantenimiento y opción recomendada (ampliar skill existente, crear skill, agregar recurso determinístico, mejorar prompt/contexto, usar herramienta existente, o delegar a agente independiente sólo con frontera clara de contexto/permisos/paralelismo). Preferir ampliar una skill existente. No crear ni modificar otras skills automáticamente salvo lo que resulte de la compuerta de riesgo (Pasos #11-13) o solicitud expresa del usuario.
9. Determinar la fecha actual (`YYYY-MM-DD`) y localizar `docs/cierres/YYYY-MM-DD.md` (crear o anexar según corresponda).
10. Escribir el reporte completo en `docs/cierres/YYYY-MM-DD.md` con la sección "Formato del reporte" de abajo (no se muestra completo en el chat — ver Paso 15).
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

# Formato del reporte

```markdown
# Nombre de archivo: YYYY-MM-DD.md
# Ubicación de archivo: docs/cierres/YYYY-MM-DD.md
# Descripción: Cierre(s) de sesión técnica del YYYY-MM-DD

# Cierre de Sesión — YYYY-MM-DD

## Sesión HH:MM — [resumen corto del alcance]

### Contexto
- Alcance de la sesión analizada, evidencia consultada y límites de evidencia (p.ej. contexto truncado/compactado)
- Cambios propios de esta sesión vs. preexistentes del worktree vs. externos

### Tareas verificadas
- [tarea]: [completada|parcial|bloqueada|no verificada] — [evidencia de contraste]

### Errores y bloqueos
- [síntoma]: [causa raíz confirmada o hipótesis explícita] — [impacto]

### Soluciones aplicadas
- [error asociado]: [fix técnico + archivo/comando] — [validación ejecutada] — [riesgo residual / condición de regresión]
  *(o "Sin resolver" si corresponde)*

### Mejoras de arquitectura agéntica propuestas

#### Prevención
- [control]: [obstáculo real que lo motiva] — [evidencia, frecuencia, beneficio, costo, opción recomendada] — Riesgo: 🟢/🟡/🔴 — [implementada|propuesta]

#### Aceleración
- [skill/plantilla/script/recurso]: [paso repetible observado] — [evidencia, frecuencia, beneficio, costo, opción recomendada] — Riesgo: 🟢/🟡/🔴 — [implementada|propuesta]

*(o "Sin propuestas en este carril" con la razón, si no aplica — no dejar la sección implícita)*

### Notas de actualización de documentación
- [archivo]: [inconsistencia encontrada y corregida] *(si aplica)*

### Auto-Merge
- Rama efímera: `<rama>` — [mergeada a dev / diferida por pedido del usuario]
- Conflictos: [ninguno | lista de archivos y criterio de resolución aplicado]

### Conocimiento a preservar
- [qué debería recordar una sesión futura sobre este trabajo, aunque no haya habido incidentes]
```

# Criterios de Aceptación

- [ ] Reporte basado exclusivamente en hechos verificables de la conversación activa; límites de evidencia declarados.
- [ ] Cada tarea está clasificada (completada/parcial/bloqueada/no verificada), no sólo listada como éxito.
- [ ] Cada error documentado tiene su solución técnica correspondiente, o se marca explícitamente como sin resolver.
- [ ] Los pendientes no se presentan como completados.
- [ ] Toda documentación desactualizada verificable fue corregida; los cambios de código fuera de alcance sólo si estaban verificados y autorizados, si no quedan como pendiente explícito.
- [ ] Las propuestas cubren ambos carriles (prevención y aceleración) o declaran explícitamente por qué un carril no aplica, y citan evidencia real.
- [ ] `docs/cierres/YYYY-MM-DD.md` creado o actualizado sin perder cierres previos del mismo día.
- [ ] Cada propuesta de evolución agéntica tiene su clasificación de riesgo 🟢/🟡/🔴; ninguna propuesta 🔴 se implementó sin respuesta explícita del usuario.
- [ ] El chat muestra exclusivamente el checklist de 5 líneas, no el reporte completo.

# Reglas adicionales

1. No elaborar ni persistir la retrospectiva, ni ejecutar el auto-merge, sin que el usuario haya declarado explícitamente el cierre de la sesión.
2. No inventar tareas, errores ni soluciones que no hayan ocurrido en la conversación activa.
3. No proponer skills/agentes/prompts especulativos: prevención requiere un obstáculo real, aceleración requiere un paso repetible ya observado.
4. No crear ni modificar otras skills automáticamente salvo solicitud expresa del usuario o alcance ya autorizado en la conversación.
5. No sobrescribir cierres de sesión previos del mismo día; anexar.
6. No incluir secretos, tokens ni credenciales en el reporte.
7. Ninguna propuesta 🔴 se implementa sin respuesta explícita del usuario — el flujo se detiene en el Paso 12.
8. El auto-merge es autónomo (incluida resolución de conflictos) salvo instrucción explícita previa de diferir esa rama en la misma sesión.
9. Mantener todo el contenido en español técnico y conciso; si no hay incidentes, mantener el reporte breve, pero igual identificar patrones exitosos reutilizables.
10. Si hubo flujo recursivo SDD/superpowers, registrar métricas de ciclo y alertas según `docs/sdd_metricas_ciclo.md`.
11. El flujo de auto-merge nunca se ejecuta si la rama activa no matchea el patrón de rama efímera (`feat|fix|docs|chore|refactor|test`/...) — evita borrar o mutar `dev`/`main` por error si no se creó una rama efímera.
