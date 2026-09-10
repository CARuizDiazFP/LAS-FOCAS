# Nombre de archivo: arquitectura_agent_awareness_2026-09-08.md
# Ubicación de archivo: docs/arquitectura_agent_awareness_2026-09-08.md
# Descripción: Propuesta de arquitectura de conciencia agéntica y coordinación segura para trabajo concurrente multi-agente

# Arquitectura de Agent Awareness y coordinación concurrente

## Objetivo

Diseñar una capa de coordinación explícita para el ecosistema de agentes del repositorio, orientada a prevenir condiciones de carrera, bloquear sobrescrituras no coordinadas y mantener un estado compartido de trabajo entre múltiples agentes.

El problema central no es la generación de contenido por sí misma, sino la falta de una capa de ownership y lock de recursos sobre artefactos compartidos entre `.agentes-comunes`, `.github`, `.claude`, `.gemini`, `.codex-skills`, `docs/`, `scripts/` y workflows de CI/CD.

## Estado actual detectado

### 1. Topología multi-agente existente

El repositorio ya contiene una estructura deliberada y madura:

- `.agentes-comunes/skills/`: fuente central de skills.
- `.github/agents/`: agentes de dominio.
- `.github/skills/`: espejo de skills para GitHub Copilot.
- `.gemini/rules/`: artefactos para Gemini.
- `.codex-skills/skills/`: artefactos para Codex.
- `.claude/commands/` y `.claude/skills/`: comandos y skills invocables del entorno Claude.

La intención es clara: un mismo conjunto de capacidades se replica a distintos entornos para que cada plataforma pueda operar con el mismo tipo de instrucciones.

### 2. Riesgos actuales de concurrencia

Los riesgos principales son:

- sincronización manual por mirror;
- ausencia de ownership por recurso compartido;
- no existe un estado de “trabajo activo” para un skill o un agent compartido;
- varios agentes pueden intentar editar el mismo prompt, skill o workflow sin coordinación;
- el cierre de tarea puede no dejar evidencia de lock/lease actual ni handoff formal;
- no existe un criterio formal para detectar drift entre fuente central y mirrors antes del merge.

### 3. Patrón ya validado en el proyecto

La capa de negocio ya demuestra un patrón sólido de serialización concurrente:

- `core/services/camara_hierarchy_service.py` usa `pg_advisory_xact_lock` para proteger check-then-create bajo concurrencia.
- La lógica del lock se asocia a una clave determinista del recurso (`base_norm`) y se mantiene por la duración de la transacción.

Ese mismo principio debe extrapolarse a la capa agéntica: un recurso compartido debe tener un `owner`, un `lease` y un `state` explícito.

## Propuesta de arquitectura

### A. Modelo de ownership de recursos

Cada recurso compartido debe tener la siguiente metadata:

```json
{
  "resource": "skill:docker-rebuild",
  "owner": "agent:docker",
  "scope": "skill",
  "state": "active",
  "leased_at": "2026-09-08T12:00:00Z",
  "heartbeat_at": "2026-09-08T12:05:00Z",
  "lease_expires_at": "2026-09-08T12:15:00Z",
  "handoff": null,
  "last_change": "2026-09-08T12:05:10Z",
  "dependency_chain": [".agentes-comunes/skills/docker-rebuild", ".github/skills/docker-rebuild"]
}
```

Reglas:

- El recurso se identifica por nombre canónico y no por ruta física.
- La escritura requiere `owner` válido y `lease_expires_at` vigente.
- El heartbeat debe renovarse antes de expirar el lease.
- Si el lease vence sin heartbeat, el recurso pasa a `stale` y otro agente puede reclamarlo con handoff explícito si hubo interrumpción.

### B. Locks de archivo y de estado

Se recomienda un modelo de dos capas:

1. Lock de recurso (local): restringe escritura concurrente sobre un componente específico.
2. Lock de estado (global del entorno): registra las tareas activas y los handoffs entre agentes.

Implementación recomendada:

- SQLite local para el trabajo de un desarrollador o sesión CLI.
- PostgreSQL para CI/CD o coordinación distribuida si varias sesiones comparten el mismo repositorio.

Patrón mínimo:

```python
class AgentLease:
    resource: str
    owner: str
    state: str
    lease_expires_at: datetime
    heartbeat_at: datetime
```

Y una política:

- `read` permitido en paralelo;
- `write` requiere lock exclusivo;
- `reconcile` debe ver si hubo stale lease antes de permitir reasignación.

### C. Agent Awareness

La capa `Agent Awareness` debe responder estas preguntas:

- ¿qué recurso está siendo editado?
- ¿qué agente lo posee?
- ¿cuándo expira el lock?
- ¿hay handoff bueno o conflicto?
- ¿qué dependencias del mismo recurso están en riesgo?

Esto se debe materializar en un único estado compartido y no en conversaciones aisladas.

### D. Criterio de sincronización y drift

La sincronización no puede ser manual ni implícita. Debe existir una verificación automática:

- si `.agentes-comunes/skills/` cambia, se valida todos los mirrors;
- si un mirror difiere, se marca `drift_detected`;
- el flujo de cierre no puede terminar con drift pendiente.

Se recomienda un script de verificación tipo `scripts/check_agent_sync.sh` que haga:

- diff entre `.agentes-comunes/skills` y `.github/skills`;
- diff entre `.agentes-comunes/skills` y `.claude/skills` para los skills habilitadas;
- validación de `source:` y `Ubicación de archivo` en mirrors;
- salida con código de error si hay drift.

## Riesgos estructurales reales

### 1. Duplicidad de fuentes de verdad

Actualmente hay una intención clara de centralizar, pero la topología sigue siendo distribuida. Esto no es un problema de funcionalidad por sí mismo, pero sí hiere la gobernanza si no hay coordinación de ownership.

### 2. Ausencia de lock explícito en la capa agéntica

Mientras la capa de negocio hace lock en Postgres, la capa operativa de agentes no tiene protección equivalente. La consecuencia es un riesgo de overwrite sobre los mismos artefactos sin notificación.

### 3. Mirrors con estados no sincronizados

El script `scripts/sync_agentes_comunes.sh` existe y ayuda, pero no es un guardrail fuerte por sí mismo. Requiere un chequeo operativo para que la sincronización no quede como tarea informal.

### 4. Handoff incompleto

Si un agente queda interrumpido, no existe un contrato de continuidad formal para los recursos activos. Se requiere `handoff` con estado y next-step para reanudar sin conflicto.

## Arquitectura propuesta

### Capas

1. Source-of-truth layer
   - `.agentes-comunes/skills/`
   - `.github/agents/`
   - `.github/prompts/`

2. Mirror layer
   - `.github/skills/`
   - `.gemini/rules/`
   - `.codex-skills/skills/`
   - `.claude/skills/`

3. Coordination layer
   - state registry;
   - locks;
   - heartbeat;
   - handoff tracking;

4. Enforcement layer
   - CI/pre-commit hook;
   - PR check;
   - script de drift detection;
   - blocked-write policy if ownership conflict.

5. Observability layer
   - task logs;
   - lease expiry metrics;
   - concurrency collisions; 
   - frequency of drift and retries.

## Reglas de orquestación operativa

1. Antes de editar un recurso compartido, el agente debe registrar `acquire`.
2. El lock es por recurso, no por sesión.
3. La escritura se bloquea si el recurso ya está `active` con otra `owner` y lease vigente.
4. Si hay conflict, el agente debe detenerse, no hacer `git checkout` ni sobrescribir.
5. Todo handoff requiere un archivo de continuidad o estado persistido.
6. Todo cierre de tarea debe dejar el resource en `idle` o `handoff` y limpiar stale locks.
7. Se debe ejecutar la sincronización de mirrors antes del cierre del cambio.
8. Cualquier PR que toque agéntica y documentación debe incluir evidencia del check de drift.

## Plan de acción recomendado

### Fase 1 — Gobernanza del estado

- Crear `.agent-state/` o equivalente.
- Definir `resource`, `owner`, `lease`, `heartbeat` y `handoff`.
- Implementar `scripts/agent_lock.py` con `acquire`, `heartbeat`, `release`, `status`, `stale-cleanup`.

### Fase 2 — Enfoque de sincronización

- Hacer de `scripts/sync_agentes_comunes.sh` una validación obligatoria del pipeline.
- Añadir `scripts/check_agent_sync.sh` a CI y pre-commit.
- Fail si `.agentes-comunes` y mirrors no coinciden.

### Fase 3 — Integración CI/CD

- Añadir una etapa en CI que valide:
  - estado de locks activos;
  - mirrors sincronizados;
  - ausencia de drift semántico;
  - cambios en `docs/` o `.github/` con responsable y handoff.

### Fase 4 — Handoffs y continuidad

- Requerir documento de handoff cuando hay lock activo y otra tarea toma el mismo recurso.
- Registrar `next_action` y `blocked_on` dentro del handoff.

### Fase 5 — Observabilidad

- Loguear cada `acquire` y `release` con timestamp y propietario.
- Medir reintentos por lock, tiempo promedio de lease y tasa de drift.

## Recomendación final

La estructura actual del proyecto ya tiene buena separación de dominios y una política documental sólida. Lo que falta no es más especialización de agentes, sino una capa operacional explícita de coordinación y control de concurrencia. La recomendación es implantar un `Agent Awareness` con ownership, leases y bloqueo de escritura por recurso, combinando la disciplina ya aplicada en la capa de negocio con la capa de gobernanza agéntica.

Esto reduce el riesgo de sobrescritura simultánea, mejora los handoffs, y convierte la sincronización de mirrors de una práctica informal en una obligación verificable.
