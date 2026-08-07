# Nombre de archivo: modulo_ingesta_cromo.md
# Ubicación de archivo: docs/modulo_ingesta_cromo.md
# Descripción: Contexto estructural del módulo de ingesta de inventario de fibra óptica desde Cromo Red

# Módulo de ingesta de inventario FO desde Cromo

**Estado:** completo, con una Etapa 7 de hardening (worker dedicado + scheduler). Las 7 etapas (acceso
y parseo, persistencia, servicio de ingesta, API + progreso en vivo, interfaz de ingesta, verificador
de servicios, worker dedicado con scheduler configurable) están implementadas, probadas y validadas
contra el Cromo real de Metrotel y `lasfocasdev-postgres`.

## Qué resuelve

Cromo Red es el sistema externo de Metrotel donde vive el inventario físico de planta externa de fibra
óptica: botellas/empalmes, cables, tubos, pelos y fusiones, con su geolocalización. Ese inventario no
está replicado en la base de LAS-FOCAS. Este módulo lo ingiere de forma periódica (disparada a demanda,
no automática) para poblar tablas propias y habilitar un **verificador de servicios**: dado un cable,
un buffer o una botella, saber qué servicios de `app.servicios` pasan por ahí.

Es una integración de **sólo lectura**: LAS-FOCAS nunca escribe en Cromo. La ingesta no reemplaza el
flujo existente de trackings `.txt`/`app.ingresos`; convive con ellos en un namespace propio dentro del
esquema `app`.

## Por qué por etapas

El volumen (del orden de 10 mil botellas y sus cables asociados) y la necesidad de validar el modelo de
datos contra la API real antes de comprometerse a un esquema de base llevaron a dividir el trabajo:

1. **Etapa 1 — Acceso y parseo** (completa): cliente HTTP de sólo lectura, parser puro de payloads a
   estructuras de dominio, script de sondeo, tests. Sin tocar la base de datos ni la interfaz. La sonda
   corrió contra el Cromo real de Metrotel y cerró los puntos abiertos del diseño (autenticación OAuth2,
   formato de respuesta, identificación de clases, peso de página).
2. **Etapa 2 — Persistencia** (completa): migración Alembic y modelos SQLAlchemy para las tablas propias
   del módulo, aisladas del resto del esquema. Sin código todavía que escriba en ellas.
3. **Etapa 3 — Servicio de ingesta** (completa): orquesta la lectura paginada, clasifica cada objeto
   como creado/actualizado/sin cambios, reconcilia referencias cruzadas y audita cada corrida. Validada
   con una corrida real acotada contra Cromo y la base dev — encontró y corrigió tres incompatibilidades
   reales entre el diseño y el comportamiento efectivo de la API/el driver async (detalle en
   `docs/PR/2026-08-06.md`).
4. **Etapa 4 — API** (completa): endpoints para disparar una corrida y seguir su progreso en vivo por
   SSE, con cancelación cooperativa. Primer uso de sesión async de DB y de tareas en background en
   `web/app/main.py` (detalle de la decisión de arquitectura en `docs/PR/2026-08-06.md`).
5. **Etapa 5 — Interfaz** (completa): vista `/admin/ingesta/cromo` — selector de clases, `psize` fijo a
   5 valores, progreso en vivo consumiendo el SSE de la Etapa 4 con `EventSource` nativo del browser
   (primer uso en el proyecto), histórico y detalle de corridas. Validada de punta a punta contra el
   backend real (Cromo + `lasfocasdev-postgres`) por HTTP/SSE crudo — el entorno de esta sesión no pudo
   levantar un browser real (sin permisos para instalar las librerías de sistema de Chromium), así que
   la renderización de Vue en sí no se vio en pantalla; el contrato de datos que consume sí se validó
   byte a byte. Detalle en `docs/PR/2026-08-06.md`.
6. **Etapa 6 — Verificador** (completa): tres consultas de sólo lectura sobre las tablas ya pobladas
   — qué servicios pasan por un cable entero, por un tubo/buffer específico, o por los cables que
   tienen una botella como extremo. Vista `/infra/cromo/verificador`, disponible para cualquier
   usuario autenticado (no requiere rol admin: es consulta, no administración). Validada contra datos
   reales de la Etapa 3 — encontró y corrigió un caso real de referencia colgada (detalle en
   `docs/PR/2026-08-06.md`).
7. **Etapa 7 — Worker dedicado y scheduler** (completa): la ejecución de la ingesta se movió a un
   contenedor propio (`cromo_worker`), separado del proceso del panel — pedido explícito para poder
   programar corridas periódicas sin competir con el tráfico web. El worker expone un pequeño control
   HTTP (FastAPI + `AsyncIOScheduler`, todo en el mismo loop de asyncio, sin threads) con `/health`,
   `/reload` y `/run`; `web/app/main.py` sigue siendo el único punto de entrada del panel, pero ahora
   delega la ejecución real vía HTTP en vez de un `asyncio.create_task` local. El intervalo, hora de
   inicio, `psize`/`max_paginas`/clases del scheduler se configuran desde una tabla propia
   (`app.cromo_ingesta_config`) editable desde el panel — arranca **deshabilitado por defecto**. De
   paso, dos correcciones reales encontradas al usar la vista contra datos ya ingeridos: un bug de
   frontend (`k.value.trim is not a function` al poner un valor en "Máximo de páginas") y una
   normalización visual de las 6 vistas admin al mismo patrón de cabecera que ya usaba `/servicios`.
   Detalle en `docs/PR/2026-08-07.md`.

Cada etapa se habilita una vez cerrada la anterior; las decisiones de una etapa pueden ajustar el diseño
de las siguientes si el sondeo contra la API real revela algo distinto de lo asumido.

## Dónde vive el código

- `core/services/cromo/`: paquete del módulo.
  - `config.py`: configuración desde variables de entorno (y Docker Secrets para credenciales),
    validada al arranque.
  - `client.py`: cliente HTTP asíncrono de sólo lectura contra la API externa, con paginación y
    reintentos acotados. No implementa ninguna operación de escritura, por diseño.
  - `parser.py`: funciones puras que traducen los payloads recibidos a las estructuras de dominio.
    Sin acceso a red ni a base de datos.
  - `modelos.py`: las estructuras de dominio del inventario (botella, cable, tubo, pelo, fusión).
  - `ingesta.py`: servicio de ingesta — orquesta las fases de conteo, cables, botellas,
    reconciliación de referencias colgadas y matching de servicios. Transacción por página (un
    commit por página, con savepoints por objeto para que uno malformado no aborte el resto) y
    cancelación cooperativa entre páginas.
  - `verificador.py`: consultas de sólo lectura sobre el inventario ya ingerido — qué servicios
    pasan por un cable, un tubo/buffer o una botella. Tolerante a referencias colgadas: un objeto sin
    fila propia pero referenciado por otro (pelo, cable) no se trata como "no encontrado".
- `scripts/cromo_sonda.py`: script de descubrimiento de sólo lectura, para relevar aspectos de la API
  externa que no se pueden resolver leyendo documentación (identificar clases desconocidas, medir
  tamaños de respuesta, etc.). No se ejecuta como parte del flujo normal de la aplicación.
- `tests/test_cromo_parser.py`, `tests/test_cromo_client.py`, `tests/test_cromo_ingesta.py`,
  `tests/test_web_cromo_ingesta.py`, `tests/test_cromo_verificador.py`,
  `tests/test_web_cromo_verificador.py`, `tests/test_cromo_worker.py`, `tests/fixtures/cromo/`:
  cobertura de parser, cliente, servicio de ingesta, verificador, worker y endpoints web, sin red ni
  DB real.
- `db/models/cromo.py`: modelos SQLAlchemy de las tablas `app.cromo_*` (catálogo, auditoría de
  corridas/eventos, inventario y config del scheduler). Documentación de cada tabla en `docs/db.md`.
- `db/alembic/versions/20260805_01_cromo_ingesta.py`, `20260806_01_cromo_ingesta_config.py`:
  migraciones que crean esas tablas, siembran el catálogo de clases y la config inicial del scheduler.
- `modules/cromo_worker/`: worker dedicado (Etapa 7) — `worker.py` (FastAPI + `AsyncIOScheduler` en
  el mismo loop de asyncio, sin threads; rutas `/health`, `/reload`, `/run`), `config.py` (constantes),
  `requirements.txt` (sólo `apscheduler`, no está en `common-requirements.txt`). Importa
  `core.services.cromo.*` — no reimplementa nada del dominio.
- `deploy/docker/cromo_worker.Dockerfile`, bloque `cromo_worker` en `deploy/docker-compose.dev.yml`:
  imagen y servicio del worker (sólo dev por ahora). Hereda `focas-base:latest`, usuario no-root.
- `web/app/main.py`: endpoints admin (`/api/admin/ingesta/cromo` y sub-rutas) — disparo de corrida
  (delega la ejecución al worker por HTTP desde la Etapa 7, ya no `asyncio.create_task` local), stream
  SSE de progreso, histórico, detalle, cancelación, y config del scheduler
  (`GET`/`POST /api/admin/ingesta/cromo/config`, `.../config/health`, `.../config/trigger`). Sigue el
  patrón vigente del archivo (`_require_admin`, CSRF contra `request.session`), con imports locales de
  `core.services.cromo.*` y `db.*` dentro de cada función, como el resto del archivo. También los
  endpoints del verificador (`/api/infra/cromo/{cables,tubos,botellas}/{n_id}/servicios`), con
  `_require_auth` en vez de `_require_admin` — son consulta, no administración.
- `web/frontend/src/api/cromo.ts`: cliente API del SPA (wrappers sobre `request`/`requestJson` de
  `src/api/client.ts`) + catálogo estático de clases botella (mismo seed que la migración) + funciones
  del verificador (`verificarServiciosPor{Cable,Tubo,Botella}`) + funciones del scheduler del worker
  (`obtenerConfigSchedulerCromo`, `guardarConfigSchedulerCromo`, `obtenerSaludWorkerCromo`,
  `dispararSchedulerCromo`).
- `web/frontend/src/admin/views/AdminIngestaCromo.vue`: vista en `/admin/ingesta/cromo` — card de
  scheduler automático (habilitar/deshabilitar, intervalo, hora de inicio, clases/psize/max_páginas
  del ciclo periódico, estado del worker, "Ejecutar ahora"), dispara corridas manuales y consume el
  SSE con `EventSource` nativo (replay por `Last-Event-ID` automático del browser, sin código propio),
  histórico y detalle. Registrada en `web/frontend/src/router/index.ts` y con su tarjeta en el hub
  `AdminIngesta.vue`, siguiendo la skill `frontend-spa-architecture`.
- `web/frontend/src/admin/components/AdminPageHeader.vue`: cabecera estándar (kicker + título +
  subtítulo) de las vistas admin, calcada del patrón ya usado en `/servicios`. Aplicada a las 6 vistas
  admin existentes (Etapa 7).
- `web/frontend/src/views/VerificadorCromoView.vue`: vista en `/infra/cromo/verificador` — selector de
  tipo de objeto (cable/tubo/botella), búsqueda por `n_id`, tabla de servicios encontrados. Vista del
  panel operativo (no de `/admin`): cualquier usuario autenticado puede usarla. Registrada en
  `router/index.ts` y con su entrada de navegación en `AppShell.vue` (grupo "Tool Kit").

## Principios de diseño

- **Sólo lectura, siempre.** El cliente no expone ningún método de escritura contra el sistema externo.
- **Credenciales fuera del código.** Se leen de variables de entorno o de Docker Secrets si están
  disponibles; nunca se loguea una credencial completa (a lo sumo, los últimos caracteres para poder
  reconocerla en logs sin exponerla).
- **Tolerancia a fallos parciales.** Un objeto malformado o inesperado no aborta el procesamiento del
  resto de una página; se reporta como error puntual y se continúa.
- **Reintentos acotados y selectivos.** Sólo ante errores de red o de servidor, con backoff exponencial
  y un tope fijo. Nunca se reintenta un error de solicitud (datos o permisos inválidos).
- **Paginación dirigida por el propio servidor externo**, no por una suposición local de tamaño de
  página o cantidad de resultados.

## Dónde está el detalle sensible

El modelo de datos completo (estructura exacta del payload, diccionario de atributos, esquema de tablas
propuesto, mecanismo de autenticación) vive en documentación interna no versionada en este repositorio,
por contener detalles operativos del proveedor. Quien continúe una etapa siguiente debe partir de ese
documento, no de este.
