# Nombre de archivo: infra.md
# Ubicación de archivo: docs/infra.md
# Descripción: Detalle de las redes, puertos y volúmenes del stack dockerizado

## Redes

- `lasfocas_net`: red bridge interna que conecta todos los servicios. Limita la exposición externa y permite la comunicación directa entre contenedores.

## Puertos

- `postgres` expone `5432` solo a la red interna mediante `expose`.
- `api` publica `8000:8000` para acceso HTTP desde el host.
- `nlp_intent` expone `8100` únicamente a la red interna.
- `pgadmin` (perfil opcional) publica `5050:80` para administración de PostgreSQL.

## Volúmenes

- `postgres_data`: persiste los datos de la base en `/var/lib/postgresql/data`.
- `bot_data`: almacena archivos y estados del bot en `/app/data`.
- `./db/init.sql` se monta de forma de solo lectura para inicializar la base.

## Variables de entorno

### Base de datos
- `POSTGRES_HOST`: host del contenedor de PostgreSQL.
- `POSTGRES_PORT`: puerto interno donde escucha PostgreSQL.
- `POSTGRES_DB`: nombre de la base de datos principal.
- `POSTGRES_USER`: usuario con permisos completos.
- `POSTGRES_PASSWORD`: contraseña del usuario de la base.

### Bot de Telegram
- `TELEGRAM_BOT_TOKEN`: token otorgado por BotFather.
- `TELEGRAM_ALLOWED_IDS`: IDs de usuarios autorizados separados por coma.

### NLP / LLM
- `LLM_PROVIDER`: proveedor de LLM a utilizar (`auto` selecciona según disponibilidad).
- `OPENAI_API_KEY`: clave para la API de OpenAI.
- `OLLAMA_URL`: URL del servicio Ollama interno.
- `INTENT_THRESHOLD`: umbral mínimo de confianza para aceptar una intención.
- `LANG`: código de idioma por defecto.
- `LOG_RAW_TEXT`: habilita el registro del texto completo recibido.
- `CACHE_TTL`: tiempo en segundos para mantener en caché respuestas del NLP.

### Informes
- `SLA_TEMPLATE_PATH`: ruta al archivo de plantilla para informes de SLA.
- `REP_TEMPLATE_PATH`: ruta a la plantilla de informes de repetitividad.
- `REPORTS_DIR`: carpeta donde se guardan los reportes generados.
- `UPLOADS_DIR`: carpeta para archivos subidos por usuarios.
- `SOFFICE_BIN`: binario de LibreOffice usado para convertir documentos.
- `MAPS_ENABLED`: habilita la generación de mapas en los informes.
- `MAPS_LIGHTWEIGHT`: utiliza mapas simplificados para reducir consumo.

### Rate limiting
- `API_RATE_LIMIT`: límite de peticiones por minuto para la API.
- `NLP_RATE_LIMIT`: límite de peticiones por minuto para nlp_intent.
