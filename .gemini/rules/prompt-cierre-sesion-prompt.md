# Nombre de archivo: prompt-cierre-sesion-prompt.md
# Ubicación de archivo: .gemini/rules/prompt-cierre-sesion-prompt.md
# Descripción: Regla Gemini portable migrada desde .github/prompts/cierre-sesion.prompt.md
---
name: "prompt-cierre-sesion-prompt"
description: "Prompt migrado desde .github/prompts/cierre-sesion.prompt.md"
source: ".github/prompts/cierre-sesion.prompt.md"
triggers:
  - "cierre-sesion"
  - "cierre"
  - "sesion"
  - "cierre de sesion"
  - "cerrar sesion"
  - "cierre chat"
  - "rol"
  - "retrospectiva"
  - "tareas"
  - "errores"
  - "bloqueos"
  - "soluciones"
  - "prevencion"
  - "aceleracion"
globs:
  - "docs/cierres/**"
  - "docs/**"
  - ".github/**"
  - ".codex-skills/**"
  - ".gemini/**"
commands:
  []
---

# Regla Prompt: cierre-sesion.prompt

> Fuente original: `.github/prompts/cierre-sesion.prompt.md`. Usar como contrato reutilizable cuando el pedido coincida con esta automatización.

---
name: Cierre de Sesión
description: "Analiza la conversación activa y genera una retrospectiva técnica: tareas verificadas contra evidencia, errores/bloqueos, soluciones aplicadas y mejoras agénticas de prevención y aceleración"
argument-hint: "Opcional: alcance o fecha, por ejemplo: cierre de la sesión de hoy sobre ingesta Cromo"
agent: "agent"
---

# Rol

Actuar como Analista de Calidad y Gestor de Conocimiento Agéntico del proyecto LAS-FOCAS. Cerrar la sesión activa extrayendo conocimiento técnico real para retroalimentar el ecosistema de agentes, tanto para evitar errores/dificultades futuras como para acelerar futuras implementaciones similares.

# Contexto

- **Gate de activación**: proceder sólo si el usuario invocó `/cierre-sesion` explícitamente, o declaró de forma inequívoca el fin de la sesión (p.ej. "Cierre chat", "cerrar sesión", "cierre de sesión", "terminamos la sesión", "este es el cierre del chat", "cerrá la sesión con una retrospectiva"). Nombrar la skill al pasar, completar una tarea, pedir estado o solicitar documentación sin declarar el cierre NO satisface el gate. Si no se cumple, no elaborar ni persistir la retrospectiva: continuar con la tarea normal o señalar en una línea que el cierre queda reservado para cuando se declare explícitamente.
- El análisis debe basarse exclusivamente en lo que realmente ocurrió en la conversación activa: tool calls ejecutadas, resultados obtenidos, errores reales, decisiones del usuario. No inventar ni generalizar. No afirmar acceso a mensajes/outputs ausentes (p.ej. contexto truncado por compactación automática de la conversación) — declarar cualquier límite de evidencia en el reporte.
- Delimitar la sesión analizada: separar cambios propios de esta conversación, cambios preexistentes del worktree (frecuente en este repo: suele haber ramas con trabajo en curso de otras sesiones) y acciones externas. No atribuir resultados sin evidencia de que ocurrieron en esta conversación.
- El reporte se persiste en `docs/cierres/YYYY-MM-DD.md`. Si ya existe un cierre para la fecha (otra sesión el mismo día), se agrega como sección nueva con marca de tiempo, sin duplicar ni sobrescribir cierres previos.
- Propuestas de **prevención**: basadas únicamente en obstáculos/errores/retrabajo reales de esta sesión. Propuestas de **aceleración**: basadas en pasos repetibles ya observados en esta sesión que agilizarían implementaciones similares futuras, no en herramientas hipotéticas sin caso de uso — aunque esta sesión no haya tenido fricción.
- Si además corresponde persistir un hallazgo en el sistema de memoria automática del agente (tipo `feedback` o `project`), señalarlo explícitamente en el reporte sin duplicar ahí el contenido completo.

# Objetivo

Producir un reporte Markdown estructurado que documente, contrastado contra evidencia real, el estado de las tareas, los errores/soluciones, y dos carriles de mejora agéntica —prevención y aceleración—, dejándolo guardado en `docs/cierres/`.

# Pasos

1. Confirmar el gate de activación. Si no se cumple, no continuar con los pasos siguientes.
2. Leer `AGENTS.md`, el historial disponible de la conversación activa, resultados de tool calls, el diff actual (`git status`/`git diff`) y la documentación de dominio afectada. Declarar cualquier límite de evidencia detectado.
3. Delimitar qué cambios son propios de esta sesión, cuáles son preexistentes del worktree y cuáles son acciones externas.
4. Contrastar cada tarea supuestamente terminada contra código, tests, logs, estado del sistema o documentación. Clasificarla como completada, parcial, bloqueada o no verificada.
5. Documentar errores, bloqueos o problemas post-implementación realmente enfrentados (no hipotéticos): síntoma, causa raíz confirmada o hipótesis explícita, impacto.
6. Detallar, con precisión técnica reutilizable, la solución aplicada a cada error/bloqueo: archivo/componente afectado, decisión técnica, validación ejecutada, condición que indicaría una regresión futura (o marcar explícitamente como sin resolver).
7. Revisar vigencia: corregir documentación desactualizada cuando la evidencia actual la contradiga. Corregir lógica fuera de la tarea principal sólo si el desajuste está verificado y el cambio es seguro y autorizado; si no, registrarlo como pendiente concreto sin afirmar que quedó resuelto.
8. Evaluar mejoras agénticas en dos carriles — **prevención** (obstáculos reales de esta sesión) y **aceleración** (pasos repetibles observados que agilizarían implementaciones similares futuras). Para cada candidata: evidencia, frecuencia esperada, beneficio, costo de mantenimiento y opción recomendada (ampliar skill existente, crear skill, agregar recurso determinístico, mejorar prompt/contexto, usar herramienta existente, o delegar a agente independiente sólo con frontera clara de contexto/permisos/paralelismo). Preferir ampliar una skill existente. No crear ni modificar otras skills automáticamente salvo solicitud expresa del usuario o alcance ya autorizado en esta conversación.
9. Determinar la fecha actual (`YYYY-MM-DD`) y revisar si existe `docs/cierres/YYYY-MM-DD.md`:
   - Si existe, conservarlo y anexar una sección nueva con encabezado `## Sesión HH:MM — <resumen corto>`.
   - Si no existe, crearlo con el encabezado obligatorio de 3 líneas y la estructura de la sección "Formato del reporte".
10. Presentar el reporte completo al usuario en el chat y confirmar la ruta del archivo guardado.

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
- [control]: [obstáculo real que lo motiva] — [evidencia, frecuencia, beneficio, costo, opción recomendada]

#### Aceleración
- [skill/plantilla/script/recurso]: [paso repetible observado] — [evidencia, frecuencia, beneficio, costo, opción recomendada]

*(o "Sin propuestas en este carril" con la razón, si no aplica — no dejar la sección implícita)*

### Notas de actualización de documentación
- [archivo]: [inconsistencia encontrada y corregida] *(si aplica)*

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
- [ ] Reporte mostrado al usuario en el mismo turno.

# Reglas adicionales

1. No elaborar ni persistir la retrospectiva sin que el usuario haya declarado explícitamente el cierre de la sesión.
2. No inventar tareas, errores ni soluciones que no hayan ocurrido en la conversación activa.
3. No proponer skills/agentes/prompts especulativos: prevención requiere un obstáculo real, aceleración requiere un paso repetible ya observado.
4. No crear ni modificar otras skills automáticamente salvo solicitud expresa del usuario o alcance ya autorizado en la conversación.
5. No sobrescribir cierres de sesión previos del mismo día; anexar.
6. No incluir secretos, tokens ni credenciales en el reporte.
7. Mantener todo el contenido en español técnico y conciso; si no hay incidentes, mantener el reporte breve, pero igual identificar patrones exitosos reutilizables.
