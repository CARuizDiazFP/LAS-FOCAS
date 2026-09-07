# Nombre de archivo: maintenance_profiles.md
# Ubicación de archivo: docs/maintenance_profiles.md
# Descripción: Perfiles operativos de mantenimiento para disco, Docker, logs y temporales

# Perfiles de Mantenimiento Operativo

## Objetivo

Estandarizar la ejecución de mantenimiento para evitar correr siempre la cadena completa (`disk-analysis` + `docker-cleanup` + `logs-cleanup` + `temp-cleanup`) cuando no es necesario.

## Perfiles

### Perfil rapido

Usar cuando:

- hay presión de tiempo
- se necesita diagnóstico inicial

Incluye:

1. `df -h /`
2. `docker system df`
3. `du -sh Logs/`

No incluye limpieza destructiva.

### Perfil estandar

Usar cuando:

- hay alerta amarilla
- se requiere recuperar espacio sin riesgo alto

Incluye:

1. diagnóstico completo de disco/Docker/logs
2. limpieza de cachés seguras (`__pycache__`, `.pyc`, caches de tooling)
3. pruning de Docker no persistente (sin volúmenes)

### Perfil profundo

Usar cuando:

- hay estado crítico (>85% disco)
- riesgo operativo inminente

Incluye:

1. todo el perfil estandar
2. validación post-limpieza obligatoria
3. reporte de riesgo residual y acciones manuales pendientes

## Guardrails comunes

1. Nunca ejecutar `docker volume prune`.
2. Nunca ejecutar `docker system prune --volumes`.
3. Confirmación explícita previa cuando la acción impacta servicios activos.

## Salida mínima por perfil

1. Perfil usado (`rapido|estandar|profundo`).
2. Espacio inicial y final.
3. Acciones ejecutadas.
4. Riesgo residual.
