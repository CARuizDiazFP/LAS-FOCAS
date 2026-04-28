# Nombre de archivo: bot.md
# Ubicación de archivo: docs/bot.md
# Descripción: Guía rápida de uso del bot de Telegram

## Variables requeridas (.env)
- TELEGRAM_BOT_TOKEN=...
- TELEGRAM_ALLOWED_IDS=11111111,22222222
- REPORTS_API_BASE=http://api:8000 *(endpoint REST para generar informes)*
- REPORTS_API_TIMEOUT=60 *(opcional, segundos de espera para la llamada)*

## Dependencias clave
- Paquetes Python: `matplotlib==3.9.2`, `contextily==1.5.2`, `pyproj==3.6.1` (incluidos en `bot_telegram/requirements.txt`).
- Paquetes nativos en Docker: `gdal-bin`, `libgdal-dev`, `libproj-dev`, `libgeos-dev`, `build-essential` (instalados en `deploy/docker/bot.Dockerfile`).
- El bot reutiliza `modules.informes_repetitividad` para generar DOCX/PDF/PNG; asegurar acceso a `Templates/` y al volumen de reportes si se requiere persistencia.

## Arranque con Docker
```bash
docker compose -f deploy/compose.yml up -d --build bot
docker compose -f deploy/compose.yml logs -f bot
```

## Prueba

Enviar /start desde un ID permitido.

Probar /ping y /help.

Los intentos de acceso de usuarios no incluidos en `TELEGRAM_ALLOWED_IDS` generan un log `acceso_denegado` con el `tg_user_id` y se responde "Acceso no autorizado" al remitente.

## Clasificación de intención

Cada mensaje de texto se envía al microservicio `nlp_intent` para determinar si es una **Consulta**, una **Acción** u **Otros**.
El bot responde con un resumen de la intención detectada. Si la confianza es baja, solicita una aclaración al usuario.

## Menú principal

El bot ofrece un menú accesible por el comando `/menu` o mediante mensajes clasificados como **Acción** que contengan la intención de abrirlo.

Botones disponibles:

- 📈 Análisis de SLA
- 📊 Informe de Repetitividad
- ❌ Cerrar

Los flujos de **Repetitividad** y **SLA** están operativos. Repetitividad consume el endpoint `POST /reports/repetitividad` de la API y reutiliza el mismo backend que la UI web.
Cuando el dataset incluye coordenadas, el bot envía el DOCX, adjunta el PDF (si se generó) y reenvía cada mapa en formato PNG.

Ejemplos de frases que abren el menú por intención:

- "bot abrí el menú"
- "abrir menú"
- "mostrar menú"

## Notas

Modo: long polling (no requiere URL pública).

Futuro: migrar a webhooks (reverse proxy + TLS) si se necesita menor latencia.

---

## Acciones para el Usuario (VM)
1. **Agregar variables al `.env`** (si no están):

```
TELEGRAM_BOT_TOKEN=tu_token
TELEGRAM_ALLOWED_IDS=11111111,22222222
```

2. **Levantar el servicio del bot**:
```bash
cd ~/proyectos/LAS-FOCAS
docker compose -f deploy/compose.yml up -d --build bot
docker compose -f deploy/compose.yml logs -f bot
```

Probar desde Telegram con un ID permitido: /start, /ping.

## Siguientes pasos (tras validar “pong” 🏓)

Conectar el bot a la API para comandos reales (ej. “/repetitividad mes=08 año=2025” → job en worker o API).

Añadir /status que consulte http://api:8000/health.

Registrar métricas de uso y logs estructurados.

Añadir menú de comandos y ayudas contextuales.

(Luego) migrar a webhooks detrás de un reverse proxy (cuando haya URL pública/SSL).

## Flujos unificados (comando y botón)

Los comandos `/sla` y `/repetitividad` ejecutan exactamente las mismas funciones que los botones del menú principal. De esta manera se evita duplicar lógica y se puede diagnosticar fácilmente cualquier problema de callbacks.

Ejemplos:

- `/sla` y botón **📈 Análisis de SLA** comparten `start_sla_flow`.
- `/repetitividad` y botón **📊 Informe de Repetitividad** comparten `start_repetitividad_flow`.

### ReplyKeyboard
El comando `/keyboard` muestra un teclado con atajos (`/sla`, `/repetitividad`, `/menu`, `/hide`).
El comando `/hide` lo oculta.

Para un diagnóstico rápido está disponible `/diag`, que muestra los contadores de invocaciones recibidas:

```
/diag
commands_sla: X | callbacks_sla: Y
commands_rep: A | callbacks_rep: B
```

Los registros (`logging`) incluyen `route`, `cmd` o `data`, y `tg_user_id` para facilitar el seguimiento.

---

## Monitor de Ingresos Técnicos (Slack)

El `IngresoListener` (`modules/slack_baneo_notifier/listener.py`) escucha en tiempo real los formularios de ingreso técnico enviados en un canal de Slack via Socket Mode y responde en el **hilo** del mensaje con el estado de baneo de la cámara.

### Variables de entorno requeridas

| Variable | Descripción |
|---|---|
| `SLACK_BOT_TOKEN` | Token del bot (`xoxb-...`) — ya usado por el worker de baneos |
| `SLACK_APP_TOKEN` | Token de Socket Mode (`xapp-...`) — nuevo, exclusivo del listener |

### Configuración en la DB (`app.config_servicios`)

El servicio se identifica con `nombre_servicio = 'slack_ingreso_listener'` y tiene los siguientes campos relevantes:

| Campo | Tipo | Descripción |
|---|---|---|
| `slack_channels` | `VARCHAR(512)` | ID del canal Slack a monitorear (ej. `C08UB8ML3LP`) |
| `activo` | `BOOLEAN` | Habilita o deshabilita el listener |
| `workflow_ids` | `VARCHAR(512)` | IDs de Workflow de Slack permitidos, separados por coma. `NULL` = sin restricción |
| `solo_workflows` | `BOOLEAN` | Si `TRUE`, solo procesa mensajes cuyo `workflow_id` esté en `workflow_ids` |

### Lógica de filtrado (campo `solo_workflows`)

- **`solo_workflows = FALSE`** (modo Dev): el bot responde a cualquier mensaje de texto en el canal. Útil durante desarrollo y pruebas.
- **`solo_workflows = TRUE`**: el bot solo responde si el evento trae un `workflow_id` y ese ID está en la lista `workflow_ids`. Mensajes de usuarios y Workflows no configurados son ignorados silenciosamente.
- Si `workflow_ids` está vacío y `solo_workflows = TRUE`, se acepta cualquier Workflow (sin filtrar por ID específico).

### Cómo obtener el Workflow ID

El `workflow_id` aparece en el log del worker (campo `workflow_id` del evento Slack) o en la URL del Workflow dentro de la configuración de Slack Workflows. Ejemplo: `Wf0B0KJF68BS`.

### Estados de cámara

| Estado | Comportamiento |
|---|---|
| `LIBRE` | ✅ Sin incidentes — se permite el ingreso |
| `DETECTADA` | ✅ Sin incidentes — se permite el ingreso (tracking inicial, no implica baneo) |
| `BANEADA` | 🚨 Se reporta el incidente de baneo activo — no acceder |

> Las cámaras recién detectadas (`DETECTADA`) ya no generan alertas erróneas de restricción a menos que tengan un incidente de baneo registrado y activo.

### Normalización de nombres de cámara (`camara_search.py`)

La búsqueda en DB usa `modules/slack_baneo_notifier/camara_search.py`.  
El preprocesamiento aplica en orden:

1. **Limpieza de puntuación** (`_limpiar_puntuacion`) — elimina comas, punto y coma, puntos no entre dígitos, y guiones con espacios (` - ` → ` `).
2. **Expansión de abreviaturas** (`_expandir_abreviaturas`) — reemplaza prefijos viales comunes.
3. **Normalización** (`_normalizar`) — unidecode + lowercase + espacios simples.
4. **Sinónimos** (`_aplicar_sinonimos`) — reemplaza términos semánticos equivalentes:

| Término escrito | Reemplazado por |
|---|---|
| `botella` | `bot` |
| `camara` *(post-unidecode de "cámara")* | `cra` |

Luego se aplica la estrategia en cascada de 4 intentos sobre el texto preprocesado:

1. **ILIKE directo** — `%nombre_norm%` sobre `Camara.nombre` **y** `CamaraAlias.alias_nombre`
2. **Tokens AND** — todos los tokens (≥ 3 chars) presentes, en nombre o alias
3. **Sin números** — reintenta 1 y 2 descartando dígitos (**omitido** si el input contiene números, ver Regla de Numeración)
4. **Sin expansión** *(fallback)* — reintenta con el nombre raw + limpieza + sinónimos, SIN expandir abreviaturas; cubre el caso en que la DB almacena la abreviatura literal (ej.: `Cra`)

#### Regla de Numeración

Si el input contiene uno o más números (ej.: `440`), solo se aceptan cámaras cuyo nombre los contenga **exactamente como palabras completas** (`\b440\b`). Esto evita emparejar `Cra Mitre 440` con `Cra Mitre 399`.  
Adicionalmente, el **Intento 3 se omite** cuando hay números en el input, ya que buscar sin dígitos ampliaría incorrectamente los candidatos.

#### Regla de Botella / Bot secundario

Si el técnico **no** menciona `bot` ni `botella` en su mensaje, los resultados de DB que coincidan con `Bot [2-9]` (bots secundarios) se descartan automáticamente. Esto evita que "Cra Bartolomé Mitre 440" empareje "Bot 2 Cra Bartolomé Mitre 440".  
Si el técnico escribe explícitamente "botella" o "bot", el filtro se desactiva para ese mensaje.

#### Abreviaturas expandidas

| Abreviatura | Expansión |
|---|---|
| `clle`, `all` | `calle` |
| `av`, `ave` | `avenida` |
| `pje`, `pas` | `pasaje` |
| `bv`, `blvd` | `boulevard` |
| `dr` | `doctor` |
| `pte` | `presidente` |
| `sn` | `san` |
| `sta` | `santa` |
| `sto` | `santo` |
| `cf` | *(eliminado — código de filial)* |

> **`cra` no se expande.** En los nombres de cámara, "Cra" se usa de forma literal (ej.: `Bot 2 Cra Poste 202 Vias FFCC Roca Hudson`). El Intento 4 garantiza encontrar la cámara incluso si otras abreviaturas modificaron el query.

### Auto-registro de cámaras desconocidas

Cuando `buscar_camara()` retorna `None`, el listener **auto-registra** la cámara en la DB con:
- `estado = PENDIENTE_REVISION`
- `origen_datos = MANUAL`
- `last_update = now()`

Y responde al técnico:
> ✅ Cámara no registrada previamente, se registra automáticamente bajo revisión. Sin incidentes activos. Podés proceder.

El administrador luego revisa las cámaras pendientes desde el panel `/admin/Servicios/Baneos` → sección **🔄 Cámaras Pendientes de Revisión** y puede:
- **Aprobar** → cambia el estado a `LIBRE` (mantiene el nombre tal como lo escribió el técnico)
- **Convertir en Alias** → crea un registro en `app.camara_alias` vinculado a una cámara existente y elimina el registro pendiente
- **Definir Nombre Canón** → permite editar el nombre al formato oficial y lo promueve a `LIBRE`; el nombre original del técnico queda guardado automáticamente como un alias en `app.camara_alias` para que futuras búsquedas del mismo término sigan resolviendo esta cámara

### Configuración desde el panel web

La sección **🎧 Monitor de Ingresos** en `/admin/Servicios/Baneos` permite:
- Ingresar el **Canal de Slack** (ID o #nombre)
- Activar/desactivar el toggle **Filtrar mensajes de usuario** (mapea a `solo_workflows`)
- Ingresar los **Workflow IDs permitidos** (se habilita solo si el filtro está activo)
- Activar/desactivar el monitor completo
