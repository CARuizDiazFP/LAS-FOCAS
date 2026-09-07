# Nombre de archivo: 2026-09-02-servicios-prov-integracion-design.md
# Ubicación de archivo: docs/superpowers/specs/2026-09-02-servicios-prov-integracion-design.md
# Descripción: Diseño de la integración con la API interna PROV para enriquecer Servicios (última milla + historial de upgrades) y del componente Timeline genérico en el frontend

# Integración API PROV para Servicios — Design

## Contexto

El flujo de ingesta de Servicios SLA depende hoy de que un operador suba un Excel manualmente
(`POST /servicios/ingest`, `api/app/routes/servicios.py`). Existe una API interna, PROV
(`https://prov.metrotel.com.ar/api/v1/ADMEQ/API_Contexto_Servicio`), que devuelve el detalle
completo de un servicio por número: cliente, dirección, equipos de última milla (nodo/equipo/puerto)
y la cadena completa de upgrades de ID con fecha y motivo. Se decidió agregar un flujo de ingesta
nuevo que consuma PROV directamente, sin retirar el flujo Excel existente (coexistencia temporal).

El objetivo de este documento es fijar el modelo de datos, el cliente HTTP con throttling, la
lógica de ingesta y el componente de frontend antes de escribir el plan de implementación tarea por
tarea.

## Datos reales de PROV (verificados en esta sesión)

Se consultaron dos servicios reales contra la API (credenciales de `.secrets/api_prov_user` /
`api_prov_pass`, Basic Auth) para confirmar la forma exacta del payload — **no se commitean** estos
JSON crudos por contener razón social/domicilio de clientes reales; los tests usan fixtures
sintéticas con la misma forma.

**Caso sin upgrades** (`nro_servicio=122214`, tipo `RPV`, un solo extremo):

```json
{
  "Result": "Success",
  "Resultado:": {
    "id_servicio": "RPV",
    "nro_servicio": "122214",
    "nro_servicio_original": "122214",
    "estado_comercial": "INSTALADO",
    "creacion": "2026-07-14 15:47:15",
    "Descripcion": "BANCO MACRO SA",
    "Direccion1": "RECONQUISTA 590 P.1",
    "Provincia1": "Capital Federal",
    "Nodo1": "CLI_Reconquista590P1_BancoITAU",
    "Equipo1": "SW_Reconquista590P1_BancoITAU",
    "Port1": "GigabitEthernet1/0/5"
  }
}
```

**Caso con cadena de upgrades** (`nro_servicio=15872` consultado — un ID histórico; PROV resuelve
solo hasta el vigente):

```json
{
  "Result": "Success",
  "Resultado:": {
    "id_servicio": "EWS",
    "nro_servicio": "63871",
    "nro_servicio_original": "15872",
    "nro_servicio_consultado": "15872",
    "nro_servicio_vigente": "63871",
    "fue_upgradeado": true,
    "estado_comercial": "INSTALADO",
    "Descripcion": "CONSEJO PROFESIONAL DE CIENCIAS ECONÓMICAS CABA",
    "Direccion1": "AYACUCHO 652",
    "Provincia1": "Capital Federal",
    "Nodo1": "Paraguay2302_CABA",
    "Equipo1": "SW_3_Paraguay2302_CABA",
    "Port1": "6",
    "cadena_upgrade": [
      {"nro_servicio": "63871", "estado_comercial": "INSTALADO", "fecha_instalacion": "2019-11-01", "fecha_baja": null, "motivo_baja": "", "es_vigente": true},
      {"nro_servicio": "46215", "estado_comercial": "DADO BAJA", "fecha_instalacion": "2017-11-23", "fecha_baja": "2019-11-01", "motivo_baja": "UPGRADE", "es_vigente": false},
      {"nro_servicio": "15872", "estado_comercial": "DADO BAJA", "fecha_instalacion": "2012-04-23", "fecha_baja": "2017-11-23", "motivo_baja": "UPGRADE", "es_vigente": false}
    ]
  }
}
```

**Payload de error (servicio inexistente, HTTP 200 igual)** — dado por el usuario, no reproducido
en esta sesión para no gastar cupo de API en un caso ya documentado:

```json
{"ProcessId":"...","DoneTime":"...","Result":"Success","Resultado:":"No hay contexto para el número de servicio ingresado"}
```

La clave para distinguir éxito de error es el **tipo** de `Resultado:`: objeto → éxito; string →
error lógico (servicio no encontrado).

**Mapeos confirmados:**

| Campo PROV | Campo propio | Nota |
|---|---|---|
| `nro_servicio` (top-level) | `Servicio.servicio_id` | Siempre el vigente, aunque se consulte un ID viejo |
| `nro_servicio_original` | `Servicio.numero_primer_servicio` | Ancla original — mismo significado que ya usa el proyecto |
| `cadena_upgrade[*].nro_servicio` (o solo `nro_servicio_original` si no hay cadena) | `Servicio.alias_ids` | Deduplicado, vía `consolidar_identidad_servicio` |
| `Descripcion` | `Servicio.cliente` / `nombre_cliente` | Reusar columna existente, sin agregar una nueva |
| `Direccion1`, `Provincia1` (y `Direccion2`/`Provincia2` si el payload trae extremo 2) | `Servicio.direccion` / `provincia` / `direccion_2` | Columnas ya existentes |
| `id_servicio` | `Servicio.tipo_servicio` | RPV, EWS, INT, ISI, ISIS, TLS, etc. |
| `Nodo{1,2}`, `Equipo{1,2}`, `Port{1,2}` | tabla nueva `ServicioEquipoUltimaMilla` | Cardinalidad la decide el payload (1 o 2 extremos), no una regla por tipo |
| `cadena_upgrade[*]` (fecha_instalacion, fecha_baja, estado_comercial, motivo_baja, es_vigente) | tabla nueva `ServicioHistorialId` | No cabe en `alias_ids` (solo strings) |
| `estado_comercial` (`INSTALADO`/`DADO BAJA`) | `Servicio.estado_servicio` (`Activo`/`Baja`) | Tabla de traducción ampliable; vía `resolver_estado_servicio` |

## Alcance

**Incluye:** cliente PROV con throttling, dos tablas nuevas, servicio de ingesta que reusa
`consolidar_identidad_servicio`/`resolver_estado_servicio`/`es_verificable_por_tipo_y_estado`, un
endpoint de refresco on-demand por servicio, extensión de `GET /servicios/detail`, script de
backfill masivo, componente `ServiceTimeline.vue` genérico, secrets de dev para PROV, migración
Alembic, documentación.

**No incluye:** retirar `/servicios/ingest` (Excel), rate limiting distribuido entre procesos
(Redis), ingesta de Reclamos/Ingresos/Mantenimientos (el Timeline queda listo para admitirlos, pero
no se implementa ninguna fuente de esos tipos todavía), secrets/compose de producción (se documenta
el paso pero no hay archivo de prod para PROV en este alcance).

## Modelo de datos (`db/models/infra.py`)

Dos tablas hijas de `Servicio`, mismo espíritu que `RutaServicio` — se reescriben completas
(delete + reinsert) en cada ingesta/refresh, porque PROV siempre devuelve el estado completo y
vigente, no un delta:

- **`app.servicios_historial_id`** (`ServicioHistorialId`): `id`, `servicio_id` (FK →
  `servicios.id`, `ondelete=CASCADE`), `numero_id`, `orden` (posición en la cadena, 0 = vigente),
  `fecha_instalacion` (Date, nullable), `fecha_baja` (Date, nullable), `estado_comercial`
  (String, nullable), `motivo_baja` (String, nullable), `es_vigente` (Boolean).
- **`app.servicios_equipos_ultima_milla`** (`ServicioEquipoUltimaMilla`): `id`, `servicio_id` (FK,
  `ondelete=CASCADE`), `extremo` (Integer, 1 o 2), `nodo`, `equipo`, `puerto`, `direccion`,
  `provincia` (todos String nullable).

Nuevo valor de enum `app.servicio_origen_datos`: `INGEST_PROV` — mismo mecanismo que ya usó este
repo para agregar un valor a un enum ya existente (`ALTER TYPE ... ADD VALUE` dentro de
`op.get_context().autocommit_block()`, precedente real en
`db/alembic/versions/20260811_01_cromo_botella_camara_padre.py`).

Relaciones nuevas en `Servicio`: `historial_ids` (ordenada por `orden`) y `equipos_ultima_milla`,
ambas `cascade="all, delete-orphan"`.

## Cliente PROV (`core/services/prov/`)

Paquete nuevo, mismo patrón que `core/services/cromo/` (`config.py` + `client.py`):

- `config.py`: dataclass `ProvConfig` (`base_url`, `user`, `password` vía `get_secret()`,
  `timeout`, `rate_limit_per_second=5`), `get_settings()` cacheado, valida secretos faltantes al
  construirse (no en import time).
- `client.py`: `ProvClient` con `httpx.AsyncClient` + `httpx.BasicAuth(user, password)`. Reintentos
  con backoff exponencial en errores de red/5xx (mismo criterio que `CromoClient`:
  `_REINTENTOS_MAX=3`, backoff base 1s). Excepciones propias: `ProvClientError` (fallas de
  transporte/HTTP) y `ProvServicioNoEncontradoError` (cuando `Resultado:` es un string, no un
  dict — se propaga el mensaje literal de PROV). Método principal:
  `async def obtener_contexto_servicio(nro_servicio: str) -> dict`.
- `rate_limiter.py`: `AsyncRateLimiter(rate_per_second: float)` — el nombre de clase que finalmente
  se implementó; la idea original de este diseño era un bucket de tokens, pero se shippeó pacing
  uniforme (cada turno se espacia `1/rate_per_second` del anterior, sin ráfagas), protegido con
  `asyncio.Lock`, usado como `await limiter.esperar_turno()` antes de cada request. No
  existe nada reutilizable hoy en el repo para esto (se buscó `Semaphore`/`rate_limit`/`throttle`
  sin resultados de código de negocio).

**Instancia compartida:** un único `ProvClient` (con su limiter) vive en el proceso de la API
(`uvicorn` corre sin `--workers`, confirmado en `api/Dockerfile:32` — un solo worker, así que un
limiter in-process alcanza para el endpoint on-demand). El script de backfill corre en un proceso
aparte con su propia instancia — **nota operativa, no un límite técnico**: si backfill y uso
interactivo corrieran a la vez, el máximo combinado teórico sube a ~10 req/s. No se construye un
limiter distribuido (Redis) para esto: es sobre-ingeniería para el volumen esperado: se documenta
como recomendación de no correr el backfill en horario de uso intensivo.

## Secrets

Se renombran `.secrets/api_prov_user` → `.secrets/Dev_api_prov_user_v1.txt` y
`.secrets/api_prov_pass` → `.secrets/Dev_api_prov_pass_v1.txt` (mismo patrón `Dev_`-prefix + `_v1`
que ya usa el resto de `.secrets/`, ver `db_password_v1`, `api_key_v1`). Se agregan los nombres
lógicos `api_prov_user_v1` / `api_prov_pass_v1` al bloque `secrets:` de
`deploy/docker-compose.dev.yml` y se montan en el servicio `api`. Producción queda documentada
como pendiente (sin archivos ni bloque de compose todavía — no hay ventana de despliegue en este
alcance).

## Lógica de ingesta (`core/services/prov/ingesta.py`)

Reusa **sin modificar** `consolidar_identidad_servicio`, `resolver_estado_servicio` y
`es_verificable_por_tipo_y_estado` de `core/services/servicios_consolidacion_service.py` — son
agnósticas de la fuente (Excel vs. PROV). La función `ingerir_contexto_prov(session, servicio,
contexto_raw)`:

1. Parsea `contexto_raw` (dict ya validado por el cliente) a un dataclass intermedio.
2. Llama a `consolidar_identidad_servicio` pasando `nro_servicio` (vigente) y
   `nro_servicio_original` (ancla) en el lugar de los parámetros hoy nombrados
   `numero_linea_excel`/`numero_primer_servicio` — la función no sabe ni le importa que la fuente
   ya no es un Excel.
3. Traduce `estado_comercial` → vocabulario propio (`INSTALADO`→`Activo`, `DADO BAJA`→`Baja`;
   diccionario ampliable si aparecen más valores reales) y llama a `resolver_estado_servicio`.
4. Actualiza `nombre_cliente`/`cliente`, `direccion`, `provincia`, `direccion_2`, `tipo_servicio`
   desde los campos top-level.
5. Borra y reinserta las filas de `ServicioEquipoUltimaMilla` (una por extremo presente en el
   payload) y de `ServicioHistorialId` (una por elemento de `cadena_upgrade`, o una sola sintética
   si no viene el array — usando `nro_servicio_original`, `estado_comercial` y `creacion` del
   nivel superior).
6. Marca `origen_datos = INGEST_PROV` sólo si el servicio no tenía ya un origen más autoritativo
   (mismo criterio de "no degradar" que ya aplica `resolver_estado_servicio` al estado).

## Endpoints (`api/app/routes/servicios.py`)

- `POST /servicios/prov/refrescar?id=...`: mismo criterio de búsqueda que `GET /servicios/detail`
  (query param `id`, matcheado por `or_(numero_primer_servicio, numero_linea, servicio_id)` —
  reusa la misma consulta, no introduce un `{path_param}` nuevo). Llama a
  `ProvClient.obtener_contexto_servicio`, corre `ingerir_contexto_prov`, hace commit y devuelve el
  detalle actualizado (mismo shape que `GET /servicios/detail`). Si el `Servicio` no existe en la
  DB → 404 igual que `/detail`; si el cliente levanta `ProvServicioNoEncontradoError` (PROV no
  tiene contexto para ese número) → `HTTPException(404, detail=<mensaje de PROV>)`.
- `GET /servicios/detail` (existente): se extiende el `response_model` para incluir
  `equipos_ultima_milla: list[...]` y `historial_ids: list[...]`, leyendo siempre de la DB (sin
  llamar a PROV) — decisión explícita del usuario para no acoplar la vista de detalle al
  rate-limit de PROV.
- `/servicios/ingest` (Excel): sin cambios.

## Backfill (`scripts/servicios_backfill_prov.py`)

Mismo patrón que `scripts/servicios_backfill_no_verificable_por_baja.py` (argparse `--apply`,
dry-run por default, `core.logging.setup_logging`), con un wrapper `asyncio.run(...)` para poder
usar `ProvClient` async. Reusa `ingerir_contexto_prov` — la misma función que usa el endpoint
on-demand — en vez de reimplementar el mapeo dentro del loop del script. Candidatos por default:
todas las filas de `app.servicios` con `numero_primer_servicio IS NOT NULL`, ordenadas por `id`;
acepta `--solo-ids ID1,ID2,...` para correr sobre un subconjunto acotado (uso típico: probar antes
de un `--apply` masivo). Respeta el rate limiter de 5 req/s durante todo el recorrido.

## Frontend

- `web/frontend/src/types/timeline.ts` (nuevo — primer archivo de tipos compartidos del proyecto):

  ```ts
  export interface TimelineEvent {
    id: string | number;
    fecha: string | null;
    tipo: 'upgrade_id' | 'reclamo' | 'ingreso' | 'mantenimiento';
    titulo: string;
    estado?: string;
    descripcion?: string;
    metadata?: Record<string, string | number | null>;
  }
  ```

  Se opta por una interfaz con `tipo` discriminante en vez de un componente genérico
  `<script setup generic="T">` (no hay precedente en el repo, sería el primer caso — la interfaz
  de arriba ya alcanza para admitir Reclamos/Ingresos/Mantenimientos sin sobre-diseñar).

- `web/frontend/src/components/servicios/ServiceTimeline.vue`: recibe `events: TimelineEvent[]`
  vía `defineProps`, reusa las clases ya existentes `.infra-detail-list`, `.vertical`,
  `.infra-state-chip` (definidas en `components/infra/ModalRegistros.vue`) y los tokens Nocturne de
  estado (`--color-state-ok/warn/error/idle`) para colorear por `estado`/`tipo` — nada hardcodeado
  (`nocturne-token-compliance`).
- `ServicioDetalleView.vue`: el panel "Histórico de IDs" (hoy `historicoIds`, que sólo concatena
  `alias_ids` numéricos) pasa a mapear `historial_ids` (del backend) a `TimelineEvent[]` y
  renderiza `<ServiceTimeline :events="..." />`. Se agrega un botón "Actualizar desde PROV" que
  llama al endpoint de refresco y recarga el detalle.
- `web/frontend/src/api/servicios.ts`: se extienden `ServicioItem`/`ServicioDetailResponse` con
  `equipos_ultima_milla`/`historial_ids`, y se agrega `refrescarServicioDesdeProv(id)`.

## Testing

- Unit tests puros de `core/services/prov/ingesta.py` (parseo/mapeo, sin DB), estilo
  `test_servicios_consolidacion_service.py`.
- Tests de `ProvClient` con `httpx` mockeado (`respx` o `unittest.mock`), incluyendo el caso "200
  sin contexto" → `ProvServicioNoEncontradoError`.
- Test de `AsyncRateLimiter` midiendo tiempo real transcurrido (no mockear `sleep`), para
  probar que 6 llamadas seguidas tardan ≥ 1s reales.
- Test de integración del nuevo endpoint contra Postgres real, mismo patrón que
  `test_servicios_ingest_routes.py` (mock del `ProvClient`, no llamadas reales a PROV en CI).
- **Fixtures anonimizadas**: los dos JSON reales consultados en esta sesión (con razón
  social/domicilio de clientes reales) no se commitean; se sintetizan fixtures con la misma forma
  y datos ficticios.
- Frontend: no hay suite de tests (no hay `vitest` instalado en el proyecto) — verificación manual
  en navegador contra el stack dev reconstruido, según pide `CLAUDE.md`.

## Documentación a actualizar

`docs/db.md` (tablas nuevas + enum), `docs/decisiones.md` (decisión de coexistencia Excel/PROV y
de no crear limiter distribuido), `docs/PR/2026-09-02.md`, y la sección de agentes/skills de
`CLAUDE.md`/`AGENTS.md` si corresponde señalar la nueva fuente de datos externa.

## Riesgos y decisiones explícitas

- **Rate limit combinado backfill + refresco interactivo** puede superar 5 req/s en el caso
  extremo de correr ambos a la vez — aceptado, documentado, no resuelto con infraestructura
  adicional en este alcance.
- **Traducción `estado_comercial` → `estado_servicio`** sólo cubre los dos valores observados
  (`INSTALADO`, `DADO BAJA`); valores nuevos deben agregarse al diccionario cuando aparezcan en
  datos reales (no hay forma de enumerarlos todos de antemano sin acceso a la documentación
  interna de PROV).
- **Producción** queda sin secrets/compose para PROV — se documenta el paso pendiente, no se
  implementa (no hay ventana de despliegue en el alcance de esta tarea, y este proyecto opera en
  modo "solo dev" salvo aviso puntual).
