# Nombre de archivo: 2026-09-23-correccion-ingresos-y-servicios-por-cable-design.md
# Ubicación de archivo: docs/superpowers/specs/2026-09-23-correccion-ingresos-y-servicios-por-cable-design.md
# Descripción: Diseño de la corrección manual de ingresos/egresos por hilo de Slack y de los comandos "Servicios <cable>" con frescura PROV — los 7 entregables acordados con el usuario

# Corrección manual de ingresos/egresos por hilo Slack + `Servicios <cable>` con frescura PROV — Design

> Documento retrospectivo: las 10 tareas de implementación (`docs/superpowers/plans/2026-09-23-correccion-ingresos-servicios.md`)
> ya están mergeadas en esta rama al momento de escribir esto. Este spec fija, para quien
> mantenga o extienda el feature, los 7 entregables acordados con el usuario antes de arrancar:
> inventario con archivos/símbolos, decisiones de producto separadas de las técnicas, el diseño
> tal como quedó construido, el esquema de datos y sus tres migraciones, los contratos de comandos
> y APIs con ejemplos reales, el plan incremental y de pruebas ejecutado, y los riesgos/medidas de
> seguridad-operación — incluidas las limitaciones conocidas, documentadas y no escondidas.

## Contexto

Dos necesidades reales, verificadas contra `lasfocasdev-postgres` y contra el código, no supuestas:

**1. Un ingreso técnico mal registrado no se podía corregir.** Si el técnico tipeó mal el nombre de
la cámara, o el formulario de egreso nunca llegó, la fila quedaba abierta para siempre.
`protection_service.py:736` y `camara_estado_service.py:191` leen `Ingreso.fecha_fin IS NULL` para
decidir que una cámara está `OCUPADA`, y una cámara `OCUPADA` fantasma bloquea operaciones de
baneo. El único mecanismo de corrección era "Revalidar ingreso", que sólo sirve cuando existe una
fila `IngresoSinMatch` pendiente (la búsqueda falló). Un ingreso que matcheó bien pero con la
cámara equivocada no tenía ninguna vía de corrección.

**2. El técnico necesita los IDs de servicio de un cable, únicos y vigentes.** Dos cosas lo
impedían:

- *Los IDs se repetían.* Un servicio puede ocupar varios pelos de FO del mismo cable — eso es
  **normal y esperado**, no un defecto —, así que una consulta por pelo lo devuelve una vez por
  pelo. Medido en dev: en el 29,6% de los pares (cable, servicio) el servicio ocupa más de un pelo
  de ese cable (28.517 de 96.395); en botellas trepa al 41,3% (33.601 de 81.351, extremo A).
  *(Cifras corregidas en el fix round 2 de esta tarea: la medición original no filtraba
  `servicio_id IS NOT NULL` y contaba pares con un match sin resolver a un servicio real — un
  `servicio_id` `NULL` no es un servicio.)* El cable `FO-FL-1003` (n_id 6610203) tiene 141 filas
  pelo↔servicio para **118 IDs distintos**.
- *El ID mostrado podía no ser el vigente, y no había forma de saberlo.* En el 18,9% de los pares
  (pelo, servicio) el número escrito en el pelo de Cromo difiere del `servicios.servicio_id`
  vigente (25.203 de 133.173) — la descripción del pelo conserva el ID viejo de la cadena de
  upgrades. Y `app.servicios` **no tiene ninguna columna de timestamp** (20 columnas, ninguna de
  fecha, medido real) — era imposible saber si una fila fue validada contra PROV alguna vez. El
  92,5% de los servicios alcanzables por cable nunca pasó por PROV (8.401 de 9.079).

**Resultado construido:** comandos `Forzar ingreso` / `Forzar egreso` en el hilo del formulario, con
auditoría inmutable; comandos `Servicios <cable>` y `Servicios <cable> B<N>` que devuelven IDs de
servicio únicos y validados contra PROV (con refresco asíncrono on-demand); y las APIs REST
equivalentes para la SPA.

---

## (a) Inventario de la implementación actual — archivos y símbolos

### Task 1 — Consulta de servicios únicos por cable/tubo

`core/services/cromo/verificador.py` (sólo agregados, `ServicioEncontrado` y las 4 consultas
existentes intactas):

- `ServicioUnico` (dataclass): `servicio_id`, `servicio_id_externo`, `numero_primer_servicio`,
  `nombre_cliente`, `cliente`, `estado_servicio`, `tipo_servicio`, `pelos_n_ids: list[int]`,
  `cantidad_pelos`, `numeros_en_pelo: list[str]` (plural — un mismo servicio puede tener dos
  `servicio_numero` distintos en dos pelos), `metodos: list[str]`.
- `ResultadoServiciosUnicos` (dataclass): `cable_n_id: int | None`, `tubo_n_id: int | None` (uno de
  los dos, según el eje consultado), `servicios: list[ServicioUnico]`.
- `servicios_unicos_por_cable(sesion, cable_n_id)` / `_por_tubo(sesion, tubo_n_id)` (`AsyncSession`)
  y sus gemelas `_sync` (`Session`, para el listener de Slack). Un solo `GROUP BY s.id` con
  `array_agg(DISTINCT ...)`, sin re-join.
- `ObjetoNoEncontrado` (excepción ya existente, reusada): criterio tolerante a referencias colgadas.

### Task 2 — Migración y modelos de corrección de ingresos

- `db/alembic/versions/20260923_01_ingresos_correcciones.py`.
- `db/models/infra.py`: `IngresoCorreccion` (tabla nueva) + `Ingreso.thread_ts`/`Ingreso.canal_id`
  (columnas nuevas, nullable).

### Task 3 — Persistir `thread_ts`/`canal_id` en el flujo en vivo

- `core/services/ingreso_service.py`: `registrar_movimiento_ingreso` y
  `registrar_intento_bloqueado` ganan kwargs opcionales `thread_ts`/`canal_id`.
- `modules/slack_baneo_notifier/listener.py`: `_registrar_movimiento_si_corresponde`,
  `_construir_respuesta_camara`, `_procesar_revalidacion_ingreso` propagan ambos campos.

### Task 4 — Parser puro de `Forzar ingreso`/`Forzar egreso`

`modules/slack_baneo_notifier/correccion_ingreso.py` (nuevo, sin DB ni Slack):

- Regexes: `_RE_FORZAR_INGRESO_CON_FECHA`/`_SIN_FECHA`, `_RE_FORZAR_EGRESO_POR_ID`/
  `_CON_FECHA`/`_BARE`, `_RE_MOMENTO_SOLO`.
- `ComandoForzarIngreso`/`ComandoForzarEgreso` (dataclasses), `IngresoAbiertoInfo`,
  `MomentoInvalidoError` (`razon` en `{"formato", "futuro", "fuera_de_rango"}`).
- `parsear_momento_ar(fecha_str, hora_str, *, ahora=None)`, `extraer_momento_solo`.
- 13 constructores `construir_respuesta_*` (10 del brief original + 3 agregados en la Task 5:
  `construir_respuesta_camara_no_encontrada`, `_ingreso_no_encontrado`, `_sin_ingreso_abierto`).
- `modules/slack_baneo_notifier/cable_info.py`: `_quitar_formato_slack` promovida a pública
  (`quitar_formato_slack`).

### Task 5 — Servicio de corrección con resolución de hilo en cascada

`core/services/ingreso_correccion_service.py` (nuevo, ~800 líneas):

- Entry point: `procesar_comando_correccion(session, *, texto, actor_slack_user_id, canal_id,
  mensaje_ts, thread_ts=None, client=None, momento_explicito=None, ahora=None) ->
  ResultadoCorreccion | None`. `None` si el texto no es ninguno de los dos comandos.
- `ResultadoCorreccion` (dataclass): `resultado`, `respuesta`, `comando`, `ingreso: Ingreso | None`,
  `auditoria: IngresoCorreccion | None`.
- `resolver_contexto_hilo(session, client, *, thread_ts, canal_id) -> ContextoHilo` (público) —
  cascada de 3 niveles (`Ingreso.thread_ts` → `IngresoSinMatch.thread_ts` →
  `client.conversations_replies`), dedupeada por `camara_id`.
- Constantes: `COMANDO_FORZAR_INGRESO`/`_EGRESO`, `FUENTE_MOMENTO_HILO`/`_EXPLICITO`, y 14
  `RESULTADO_*` (ver sección de contratos).
- `core/services/ingreso_service.py`: `cerrar_ingreso_forzado(session, *, ingreso, momento)` nueva
  — cierra exactamente la fila que el caller ya resolvió, sin reseleccionar por heurística.

### Task 6 — Wiring en el listener y flujo de fecha pendiente

`modules/slack_baneo_notifier/listener.py`:

- `_procesar_correccion_ingreso` (nuevo) — enganchado en `_handle_message`, dentro del bloque
  `if event_thread_ts and event_thread_ts != event_ts:`, después de
  `_procesar_seguimiento_empalme`/`_procesar_revalidacion_ingreso` y antes del filtro
  `solo_workflows`.
- `_procesar_fecha_pendiente_seguimiento`, `_pendiente_fecha_vigente` (guard de 30 min, última fila
  del hilo por `created_at DESC`), `_responder_error_correccion`.
- Constante `_VENTANA_PENDIENTE_FECHA = timedelta(minutes=30)`.

### Task 7 — Tabla de sincronización PROV y su escritura

- `db/alembic/versions/20260923_02_servicios_sync_prov.py` (+ `20260923_03`, ver Task 9).
- `db/models/infra.py`: `ServicioSyncProv` + `Servicio.sync_prov` (relación 1-a-1).
- `core/services/prov/ingesta.py::ingerir_contexto_prov` — upsert agregado al final (único embudo).
- `core/services/prov/frescura.py` (nuevo): `servicios_vencidos`/`_sync` (batch), `horas_frescura()`
  (lee `PROV_FRESCURA_HORAS`, default 48).

### Task 8 — Comandos `Servicios <cable>` / `Servicios <cable> B<N>`

`modules/slack_baneo_notifier/cable_info.py`:

- `_RE_SERVICIOS_BUFFER`/`_RE_SERVICIOS_CABLE`, `extraer_comando_servicios_buffer`/`_cable`.
- `_agrupar_servicios_por_buffer` (2 queries batch sobre todo el cable, sin N+1).
- `construir_respuesta_servicios_cable`/`_buffer`.
- `_describir_pelo`/`construir_respuesta_info_buffer` ganan el parámetro opcional
  `vencidos: set[int] | None = None` (marcador `🕒`).

`modules/slack_baneo_notifier/listener.py`: `_handle_servicios_cable`/`_handle_servicios_buffer`,
dispatch en `_handle_app_mention`.

### Task 9 — Refresco PROV asíncrono + credenciales del worker

- `modules/slack_baneo_notifier/refresco_prov.py` (nuevo): `refrescar_servicios_vencidos`
  (fire-and-forget), `_priorizar_por_antiguedad`, `_refrescar_un_servicio`,
  `_persistir_intento_fallido`, `TOPE_SERVICIOS_POR_COMANDO=25`, `CONCURRENCIA_MAXIMA=3`
  (`Semaphore`), `DEADLINE_SEGUNDOS=120`, candado de proceso `_cables_en_refresco: set[int]`.
- `modules/slack_baneo_notifier/worker.py`: captura `asyncio.get_running_loop()` en `_main_loop` y
  lo pasa a `IngresoListener(loop=...)`.
- `modules/slack_baneo_notifier/listener.py`: `_disparar_refresco_prov` (encola con
  `asyncio.run_coroutine_threadsafe`, nunca espera el resultado).
- `deploy/docker-compose.dev.yml` / `deploy/compose.yml`: `api_prov_user_v1`/`api_prov_pass_v1`
  agregados a `secrets:` de `slack_baneo_worker`.
- `db/alembic/versions/20260923_03_servicios_sync_prov_nullable.py` (fix de revisión: NULL en vez
  de centinela `1970-01-01` para un intento fallido sin éxito previo).

### Task 10 — APIs REST

`web/app/main.py` (sólo agregados, sección después de
`/api/infra/cromo/botellas/{n_id}/servicios`):

- 4 rutas: `GET .../cables/resolver`, `GET .../cables/{id}/servicios-unicos`,
  `GET .../cables/{id}/buffers/{numero}/servicios-unicos`,
  `POST .../cables/{id}/servicios-unicos/refrescar-prov`.
- 12 modelos Pydantic (7 de respuesta + 5 de error, sólo para `/docs` — los handlers siguen
  devolviendo `JSONResponse` a mano).
- Helpers: `_frescura_por_servicio`, `_identidad_cable`, `_resolver_cable_por_texto`,
  `_resolver_buffer_por_numero`, `_ejecutar_refresco_prov_lote` (orquestación propia, reusa
  `_priorizar_por_antiguedad`/`_refrescar_un_servicio` de la Task 9 pero no
  `refrescar_servicios_vencidos` — ver sección (c)).

`web/frontend/src/api/cromo.ts`: 7 interfaces + 4 funciones
(`obtenerServiciosUnicosPorCable`/`_Buffer`, `resolverCable`, `refrescarServiciosUnicosProv`).

---

## (b) Decisiones de producto/operación vs. decisiones técnicas

Separadas a propósito: las primeras las tomó o confirmó el usuario y sólo él las revierte; las
segundas son elección de implementación y se pueden cambiar sin volver a preguntar.

### Decisiones de producto/operación (tomadas o confirmadas con el usuario)

1. **Sin allowlist.** Cualquiera del canal puede ejecutar `Forzar ingreso`/`Forzar egreso`. La
   auditoría inmutable (`app.ingresos_correcciones`) es el único control, y el bot publica en el
   hilo quién ejecutó qué (`actor_nombre` en cada respuesta OK).
2. **Un operador puede cerrar el ingreso abierto de otro técnico.** Con 2+ candidatos, el bot los
   lista (`id`/técnico/`fecha_inicio`) y exige `Forzar egreso #<id>` — nunca adivina.
3. **Sin `motivo` obligatorio.** El campo existe en la auditoría (`Text NULL`) pero no hay palabra
   clave que lo capture salvo cuando hay un delimitador natural (después de la fecha, después del
   `#<id>`).
4. **`Forzar ingreso` sobre un grupo hoy baneado registra un INGRESO real**, nunca
   `INTENTO_BLOQUEADO`: el operador afirma que el técnico entró, y el baneo de *ahora* no es
   evidencia sobre el pasado. Ver `docs/decisiones.md`, entrada 2026-09-23.
5. **Los comandos funcionan sólo dentro de un hilo**, no como mensaje raíz — pedido explícito del
   usuario: ancla la auditoría al formulario original (Ingreso/Egreso/IngresoSinMatch) que generó
   ese hilo. Ver `docs/decisiones.md`.
6. **El comando nuevo responde de inmediato con el dato Cromo** y publica un segundo mensaje en el
   hilo cuando termina el refresco PROV — nunca hace esperar al técnico por la llamada de red.
7. **Consulta nueva de servicios únicos, sin modificar las cuatro existentes.** Varios pelos por
   servicio es **normal** (un servicio puede ocupar 1, 2 o más pelos de FO), no un defecto. La
   vista por-pelo del Verificador es correcta para su propósito (columna "Pelo" por fila); la vista
   por-ID única es otra vista legítima, con otro propósito. Conviven — `Servicios <cable> B<N>` no
   reemplaza a `Verificar cable <cable> B<N>`.
8. **Backfill PROV (`scripts/servicios_backfill_prov.py`) es prerrequisito de despliegue, no una
   mejora opcional.** El 92,5% de los servicios nunca pasó por PROV; sin el backfill, todo cuenta
   como vencido y cada comando choca contra el tope de 25 durante meses.
9. **Las credenciales PROV se montan en el worker Slack** (no se delega a `api` por HTTP) — el
   refresco corre en el mismo proceso que ya tiene Socket Mode abierto.

### Decisiones técnicas (elección de implementación)

1. **Tabla nueva `ingresos_correcciones`, no extensión de `IngresoSinMatch`.** Esa tabla modela "el
   nombre no matcheó" (subconjunto de casos) y sus filas *se mutan*
   (`resuelto_via_empalme`/`resuelto_via_revalidacion`) — semántica opuesta a un log inmutable. Una
   corrección puede ocurrir en un hilo que matcheó perfecto.
2. **Trigger de inmutabilidad a nivel de DB** (`BEFORE UPDATE OR DELETE ... RAISE EXCEPTION`), no
   sólo una convención de código: la diferencia entre una promesa de docstring (violable por
   cualquier script one-off) y una garantía real.
3. **Cascada de resolución de hilo en 3 niveles** (`Ingreso.thread_ts` → `IngresoSinMatch.thread_ts`
   → `client.conversations_replies`), en vez de exigir siempre el `thread_ts` propio: cubre los
   hilos históricos anteriores a la migración `20260923_01`. El momento del hilo sale del propio
   `thread_ts` (que en Slack *es* el `ts` del mensaje raíz), no de `IngresoSinMatch.created_at`
   (cuándo el listener procesó el mensaje, no cuándo se envió).
4. **`servicios_sync_prov` como tabla y no columna en `app.servicios`**: esa tabla no tiene ni un
   solo timestamp, la escriben tres ingestas distintas que re-etiquetan `origen_datos`
   incondicionalmente, y el estado de *fallo* no pertenece a la fila de dominio.
5. **`GROUP BY s.id` de una sola pasada**, sin CTE ni re-join: el índice único de
   `cromo_servicio_match` es `(pelo_n_id, servicio_numero)`, no `(pelo_n_id, servicio_id)` — hay 85
   pares con dos filas (el pelo menciona el ID viejo y el nuevo del mismo servicio); un re-join
   multiplicaría esas filas.
6. **Refresco encolado con `asyncio.run_coroutine_threadsafe`**, nunca esperado: el listener de
   Slack corre en un thread daemon aparte del loop asyncio del worker; encolar y no esperar es lo
   que permite responder al técnico de inmediato.
7. **Orden de prioridad del tope de 25 por `ultimo_intento`, no por `ultima_sincronizacion_ok`**: un
   servicio que PROV nunca puede resolver quedaría con la fecha de éxito fija en el pasado para
   siempre, ganando indefinidamente el primer lugar de la cola y desplazando a los que sí se
   podrían refrescar.
8. **`NULL` en vez de centinela `1970-01-01`** para "nunca sincronizó con éxito" (migración
   `20260923_03`, fix de revisión sobre la Task 9): la consulta de frescura ya trata `NULL` como
   vencido; un centinela era un segundo encoding del mismo estado, y obligaba a cualquier
   consumidor futuro a importar una constante privada del módulo de Slack.
9. **Las rutas REST en `web/app/main.py` y no en `api/app/routes/`**: precedente ya escrito dos
   veces en `docs/decisiones.md` (2026-08-19 y 2026-08-22) — `api/app/` es API-key
   máquina-a-máquina sin concepto de rol, no usable desde el navegador; el 100% de los endpoints
   Cromo vive en `web/app/main.py` con `_require_auth`.
10. **El POST de refresco REST no reusa `refrescar_servicios_vencidos` tal cual**: esa función es
    fire-and-forget y exige `client`/`channel`/`thread_ts` de Slack — la ruta REST necesita el
    resultado real dentro del mismo request. Reusa sólo las piezas agnósticas de Slack
    (`_priorizar_por_antiguedad`/`_refrescar_un_servicio`) en `_ejecutar_refresco_prov_lote`.

---

## (c) Diseño recomendado (tal como quedó construido)

### Flujo de `Forzar ingreso` / `Forzar egreso`

```
mensaje en un hilo (respuesta, nunca raíz)
  │
  ├─ ¿matchea la gramática de Forzar ingreso/egreso? (correccion_ingreso.py, puro)
  │     no → sigue el flujo normal del listener (empalme / revalidación / búsqueda de cámara)
  │     sí ↓
  │
  ├─ resolver_contexto_hilo(thread_ts)                              [Task 5, cascada 3 niveles]
  │     nivel 1: Ingreso.thread_ts (sin red)
  │     nivel 2: IngresoSinMatch.thread_ts (sin red, siempre se consulta también)
  │     nivel 3: client.conversations_replies (requiere channels:history)
  │     ninguno → RESULTADO_HILO_SIN_FORMULARIO (pide cámara + fecha explícitas)
  │
  ├─ resolver cámara/botella (buscar_camara_o_botella_cromo)
  │     no encontrada → RESULTADO_CAMARA_NO_ENCONTRADA
  │     ambigua       → RESULTADO_CAMARA_AMBIGUA (lista candidatos)
  │
  ├─ _resolver_momento(ctx.tipo, comando, fecha_explicita)           [tabla del momento implícito]
  │     tipo hilo == tipo forzado           → momento = ts del hilo
  │     tipo hilo != tipo forzado, sin fecha → RESULTADO_PENDIENTE_FECHA (estado, no rechazo)
  │     fecha explícita presente            → gana siempre
  │
  ├─ (sólo Forzar egreso) resolver conjunto de INGRESO abiertos de la cámara
  │     0 candidatos → sólo cámara+fecha explícitas asienta (OK_EGRESO_ASENTADO);
  │                     el resto → SIN_INGRESO_ABIERTO
  │     1 candidato  → cerrar_ingreso_forzado → OK_EGRESO_CERRADO
  │     2+           → VARIOS_INGRESOS_ABIERTOS (exige #<id>)
  │
  └─ _finalizar: escribe SIEMPRE una fila en ingresos_correcciones (incluidos los rechazos)
        + marca IngresoSinMatch.resuelto_via_revalidacion si corresponde
        + responde en el hilo con el texto ya armado (correccion_ingreso.py)

Respuesta de seguimiento "sólo DD-MM-AAAA HH:MM" (fecha pendiente):
  ¿hay PENDIENTE_FECHA vigente (< 30 min) para este thread_ts, sin fila terminal posterior?
    sí → re-ejecuta procesar_comando_correccion(comando_crudo original, momento_explicito=fecha)
         (escribe una fila NUEVA — la tabla es append-only, nunca muta la PENDIENTE_FECHA)
    no → se ignora en silencio (puede ser cualquier texto sin relación)
```

### Flujo de `Servicios <cable>` / `Servicios <cable> B<N>`

```
@bot Servicios <cable> [B<N>]
  │
  ├─ resolver cable (buscar_cable_por_n_id_o_nombre) / buffer (resolver_tubo_por_numero)
  │     0 o 2+ matches → mismo criterio que "Info cable"/"Verificar cable"
  │
  ├─ servicios_unicos_por_cable_sync / _por_tubo_sync (Task 1)      → IDs únicos, agrupados
  ├─ servicios_vencidos_sync (Task 7, batch)                        → cuáles están vencidos
  ├─ construir_respuesta_servicios_cable/_buffer                    → primer mensaje inmediato
  │     (IDs por buffer + discrepancias "en el pelo figura otro número" + conteo de vencidos)
  │
  └─ _disparar_refresco_prov (si hay vencidos, hay loop, PROV configurado)
        encola refrescar_servicios_vencidos vía run_coroutine_threadsafe (fire-and-forget)
        └─ segundo chat_postMessage en el mismo hilo cuando termina:
              éxitos/fallidos nominales, motivo de cada fallo, candado por cable_n_id
```

### Equivalente REST (Task 10)

```
GET  /api/infra/cromo/cables/resolver?q=<n_id|nombre>
GET  /api/infra/cromo/cables/{cable_n_id}/servicios-unicos
GET  /api/infra/cromo/cables/{cable_n_id}/buffers/{numero}/servicios-unicos
POST /api/infra/cromo/cables/{cable_n_id}/servicios-unicos/refrescar-prov   (CSRF)
```

Los 2 GET de servicios únicos son de sólo lectura (`refresco_prov.estado = "no_solicitado"`); el
POST awaitea el lote dentro del propio request (no hay hilo de Slack al que postear un segundo
mensaje) y devuelve el resultado real en la misma respuesta HTTP.

---

## (d) Esquema de datos y migraciones

### Columnas nuevas en `app.ingresos` (migración `20260923_01`)

| Columna | Tipo | Nullable | Descripción |
|---|---|---|---|
| `thread_ts` | `VARCHAR(32)` | sí (indexada `ix_ingresos_thread_ts`) | `ts` del hilo de Slack donde se originó el movimiento. Vacía en filas anteriores a esta migración. |
| `canal_id` | `VARCHAR(32)` | sí | Canal de Slack del movimiento. |

En el camino "Egreso" que **cierra** una fila `Ingreso` existente, estos dos campos **no se pisan**
— conservan los del ingreso original (la Task 5 los necesita intactos para poder ubicar el hilo
desde la fila).

### Tabla `app.ingresos_correcciones` (append-only, migración `20260923_01`)

| Columna | Tipo | Nullable | Descripción |
|---|---|---|---|
| `id` | Integer (PK) | no | — |
| `comando` | `String(32)` | no | `FORZAR_INGRESO` \| `FORZAR_EGRESO`. |
| `actor_slack_user_id` | `String(32)` | no | Quién ejecutó el comando (siempre se conoce). |
| `actor_nombre` | `String(255)` | sí | Nombre resuelto — puede no resolverse, mismo criterio que `Ingreso.tecnico_id`. |
| `canal_id` | `String(32)` | no | — |
| `thread_ts` | `String(32)` | sí (indexada) | `NULL` si el comando no fue una respuesta en un hilo. |
| `mensaje_ts` | `String(32)` | no | `ts` del mensaje del comando en sí. |
| `comando_crudo` | `Text` | no | Texto íntegro del comando — lo re-lee el flujo de fecha pendiente. |
| `motivo` | `Text` | sí | Sin palabra clave obligatoria (decisión de producto). |
| `camara_texto_solicitado` | `String(512)` | no | Nunca cadena vacía — `"(del hilo)"` en la forma bare, `"#<id>"` en la forma por id, `"(no parseado)"` si murió antes de tener nombre. |
| `camara_id_resuelta` | FK → `app.camaras.id`, `ON DELETE SET NULL` | sí | — |
| `cromo_botella_id_resuelta` | `BigInteger`, FK → `app.cromo_botellas.n_id`, `ON DELETE SET NULL` | sí | — |
| `momento_solicitado` / `momento_efectivo` | `timestamptz` | sí | `NULL` en el estado `PENDIENTE_FECHA` (todavía no hay fecha resuelta). |
| `fuente_momento` | `String(16)` | sí | `hilo` \| `explicito`. |
| `ingreso_id` | FK → `app.ingresos.id`, `ON DELETE SET NULL` | sí | Sólo si la corrección creó/cerró un `Ingreso` real. |
| `resultado` | `String(64)` | no | Ver los 14 valores en la sección de contratos. |
| `error_detalle` | `Text` | sí | — |
| `created_at` | `timestamptz` | no (indexada) | — |

Índices adicionales sobre las 3 FKs (Postgres no las indexa automáticamente). `comando`/
`resultado`/`fuente_momento` son `String`, no enum de Postgres: sus valores crecieron durante las
Tasks 5 y 6 (`resultado` terminó con 14), y un enum hubiera exigido una migración `ALTER TYPE ADD
VALUE` por cada uno.

**Trigger de inmutabilidad**: función `app.ingresos_correcciones_bloquear_mutacion()` +
`trg_ingresos_correcciones_inmutable` (`BEFORE UPDATE OR DELETE ... FOR EACH ROW`), `RAISE
EXCEPTION` ante cualquier intento. Verificado real contra `lasfocasdev-postgres`: un `UPDATE`/
`DELETE` de prueba sobre una fila insertada a mano dieron `exit code 1` con el mensaje `"app.
ingresos_correcciones es append-only: UPDATE/DELETE sobre id=1 está prohibido (log de auditoría
inmutable)"`.

### Tabla `app.servicios_sync_prov` (migraciones `20260923_02` + `20260923_03`)

| Columna | Tipo | Nullable (estado final, post `_03`) | Descripción |
|---|---|---|---|
| `id` | Integer (PK) | no | — |
| `servicio_id` | Integer, FK → `app.servicios.id`, `ON DELETE CASCADE`, **UNIQUE** | no | Una fila por Servicio. |
| `ultima_sincronizacion_ok` | `timestamptz` | **sí** (era `NOT NULL` en `_02`, revertido en `_03`) | Momento del último refresco EXITOSO. `NULL` = nunca sincronizó con éxito. |
| `ultimo_intento` | `timestamptz` | sí | Momento del último intento, exitoso o no — usado para priorizar el tope de 25. |
| `ultimo_error` | `Text` | sí | Se limpia en cada éxito. |
| `nro_servicio_consultado` | `String(64)` | sí | Trazabilidad de auditoría. |
| `created_at` / `updated_at` | `timestamptz` | no | — |

Sin índice propio sobre `ultima_sincronizacion_ok`: la consulta de frescura siempre filtra primero
por `servicio_id = ANY(:ids)` (hasta ~118 por llamada), y el índice UNIQUE ya acota el trabajo.

### Historial de las 3 migraciones

| Revisión | Archivo | Descripción |
|---|---|---|
| `20260923_01` | `20260923_01_ingresos_correcciones.py` | Columnas `thread_ts`/`canal_id` en `app.ingresos` + tabla `app.ingresos_correcciones` con trigger de inmutabilidad. |
| `20260923_02` | `20260923_02_servicios_sync_prov.py` | Tabla `app.servicios_sync_prov` (`ultima_sincronizacion_ok NOT NULL` en esta versión). |
| `20260923_03` | `20260923_03_servicios_sync_prov_nullable.py` | `ALTER COLUMN ultima_sincronizacion_ok DROP NOT NULL` — fix de revisión de la Task 9 (ver decisión técnica 8 arriba). `downgrade()` restaura el `NOT NULL` y **fallaría** si para entonces hay filas con `NULL` (ver sección de riesgos). |

Las tres verificadas con `upgrade head → downgrade -1/-2 → upgrade head` real contra
`lasfocasdev-postgres` (comandos y salidas completos en los reportes de las Tasks 2/7/9 y en
`docs/PR/2026-09-24.md`).

---

## (e) Contratos de comandos y APIs, con ejemplos

### Gramática de `Forzar ingreso` / `Forzar egreso`

```
Forzar ingreso <CAMARA>
Forzar ingreso <CAMARA> DD-MM-AAAA HH:MM
Forzar egreso
Forzar egreso <CAMARA> DD-MM-AAAA HH:MM
Forzar egreso #<ingreso_id>
```

Sólo dentro de un hilo (respuesta, nunca mensaje raíz). El datetime va anclado al final con `.+?`
no-goloso (mismo patrón que `_RE_CABLE_BUFFER`); el nombre de cámara tolera negrita de Slack
(`*Cra Balcarce 302*`, saneado por `quitar_formato_slack`).

**Ejemplos de respuesta real** (constructores en `correccion_ingreso.py`):

```
✅ Ingreso forzado registrado en *Cra Mitre 440* — 20-09-2026 10:00. Ejecutado por *Juan Pérez*.

✅ Egreso forzado registrado en *Cra Mitre 440* (ingreso de *Juan Pérez*) — cierra el ingreso
abierto, 21-09-2026 08:30. Ejecutado por *María Gómez*.

⚠️ Para forzar un egreso en *Cra Mitre 440* hace falta la fecha y hora — reenviá el comando
completo (*Forzar egreso Cra Mitre 440 DD-MM-AAAA HH:MM*) o respondé en este mismo hilo sólo con
*DD-MM-AAAA HH:MM*.

⚠️ Hay *2* ingresos abiertos en *Cra Mitre 440* — elegí cuál cerrar con *Forzar egreso #<id>*:
• *#101* — Juan Pérez — ingresó 20-09-2026 10:00
• *#102* — técnico no identificado — ingresó 21-09-2026 07:15
```

**Los 14 valores de `IngresoCorreccion.resultado`** (constantes de
`core/services/ingreso_correccion_service.py`): `OK_INGRESO`, `OK_EGRESO_CERRADO`,
`OK_EGRESO_ASENTADO`, `CAMARA_AMBIGUA`, `CAMARA_NO_ENCONTRADA`, `VARIOS_INGRESOS_ABIERTOS`,
`SIN_INGRESO_ABIERTO`, `EGRESO_ANTERIOR_AL_INGRESO`, `INGRESO_YA_CERRADO`,
`INGRESO_NO_ENCONTRADO`, `HILO_SIN_FORMULARIO`, `MOMENTO_INVALIDO`, `ERROR_INTERNO`,
`PENDIENTE_FECHA` (estado, no rechazo — habilita la respuesta de seguimiento).

### Gramática de `Servicios <cable>`

```
Servicios <cable>
Servicios <cable> B<N>
```

**Ejemplo real** (`F-VFL-IND`, n_id 6613293, verificado contra `lasfocasdev-postgres`):

```
🧾 Servicios del cable *F-VFL-IND* — 28 ID(s) únicos
B1 (AZ): 61942, 106595, 108094, 62174, 62175, 67189, 106761
B2 (NR): 93150, 93154, 107487, 121274, 114228, 116370, 64932, 76923
...
⚠️ En el pelo figura otro número: 108875 (el pelo dice 108305)
🕒 28 con validación PROV vencida — refrescando…
```

Segundo mensaje (Task 9, cuando el refresco termina):

```
✅ Refresco PROV completado — 25 actualizados, 3 no se pudieron refrescar:
• 108305 — no encontrado en PROV
• 121274 — PROV respondió 500
• 64932 — se agotó el tiempo del lote antes de poder intentarlo
```

### APIs REST (`web/app/main.py`, `_require_auth` — cookie de sesión, no API-key)

**`GET /api/infra/cromo/cables/resolver?q=F-VFL-IND`** → `200`:
```json
{"n_id": 6613293, "nombre": "F-VFL-IND", "capacidad": "72-BRUG"}
```
`q` ambiguo (ej. `F-ALV-2335`, uno de los duplicados reales conocidos) → `409`:
```json
{"codigo": "AMBIGUO", "candidatos": [
  {"n_id": 9005904, "nombre": "F-ALV-2335", "capacidad": "72-BRUG"},
  {"n_id": 9006460, "nombre": "F-ALV-2335", "capacidad": "72-BRUG"}
]}
```
`q` sin match → `404 {"codigo": "NO_ENCONTRADO"}`.

**`GET /api/infra/cromo/cables/{cable_n_id}/servicios-unicos`** → `200`:
```json
{
  "cable_n_id": 6610203,
  "cable_nombre": "FO-FL-1003",
  "buffer": null,
  "datos_al": "2026-09-24T12:00:00+00:00",
  "servicios": [
    {
      "servicio_id": 4521, "servicio_id_externo": "108875",
      "numero_primer_servicio": "108305", "nombre_cliente": "...", "cliente": "...",
      "estado_servicio": "Activo", "tipo_servicio": "FO",
      "pelos_n_ids": [6848900], "cantidad_pelos": 1,
      "numeros_en_pelo": ["108305"], "metodos": ["descripcion"],
      "frescura": {"ultima_sincronizacion_prov": null, "antiguedad_horas": null, "vencida": true}
    }
  ],
  "refresco_prov": {"estado": "no_solicitado", "fallidos": []}
}
```
Cable no encontrado → `404 {"codigo": "NO_ENCONTRADO", "error": "..."}`.

**`GET .../buffers/{numero}/servicios-unicos`** → mismo cuerpo, con `buffer: {"numero": 1, "orden":
0, "nombre_color": "AZ"}`. Buffer fuera de rango → `404 {"codigo": "NO_ENCONTRADO",
"total_buffers": 6}`.

**`POST .../servicios-unicos/refrescar-prov`** (body `{"csrf_token": "..."}`) → mismo cuerpo que el
GET por cable, con `refresco_prov.estado` en `"sin_vencidos"` / `"completado"` / `"parcial"` (con
`fallidos` poblado). `403` si el CSRF es inválido; `502 {"error": "PROV no está configurado: ..."}`
si `ProvConfigError`.

Las 4 rutas dan `401` (no `404`) sin sesión — confirmado real contra `lasfocasdev-web`, es la
evidencia de que el wiring quedó registrado.

---

## (f) Plan incremental y de pruebas (ejecutado)

Orden de dependencias real (`docs/superpowers/plans/2026-09-23-correccion-ingresos-servicios.md`):

```
Task 1 (servicios únicos)  ─────────────────────────────┐
Task 2 (migración+modelos) → Task 3 (persistir hilo)     ├→ Task 8 (comandos Servicios) → Task 9 (refresco async)
                            → Task 4 (parser puro)        │        ↑ Task 7 (tabla sync PROV) ┘
                            → Task 5 (servicio corrección, dep. 2+3+4)
                            → Task 6 (wiring listener, dep. 5)
Task 1 + Task 7 ──────────────────────────────────────────→ Task 10 (APIs REST)
Todas ────────────────────────────────────────────────────→ Task 11 (esta documentación)
```

Cada tarea se ejecutó con `superpowers:subagent-driven-development`: implementación + tests +
verificación real contra `lasfocasdev-postgres`, seguida de una ronda de revisión de calidad que en
4 de las 10 tareas (4, 5, 6, 9, 10) encontró hallazgos reales corregidos con evidencia de
mutación (romper la regla a propósito, confirmar que el test correspondiente falla, restaurar).
Highlights de esas rondas:

- **Task 5**: dedup de `resolver_contexto_hilo` por `camara_id` (no por longitud de lista) —
  bug real que hacía `CAMARA_AMBIGUA` en vez de `VARIOS_INGRESOS_ABIERTOS` cuando dos ejecuciones
  de `Forzar ingreso` caían en la misma cámara del mismo hilo.
- **Task 6**: `_pendiente_fecha_vigente` cortaba de raíz en cuanto veía una fila terminal después de
  un `PENDIENTE_FECHA` ya visto, aunque hubiera uno más nuevo después — reproducido y corregido
  contra Postgres real con 3+ filas (ningún fixture mockeado los tenía).
- **Task 9**: 5 Important (excepción sin `except` de nivel superior, blindaje incompleto en
  `_disparar_refresco_prov`, centinela `1970` reemplazado por `NULL` — migración `20260923_03` —,
  candado sin aviso al segundo técnico, camino feliz sin cobertura).
- **Task 10**: `_ejecutar_refresco_prov_lote` sin test directo (los 6 tests del POST mockeaban la
  función entera) — 3 tests nuevos con mutación real (deadline, `return_exceptions`, motivo por
  servicio).

### Evolución de la suite

| Hito | passed | skipped |
|---|---|---|
| Baseline (antes de esta rama, `docs/PR/2026-09-21.md`) | 1806 | 5 |
| Tras Task 10 (fin de implementación) | 2040 | 5 |

Los 5 `skipped` constantes confirman que Postgres estuvo presente en cada corrida (sin DB serían
~90 y los tests de integración no correrían). `tests/test_cromo_worker.py::
test_build_trigger_con_hora_inicio_pasada_suma_un_intervalo` es un flake horario conocido y ajeno
(falla sólo entre 00:00 y 00:59 hora Argentina, documentado en `docs/decisiones.md` 2026-08-22) —
no cuenta contra este plan.

### Verificación de infraestructura, no sólo de tests unitarios

- Las 3 migraciones: `upgrade head → downgrade -1 → upgrade head` real contra
  `lasfocasdev-postgres`, más una prueba directa de que el trigger de `ingresos_correcciones`
  rechaza `UPDATE`/`DELETE`.
- Las 4 rutas REST: `401` (no `404`) sin sesión contra `lasfocasdev-web` reconstruido — confirma
  wiring real, no sólo que el módulo compile.
- Secrets PROV montados en `lasfocasdev-slack-baneo-worker` (`docker exec ... ls /run/secrets/`).
- Consulta de servicios únicos: contra el cable de control `FO-FL-1003` (n_id 6610203), 141 filas
  por-pelo → **exactamente 118** filas únicas, 0 `servicio_id` repetidos.
- `npx vue-tsc --noEmit` + `npm run build`: mismos 4 errores preexistentes de `InfraTab.vue`
  (ajenos a este plan), nada nuevo.
- **Producción nunca se tocó**: `lasfocas-*` sin reiniciar en todo el plan.

---

## (g) Riesgos y medidas de seguridad/operación

### Seguridad

- **Sin allowlist en los comandos de corrección** (decisión de producto): el control es la
  auditoría inmutable, no un permiso. Cualquier revisión de incidente parte de
  `app.ingresos_correcciones`, que nadie puede alterar retroactivamente (trigger de DB, no sólo
  código de aplicación).
- **CSRF real en el POST de refresco REST** — verificado con `csrf_token` inválido sobre una
  sesión autenticada real → `403`.
- **Secrets PROV montados sólo donde se usan** (`slack_baneo_worker`), nunca logueados
  (`ProvClient._get` ya logueaba `respuesta.text` en un 4xx antes de este plan — comportamiento
  preexistente, no una exposición nueva introducida acá).
- **`api/app/` no expone estas rutas**: quedan detrás de `_require_auth` (cookie de sesión), nunca
  accesibles con la API-key máquina-a-máquina.

### Limitaciones conocidas (documentadas, no escondidas)

1. **Ventana de carrera en el seguimiento de fecha pendiente** (Task 6). Socket Mode despacha con
   un `ThreadPoolExecutor` y cada evento abre su propia sesión, así que dos respuestas de fecha
   casi simultáneas en el mismo hilo pueden ejecutar el forzado dos veces. **Se demostró
   empíricamente contra Postgres real** que `SELECT ... FOR UPDATE` **no** cierra esta carrera: al
   desbloquearse, el segundo hilo sigue viendo la fila vieja como "la última" porque Postgres no
   re-evalúa el `ORDER BY`/`LIMIT` tras esperar el lock (comportamiento estándar de
   EvalPlanQual — el lock opera sobre la fila puntual, no relanza el plan completo). Mitigantes:
   la ventana es angosta (hay que responder dentro de los mismos segundos), y la auditoría
   append-only hace que una doble ejecución sea siempre detectable después del hecho (dos filas
   con `momento_explicito` idéntico y `created_at` casi iguales). Cerrar esto de verdad exigiría un
   advisory lock de sesión con ciclo de vida cuidado (o único punto de commit en el servicio de la
   Task 5, que hoy comitea en dos puntos) — fuera de alcance de este plan.
2. **El POST de refresco REST mantiene abierto el request hasta 120 s** (el `DEADLINE_SEGUNDOS` de
   la Task 9) **y no comparte el candado por-cable** (`_cables_en_refresco`, `set` de proceso
   privado del módulo de Slack) con el camino de Slack (Task 10): un POST REST y un comando de
   Slack simultáneos sobre el mismo cable disparan el lote dos veces. Sin corrupción de datos —
   cada refresco exitoso simplemente vuelve a escribir `ultima_sincronizacion_ok` — sólo llamadas
   duplicadas a PROV.
3. **No hay guard contra `Forzar ingreso` repetido**: dos técnicos en la misma cámara es legítimo,
   así que un guard genérico lo bloquearía. Una doble ejecución por error queda visible en la
   auditoría (dos filas `OK_INGRESO` de la misma cámara/hilo) y se corrige con un `Forzar egreso
   #<id>`.
4. **La escritura del movimiento y la de la auditoría no son atómicas** (dos transacciones
   distintas dentro de `_finalizar`): una caída del worker entre ambas deja una mutación sin
   rastro en `ingresos_correcciones`. Es estructural — arreglarlo exigiría cambiar el contrato de
   `registrar_movimiento_ingreso`/`cerrar_ingreso_forzado` para que compartan la transacción con la
   escritura de auditoría, fuera de alcance de este plan.
5. **El `downgrade()` de `20260923_03`** restaura el `NOT NULL` de `ultima_sincronizacion_ok` y
   **fallaría** si para entonces existen filas con `NULL` (el camino de intento fallido de la
   Task 9 las crea). Falla fuerte y atómica (el `ALTER COLUMN` completo revienta), nunca corrompe
   datos — pero un downgrade en un entorno con volumen real necesitaría un backfill previo que hoy
   no existe (la tabla tenía 0 filas en dev al migrar, y no existe en prod).
6. **`PROV_FRESCURA_HORAS`** (default 48) no está registrada en `.env.dev` ni en los compose —
   mismo criterio que su gemela `CROMO_TRACKING_CACHE_TTL_HORAS` (tampoco lo está). Ambas dependen
   del default de código; documentadas en `docs/bot.md`.

### Riesgo operativo (no de seguridad)

- **Backfill PROV como gate de despliegue**: anunciar `Servicios <cable>` antes de correr
  `scripts/servicios_backfill_prov.py --apply` deja el 100% de cualquier lote como vencido durante
  meses (el rate limiter de PROV no es distribuido, `docs/decisiones.md` 2026-09-02, Decisión 3) —
  el comando quedaría permanentemente saturado contra el tope de 25.
- **Producción sigue sin secrets/compose de PROV** salvo la corrección de esta entrada (ver
  `docs/decisiones.md`, corrección 2026-09-23/24 sobre la nota del 2026-09-02): los archivos de
  secret existen y `.env` tiene `PROV_BASE_URL`, pero no hay ventana de despliegue en el alcance de
  este plan — sigue en modo "solo dev" salvo aviso puntual del usuario.

---

## Referencias

- Plan de implementación: `docs/superpowers/plans/2026-09-23-correccion-ingresos-servicios.md`.
- Reportes de las 10 tareas:
  `.superpowers/sdd/2026-09-23-correccion-ingresos-servicios/task-{1..10}-report.md`.
- `docs/bot.md` — comandos de corrección, scope `channels:history`, backfill PROV.
- `docs/slack_app_cables.md` — comandos `Servicios`, coexistencia con `Verificar cable`.
- `docs/db.md` — tablas `ingresos_correcciones`/`servicios_sync_prov`, historial de migraciones.
- `docs/decisiones.md` — entradas 2026-09-23 (allowlist, tabla nueva, hilo, consulta nueva,
  `servicios_sync_prov`) y corrección de la nota 2026-09-02 sobre PROV en producción.
- `docs/PR/2026-09-24.md` — comandos ejecutados, impacto y riesgos del PR.
