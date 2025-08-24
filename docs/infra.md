# Nombre de archivo: infra.md
# Ubicación de archivo: docs/infra.md
# Descripción: Detalle de las redes, puertos y volúmenes del stack dockerizado

## Redes

- `lasfocas_net`: red bridge interna que conecta todos los servicios. Limita la exposición externa y permite la comunicación directa entre contenedores.

## Puertos

- `postgres` expone `5432` solo a la red interna mediante `expose`.
- `api` publica `8000:8000` para acceso HTTP desde el host.
- `nlp_intent` expone `8100` únicamente a la red interna.
- `redis` expone `6379` solo a la red interna y se activa con el perfil `worker`.
  Se utiliza como backend de la cola RQ que procesa informes de manera asíncrona.
- `ollama` expone `11434` solo a la red interna.
- `pgadmin` (perfil opcional) publica `5050:80` para administración de PostgreSQL.

## Volúmenes

- `postgres_data`: persiste los datos de la base en `/var/lib/postgresql/data`.
- `bot_data`: almacena archivos y estados del bot en `/app/data`.
- `./db/init.sql` y `./db/init_users.sh` se montan de forma de solo lectura para inicializar la base y crear usuarios.
- `ollama_data`: guarda los modelos descargados en `/root/.ollama`.

## Recursos

- `postgres`: límite de `0.5` CPU y `512MB` de RAM para contener el uso de la base.
- `api`: límite de `1` CPU y `512MB` de RAM para evitar que una carga intensa afecte al resto de servicios.
- `web`: límite de `0.5` CPU y `256MB` de RAM para servir contenido estático con bajo consumo.
- `bot`: límite de `0.5` CPU y `256MB` de RAM, suficiente para manejar mensajes sin consumir recursos excesivos.
- `worker`: límite de `0.5` CPU y `256MB` de RAM destinado a tareas en segundo plano.
- `redis`: límite de `0.25` CPU y `128MB` de RAM; solo se inicia con el perfil `worker`.
- `nlp_intent`: límite de `1` CPU y `1GB` de RAM debido al procesamiento de lenguaje natural.
- `ollama`: límite de `1` CPU y `2GB` de RAM para el servicio de modelos LLM.
- `pgadmin`: límite de `0.25` CPU y `256MB` de RAM; se usa solo para administración.

## Cola de tareas

La API y el bot encolan trabajos en Redis mediante RQ. El servicio `worker` toma los
jobs de la cola `informes` y genera los documentos sin bloquear a los clientes.

## Healthchecks

- `postgres`: ejecuta `pg_isready` para confirmar que la base responde.
- `api`: solicita `http://localhost:8000/health`.
- `web`: consulta `http://localhost:8080/health`.
- `nlp_intent`: corre `healthcheck.sh` interno.
- `bot`: ejecuta `healthcheck.sh` propio del bot.
- `worker`: realiza `python -c 'import os'` como verificación simple del intérprete.
- `redis`: usa `redis-cli ping` para confirmar disponibilidad.
- `ollama`: consulta `http://localhost:11434/api/tags`.
- `pgadmin`: consulta `http://localhost:80/login`.

## Perfiles opcionales

- `worker`: habilita `redis` y el servicio de tareas en segundo plano.
- `pgadmin`: expone una interfaz web para administración de PostgreSQL.
  Se activa con `docker compose -f deploy/compose.yml --profile pgadmin up -d`.

## Política de rotación

Las credenciales montadas como secrets deben rotarse cada 90 días.
La actualización del archivo en `deploy/secrets/` y el redeploy del servicio bastan para aplicar la rotación.
Para más detalles consultar `docs/security.md`.

## Seguridad

- `api`, `bot`, `web` y `worker` se ejecutan con un usuario no root dentro de sus contenedores, aplicando el principio de mínimos privilegios.
- El servicio `web` solo expone el puerto `8080` dentro de la red interna; para publicarlo externamente se debe configurar un proxy inverso.

## Variables de entorno

El archivo `.env.sample` es la fuente única de verdad para todas las variables de entorno. Este listado resume su propósito y origen.

Las credenciales sensibles (`POSTGRES_PASSWORD`, `POSTGRES_APP_PASSWORD`, `POSTGRES_READONLY_PASSWORD`, `TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY`, `SMTP_*`, `WEB_ADMIN_*`, `WEB_LECTOR_*`, `WEB_PASSWORD` y `NOTION_TOKEN`) se obtienen desde archivos en `/run/secrets/` cuando se utilizan Docker Secrets.

### Base de datos
- `POSTGRES_HOST`: host del contenedor de PostgreSQL.
- `POSTGRES_PORT`: puerto interno donde escucha PostgreSQL.
- `POSTGRES_DB`: nombre de la base de datos principal.
- `POSTGRES_USER`: usuario administrador del contenedor.
- `POSTGRES_PASSWORD`: contraseña del usuario administrador.
- `POSTGRES_APP_USER`: usuario de aplicación con permisos mínimos.
- `POSTGRES_APP_PASSWORD`: contraseña del usuario de aplicación.
- `POSTGRES_READONLY_PASSWORD`: contraseña del usuario de solo lectura.

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
- `BOT_RATE_LIMIT`: cantidad de mensajes permitidos por intervalo para el bot.
- `BOT_RATE_INTERVAL`: intervalo en segundos asociado a `BOT_RATE_LIMIT`.

### Web Panel
- `WEB_ADMIN_USERNAME`: usuario con permisos de administrador.
- `WEB_ADMIN_PASSWORD`: contraseña del administrador.
- `WEB_LECTOR_USERNAME`: usuario con permisos de lectura.
- `WEB_LECTOR_PASSWORD`: contraseña del usuario de lectura.
- `WEB_USERNAME`: usuario heredado para compatibilidad; equivale a `WEB_ADMIN_USERNAME`.
- `WEB_PASSWORD`: contraseña heredada para compatibilidad; equivale a `WEB_ADMIN_PASSWORD`.

### Integraciones
- `NOTION_TOKEN`: token de acceso para la API de Notion.
- `SMTP_HOST`: servidor SMTP utilizado para enviar correos.
- `SMTP_PORT`: puerto del servidor SMTP.
- `SMTP_USER`: usuario para autenticación SMTP.
- `SMTP_PASSWORD`: contraseña del usuario SMTP.
- `SMTP_FROM`: dirección de correo remitente por defecto.
