# Nombre de archivo: bot.md
# Ubicación de archivo: docs/bot.md
# Descripción: Guía rápida de uso del bot de Telegram

## Variables requeridas (.env)
- TELEGRAM_BOT_TOKEN=...
- TELEGRAM_ALLOWED_IDS=11111111,22222222

## Arranque con Docker
```bash
docker compose -f deploy/compose.yml up -d --build bot
docker compose -f deploy/compose.yml logs -f bot
```

## Prueba

Enviar /start desde un ID permitido.

Probar /ping y /help.

Ver logs para validar que usuarios no permitidos no reciben respuesta.

## Clasificación de intención

Cada mensaje de texto se envía al microservicio `nlp_intent` para determinar si es una **Consulta**, una **Acción** u **Otros**.
El bot responde con un resumen de la intención detectada. Si la confianza es baja, solicita una aclaración al usuario.

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
