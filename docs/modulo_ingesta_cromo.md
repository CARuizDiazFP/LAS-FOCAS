# Nombre de archivo: modulo_ingesta_cromo.md
# Ubicación de archivo: docs/modulo_ingesta_cromo.md
# Descripción: Contexto estructural del módulo de ingesta de inventario de fibra óptica desde Cromo Red

# Módulo de ingesta de inventario FO desde Cromo

**Estado:** completo, con Etapas 7-9 de hardening/explotación de datos (worker dedicado + scheduler;
tratamiento de datos ya ingeridos + inventario navegable; filtros extendidos + detalle jerárquico +
navegación cruzada). Las 9 etapas están implementadas, probadas y validadas contra el Cromo real de
Metrotel y `lasfocasdev-postgres`.

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
8. **Etapa 8 — Tratamiento de datos e inventario** (completa): con las primeras corridas reales
   completas ya hechas, aparecieron y se corrigieron tres problemas reales de calidad de dato —
   fusiones que nunca llegaban (necesitan su propio barrido directo, no vienen embebidas como se
   documentaba), geolocalización nunca calculada (el dato real viaja proyectado, no en la clave
   documentada — reproyección + backfill de las filas ya ingeridas), y una clasificación de pelos
   invertida (`LIBRE`↔`CLIENTE`). Sobre esos datos ya corregidos, un **inventario de cables**
   navegable (búsqueda + paginación) en `/infra/cromo/cables`, complementario al verificador puntual
   de la Etapa 6. Detalle en `docs/PR/2026-08-07.md`.
9. **Etapa 9 — Filtros extendidos, detalle jerárquico y navegación cruzada** (completa): el inventario
   de cables de la Etapa 8b ganó 3 filtros nuevos (Id de cable exacto; Botella asociada, `ILIKE` sobre
   los extremos ya desnormalizados; Servicio asociado, vía subquery **no correlacionada** — `c.n_id IN
   (...)`, no `EXISTS (...)`, para que Postgres resuelva el join una sola vez por request y no una vez
   por cada una de las 30.000+ filas candidatas), y un endpoint + panel de detalle jerárquico en
   acordeón por cable (`core/services/cromo/detalle.py`, nuevo): extremos, Buffers/tubos y sus Pelos,
   con el servicio matcheado de cada pelo si existe — 3 queries fijas, nunca N+1. Navegación cruzada
   real: click en un servicio matcheado navega a `/servicios/ID/...`; click en una Botella extremo
   navega al Verificador Cromo (única vista de detalle de botella que existe — al momento de esta
   etapa, no había relación entre `cromo_botellas.n_id` y la tabla de Cámaras de Infra; desde
   2026-08-11 sí existe, ver nota más abajo) precargado vía query params. El link "Cables"
   del sidebar se movió del grupo "Tool Kit" al nuevo grupo expandible "Infraestructura FO" (pedido
   explícito, distinto del Verificador, que se queda en "Tool Kit"). Detalle en `docs/PR/2026-08-10.md`.

Cada etapa se habilita una vez cerrada la anterior; las decisiones de una etapa pueden ajustar el diseño
de las siguientes si el sondeo contra la API real revela algo distinto de lo asumido.

**Nota (2026-08-10, fuera de las etapas de ingesta — módulo Infra/Baneos)**: `cromo_botellas` ganó un
segundo consumidor de sólo lectura, un listado unificado que combina Cromo con las Botellas "legado" de
la jerarquía Cámara→Botella de Infra/Baneos (`app.camaras` con `camara_padre_id`). No agrega ni modifica
ningún campo/relación de la ingesta — es una nueva query de agregación (`UNION ALL`) del lado consumidor.
Documentado en `docs/infra.md`, sección "Submódulo Botellas (listado unificado)".

**Nota (2026-08-11)**: a diferencia de la nota anterior, este cambio **sí** agrega columnas a
`cromo_botellas` — `camara_id` (FK a `app.camaras.id`) y `estado` (migración `20260811_01`), poblados
por `scripts/cromo_backfill_camara_padre.py` para vincular cada Botella a una Cámara padre propia con
estado operativo. Deliberadamente **excluidas** de `_BOTELLA_CAMPOS` (`core/services/cromo/ingesta.py`)
y del dataclass `Botella` (`core/services/cromo/modelos.py`) — ninguna corrida futura de la ingesta las
toca (`_upsert_versionado`/`_copiar_campos` sólo `setattr`ean los campos listados explícitamente), así
que el vínculo sobrevive intacto a reingestas periódicas. Costo aceptado: filas *nuevas* que aparezcan
en una reingesta futura (`n_id` nunca visto) entran con `camara_id=NULL`/`estado='NO_OPERATIVA'` hasta
la siguiente corrida manual de ese script — mismo patrón operativo que `cromo_backfill_geo.py`/
`cromo_backfill_servicio_prefijos.py` (correr después de cada ingesta relevante, no auto-encadenado).
Documentado en `docs/infra.md`, sección "Cámara padre para Botellas Cromo".

## Dónde vive el código

- `core/services/cromo/`: paquete del módulo.
  - `config.py`: configuración desde variables de entorno (y Docker Secrets para credenciales),
    validada al arranque.
  - `client.py`: cliente HTTP asíncrono de sólo lectura contra la API externa, con paginación y
    reintentos acotados. No implementa ninguna operación de escritura, por diseño.
  - `parser.py`: funciones puras que traducen los payloads recibidos a las estructuras de dominio.
    Sin acceso a red ni a base de datos.
  - `modelos.py`: las estructuras de dominio del inventario (botella, cable, tubo, pelo, fusión).
  - `alias_service.py` (2026-08-19): escudo manual contra basura conocida de Cromo — carga en
    memoria (una sola query por corrida) la tabla `app.cromo_botella_alias` y resuelve, para un
    `n_id` de botella marcado a mano, si debe fusionarse dentro de otro n_id "golden" o anularse
    directamente. Ver `docs/db.md` (tabla `cromo_botella_alias`) y `docs/decisiones.md` (2026-08-19).
  - `ingesta.py`: servicio de ingesta — orquesta las fases de conteo, cables, botellas,
    reconciliación de referencias colgadas y matching de servicios. Transacción por página (un
    commit por página, con savepoints por objeto para que uno malformado no aborte el resto) y
    cancelación cooperativa entre páginas. Desde 2026-08-19, las fases de cables/botellas/fusiones
    consultan `alias_service` antes de cada upsert: un `n_id` aliaseado nunca crea/actualiza su
    propia `CromoBotella`, y cualquier referencia blanda hacia él (extremo de cable, parent de
    fusión) se redirige o se anula según corresponda. Desde 2026-08-14, `fase_servicios` ya no deja un
    `servicio_numero` sin match como sólo traza de auditoría: si el número es "plausible" (longitud
    4-6 dígitos, `parser.py::es_numero_servicio_plausible`) crea un `Servicio` placeholder
    (`categoria=0`, `origen_datos=INFERIDO_CROMO`) vía `ON CONFLICT DO NOTHING RETURNING id`, con
    cache en memoria por corrida para no reintentar la misma alta cientos de veces cuando muchos
    pelos comparten número. Ver `docs/decisiones.md` (2026-08-14) para el detalle completo, incluida
    la re-etiqueta a `INGEST_EXCEL` cuando un Excel real enriquece después el mismo placeholder.
  - `verificador.py`: consultas de sólo lectura sobre el inventario ya ingerido — qué servicios
    pasan por un cable, un tubo/buffer o una botella. Tolerante a referencias colgadas: un objeto sin
    fila propia pero referenciado por otro (pelo, cable) no se trata como "no encontrado". Desde
    2026-08-18, `servicios_por_botella` también resuelve `cables: list[CableDeBotella]` (id, nombre,
    cantidad de servicios de cada cable que tiene la botella como extremo) con una query propia
    (`_SQL_CABLES_DE_BOTELLA`, subselect correlacionado para el conteo — mismo patrón que
    `inventario.py`) — alimenta la tarjeta "Cables asociados" del detalle de Botella en el
    Verificador. Los empalmes (fusiones internas de la botella) tienen su propio módulo dedicado,
    `empalmes.py` (ver más abajo), en vez de ser un campo más de `ResultadoBotella`.
  - `inventario.py`: búsqueda paginada de cables (Etapa 8b, filtros extendidos en Etapa 9) — distinto
    del verificador ("listame cables", no "qué servicios pasan por este cable puntual"). `ILIKE`
    parcial sobre nombre/jerarquía/propietario/botella (extremos ya desnormalizados), exacto sobre
    vigente/n_id, `IN (subquery no correlacionada)` sobre servicio asociado (evita re-ejecutar el join
    por cada una de las filas candidatas), con conteo de servicios matcheados por cable.
  - `detalle.py` (Etapa 9): detalle jerárquico de un cable puntual — metadata + extremos + Buffers/
    tubos + Pelos de cada tubo, con el servicio matcheado de cada pelo si existe. 3 queries fijas
    (cable, tubos del cable, todos los pelos del cable con su match ya resuelto por LEFT JOIN),
    agrupadas en Python por `tubo_n_id` — nunca N+1. Mismo criterio de referencia colgada tolerante
    que `verificador.py`, extendido a nivel tubo.
  - `empalmes.py`: resuelve los empalmes (fusiones — "fusión" y "empalme" son sinónimos en este
    dominio) internos de una Botella a partir de `app.cromo_fusiones`/`cromo_pelos`/`cromo_cables`/
    `cromo_tubos` ya ingeridos — nunca contra la API de Cromo. Dos hallazgos de diagnóstico real
    (`lasfocasdev-postgres`, sólo 5 filas de `cromo_fusiones` en todo el ambiente) que contradicen el
    diseño documentado más arriba: (1) `cromo_fusiones.botella_n_id` nunca viene poblado en la
    práctica — el barrido directo por clase 132 no trae `parent` — así que la pertenencia de una
    fusión a una botella se infiere por join indirecto: alguno de sus dos pelos pertenece a un cable
    que tiene esa botella como `extremo_a_n_id`/`extremo_b_n_id` (mismo patrón de
    `_SQL_CABLES_DE_BOTELLA` de `verificador.py`), validado end-to-end contra la botella real 9345594
    (Cra Alberdi 290) y su única fusión ingerida (17-1). (2) "Splitter" no es una clase Cromo propia
    (el catálogo `app.cromo_clases` sólo tiene BOTELLA/CABLE/TUBO/PELO/FUSION) — se detecta
    estructuralmente: un mismo pelo (`n_id`) que se repite como origen en 2+ filas de
    `cromo_fusiones` de la misma botella es la firma física de un Splitter (fan-out), con un
    fallback secundario por regex `^[Ss]\d+-\d+$` sobre `nombre_par` para patas sueltas/colgadas que
    no se pueden agrupar (únicos 2 ejemplos reales: "S7-1", "S4-1"). Expone
    `empalmes_de_botella(sesion, botella_n_id) -> ResultadoEmpalmesBotella` (cables de origen +
    lista de empalmes, cada uno con `es_splitter`/`splitter_destinos`/`splitter_ratio`), consumido
    por `GET /api/infra/cromo/botellas/{n_id}/empalmes` en `web/app/main.py` y por la vista dedicada
    `EmpalmesBotellaCromoView.vue` (`/infra/cromo/verificador/empalmes?n_id=...`, tabla filtrable por
    Cable Origen). Tests en `tests/test_cromo_empalmes.py` (sin DB real, mismo patrón de sesión falsa
    que `tests/test_cromo_verificador.py`).
  - `live_lookup_service.py` (2026-08-19): visor en vivo de un elemento Cromo por `n_id` — un único
    `GET /db/objects/{id}` (`CromoClient.get_objeto`) contra Cromo, **nunca** contra las tablas ya
    ingeridas y **nunca** persiste nada. Distinto de todo lo demás en este paquete: es la única
    consulta que golpea la API externa fuera de una corrida de ingesta. Etiquetas legibles para los
    `at[]` crudos vía `parser.ATRIBUTOS_CONOCIDOS`; la clase se resuelve contra el catálogo ya
    existente `app.cromo_clases` (sin duplicar el mapeo clase→etiqueta). 404 de Cromo se traduce a
    `ObjetoNoEncontrado` (mismo contrato que `verificador.py`/`detalle.py`); cualquier otra falla de
    Cromo se deja propagar para que la ruta la mapee a 502. Endpoint
    `GET /api/infra/cromo/elementos/{n_id}/vivo` en `web/app/main.py`, modal
    `ModalVerificadorCromo.vue` desde el botón "Ver info en Cromo" del detalle de Botella
    (`VerificadorCromoView.vue`). Ver `docs/decisiones.md` (entrada 2026-08-19).
  - `validador_datos_service.py` (2026-08-19): herramienta de Tool Kit "Validar datos DB Cromo" —
    distinta de `live_lookup_service.py` (que sólo devuelve los atributos planos de un objeto): acá se
    le aplica el MISMO parseo que usa esta ingesta (`parser.parse_objeto` — el dispatcher genérico por
    clase que también usa `parse_pagina` — más `parse_arbol_botella`/`extraer_tubos_y_pelos` si el
    objeto es una botella o un cable con `inner[]` propio), armando el árbol completo
    (cables/tubos/pelos/fusiones) para diagnóstico visual. Cero acceso a la base de datos local, ni
    siquiera en lectura — los servicios de cada pelo se muestran crudos
    (`servicio_raw`/`servicio_numero`), nunca matcheados contra `app.servicios`. Una clase excluida o
    no soportada no rompe la herramienta — queda en `errores_parseo`, `tipo_objeto="Desconocido"`.
    Endpoint `GET /api/infra/cromo/validar/{n_id}` en `web/app/main.py` (sin sesión de DB en
    absoluto), vista dedicada `ValidarDatosCromoView.vue` en `/toolkit/validar-datos-cromo` (Tool
    Kit) — herramienta separada de "Verificador Cromo", confirmado explícitamente con el usuario. Ver
    `docs/decisiones.md` (entrada 2026-08-19, tercera del día).
- `scripts/cromo_sonda.py`: script de descubrimiento de sólo lectura, para relevar aspectos de la API
  externa que no se pueden resolver leyendo documentación (identificar clases desconocidas, medir
  tamaños de respuesta, etc.). No se ejecuta como parte del flujo normal de la aplicación.
- `scripts/cromo_backfill_geo.py`: backfill one-off (Etapa 8b) de `latitud`/`longitud` en
  `cromo_botellas` ya ingeridas, a partir de `pts_raw` ya almacenado — no pega contra Cromo, idempotente.
- `scripts/cromo_backfill_servicio_prefijos.py` (Etapa 9c): backfill one-off de `servicio_numero`/
  `tipo_asociacion` en `cromo_pelos` ya ingeridos, tras ampliar los prefijos que reconoce
  `parser.py::parsear_servicio()` (antes sólo "FO", ahora también TLS/DWDM/INT/EWS/RPV/TDM/ATD/VID/
  TRUNK). Reusa las queries de `ingesta.fase_servicios()` para el matching contra `app.servicios`, sin
  duplicar lógica. Corrido contra `lasfocasdev-postgres`: 91.654 pelos re-clasificados de
  `INDETERMINADO` a `CLIENTE`, 7.042 con match real resuelto.
- `scripts/cromo_backfill_placeholders_servicios.py` (2026-08-14): backfill one-off del historial
  acumulado de `cromo_servicio_match` sin match (`servicio_id IS NULL`) — mismo criterio de
  plausibilidad de longitud que la lógica en vivo de `fase_servicios`, un placeholder por
  `servicio_numero` distinto (no por fila de match), re-validado contra el estado actual de
  `app.servicios` (incluido `alias_ids`) antes de crear nada. Corrido contra `lasfocasdev-postgres`:
  9.054 `Servicio` placeholder creados, 112.340 filas de `cromo_servicio_match` resueltas, 3.144 sin
  resolver (números de 1-3 u 8-10 dígitos, basura de parseo). Idempotente por construcción.
- `tests/test_cromo_parser.py`, `tests/test_cromo_client.py`, `tests/test_cromo_ingesta.py`,
  `tests/test_web_cromo_ingesta.py`, `tests/test_cromo_verificador.py`,
  `tests/test_web_cromo_verificador.py`, `tests/test_cromo_worker.py`, `tests/test_cromo_inventario.py`,
  `tests/test_web_cromo_inventario.py`, `tests/test_cromo_detalle.py`, `tests/test_web_cromo_detalle.py`,
  `tests/test_cromo_empalmes.py`,
  `tests/fixtures/cromo/`: cobertura de parser, cliente, servicio de ingesta, verificador, worker,
  inventario, detalle jerárquico, empalmes y endpoints web, sin red ni DB real.
- `db/models/cromo.py`: modelos SQLAlchemy de las tablas `app.cromo_*` (catálogo, auditoría de
  corridas/eventos, inventario y config del scheduler). Documentación de cada tabla en `docs/db.md`.
- `db/alembic/versions/20260805_01_cromo_ingesta.py`, `20260806_01_cromo_ingesta_config.py`,
  `20260807_01_cromo_fusiones_botella_nullable.py`: migraciones que crean esas tablas, siembran el
  catálogo de clases, la config inicial del scheduler, y relajan `cromo_fusiones.botella_n_id` a
  nullable (Etapa 8a — las fusiones del barrido directo no traen `parent`).
- `modules/cromo_worker/`: worker dedicado (Etapa 7) — `worker.py` (FastAPI + `AsyncIOScheduler` en
  el mismo loop de asyncio, sin threads; rutas `/health`, `/reload`, `/run`), `config.py` (constantes),
  `requirements.txt` (sólo `apscheduler`, no está en `common-requirements.txt`). Importa
  `core.services.cromo.*` — no reimplementa nada del dominio.
- `deploy/docker/cromo_worker.Dockerfile`, bloque `cromo_worker` en `deploy/docker-compose.dev.yml`:
  imagen y servicio del worker (sólo dev por ahora). Hereda `focas-base:latest`, usuario no-root.
  Copia además `modules/slack_baneo_notifier/` (2026-08-22): `core/services/cromo/ingesta.py` importa
  `botella_recompute_queue` → `botella_duplicados_service` → `camara_hierarchy_service`, que reusa los
  helpers de normalización de ese submódulo. Sin ese `COPY` el worker arranca en
  `ModuleNotFoundError` y, con `restart: unless-stopped`, queda en crash-loop — al agregar un import
  nuevo en `core/` hay que revisar qué arrastra a los Dockerfiles de los workers, que copian sólo un
  subconjunto de `modules/`.
- `web/app/main.py`: endpoints admin (`/api/admin/ingesta/cromo` y sub-rutas) — disparo de corrida
  (delega la ejecución al worker por HTTP desde la Etapa 7, ya no `asyncio.create_task` local), stream
  SSE de progreso, histórico, detalle, cancelación, y config del scheduler
  (`GET`/`POST /api/admin/ingesta/cromo/config`, `.../config/health`, `.../config/trigger`). Sigue el
  patrón vigente del archivo (`_require_admin`, CSRF contra `request.session`), con imports locales de
  `core.services.cromo.*` y `db.*` dentro de cada función, como el resto del archivo. También los
  endpoints del verificador (`/api/infra/cromo/{cables,tubos,botellas}/{n_id}/servicios` — el de
  botella agrega `cables: [{n_id, nombre, cantidad_servicios}]` desde 2026-08-18), del
  inventario (`GET /api/infra/cromo/cables`, con `q`/`jerarquia`/`propietario`/`vigente`/`n_id`/
  `botella`/`servicio`/`limit`/`offset`, los 3 últimos agregados en la Etapa 9) y del detalle
  jerárquico (`GET /api/infra/cromo/cables/{n_id}/detalle`, Etapa 9), todos con `_require_auth` en vez
  de `_require_admin` — son consulta, no administración.
- `web/frontend/src/api/cromo.ts`: cliente API del SPA (wrappers sobre `request`/`requestJson` de
  `src/api/client.ts`) + catálogo estático de clases botella (mismo seed que la migración) + funciones
  del verificador (`verificarServiciosPor{Cable,Tubo,Botella}`, con `CromoVerificacionBotella.cables:
  CromoCableDeBotella[]` desde 2026-08-18) + funciones del scheduler del worker
  (`obtenerConfigSchedulerCromo`, `guardarConfigSchedulerCromo`, `obtenerSaludWorkerCromo`,
  `dispararSchedulerCromo`) + `buscarInventarioCables` (Etapa 8b, filtros `nId`/`botella`/`servicio`
  agregados en Etapa 9) + `obtenerDetalleCable` (Etapa 9, detalle jerárquico) +
  `obtenerEmpalmesDeBotella` (empalmes/fusiones internas de una botella, consumida por
  `EmpalmesBotellaCromoView.vue`).
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
  `router/index.ts` y con su entrada de navegación en `AppShell.vue` (grupo "Tool Kit"). Desde la
  Etapa 9 también lee `route.query.tipo`/`route.query.n_id` en `onMounted` y dispara la búsqueda
  automáticamente si vienen presentes — es el destino de la navegación cruzada desde el detalle de un
  cable (click en una Botella extremo). Desde 2026-08-18, cuando `tipo === 'botella'` el resultado
  agrega una tarjeta "Cables asociados" (tabla minimalista ID/Nombre de Cable/Servicios Asociados,
  mismo patrón accesible `role="button"` + `tabindex` + `@keydown.enter` que
  `InventarioCablesCromoView.vue`) cuyo click navega con `router.push` directo al detalle jerárquico
  dedicado del cable (`/infra/cromo/cables/ID<n_id>`, `CableDetalleCromoView.vue`) — no se queda en
  este Verificador con `tipo=cable`, porque esa tarjeta sólo expone servicios, no tubos/pelos (primer
  intento, corregido el mismo día: hacía `router.push({ query: { tipo: 'cable', n_id } })` para
  quedarse en la misma vista; se descartó porque el detalle real de un cable — tubos/buffers/pelos —
  sólo existe en `CableDetalleCromoView.vue`, no en esta tarjeta de servicios). Cuando
  `tipo === 'botella'` también agrega una tarjeta "Empalmes" (sólo un link, sin tabla propia acá) que
  navega con `router.push` a la vista dedicada `EmpalmesBotellaCromoView.vue`
  (`/infra/cromo/verificador/empalmes?tipo=botella&n_id=<n_id>`).
- `web/frontend/src/views/InventarioCablesCromoView.vue` (Etapa 8b): inventario navegable en
  `/infra/cromo/cables` — buscador (nombre/jerarquía/propietario/vigente, + Id de cable/Botella/
  Servicio desde la Etapa 9) + paginación. Cada fila es clickeable (Etapa 9) y navega a la vista de
  detalle dedicada. Vista del panel operativo, mismo criterio de auth que el verificador. Registrada
  en `router/index.ts`; su entrada de navegación en `AppShell.vue` vive desde la Etapa 9 en el grupo
  "Infraestructura FO" (antes "Tool Kit", junto al Verificador — se separaron a pedido explícito).
- `web/frontend/src/views/CableDetalleCromoView.vue` (Etapa 9, reemplaza el modal inicial de la misma
  etapa): vista dedicada en `/infra/cromo/cables/ID:nId` — metadata del cable, extremos (clickeables →
  Verificador Cromo precargado) y un acordeón de Buffers/tubos (reusa `AccordionItem.vue`, patrón
  single-open) con la tabla de Pelos de cada uno (número, color, tipo de asociación, **descripción
  cruda** `servicio_raw` — siempre visible, incluso sin match resuelto — y servicio matcheado
  clickeable → `/servicios/ID/...`). Mismo patrón de página dedicada que `CamaraDetailView.vue`
  (hero + back-link, no modal): un cable con 24 tubos no cabe cómodo en un `<dialog>`, y el pedido
  explícito fue que el detalle sea una vista propia, navegable con URL directa
  (`/infra/cromo/cables/ID<n_id>`), no un panel superpuesto.
- `web/frontend/src/views/EmpalmesBotellaCromoView.vue`: vista dedicada en
  `/infra/cromo/verificador/empalmes?tipo=botella&n_id=<n_id>` — tabla de empalmes (fusiones) internos
  de una Botella, filtrable por un `<select>` "Cable Origen" (por defecto el primer cable con datos),
  con orden/buffer/color de pelo mostrados como código literal de Cromo (sin mapeo a hex, ej. "AZ",
  "NR", "AZ-R" tal cual vienen en `cromo_pelos.color`/`cromo_tubos.nombre_color`) y las filas de tipo
  Splitter agrupadas en una sola fila por pelo de origen ("Splitter 1-N", con el detalle de cada pata
  en `splitter_destinos`). Mismo patrón de página dedicada (hero + back-link) que
  `CableDetalleCromoView.vue`. Consume `obtenerEmpalmesDeBotella` (`src/api/cromo.ts`) contra
  `GET /api/infra/cromo/botellas/{n_id}/empalmes`. Punto de entrada: la tarjeta "Empalmes" del
  detalle de Botella en `VerificadorCromoView.vue` (sólo redirige, no trae datos ahí).
- Los nombres de extremo (`extremo_a`/`extremo_b`) que muestran `InventarioCablesCromoView.vue`,
  `CableDetalleCromoView.vue` y `VerificadorCromoView.vue` se resuelven en `core/services/cromo/
  {inventario,detalle,verificador}.py` vía `LEFT JOIN` a `cromo_botellas` (Etapa 9c) — no desde las
  columnas crudas `cromo_cables.extremo_a_nombre`/`extremo_b_nombre` (Cromo nunca manda un atributo
  separado para el extremo B, ver §13.10 de la doc privada).

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
