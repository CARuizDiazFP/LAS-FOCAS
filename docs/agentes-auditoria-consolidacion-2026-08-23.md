# Nombre de archivo: agentes-auditoria-consolidacion-2026-08-23.md
# Ubicación de archivo: docs/agentes-auditoria-consolidacion-2026-08-23.md
# Descripción: Auditoría integral de duplicidades y complementariedad del ecosistema multi-agente

# Auditoría de Consolidación Multi-Agente (2026-08-23)

## Alcance

Relevamiento integral de:

- .agentes-comunes
- .github (agents, prompts, skills)
- .gemini/rules
- .codex-skills/skills
- .claude (commands, skills)
- Artefactos SDD/superpowers relacionados

Objetivo: detectar duplicidades exactas/parciales, complementariedades y fricciones operativas para consolidar sin perder flujos críticos.

## Inventario cuantitativo

- Archivos por ecosistema:
  - .claude: 12
  - .gemini: 52
  - .codex-skills: 28
  - .github: 54
  - .agentes-comunes: 32
- Catálogo de skills:
  - .agentes-comunes/skills: 25
  - .github/skills: 25
  - .codex-skills/skills: 24
  - .gemini/rules (skill-*.md): 24
  - .claude/skills: 3
- Prompts y agentes:
  - .github/prompts: 8
  - .claude/commands: 8
  - .gemini/rules (prompt-*.md): 8
  - .github/agents: 13
  - .gemini/rules (agent-*.md): 13

## Hallazgos clasificados

### 1) Duplicidad total

1. Skills espejo exactas entre fuente central y GitHub:
   - Evidencia: diff -qr sin diferencias entre .agentes-comunes/skills y .github/skills.
   - Impacto: doble mantenimiento si no se automatiza sincronización.
2. Cobertura 1:1 de catálogo por nombre en prompts/commands y agentes:
   - .github/prompts ↔ .claude/commands ↔ .gemini/rules/prompt-*.md
   - .github/agents ↔ .gemini/rules/agent-*.md

### 2) Duplicidad parcial

1. repo-update vs repo-updater:
   - repo-update es alias legacy del flujo principal.
   - Valor: compatibilidad histórica.
   - Riesgo: confusión de entrada y rutas de mantenimiento paralelas.
2. Seguridad (superposición por diseño):
   - skill security-scan y prompt revisar-seguridad comparten pipeline (secretos, dependencias, SAST, hardening).
   - Riesgo: drift de checklist si no hay contrato único de severidad/salida.
3. Mantenimiento operacional fragmentado:
   - disk-analysis, docker-cleanup, logs-cleanup, temp-cleanup + prompt mantenimiento-disco.
   - Hay solapamiento de comandos, umbrales y guardrails.
4. Guardrails repetitivos de pre-check:
   - dev-workflow, frontend-spa-architecture y nocturne-token-compliance introducen validaciones obligatorias consecutivas.
   - Riesgo: sesiones largas por chequeos reiterados sobre el mismo diff.

### 3) Complementariedad

1. Cadena de seguridad (correctamente modular):
   - secret-detection + dependency-audit + sast-analysis + security-scan + revisar-seguridad.
2. Cadena de cierre/documentación:
   - cierre-sesion + generar-pr-diario + repo-updater.
3. Cadena Cromo:
   - cromo-diagnostico-real (validación de supuestos) + cromo-inventario (explotación de datos ingeridos).
4. Cadena frontend:
   - frontend-spa-architecture + nocturne-token-compliance.
5. Flujos críticos de documentación y aprendizaje operativo:
   - cierre-sesion: releva la conversación activa para aprendizaje y mejora agéntica.
   - generar-pr-diario: registra cambios técnicos y validaciones del día.
   - Relación entre ambos: complementarios, no duplicados.

## Verificación de flujos críticos (sin pérdida funcional)

### cierre-sesion

- .github/prompts/cierre-sesion.prompt.md conserva gate de activación explícito, formato de reporte, criterios y guardrails.
- .claude/commands/cierre-sesion.md mantiene la misma semántica operativa.
- .agentes-comunes/skills/cierre-sesion/SKILL.md mantiene workflow y restricciones para uso invocable.
- .gemini/rules/prompt-cierre-sesion-prompt.md conserva el cuerpo del prompt original + metadata de activación.

### generar-pr-diario

- .github/prompts/generar-pr-diario.prompt.md mantiene estructura esperada, reglas obligatorias y salida.
- .claude/commands/generar-pr-diario.md mantiene el flujo ejecutable equivalente.
- .gemini/rules/prompt-generar-pr-diario-prompt.md preserva el contrato original como regla portable.

Conclusión: ambos flujos críticos permanecen operativos y trazables en los tres entornos.

## Análisis específico de superpowers

### Naturaleza de los componentes detectados

1. Artefactos operativos locales:
   - `.superpowers/sdd/groovy-beaming-lemur/` contiene ledger, briefs, reportes y diffs de revisión.
   - Impacto: evidencia real del flujo recursivo aplicado en este repo.
2. Especificaciones y planes versionados:
   - `docs/superpowers/plans/` y `docs/superpowers/specs/` documentan planificaciones SDD.
   - Impacto: referencia técnica reproducible para tareas complejas.
3. Referencias a skills externas:
   - Los planes usan `superpowers:subagent-driven-development` y `superpowers:executing-plans` como orquestadores externos.
   - Hallazgo: no existen skills locales con esos nombres en `.agentes-comunes/skills/`, `.github/skills/`, `.claude/skills/` o `.gemini/rules/`.

### Fricción superpowers identificada

1. Riesgo de sesiones largas por re-review en cascada sin límite formal ejecutable.
2. Criterio de corte actualmente documentado en texto (gobernanza), pero no consolidado en una política operativa única.
3. Ledger SDD ignorado por git (`.superpowers/`), útil para operación diaria pero con trazabilidad parcial si no se resume en docs.

## Fricciones actuales detectadas

1. Alto costo de sincronización manual entre mirrors por cambios de contenido.
2. Inconsistencia de cobertura de mirrors en Claude (3 skills invocables de 25).
3. Potencial de recursión larga cuando se encadenan múltiples skills obligatorias sin criterio de corte por “sin hallazgos nuevos”.
4. Metadatos heredados en archivos centralizados (algunos encabezados todavía referencian rutas originales .github/skills), sin impacto funcional directo, pero con deuda de trazabilidad documental.

## Plan de consolidación recomendado

### Fase 0 (estabilización superpowers)

1. Preservar explícitamente el ledger SDD activo cuando la sesión fue interrumpida por límites de consumo/tiempo (no borrar ni cerrar en falso).
2. Dejar estado y próximos pasos listos para handoff a otro agente.
3. Resumir en documentación permanente cualquier hallazgo Critical/Important confirmado en flujo recursivo.
4. Mantener `.superpowers/` como espacio operativo efímero y reflejar decisiones cerradas en `docs/`.

### Fase A (inmediata)

1. Mantener .agentes-comunes/skills como fuente única de skills.
2. Mantener .github/agents y .github/prompts como fuentes únicas de agentes/prompts.
3. Ejecutar sincronización tras cambios con scripts/sync_agentes_comunes.sh.
4. Definir criterio de corte para flujo recursivo:
   - cerrar ciclo cuando una re-review no trae hallazgos nuevos.
   - evitar más de una re-review por mismo delta salvo hallazgo crítico nuevo.
   - formalizar esta regla en la política `docs/politica_recursion_sdd.md`.

### Fase B (reducción de duplicidad parcial)

1. Consolidar repo-update como alias mínimo (sin lógica propia adicional).
2. Unificar contrato de salida de seguridad en un único esquema (severidad, evidencia, mitigación) reutilizable por prompt y skill.
3. Definir “maintenance-profile” (rápido/estándar/profundo) para evitar ejecutar siempre toda la cadena disk+docker+logs+temp.

### Fase C (gobernanza y calidad)

1. Agregar verificación CI de drift de mirrors:
   - fail si .agentes-comunes/skills y .github/skills divergen.
2. Agregar checklist de “redundancia semántica” en PRs de customizations.
3. Normalizar metadatos de ubicación en .agentes-comunes/skills para trazabilidad consistente.

### Fase D (observabilidad del flujo recursivo)

1. Registrar métricas por ciclo:
   - cantidad de re-reviews por tarea.
   - hallazgos nuevos por ronda.
   - tiempo total por task/fix wave.
2. Alertar en cierre de sesión cuando se exceda umbral de rondas previsto.
3. Ajustar la política de corte con datos reales, no sólo por percepción.

## Decisiones aplicadas en esta iteración

1. Se mantuvo el flujo recursivo SDD/superpowers (no se desactiva).
2. Se centralizó la referencia de fuente de skills en documentación de gobernanza:
   - AGENTS.md
   - CLAUDE.md
   - GEMINI.md
   - docs/Mate_y_Ruta.md
3. Se añadieron artefactos de operación:
   - .agentes-comunes/README.md
   - scripts/sync_agentes_comunes.sh
4. Se implementaron entregables de Fase B y Fase D:
   - `docs/seguridad_contrato_salida.md` (contrato unificado de salida de seguridad).
   - `docs/maintenance_profiles.md` (perfiles rapido/estandar/profundo para mantenimiento).
   - `docs/sdd_metricas_ciclo.md` (métricas y alertas del flujo recursivo).
5. Se creó handoff independiente para continuidad de sesión SDD interrumpida:
   - `docs/handoffs/sdd-groovy-beaming-lemur-handoff-2026-08-23.md`.

## Riesgos residuales

1. Drift futuro si no se ejecuta sincronización tras cambios.
2. Diferencias de ergonomía entre plataformas (Claude/Gemini/Codex) por formato wrapper.
3. Riesgo de ciclos largos si no se respeta criterio de corte en re-reviews.
4. Dependencia de referencias `superpowers:*` externas en planes SDD (sin implementación local equivalente).

## Recomendación final

Conservar el modelo recursivo actual, pero con gobernanza de corte y sincronización automática. Este enfoque reduce tiempos sin sacrificar cobertura ni trazabilidad, y evita pérdida de funcionalidades críticas como cierre-sesion y generar-pr-diario.
