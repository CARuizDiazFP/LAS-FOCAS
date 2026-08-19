---
name: "las-focas-cierre-sesion"
description: "Usar al finalizar una sesión de trabajo, sólo con declaración explícita de cierre, para generar una retrospectiva técnica: tareas verificadas, errores/bloqueos, soluciones aplicadas y mejoras agénticas de prevención y aceleración"
metadata:
  short-description: "Usar al finalizar una sesión de trabajo, sólo con declaración explícita de cierre, para generar una retrospectiva técnica: tareas verif..."
  source: ".github/skills/cierre-sesion/SKILL.md"
  triggers:
    - "cierre-sesion"
    - "cierre"
    - "sesion"
    - "cierre de sesion"
    - "cerrar sesion"
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

> Fuente original: `.github/skills/cierre-sesion/SKILL.md`. Copia portable generada porque `.codex/` está montado como solo lectura en esta sesión.

# Habilidad: Cierre de Sesión

Workflow invocable para analizar la conversación activa al finalizar el trabajo y extraer conocimiento técnico factual que retroalimente el ecosistema de agentes del proyecto, tanto para prevenir errores futuros como para acelerar implementaciones similares.

## Cuándo usar

Usar esta skill sólo cuando el usuario declara explícitamente el fin de la sesión:

- invoca `/cierre-sesion` explícitamente, o
- escribe una frase inequívoca de cierre: "Cierre chat", "cerrar sesión", "cierre de sesión", "terminamos la sesión", "este es el cierre del chat", "cerrá la sesión con una retrospectiva"

**No** activar por sólo nombrar la skill al pasar, completar una tarea, pedir estado o solicitar documentación. Si un trigger heurístico dispara esta skill sin ese gate cumplido, no elaborar ni persistir la retrospectiva: continuar la tarea normal e indicar en una línea que el cierre queda reservado para cuando se declare explícitamente.

## Procedimiento

1. Confirmar el gate de activación. Si no se cumple, no continuar con los pasos siguientes.
2. Leer `AGENTS.md`, el historial disponible de la conversación activa, resultados de tool calls, el diff actual (`git status`/`git diff`) y la documentación de dominio afectada. Declarar cualquier límite de evidencia detectado (p.ej. contexto truncado por compactación automática).
3. Delimitar qué cambios son propios de esta sesión, cuáles son preexistentes del worktree y cuáles son acciones externas.
4. Contrastar cada tarea supuestamente terminada contra código, tests, logs, estado del sistema o documentación. Clasificarla como completada, parcial, bloqueada o no verificada.
5. Documentar errores, bloqueos o problemas post-implementación realmente enfrentados: síntoma, causa raíz confirmada o hipótesis explícita, impacto.
6. Detallar con precisión reutilizable la solución aplicada a cada error/bloqueo: archivo/componente, decisión técnica, validación ejecutada, condición que indicaría una regresión futura (o marcar sin resolver).
7. Revisar vigencia: corregir documentación desactualizada cuando la evidencia la contradiga. Corregir lógica fuera de la tarea principal sólo si está verificado y autorizado; si no, registrar como pendiente concreto.
8. Evaluar mejoras agénticas en dos carriles — prevención (obstáculos reales de esta sesión) y aceleración (pasos repetibles observados que agilizarían implementaciones similares futuras). Por cada candidata: evidencia, frecuencia esperada, beneficio, costo de mantenimiento y opción recomendada, prefiriendo ampliar una skill existente.
9. Determinar la fecha actual (`YYYY-MM-DD`) y crear o anexar `docs/cierres/YYYY-MM-DD.md` sin perder cierres previos del mismo día.
10. Mostrar el reporte completo al usuario y confirmar la ruta del archivo guardado.

## Referencias

- [Prompt asociado](../../prompts/cierre-sesion.prompt.md)

## Guardrails

1. Basarse únicamente en hechos verificables de la conversación activa; no inventar tareas, errores ni soluciones. Declarar límites de evidencia.
2. No proponer skills/agentes/prompts especulativos: prevención requiere un obstáculo real, aceleración requiere un paso repetible ya observado.
3. No crear ni modificar otras skills automáticamente salvo solicitud expresa del usuario o alcance ya autorizado en la conversación. Si se cataloga una skill nueva, verificar que tenga mirror en `.claude/skills/<nombre>/SKILL.md` para ser invocable por el tool `Skill`.
4. No sobrescribir cierres de sesión previos del mismo día; anexar como sección nueva.
5. No incluir secretos, tokens ni credenciales en el reporte.
6. No mezclar el reporte de cierre con el flujo de `repo-updater`; el cierre es retrospectiva de conversación, no auditoría de diff/commit.
7. Sin declaración explícita de cierre del usuario, no elaborar ni persistir la retrospectiva.

## Resultado esperado

- Reporte Markdown con tareas verificadas contra evidencia, errores/bloqueos, soluciones aplicadas y mejoras agénticas de prevención y aceleración.
- `docs/cierres/YYYY-MM-DD.md` creado o actualizado con la sección de la sesión.
- Reporte presentado al usuario en el mismo turno.
