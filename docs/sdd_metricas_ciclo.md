# Nombre de archivo: sdd_metricas_ciclo.md
# Ubicación de archivo: docs/sdd_metricas_ciclo.md
# Descripción: Métricas operativas para observabilidad del flujo recursivo SDD/superpowers

# Métricas de Ciclo SDD/superpowers

## Objetivo

Medir la eficiencia real del flujo recursivo para ajustar la política de corte con datos verificables.

## Métricas obligatorias por task

1. `rondas_review_total`: cantidad de reviews/re-reviews ejecutadas.
2. `hallazgos_nuevos_por_ronda`: conteo de hallazgos Critical/Important nuevos por ronda.
3. `fix_waves_total`: cantidad de fix waves ejecutadas.
4. `tiempo_total_task`: tiempo transcurrido desde dispatch hasta cierre.
5. `estado_cierre`: `closed|handoff|blocked`.

## Umbrales de alerta

1. Alerta amarilla:
   - `rondas_review_total > 2`.
2. Alerta roja:
   - `rondas_review_total > 3`.
   - o `fix_waves_total > 2`.

## Uso en cierre-sesion

Si se detecta alerta roja:

1. declarar explícitamente el exceso de rondas
2. justificar continuidad o recomendar handoff
3. registrar acción correctiva para próxima iteración

## Plantilla de registro

```markdown
## Métricas SDD por task
- Task:
- rondas_review_total:
- hallazgos_nuevos_por_ronda:
- fix_waves_total:
- tiempo_total_task:
- estado_cierre:
- alerta:
- decisión:
```
