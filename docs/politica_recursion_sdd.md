# Nombre de archivo: politica_recursion_sdd.md
# Ubicación de archivo: docs/politica_recursion_sdd.md
# Descripción: Política operativa para acotar el flujo recursivo SDD/superpowers sin desactivarlo

# Política de Recursión SDD/superpowers

## Objetivo

Mantener el flujo recursivo habilitado para tareas complejas, reduciendo ciclos redundantes y sesiones excesivamente largas.

## Reglas operativas

1. Regla de corte base:
   - Si una re-review no introduce hallazgos nuevos (Critical/Important), cerrar el ciclo.
2. Regla de rondas por delta:
   - Máximo 1 re-review por el mismo delta.
   - Excepción: permitir una ronda adicional sólo si aparece un hallazgo Critical nuevo y verificable.
3. Regla de severidad:
   - Hallazgos Minor/Nit no habilitan rondas extra por sí solos.
   - Se documentan como deferred con justificación explícita.
4. Regla de consolidación:
   - Agrupar fixes relacionados en una única fix wave cuando sea viable.
5. Regla de trazabilidad:
   - Todo cierre de ciclo debe registrar evidencia mínima: diff, validación y estado de hallazgos.

## Criterios de cierre de ciclo

Un ciclo SDD se considera cerrado cuando:

1. No hay Critical/Important abiertos para el alcance actual.
2. Las diferencias restantes son Minor deferred aceptadas.
3. Existe evidencia de validación proporcional al cambio.

## Excepciones permitidas

1. Cambio de alcance solicitado por el usuario.
2. Hallazgo crítico nuevo confirmado por revisión independiente.
3. Dependencia externa que impide validar en la ronda actual (debe quedar registrada).
4. Interrupción de sesión por límite de consumo/tiempo: preservar ledger y preparar handoff, sin marcar cierre artificial.

## Integración con documentación

- Referencia de gobernanza:
  - `AGENTS.md`
  - `CLAUDE.md`
  - `GEMINI.md`
  - `.agentes-comunes/README.md`
- Registro de sesión y aprendizaje:
  - `docs/cierres/YYYY-MM-DD.md`
  - `docs/agentes-auditoria-consolidacion-2026-08-23.md`

## Nota

Esta política no desactiva superpowers ni SDD. Establece límites de iteración para mejorar throughput sin sacrificar calidad.