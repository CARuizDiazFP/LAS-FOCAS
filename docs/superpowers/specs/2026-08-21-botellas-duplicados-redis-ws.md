# Nombre de archivo: 2026-08-21-botellas-duplicados-redis-ws.md
# Ubicación de archivo: docs/superpowers/specs/2026-08-21-botellas-duplicados-redis-ws.md
# Descripción: Spec — caché Redis + worker dedicado + WebSocket para el visor de Botellas duplicadas

# Redis + worker dedicado + WebSocket para el visor de Botellas duplicadas

## Contexto y premisa corregida

El visor `/admin/servicios/viewer/Botellas` depende de `detectar_grupos_duplicados_botellas`
(`core/services/botella_duplicados_service.py:54-131`): 2 queries con `joinedload` sobre
`Camara`+`CromoBotella` sin paginar, agrupadas en Python. El costo escala con el tamaño total de esas
tablas, no con la cantidad de duplicados. Se pidió desacoplar ese recálculo del hilo HTTP con
background tasks + caché Redis + notificación WebSocket, usando Docker.

Verificado leyendo `web/app/main.py` (no por memoria/documentación vieja):

- La función se llama de forma síncrona en **3** lugares: GET del visor (línea 5346), GET de export
  de inconsistencias (línea 5676), y **dentro** de `POST apropiar-masivo` (línea 5503) — este último
  la necesita como insumo de su propia lógica (decide qué grupos son `resoluble`), no sólo para
  responder.
- Hay **7** endpoints mutadores que cambian datos que afectan esa agrupación (`vigente`,
  `camara_id`/`camara_padre_id`, `nombre`) pero **ninguno la recalcula server-side** — dependen de que
  el frontend dispare un GET aparte después:
  - `POST /api/infra/botellas/apropiar` (`botellas_apropiar_web`, línea 5411)
  - `POST /api/infra/botellas/apropiar-masivo` (`botellas_apropiar_masivo_web`, línea 5479 — éste sí
    llama a la función, pero como INSUMO propio, no para notificar)
  - `POST /api/infra/botellas/consolidar` (`botellas_consolidar_web`, línea 5574)
  - `POST /api/infra/botellas/eliminar` (`botellas_eliminar_web`, línea 5728)
  - `POST /api/infra/botellas/{n_id}/repoblar-cables` (`botella_repoblar_cables_web`, línea 6449)
  - `POST /api/infra/botellas/{n_id}/separar-padre` (`botella_separar_padre_web`, línea 6543)
  - `PATCH /api/infra/botellas/{n_id}/nombre` (`botella_actualizar_nombre_web`, línea 6503)

  **Corrección sobre la decisión previa del usuario** ("aplicar a las 6 mutaciones del visor"): son
  **7**, no 6 — la exploración inicial no había listado la apropiación individual
  (`botellas_apropiar_web`). Se agrega a la lista sin volver a preguntar: mismo criterio ("cambia
  datos que afectan la agrupación") que ya se había aprobado para las otras seis.

- **Sólo `AdminBotellasViewer.vue`** muestra la agrupación de duplicados hoy, y de los 7 mutadores
  arriba, sólo 3 tienen un handler en ese archivo que dispara el reload pesado
  (`Promise.all([reloadDuplicados(), reloadFromZero()])`): apropiación individual
  (`handleApropiada`, líneas 422-425), apropiación masiva (`confirmarApropiacionMasiva`, líneas
  433-448) y consolidar (`handleConsolidado`, líneas 464-466, disparado por el evento `@consolidado`
  de `ModalConsolidarBotellas.vue`). Los otros 4 mutadores (eliminar, repoblar-cables, separar-padre,
  editar nombre) viven en `VerificadorCromoView.vue` y `CamaraDetailView.vue` — ninguno de los dos
  muestra la agrupación de duplicados, y sus handlers actualizan la UI localmente sin re-disparar esa
  búsqueda (comentario explícito en `onGuardarNombre`: "se refleja inmediato en la UI, sin re-disparar
  la búsqueda"). `separarBotellaDeCamaraPadre` no tiene ningún consumidor en el frontend actual pese a
  existir el endpoint y el botón "Separar a nueva Cámara" en `VerificadorCromoView.vue:85` — ese botón
  llama a `separarBotellaDeCamaraPadre` en la línea 602, sí tiene consumidor (corrección menor sobre
  un hallazgo previo que lo daba por sin uso).

  **Decisión de alcance** (regla YAGNI aplicada, no fue necesario volver a preguntar): el backend
  invalida caché + encola recálculo + publica WebSocket para los 7 endpoints por igual (así cualquier
  panel admin abierto con el visor de duplicados queda al día sin importar desde qué vista se disparó
  la mutación). El frontend sólo necesita el composable WS + refetch silencioso en
  `AdminBotellasViewer.vue` — es la única vista que muestra la agrupación; no hay nada que refrescar
  en `VerificadorCromoView.vue`/`CamaraDetailView.vue` porque no exhiben ese dato.

## Arquitectura

```
7 endpoints mutadores (apropiar, apropiar-masivo, consolidar, eliminar,
repoblar-cables, separar-padre, nombre)
        │  mutación normal, sin cambios de negocio
        └─► encolar_recalculo_duplicados_botellas(motivo)
                 ├─► DELETE cache:botellas_duplicados:v1   (invalida, best-effort)
                 └─► RPUSH admin:recompute:jobs {"kind":"botellas_duplicados","motivo":...}
                              │
                              ▼
             botellas_recalculo_worker (contenedor nuevo, BLPOP en loop)
                              │  detectar_grupos_duplicados_botellas(session) — función sin tocar
                              ├─► SET cache:botellas_duplicados:v1 <json>  (TTL 24h, red de seguridad)
                              └─► PUBLISH admin-notifications {"type":"botellas_duplicados_recalculado","at":...}
                                              │
                                              ▼
                              web (proceso ya corriendo) — task de arranque suscripta al canal
                                              │  reenvía a cada WebSocket en /ws/admin-notifications
                                              ▼
                              AdminBotellasViewer.vue — composable WS → refetch silencioso

3 endpoints de lectura (viewer duplicados, export inconsistencias, apropiar-masivo):
  GET cache:botellas_duplicados:v1 primero → hit: evita el scan completo.
  Miss (frío o Redis caído) → cómputo síncrono actual sin cambios + SET oportunista del resultado.
```

Redis nunca es una dependencia dura: cualquier fallo (enqueue, cache-read, publish, subscribe) se
atrapa y loguea; el comportamiento cae al de hoy (síncrono, correcto, sólo sin la mejora de
velocidad).

## Decisiones de infraestructura (confirmadas con el usuario)

- **Redis nuevo** (hoy no existe ningún uso real en el repo) con tres roles: caché, cola de jobs,
  bus pub/sub.
- **Worker Docker dedicado nuevo** (`modules/botellas_recalculo_worker/`, mismo layout que
  `modules/cromo_worker/`: propio `worker.py`/`config.py`/`requirements.txt`, imagen `focas-base` +
  Dockerfile propio, FastAPI mínima con `/health`) — no `BackgroundTasks` de FastAPI ni Celery.
- **Canal WebSocket genérico** `admin-notifications` — no existe hoy ningún mecanismo de broadcast
  (`web/chat_ws.py` es 1 conexión ↔ 1 orchestrator, sin registro de conexiones activas). El envelope
  del mensaje (`{"type": ..., "at": ...}`) permite que un futuro segundo `kind` de recálculo (p. ej.
  Cámaras duplicadas) reuse el mismo canal sin rediseñar el transporte, aunque hoy sólo se implementa
  el caso de Botellas.
- **Redis + el worker nuevo en ambos `docker-compose`** (dev y prod). En dev se levantan y se prueban
  reales. En prod el compose queda con los servicios definidos en código pero **sin recrear
  contenedores ahora** — mismo patrón que la subred /16→/24 (`docs/mantenimiento_redes_produccion.md`):
  listos para la próxima ventana de mantenimiento. Nota real encontrada en la exploración: `cromo_worker`
  (el precedente de "worker dedicado" en este repo) **no existe en `deploy/compose.yml` (prod)** —
  sólo en dev. El nuevo bloque de prod se mirror desde el patrón de `postgres`/`api` que sí están en
  prod, no literalmente desde `cromo_worker`.

## Convenciones exactas a usar (para que las tareas no diverjan)

| Concepto | Valor |
|---|---|
| Cache key | `cache:botellas_duplicados:v1` |
| Cache TTL | 86400s (24h) — red de seguridad; la invalidación real es explícita en cada mutación |
| Queue key (lista Redis) | `admin:recompute:jobs` |
| Job payload | `{"kind": "botellas_duplicados", "motivo": "<str>"}` |
| Canal pub/sub | `admin-notifications` |
| Mensaje WS | `{"type": "botellas_duplicados_recalculado", "at": "<iso8601 UTC>"}` |
| Endpoint WS | `GET /ws/admin-notifications` (upgrade) |
| Health del worker nuevo | puerto `8097` interno (`cromo_worker` ya usa `8096`) |
| Imagen Redis | `redis:7.4-alpine` (pinneada, no `latest`) |
| Servicios compose nuevos | `redis`, `botellas_recalculo_worker` |
| Secret Redis (dev) | `Dev_redis_password_v1.txt` → secret `redis_password_v1` |
| Secret Redis (prod) | `redis_password_v1.txt` → secret `redis_password_v1` |
| Dependencia Python nueva | `redis==5.0.8` en `common-requirements.txt` |
| Módulo cliente Redis | `core/cache/redis_client.py` (`get_redis() -> Redis`, lazy, no lanza al construir) |
| Módulo caché/cola | `core/services/botella_recompute_queue.py` |
| Worker nuevo | `modules/botellas_recalculo_worker/{worker.py,config.py,requirements.txt}` |
| Dockerfile worker | `deploy/docker/botellas_recalculo_worker.Dockerfile` |
| Canal WS backend | `web/admin_ws.py` (`ConnectionManager`, `mount_admin_websocket(app, ...)`) |
| Composable frontend | `web/frontend/src/composables/useAdminNotifications.ts` |

## Fuera de alcance (YAGNI, explícito)

- No se generaliza el worker para otros `kind` de recálculo (p. ej. Cámaras duplicadas) — el
  dispatch table queda con un solo `kind` registrado hoy.
- No se toca `VerificadorCromoView.vue` ni `CamaraDetailView.vue` — no muestran la agrupación de
  duplicados, no tienen nada que refrescar.
- No se ejecuta ningún `docker compose up`/`restart` contra prod como parte de este trabajo.
- No se reemplaza `BackgroundTasks`/Celery en ningún otro módulo existente del repo.
