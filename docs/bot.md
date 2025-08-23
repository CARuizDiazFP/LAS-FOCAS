# Nombre de archivo: bot.md
# Ubicación de archivo: docs/bot.md
# Descripción: Guía rápida de uso del bot de Telegram

## Variables requeridas (.env)
- TELEGRAM_ALLOWED_IDS=11111111,22222222
- INTENT_THRESHOLD=0.7  # Umbral mínimo de confianza para aceptar una intención
- BOT_RATE_LIMIT=20       # Máximo de mensajes por usuario
- BOT_RATE_INTERVAL=60    # Ventana en segundos para el límite
- WORK_HOURS=false        # "true" calcula SLA en horario laboral
- SOFFICE_BIN=/usr/bin/soffice  # Opcional, habilita PDF

## Arranque con Docker

La imagen del bot copia los directorios `bot_telegram`, `modules` y `core` para
que los flujos `/sla` y `/repetitividad` funcionen correctamente.

La imagen incluye LibreOffice en modo headless, lo que permite convertir los
reportes a PDF siempre que se defina `SOFFICE_BIN=/usr/bin/soffice` en el
entorno. Si falta, el bot informa que no se generará PDF.

```bash
docker compose -f deploy/compose.yml up -d --build bot
docker compose -f deploy/compose.yml logs -f bot
```

## Healthcheck

El contenedor ejecuta `bot_telegram/healthcheck.sh` para comprobar que el proceso siga enviando latidos. Si el script falla, Docker reinicia el servicio.

## Prueba

Enviar /start desde un ID permitido.

Probar /ping y /help.

Los intentos de acceso de usuarios no incluidos en `TELEGRAM_ALLOWED_IDS` generan un log `acceso_denegado` con el `tg_user_id` y se responde "Acceso no autorizado" al remitente.

## Logging y `request_id`

- Cada actualización del bot genera un `request_id` único que se adjunta a los logs.
- La salida de `logging` está en formato JSON con los campos `service`, `action`, `tg_user_id` y `request_id`.

## Clasificación de intención

Cada mensaje de texto se envía mediante `httpx` al microservicio `nlp_intent` para determinar si es una **Consulta**, una **Acción** u **Otros**.
Se valida que la confianza esté entre `0` y `1` y se respeta el `INTENT_THRESHOLD` (0.7 por defecto): si la confianza devuelta es menor, se solicita una aclaración al usuario antes de continuar.
El bot aplica un límite de `BOT_RATE_LIMIT` mensajes por `BOT_RATE_INTERVAL` segundos por usuario; si se excede, responde "Rate limit alcanzado".
Cuando el microservicio devuelve `429 Too Many Requests`, se informa "Servicio saturado".

## Menú principal

El bot ofrece un menú accesible por el comando `/menu` o mediante mensajes clasificados como **Acción** que contengan la intención de abrirlo.

Botones disponibles:

- 📈 Análisis de SLA
- 📊 Informe de Repetitividad
- ❌ Cerrar

Los flujos de **Repetitividad** y **SLA** están operativos.

El comando `/repetitividad` valida la estructura del Excel recibido y genera un
DOCX. Si se define `SOFFICE_BIN`, también genera un PDF. Tras enviar los
archivos, el bot responde con enlaces a cada formato.

Ejemplos de frases que abren el menú por intención:

- "bot abrí el menú"
- "abrir menú"
- "mostrar menú"

## Notas

Modo: long polling (no requiere URL pública).

Futuro: migrar a webhooks (reverse proxy + TLS) si se necesita menor latencia.

______________________________________________________________________

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

## Casos de prueba automatizados

Las pruebas `tests/test_bot_conversations.py` cubren conversaciones completas de los flujos `/sla` y `/repetitividad`.
Se simulan respuestas del microservicio `nlp_intent` y se generan archivos de ejemplo en tiempo de prueba para verificar la creación de reportes en formatos DOCX y PDF.
