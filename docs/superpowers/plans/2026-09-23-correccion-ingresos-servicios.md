# Nombre de archivo: 2026-09-23-correccion-ingresos-servicios.md
# Ubicación de archivo: docs/superpowers/plans/2026-09-23-correccion-ingresos-servicios.md
# Descripción: Plan de implementación tarea por tarea de la corrección manual de ingresos/egresos por hilo Slack y los comandos "Servicios <cable>" con frescura PROV

# Corrección manual de ingresos/egresos por hilo Slack + comando `Servicios` con frescura PROV — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: usar `superpowers:subagent-driven-development` para ejecutar este plan tarea por tarea. Los headings `### Task N:` son los que matchea el `task-brief` (`^#+[ \t]+Task[ \t]+[0-9]+`).

## Context

Dos necesidades reales, verificadas contra `lasfocasdev-postgres` y contra el código, no supuestas:

**1. Un ingreso técnico mal registrado no se puede corregir.** Si el técnico tipeó mal el nombre de la cámara, o el formulario de egreso nunca llegó, la fila queda abierta para siempre. Eso no es cosmético: `protection_service.py:736` y `camara_estado_service.py:191` leen `Ingreso.fecha_fin IS NULL` para decidir que una cámara está `OCUPADA`, y una cámara `OCUPADA` fantasma bloquea operaciones de baneo. Hoy el único mecanismo de corrección es "Revalidar ingreso", que sólo sirve cuando existe una fila `IngresoSinMatch` pendiente — es decir, cuando la búsqueda falló. Un ingreso que matcheó bien pero con la cámara equivocada no tiene ninguna vía de corrección.

**2. El técnico necesita los IDs de servicio de un cable, únicos y vigentes.** Dos cosas lo impiden hoy:

- *Los IDs se repiten.* Un servicio puede ocupar varios pelos de FO del mismo cable — eso es **normal y esperado**, no un defecto —, así que una consulta por pelo lo devuelve una vez por pelo. Medido en dev: en el 29,6% de los pares (cable, servicio) el servicio ocupa más de un pelo de ese cable (28.517 de 96.395); en botellas trepa al 41,3% (33.601 de 81.351, extremo A). *(Cifras corregidas en la Task 11, fix round 2: la medición original no filtraba `servicio_id IS NOT NULL` y contaba pares falsos con match sin resolver — sólo cuenta un match con `servicio_id` real.)* El cable `FO-FL-1003` (n_id 6610203) tiene 141 filas pelo↔servicio para **118 IDs distintos**. Para un listado de IDs eso es ruido; para la tabla del Verificador —que tiene una columna "Pelo" por fila— es el dato correcto. De ahí que la consulta nueva sea **nueva**, y las existentes no se toquen.

- *El ID mostrado puede no ser el vigente, y no hay forma de saberlo.* En el 18,9% de los pares (pelo, servicio) el número escrito en el pelo de Cromo difiere del `servicios.servicio_id` vigente (25.203 de 133.173) — la descripción del pelo conserva el ID viejo de la cadena de upgrades. Y `app.servicios` **no tiene ninguna columna de timestamp**: ni `updated_at` ni `created_at` (verificado: 20 columnas, ninguna de fecha). Hoy es literalmente imposible saber si una fila fue validada contra PROV alguna vez. El 92,5% de los servicios alcanzables por cable nunca pasó por PROV (8.401 de 9.079).

**Resultado esperado:** comandos `Forzar ingreso` / `Forzar egreso` en el hilo del formulario, con auditoría inmutable; comandos `Servicios <cable>` y `Servicios <cable> B<N>` que devuelven IDs de servicio únicos y validados contra PROV; y las APIs REST equivalentes para la SPA.

**Decisiones ya tomadas con el usuario** (no re-abrir durante la ejecución):
- Sin allowlist: cualquiera del canal puede ejecutar los comandos de corrección. La auditoría es el único control, y el bot publica en el hilo quién ejecutó qué.
- Un operador puede cerrar el ingreso abierto de otro técnico. Si hay más de un candidato, el bot los lista y exige elegir por ID.
- Sin `motivo` obligatorio.
- El comando nuevo responde de inmediato con el dato Cromo y publica un segundo mensaje en el hilo cuando termina el refresco PROV.
- Las credenciales PROV se montan en el worker Slack (no se delega a `api` por HTTP).
- **Las cuatro consultas existentes del verificador (`servicios_por_cable`/`_tubo`/`_botella`/`_odf`) no se modifican.** Su forma por-pelo es correcta.

**Spec:** escribir `docs/superpowers/specs/2026-09-23-correccion-ingresos-y-servicios-por-cable-design.md` en la Task 11, a partir de este Context y de las decisiones de abajo.

---

## Global Constraints

- **Worktree obligatorio antes de tocar nada** (`CLAUDE.md`): `python scripts/agent_worktree.py start --agent claude-slack --type feat --task correccion-ingresos-servicios`. Nunca trabajar en el checkout de control.
- Encabezado de 3 líneas (`# Nombre de archivo` / `# Ubicación de archivo` / `# Descripción`) en todo archivo nuevo o modificado.
- `source .venv/bin/activate` antes de `pytest` / `alembic`.
- **Baseline de tests: 1806 passed, 5 skipped** (`docs/PR/2026-09-21.md:100`). Los 5 skipped implican Postgres presente; sin DB son ~90 skipped y la suite queda verde sin haber corrido los tests de integración.
- **Nada de lo que ya está en uso cambia de contrato.** Ni `ServicioEncontrado`, ni `_serializar_servicio_encontrado`, ni los endpoints `/cables/{id}/servicios` y `/tubos/{id}/servicios`, ni el comando `Verificar cable X B<N>`. Todo lo nuevo va por símbolos nuevos.
- Toda migración lleva `downgrade()` implementado y verificado con upgrade → downgrade → upgrade contra `lasfocasdev-postgres`. **No hay precedente de test automatizado de migraciones en el repo**; la verificación es manual y hay que dejarla registrada.
- `text()` + psycopg3: bind nombrado con espacio antes del cast (`:ids ::bigint[]`, nunca `:ids::bigint[]`).
- Ningún `UPDATE`/`DELETE` directo sobre `app.ingresos` desde los comandos nuevos: todo pasa por `core/services/ingreso_service.py`.
- Los comandos de corrección son eventos `message` (los escribe una persona) y se evalúan **antes** del filtro `solo_workflows`, igual que `_procesar_seguimiento_empalme` y `_procesar_revalidacion_ingreso`. Los comandos `Servicios` son `app_mention`, como el resto de los comandos de cable.
- Prohibido tocar el stack de producción (`lasfocas-*`). Rebuild y pruebas sólo contra `lasfocasdev-slack-baneo-worker` / `lasfocasdev-web`.

---

### Task 1: Consulta nueva de servicios únicos por cable y por tubo

Independiente del resto. **No modifica ninguna consulta, dataclass ni endpoint existente** — agrega símbolos nuevos al lado.

**Files:**
- Modify: `core/services/cromo/verificador.py` (sólo agregados)
- Create: tests en `tests/test_cromo_verificador.py` (archivo existente, casos nuevos)

**Interfaces:**
- Produces: `ServicioUnico`, `ResultadoServiciosUnicos`, `servicios_unicos_por_cable` / `_por_tubo` (async) y sus gemelas `_sync`. Consumidos por las Tasks 8 y 10.

- [ ] **Step 1: Dataclasses nuevos, sin tocar `ServicioEncontrado`**

```python
@dataclass(slots=True)
class ServicioUnico:
    servicio_id: int                    # PK de app.servicios
    servicio_id_externo: str            # el ID vigente
    numero_primer_servicio: str | None
    nombre_cliente: str | None
    cliente: str | None
    estado_servicio: str | None
    tipo_servicio: str | None
    pelos_n_ids: list[int]              # todos los pelos por los que pasa
    cantidad_pelos: int
    numeros_en_pelo: list[str]          # servicio_numero distintos, para contrastar con el vigente
    metodos: list[str]
```

Un dataclass propio y no campos nuevos en `ServicioEncontrado` porque la semántica es distinta (por-servicio vs. por-pelo) y porque `ServicioEncontrado` está compartido con `detalle.py:156-183`, con `_serializar_servicio_encontrado` (5 call-sites) y con la interfaz TS `CromoServicioEncontrado` (4 tipos de respuesta). Tocarlo propaga a todo eso sin necesidad.

`numeros_en_pelo` en plural y no un solo valor: con varios pelos, cada uno puede traer un `servicio_numero` distinto (el viejo en uno, el nuevo en otro). Quedarse con uno sería elegir arbitrariamente.

- [ ] **Step 2: SQL — un solo `GROUP BY`, sin re-join**

```sql
SELECT s.id, s.servicio_id, s.numero_primer_servicio, s.nombre_cliente, s.cliente,
       s.estado_servicio, s.tipo_servicio,
       array_agg(DISTINCT p.n_id ORDER BY p.n_id)            AS pelos_n_ids,
       count(DISTINCT p.n_id)                                AS cantidad_pelos,
       array_agg(DISTINCT m.servicio_numero)                 AS numeros_en_pelo,
       array_agg(DISTINCT m.metodo)                          AS metodos
FROM app.cromo_pelos p
JOIN app.cromo_servicio_match m ON m.pelo_n_id = p.n_id
JOIN app.servicios s ON s.id = m.servicio_id
WHERE p.cable_n_id = :cable_n_id          -- o p.tubo_n_id = :tubo_n_id
GROUP BY s.id
ORDER BY s.id
```

`GROUP BY s.id` a secas alcanza: es la PK de `app.servicios` y Postgres resuelve la dependencia funcional del resto de las columnas de `s`.

**No resolverlo con un CTE que haga `JOIN` de vuelta a `cromo_servicio_match` por un pelo representativo.** El índice único de esa tabla es `ux_cromo_match_pelo_nro (pelo_n_id, servicio_numero)`, **no** `(pelo_n_id, servicio_id)`: hay 85 pares (pelo, servicio) con dos filas, porque la descripción del pelo menciona el ID viejo y el nuevo del mismo servicio (ej. pelo `6848348` → servicio `26179` vía `"108013"` y `"66041"`). Un re-join volvería a multiplicar esas filas. El `GROUP BY` de una pasada lo evita por construcción.

- [ ] **Step 3: Cuatro funciones**

`servicios_unicos_por_cable(sesion, cable_n_id)` y `servicios_unicos_por_tubo(sesion, tubo_n_id)` sobre `AsyncSession`, más sus gemelas `_sync` sobre `Session` para el listener de Slack, que corre en un callback síncrono de Bolt. Es el mismo patrón de gemelas ya establecido por `servicios_por_tubo_sync` (`verificador.py:455`): misma `text()`, sólo cambia el `await`.

Reusar el criterio de "no encontrado" tolerante a referencias colgadas que ya usan las funciones existentes (`_SQL_EXISTE_CABLE_POR_PELOS` / `_SQL_EXISTE_TUBO_POR_PELOS`): un cable puede tener pelos con servicio matcheado aunque su fila propia todavía no se haya ingerido.

- [ ] **Step 4: Tests**

`tests/test_cromo_verificador.py` usa `_SesionFake`, que matchea por **substring del SQL compilado**; las claves del dict de respuestas para las consultas nuevas tienen que coincidir con el texto real o el fake devuelve `[]` en silencio. `_SesionSyncFake` ya existe en el mismo archivo para las gemelas sync.

Caso discriminante obligatorio: un servicio con **tres pelos** en el mismo cable debe devolver **una** fila con `cantidad_pelos == 3` y los tres `pelos_n_ids`. Y un caso con dos `servicio_numero` distintos para el mismo (pelo, servicio) debe seguir devolviendo una sola fila, con los dos números en `numeros_en_pelo` — es el gotcha de los 85 pares.

---

### Task 2: Migración y modelos de corrección de ingresos

**Files:**
- Create: `db/alembic/versions/20260923_01_ingresos_correcciones.py` (`down_revision = "20260919_04"`)
- Modify: `db/models/infra.py`

- [ ] **Step 1: Columnas de hilo en `app.ingresos`**

`thread_ts VARCHAR(32) NULL` (indexada) y `canal_id VARCHAR(32) NULL`. Hoy `app.ingresos` no guarda nada del hilo, así que **no hay forma de llegar del hilo al `Ingreso`** para un caso que matcheó bien; sólo `IngresoSinMatch` guarda `thread_ts`, y sólo para los casos que fallaron. Estas columnas cierran el hueco de acá en adelante; los hilos históricos se resuelven por los niveles 2 y 3 de la cascada (Task 5).

- [ ] **Step 2: Tabla `app.ingresos_correcciones`, append-only**

Columnas: `id`, `comando` (`FORZAR_INGRESO`|`FORZAR_EGRESO`), `actor_slack_user_id`, `actor_nombre`, `canal_id`, `thread_ts` (indexada), `mensaje_ts`, `comando_crudo` (Text), `motivo` (Text NULL), `camara_texto_solicitado`, `camara_id_resuelta` (FK `app.camaras.id` ON DELETE SET NULL), `cromo_botella_id_resuelta` (BigInteger FK ON DELETE SET NULL), `momento_solicitado`, `momento_efectivo`, `fuente_momento` (`hilo`|`explicito`), `ingreso_id` (FK `app.ingresos.id` ON DELETE SET NULL), `resultado`, `error_detalle` (Text NULL), `created_at` (indexada).

Tabla nueva y **no** extensión de `IngresoSinMatch`: esa tabla modela "el nombre no matcheó", existe sólo para un subconjunto de hilos, y sus filas *se mutan* (`resuelto_via_empalme`, `resuelto_via_revalidacion`) — semántica opuesta a un log inmutable. Una corrección puede ocurrir en un hilo que matcheó perfecto.

- [ ] **Step 3: Trigger de inmutabilidad**

`BEFORE UPDATE OR DELETE ON app.ingresos_correcciones ... RAISE EXCEPTION`, con su `DROP TRIGGER` + `DROP FUNCTION` en el `downgrade()`. Es la diferencia entre inmutabilidad real y una promesa en un docstring.

- [ ] **Step 4: Verificar la migración contra dev**

`alembic upgrade head` → `downgrade -1` → `upgrade head` contra `lasfocasdev-postgres`, y una prueba real de que el trigger rechaza un `UPDATE` sobre una fila insertada a mano. Registrar la salida.

---

### Task 3: Persistir `thread_ts`/`canal_id` en el flujo en vivo

Depende de la Task 2.

**Files:**
- Modify: `core/services/ingreso_service.py`
- Modify: `modules/slack_baneo_notifier/listener.py`
- Modify: `tests/test_ingreso_service.py`, `tests/test_slack_ingreso_listener.py`

- [ ] **Step 1: Propagar los dos campos**

`registrar_movimiento_ingreso` y `registrar_intento_bloqueado` aceptan `thread_ts: str | None = None` y `canal_id: str | None = None` (kwargs opcionales, mismo estilo que `momento`), y los escriben en la fila nueva. En el camino "Egreso" que **cierra** una fila existente no se pisan los del ingreso original.

`_registrar_movimiento_si_corresponde` (`listener.py:252`) los recibe y los pasa. `_construir_respuesta_camara` ya tiene `thread_ts` y `channel` en su firma.

**Cuidado:** `tests/test_slack_ingreso_listener.py:757-810` assertea `mock_registrar.assert_called_once_with(...)` con la lista completa de kwargs. Los dos kwargs nuevos rompen esa aserción exacta en varios tests — actualizarlos es parte de la tarea, no un efecto colateral a ignorar.

---

### Task 4: Parser de los comandos `Forzar ingreso` / `Forzar egreso`

Independiente de las Tasks 2 y 3. Funciones puras, sin DB ni Slack: es la tarea más fácil de testear a fondo.

**Files:**
- Create: `modules/slack_baneo_notifier/correccion_ingreso.py`
- Modify: `modules/slack_baneo_notifier/cable_info.py` (promover `_quitar_formato_slack`)
- Create: `tests/test_slack_correccion_ingreso.py`

- [ ] **Step 1: Gramática**

```
Forzar ingreso <CAMARA>
Forzar ingreso <CAMARA> DD-MM-AAAA HH:MM
Forzar egreso
Forzar egreso <CAMARA> DD-MM-AAAA HH:MM
Forzar egreso #<ingreso_id>
```

El datetime va anclado al final y el nombre de cámara se captura con `.+?` no-goloso — mismo patrón que `_RE_CABLE_BUFFER` (`cable_info.py:52`), por la misma razón: sin eso el nombre se come el sufijo.

Regex adicional `_RE_MOMENTO_SOLO` para la respuesta de seguimiento con sólo `DD-MM-AAAA HH:MM` (Task 6).

- [ ] **Step 2: Reusar el saneado de formato de Slack**

`_quitar_formato_slack` (`cable_info.py:79`) es privado y resuelve un bug real reproducido en 2026-08-25: Slack manda `*negrita*` con los asteriscos literales, y eso rompía tanto el match exacto como el ancla `$` del regex con sufijo. Un técnico va a escribir `Forzar egreso *Cra Balcarce 302*` igual que escribía `info cable *F-VDP-JUR*`. Promoverlo a público y reusarlo — no reimplementarlo.

Para el nombre de cámara, reusar `limpiar_ruido_operativo` (`camara_search.py`), igual que el flujo en vivo.

- [ ] **Step 3: Parseo de fecha/hora en hora de Buenos Aires**

El worker corre con `TZ=America/Argentina/Buenos_Aires` (`deploy/docker-compose.dev.yml:268`) y el técnico escribe hora local. Parsear con `ZoneInfo("America/Argentina/Buenos_Aires")` y convertir a UTC antes de devolver, porque `registrar_movimiento_ingreso` persiste `datetime.now(timezone.utc)`.

Rechazar fecha futura y fecha anterior a 90 días (protección contra el error de tipeo de año, que con `DD-MM-AAAA` da una fecha absurda en vez de un desvío chico).

- [ ] **Step 4: Constructores de respuesta**

Un constructor por caso, todos devolviendo `str` — mismo estilo que `construir_respuesta_*` de `cable_info.py`. Cubrir: OK ingreso, OK egreso cerrado, OK egreso asentado, falta fecha, cámara ambigua (con candidatos), varios ingresos abiertos (con `id`/técnico/`fecha_inicio`), egreso anterior al ingreso, ingreso ya cerrado, hilo sin formulario, fecha fuera de rango.

---

### Task 5: Servicio de corrección con resolución de hilo en cascada

Depende de las Tasks 2, 3 y 4.

**Files:**
- Create: `core/services/ingreso_correccion_service.py`
- Create: `tests/test_ingreso_correccion_service.py`

- [ ] **Step 1: Resolver el formulario original desde `thread_ts`, en tres niveles**

1. `Ingreso.thread_ts` (Task 2) — el `Ingreso` real del hilo, sin llamadas de red.
2. `IngresoSinMatch.thread_ts` — da `texto_mensaje` y `created_at`.
3. `client.conversations_replies(channel, ts=thread_ts, limit=1)` — el mensaje raíz del hilo. Cubre los hilos históricos que no tienen ninguna de las dos.

El `ts` del mensaje raíz es la fuente preferida del momento, no `IngresoSinMatch.created_at`: ese último es cuándo el listener **procesó** el mensaje, no cuándo se envió.

Esto además disuelve el caso "más de un caso en el hilo": un mensaje multi-botella crea varias filas `IngresoSinMatch` con el mismo `thread_ts`, pero todas comparten un único `ts` de mensaje raíz.

**Requiere el scope `channels:history` (o `groups:history`) en el panel de la Slack App** — no verificable desde el código, mismo criterio que `app_mentions:read` y `users:read` (ver `listener.py:17-19` y `slack_user_resolver.py:14-16`). Dejarlo anotado en `docs/bot.md` y degradar con gracia si la llamada falla: si no hay nivel 1 ni 2 y `conversations.replies` no responde, se pide la forma con fecha explícita.

- [ ] **Step 2: Tipo y técnico del formulario**

Reusar `extraer_tipo_movimiento` y `extraer_slack_user_id_autorizacion` (`camara_search.py:309, 326`) + `resolver_nombre_tecnico` (`slack_user_resolver.py`). Si el técnico no se puede resolver, **no bloquear**: registrar con `tecnico_id=NULL` y decirlo en la respuesta. El valor operativo (cámara `OCUPADA`/`LIBRE`) no depende de la identidad, y la fila de auditoría siempre tiene al actor.

- [ ] **Step 3: Regla del momento implícito**

| Hilo | Comando | Momento |
|---|---|---|
| Ingreso | `Forzar ingreso <CAMARA>` | `ts` del hilo |
| Egreso | `Forzar egreso <CAMARA>` | `ts` del hilo |
| Ingreso | `Forzar egreso` | **fecha/hora explícita, siempre** |
| Egreso | `Forzar ingreso` | **fecha/hora explícita, siempre** |

El momento implícito sólo se toma del hilo cuando el tipo del formulario coincide con el tipo forzado. Forzar un egreso en el hilo de un formulario de *Ingreso* con el `ts` de ese hilo registraría una visita de duración cero — el mismo error que `ingreso_service.py` ya evita a propósito al dejar `fecha_inicio=None` en un egreso huérfano (ver su docstring, línea 68-78). Cuando no coincide, el bot **pide** la fecha en vez de rechazar (Task 6).

- [ ] **Step 4: Resolución del egreso, sin fallback implícito**

**Regla dura:** nunca llamar a `registrar_movimiento_ingreso(tipo_movimiento="Egreso")` a ciegas. Esa función, si no encuentra un ingreso abierto, **crea una fila EGRESO huérfana** (`ingreso_service.py:117-126`) — correcto para el flujo en vivo, inaceptable para una corrección que alguien puede repetir por error. El camino forzado:

1. Resuelve el conjunto de ingresos abiertos candidatos (`tipo=INGRESO`, `fecha_fin IS NULL`) de la cámara resuelta.
2. Cero candidatos → sólo la forma con cámara y fecha explícitas puede **asentar** deliberadamente; las demás responden que no hay nada que cerrar.
3. Un candidato → lo cierra.
4. Dos o más → los lista con `id`, técnico y `fecha_inicio`, y exige `Forzar egreso #<id>`. Nunca adivina.

Validación: `momento_egreso > ingreso.fecha_inicio`, estricto. Si no, rechaza mostrando el `fecha_inicio` real.

- [ ] **Step 5: Auditoría en todos los caminos**

Escribir una fila en `ingresos_correcciones` en **cada** invocación, incluidos los rechazos, con `resultado` y `error_detalle`. Cuando la corrección resuelve un caso pendiente del hilo, marcar también ese `IngresoSinMatch` (`ingreso_id` + `resuelto_via_revalidacion`) para que no quede colgado.

`Forzar ingreso` sobre un grupo hoy baneado registra un **INGRESO real**, no `INTENTO_BLOQUEADO`: el operador está afirmando que el técnico entró, y el estado de baneo *actual* no es evidencia sobre el pasado. La respuesta avisa si el grupo está baneado ahora. Decisión deliberada — documentarla en `docs/decisiones.md`.

---

### Task 6: Wiring en el listener y flujo de fecha pendiente

Depende de la Task 5.

**Files:**
- Modify: `modules/slack_baneo_notifier/listener.py`
- Modify: `tests/test_slack_ingreso_listener.py`

- [ ] **Step 1: `_procesar_correccion_ingreso`**

Método nuevo con la misma forma que `_procesar_revalidacion_ingreso` (`listener.py:495`): devuelve `True` cuando el texto matchea el trigger (el caller corta) y `False` cuando no aplica. Se engancha en `_handle_message` dentro del bloque `if event_thread_ts and event_thread_ts != event_ts` (línea 655), junto a los otros dos, **antes** del filtro `solo_workflows` — por la misma razón documentada ahí: un mensaje manual de una persona no trae `workflow_id` y el filtro lo descartaría antes de llegar.

- [ ] **Step 2: Fecha pendiente, sin mutar la auditoría**

Cuando el tipo del hilo no coincide, el bot pide la fecha y escribe una fila con `resultado='PENDIENTE_FECHA'`. El operador puede responder de dos formas: reenviar el comando completo con la fecha, o contestar en el hilo sólo con `DD-MM-AAAA HH:MM`.

El segundo camino **no muta** la fila anterior: escribe una fila nueva con la ejecución. El guard para no interpretar cualquier fecha suelta del canal es el mismo patrón estricto de `_procesar_seguimiento_empalme` (`listener.py:462`): tiene que existir una fila `PENDIENTE_FECHA` para ese `thread_ts` exacto, de menos de 30 minutos.

- [ ] **Step 3: Nunca romper la respuesta por un fallo de DB**

Mismo contrato que `_registrar_movimiento_si_corresponde` (`listener.py:298-305`): `try/except` con `session.rollback()` en el handler. Un `commit()` fallido deja la sesión compartida en estado inactivo y cualquier operación posterior relanza `PendingRollbackError`.

- [ ] **Step 4: Tests**

Seguir el patrón real del archivo: `_make_event_reply(text, thread_ts, ts)` (línea 2478) para eventos dentro de un hilo, `client_mock = MagicMock()` con aserciones sobre `chat_postMessage.call_args.kwargs`, y `session.query.side_effect` discriminando por modelo (línea 2484). Cubrir los 10 casos de respuesta de la Task 4 más el ciclo completo de fecha pendiente.

---

### Task 7: Tabla de sincronización PROV y su escritura

Independiente de las Tasks 1-6.

**Files:**
- Create: `db/alembic/versions/20260923_02_servicios_sync_prov.py` (`down_revision = "20260923_01"`)
- Modify: `db/models/infra.py`
- Modify: `core/services/prov/ingesta.py`
- Create: `core/services/prov/frescura.py`
- Modify: `tests/test_prov_ingesta.py`; Create: `tests/test_prov_frescura.py`

- [ ] **Step 1: Tabla `app.servicios_sync_prov`**

`servicio_id` (FK `app.servicios.id` ON DELETE CASCADE, único), `ultima_sincronizacion_ok` (timestamptz NOT NULL), `ultimo_intento`, `ultimo_error` (Text NULL), `nro_servicio_consultado`, `created_at`, `updated_at`.

Tabla y no columna en `app.servicios`, por tres razones concretas: esa tabla hoy no tiene **ni un solo** timestamp; la escriben tres ingestas distintas (Excel, PROV, placeholders Cromo) y `origen_datos` se re-etiqueta incondicionalmente en cada una (`prov/ingesta.py:262`), que es exactamente el "pisado por ingesta ajena" a evitar; y el estado de *fallo* no pertenece a la fila de dominio.

- [ ] **Step 2: Escribir en el único embudo**

Upsert al final de `ingerir_contexto_prov` (`core/services/prov/ingesta.py:178`), que es por donde pasan los tres consumidores: el endpoint on-demand (`api/app/routes/servicios.py:686`), el backfill (`scripts/servicios_backfill_prov.py:117`) y el camino Slack nuevo. Un solo punto de acoplamiento, tres consumidores cubiertos.

- [ ] **Step 3: Servicio de frescura**

`core/services/prov/frescura.py` con la consulta batch "dado un conjunto de `servicio_id`, cuáles están vencidos" (`ultima_sincronizacion_ok IS NULL OR < now() - :horas`), en versión async y sync (el listener de Slack es síncrono — mismo patrón de gemelas que ya usa `verificador.py`). Umbral por `PROV_FRESCURA_HORAS`, default 48.

- [ ] **Step 4: Backfill como prerrequisito operativo, no como mejora**

El 92,5% de los servicios alcanzables por cable nunca pasó por PROV. Sin correr `scripts/servicios_backfill_prov.py` primero, **todos** cuentan como vencidos y cada comando choca contra el tope de refresco durante meses sin alcanzar el régimen estacionario. Dejarlo escrito en `docs/bot.md` y en el PR como paso previo al anuncio del comando, con el recordatorio ya documentado de no correrlo en horario de uso intensivo (`docs/decisiones.md`, Decisión 3 del 2026-09-02: el rate limiter no es distribuido y el máximo combinado sube a ~10 req/s).

---

### Task 8: Comandos `Servicios <cable>` y `Servicios <cable> B<N>`

Depende de las Tasks 1 y 7. Sin refresco todavía: sólo marca la frescura.

**Files:**
- Modify: `modules/slack_baneo_notifier/cable_info.py`
- Modify: `modules/slack_baneo_notifier/listener.py` (`_handle_app_mention`)
- Modify: `tests/test_slack_cable_info.py`

- [ ] **Step 1: Parsers**

```python
_RE_SERVICIOS_BUFFER = re.compile(r"(?i)^servicios\s+(?:cable\s+)?(.+?)\s+(?:b|buffer)\s*(\d+)$")
_RE_SERVICIOS_CABLE  = re.compile(r"(?i)^servicios\s+(?:cable\s+)?(.+)$")
```

El de buffer se intenta primero, misma precedencia y misma razón que el par existente (`listener.py:846-852`). Verificado que el verbo está libre: hoy `Servicios <lo que sea>` no matchea ningún comando (`_RE_INFO_CABLE` exige "info cable", `_RE_CABLE_BUFFER` exige el sufijo `B<N>`).

Reusar `buscar_cable_por_n_id_o_nombre` y `_resolver_cable_o_responder` (`listener.py:812`), que ya manejan el caso de 0 y 2+ cables con el mismo nombre; y `resolver_tubo_por_numero` / `contar_buffers_cable` para el buffer humano (`orden = N - 1`).

- [ ] **Step 2: Formato de respuesta — IDs únicos, no detalle de pelo**

```
🧾 Servicios del cable *F-VFL-IND* — 24 ID(s) únicos
B1 (AZ): 133345, 140002, 145001
B2 (NR): 145002, 150001
⚠️ En el pelo figura otro número: 133345 (el pelo dice 122214)
🕒 6 con validación PROV vencida — refrescando…
```

Un ID por servicio, aunque ocupe varios pelos — que es lo normal. La línea "en el pelo figura otro número" compara `servicio_id_externo` contra `numeros_en_pelo`; ambos vienen de `ServicioUnico` (Task 1), no hace falta ningún dato nuevo. Es el 18,9% medido.

Con la salida acotada a IDs, el cable entero entra cómodo en un mensaje (118 IDs son ~950 caracteres): no hace falta truncar. El agrupamiento por buffer se mantiene — es barato y es lo que pidió el usuario para segmentar.

- [ ] **Step 3: `Verificar cable X B<N>` no se toca**

`Servicios <cable> B<N>` y el `Verificar cable <cable> B<N>` existente responden sobre el mismo cable y buffer, pero con propósito distinto: el existente lista los servicios **por pelo** (una línea por pelo, que es el dato físico correcto) y el nuevo lista **IDs únicos** con frescura y refresco. Son consultas distintas y coexisten; no hay que unificarlos ni cambiar el comportamiento del existente.

- [ ] **Step 4: Marcador de frescura en `Info cable X B<N>`**

Agregar sólo el `🕒` en los pelos cuyo servicio está vencido, sin cambiarle la función ni disparar refresco. Cierra el gap señalado —hoy muestra el último ID conocido sin decir si fue validado— sin convertir ese comando en otro.

---

### Task 9: Refresco PROV asíncrono y credenciales en el worker

Depende de las Tasks 7 y 8.

**Files:**
- Create: `modules/slack_baneo_notifier/refresco_prov.py`
- Modify: `modules/slack_baneo_notifier/worker.py`, `modules/slack_baneo_notifier/listener.py`
- Modify: `deploy/docker-compose.dev.yml`, `deploy/compose.yml`
- Create: `tests/test_slack_refresco_prov.py`

- [ ] **Step 1: Exponer el event loop del worker**

`worker.py::_main_loop` ya corre un loop asyncio vivo que idlea en `await asyncio.sleep(3600)` (línea 331), y el listener corre en un daemon thread aparte (línea 321). Capturar el loop con `asyncio.get_running_loop()` dentro de `_main_loop` y pasárselo al `IngresoListener`. Desde el thread del listener, encolar con `asyncio.run_coroutine_threadsafe`. Sin loop disponible (tests, uso standalone), saltear el refresco y decirlo en la respuesta.

- [ ] **Step 2: La corrutina de refresco, acotada**

`Semaphore(3)` de concurrencia; `max_reintentos=0` por servicio (es interactivo, no el backfill — mismo criterio que `_PROV_REFRESCAR_MAX_REINTENTOS=1` en `api/app/routes/servicios.py:683`); deadline global de 120 s; tope de 25 servicios por comando, ordenados por antigüedad; candado por `cable_n_id` para que dos personas no refresquen el mismo cable a la vez.

**Una sesión corta de DB por servicio, nunca sostenida a través de la llamada de red** — el precedente explícito de `refrescar_servicio_desde_prov` (`api/app/routes/servicios.py:686-697`), que dejó de usar `Depends(get_async_db)` justamente por esto.

Reusar `get_prov_client()` (comparte el `AsyncRateLimiter` de 5 req/s del proceso) e `ingerir_contexto_prov` sin modificar.

- [ ] **Step 3: Mensaje de seguimiento**

Segundo `chat_postMessage` en el mismo hilo con qué IDs cambiaron y **la lista nominal de los que no se pudieron refrescar, con el motivo de cada uno** (no encontrado en PROV / 4xx / timeout). El primer mensaje con el dato Cromo ya salió, así que un fallo de PROV nunca oculta el resultado local.

`ProvConfigError` se captura **antes** de encolar: el primer mensaje dice "PROV no está configurado en este entorno" y no hay segundo mensaje. Mismo criterio que el 503 del endpoint (`api/app/routes/servicios.py:721`).

- [ ] **Step 4: Montar los secrets**

Agregar `api_prov_user_v1` y `api_prov_pass_v1` a la lista `secrets:` del servicio `slack_baneo_worker` en los **dos** compose. Verificado: `lasfocasdev-slack-baneo-worker` hoy monta sólo `db_password_v1`, `slack_bot_token_v1`, `slack_app_token_v1`, y prod está igual. El bloque `secrets:` de nivel raíz **ya declara** ambos en los dos archivos y los cuatro `.secrets/*api_prov*` existen y no están vacíos — el cambio son dos líneas por archivo. `PROV_BASE_URL` ya llega por `env_file`.

> Nota: `docs/decisiones.md` (2026-09-02, "No hecho / pendiente") dice que PROV no está configurado en producción. Está desactualizado: los secrets de prod existen y `.env` tiene `PROV_BASE_URL`. Corregirlo en la Task 11.

- [ ] **Step 5: Logs sin secretos**

Log estructurado `action=prov_refresco_slack evento=... cable_n_id=... total=... refrescados=... fallidos=... duracion_ms=...`. Nunca loguear `ProvConfig.user`/`password`. Tener presente que `ProvClient._get` ya loguea `respuesta.text` ante un 4xx (`client.py:140-143`) — comportamiento preexistente, no agregar exposición nueva.

- [ ] **Step 6: Tests**

`httpx.MockTransport` para el cliente (patrón de `tests/test_prov_client.py:20-40`) y el `_ClientePROVFalso` duck-typed inyectado por `monkeypatch` (patrón de `tests/test_servicios_prov_routes.py:105`). Neutralizar el backoff con `monkeypatch.setattr("core.services.prov.client.asyncio.sleep", _sin_espera)`. Tests con `@pytest.mark.asyncio` explícito: `pytest-asyncio` corre en modo strict (no hay `asyncio_mode` en `pytest.ini`).

Casos: tope de 25 respetado, deadline corta el lote, un fallo puntual no aborta el resto, PROV no configurado no encola nada, el candado por cable evita el refresco duplicado.

---

### Task 10: APIs REST

Depende de las Tasks 1 y 7. **Rutas nuevas; las dos existentes no se tocan.**

**Files:**
- Modify: `web/app/main.py` (sólo agregados)
- Modify: `web/frontend/src/api/cromo.ts` (sólo agregados)
- Create: `tests/test_web_cromo_servicios_unicos.py`

- [ ] **Step 1: Las cuatro rutas nuevas**

```
GET  /api/infra/cromo/cables/{cable_n_id}/servicios-unicos
GET  /api/infra/cromo/cables/{cable_n_id}/buffers/{numero}/servicios-unicos
GET  /api/infra/cromo/cables/resolver?q=<n_id|nombre>
POST /api/infra/cromo/cables/{cable_n_id}/servicios-unicos/refrescar-prov   (CSRF)
```

Rutas nuevas y no extensión de `/cables/{id}/servicios`: ese endpoint devuelve la vista por-pelo que consume la tabla del Verificador, con su columna "Pelo". Son dos vistas legítimas del mismo dato y conviven.

En `web/app/main.py` y no en `api/app/routes/`: el repo ya decidió esto por escrito dos veces (`docs/decisiones.md`, 2026-08-19 y 2026-08-22). `api/app/` es API-key máquina-a-máquina, sin concepto de rol, no usable desde el navegador; el 100% de los endpoints Cromo vive en `web/app/main.py` con `_require_auth`. Y la lección de la Task 11 de la integración PROV: un endpoint en `api/app/routes` necesita igual su proxy escrito a mano en `web/app/main.py`, porque no hay proxy genérico.

`resolver` responde 200 con el cable único, 404 `{"codigo": "NO_ENCONTRADO"}` o **409 `{"codigo": "AMBIGUO", "candidatos": [...]}`** — hay al menos 2 pares de nombres duplicados reales conocidos (`F-ALV-2335`, `F-LEM-11-A`) sobre ~32.782 cables; la ambigüedad se hace explícita en vez de elegir una.

Cada respuesta lleva la identidad del cable (y del buffer, con su `numero` humano, `orden` y `nombre_color`), `datos_al`, `frescura` por servicio (`ultima_sincronizacion_prov`, `antiguedad_horas`, `vencida`) y un bloque `refresco_prov` con `estado` y `fallidos` nominales. Cada servicio lleva `cantidad_pelos` y `pelos_n_ids`: el ID es único, pero la cantidad de fibras que ocupa es información útil, no ruido.

- [ ] **Step 2: Modelos Pydantic**

`web/app/main.py` devuelve `JSONResponse` a mano en todos lados, así que no documenta nada en `/docs`. Es la única desventaja real frente a `api/app/routes/`. Compensarla con `response_model` explícito en estas cuatro rutas.

- [ ] **Step 3: Tests**

Copiar el patrón del repo, no factorizarlo (hay 18 copias de `_Cur`/`_Conn`/`_connect_admin_ok`/`_login` y 22 de `_SesionFake`; factorizar está fuera de alcance). `_require_auth` **no se mockea**: se hace login real contra un `psycopg.connect` falso. Parchear `"db.session.AsyncSessionLocal"` por string.

Para ejercer CSRF en el POST hace falta `monkeypatch.setenv("TESTING", "false")` explícito: `tests/test_slack_*.py` hacen `os.environ.setdefault("TESTING", "true")` a nivel de módulo sin revertirlo, y si corren antes dejan el chequeo salteado en silencio (gotcha ya documentado en `tests/test_web_botellas_admin.py:387-391`).

Incluir el test de 401 sin sesión, que es el que confirma el wiring real de la ruta.

---

### Task 11: Documentación y PR

- [ ] **Step 1: Spec del diseño**

Escribir `docs/superpowers/specs/2026-09-23-correccion-ingresos-y-servicios-por-cable-design.md` con los 7 entregables acordados (inventario, decisiones producto/técnicas separadas, esquema y migraciones, contratos con ejemplos, plan incremental, plan de pruebas, riesgos).

- [ ] **Step 2: Docs temáticas**

- `docs/bot.md`: comandos de corrección, scope `channels:history` requerido, backfill PROV como prerrequisito.
- `docs/slack_app_cables.md`: comandos `Servicios`, y por qué conviven con `Verificar cable X B<N>` (IDs únicos vs. detalle por pelo) en vez de reemplazarlo; el `🕒` en `Info cable X B<N>`.
- `docs/db.md`: `ingresos_correcciones`, `servicios_sync_prov`, columnas nuevas de `ingresos`, y las dos migraciones en la tabla de revisiones.
- `docs/decisiones.md`: entrada nueva con las decisiones deliberadas (sin allowlist y por qué la auditoría es el control; tabla nueva y no extensión de `IngresoSinMatch`; `Forzar ingreso` registra INGRESO real sobre grupo baneado; consulta nueva en vez de modificar las existentes, porque varios pelos por servicio es lo normal) **y la corrección de la nota obsoleta de 2026-09-02** sobre PROV en producción.
- `docs/PR/2026-09-23.md` vía `/generar-pr-diario`.

---

## Fuera de alcance (no hacer sin pedirlo)

El chip del Verificador (`VerificadorCromoView.vue:87`, `{{ resultado.servicios.length }} servicio(s)`) cuenta **filas por pelo**, no servicios, así que para un cable con servicios multi-pelo muestra un número más alto que el contador del inventario (`inventario.py:106`, que sí usa `count(DISTINCT m.servicio_id)`). Es una inconsistencia de etiqueta, no de datos, y arreglarla —relabelar a "N pelo(s) con servicio" o contar IDs distintos en el cliente— es un cambio chico pero ajeno a este plan. Dejarlo anotado, no bundlearlo.

---

## Verificación

**Suite completa** (línea base **1806 passed, 5 skipped**):

```bash
source .venv/bin/activate
POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5433 POSTGRES_DB=focas_dev POSTGRES_USER=FOCALBOT \
POSTGRES_PASSWORD="$(cat .secrets/Dev_db_password_v1.txt)" \
LLM_PROVIDER=heuristic pytest -q
```

Si el conteo de `skipped` sube a ~90, la corrida **no tuvo Postgres** y los ~29 tests de integración no se ejecutaron: la suite queda verde sin haber probado nada de DB. El número de skipped es la señal, no el de passed.

Como este plan no modifica ninguna consulta ni contrato existente, **ningún test preexistente debería cambiar de resultado** salvo los de `tests/test_slack_ingreso_listener.py` / `tests/test_ingreso_service.py` que assertean kwargs exactos (Task 3). Un fallo en cualquier otro lado es señal de que algo se tocó de más.

**Migraciones** (no hay test automatizado; verificación manual obligatoria):

```bash
alembic -c db/alembic.ini upgrade head --sql      # revisar el SQL antes de aplicar
alembic -c db/alembic.ini upgrade head
alembic -c db/alembic.ini downgrade -1
alembic -c db/alembic.ini upgrade head
```
Más una prueba real de que el trigger rechaza `UPDATE` y `DELETE` sobre una fila de `ingresos_correcciones` insertada a mano.

**Frontend:**
```bash
cd web/frontend && npx vue-tsc --noEmit && npm run build
```
Los 4 errores preexistentes de `InfraTab.vue` son ajenos y deben seguir siendo exactamente 4.

**Consulta nueva, contra datos reales:**

```sql
-- FO-FL-1003 (n_id 6610203): la consulta por pelo da 141 filas; la nueva debe dar 118
SELECT count(*) FROM ( <servicios_unicos_por_cable con :cable_n_id = 6610203> ) q;
-- y ningún servicio_id repetido:
SELECT servicio_id, count(*) FROM ( <la misma> ) q GROUP BY 1 HAVING count(*) > 1;  -- 0 filas
```

**End-to-end real contra dev** (nunca contra `lasfocas-*`):

1. Reconstruir y reiniciar `lasfocasdev-slack-baneo-worker` y `lasfocasdev-web`. **Verificar la imagen de cada contenedor tocado**, no sólo del principal: un `TestClient` in-process nunca detecta código deployado stale.
2. `curl` sin sesión a las cuatro rutas nuevas → debe dar **401, no 404**. Es lo que confirma el wiring; un 404 significa que la ruta no quedó registrada.
3. `docker exec lasfocasdev-slack-baneo-worker ls /run/secrets/` debe listar `api_prov_user_v1` y `api_prov_pass_v1`, y el log del worker debe mostrar la conexión Socket Mode sin errores.
4. En el canal real de dev (`@sandy02` / `registrador_de_ingres`, app de **dev**, nunca la de prod `lasfocas_cambot`): `@bot Servicios F-VFL-IND` y `@bot Servicios F-VFL-IND B1`, verificando que ningún ID se repite; y un ciclo completo de `Forzar egreso` en el hilo de un formulario de ingreso, incluyendo el pedido de fecha y la respuesta con sólo `DD-MM-AAAA HH:MM`.
5. Confirmar en DB que la fila de `ingresos_correcciones` quedó escrita con el actor correcto y que `app.ingresos` refleja el cierre.
