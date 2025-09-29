# Nombre de archivo: web.md
# Ubicación de archivo: docs/web.md
# Descripción: Documentación del microservicio Web (UI + FastAPI)

# Web (UI) — LAS-FOCAS

## Resumen

Servicio FastAPI que expone:
- UI dark-style con barra de botones (SLA, Repetitividad, Comparador FO).
- Chat REST que integra `nlp_intent` para clasificación de intención.

## Estructura y archivo principal

La implementación única de la aplicación vive en `web/web_app/main.py` y el contenedor la lanza con:
```
uvicorn web_app.main:app --host 0.0.0.0 --port 8080
```
Anteriormente existía un duplicado en `web/app/main.py` que fue eliminado (se dejó un stub temporal hasta su retiro definitivo). Cualquier referencia antigua debe migrarse a `web_app.main`.

## Logging

Centralizado vía `core.logging.setup_logging`.

- Formato: `timestamp service=<servicio> level=<nivel> msg=<mensaje>`.
- Variable `LOG_LEVEL` (ej: DEBUG, INFO, WARNING) controla el nivel base.
- En `ENV=development` se escribe además a `Logs/web.log` (rotativo 5MB x3). En otros entornos sólo stdout.
- Archivos ignorados por git (`Logs/`).
- Eventos clave:
  - `action=login result=success|fail|error ...`
  - Errores de bcrypt / DB → nivel ERROR / stacktrace con `logger.exception`.
  - Futuro: métricas y auditoría podrán centralizarse en `api`.


## Endpoints

- GET /health → status simple.
- GET /login → formulario de login.
- POST /login → autentica con app.web_users (bcrypt). Rate limit: 5/min por sesión.
- GET /logout → cierra sesión.
- GET / → panel (requiere sesión). Inyecta API_BASE y CSRF en la plantilla.
- POST /api/chat/message → clasifica texto usando NLP. Requiere CSRF si hay sesión. Rate limit: 30/min por sesión.
- POST /api/users/change-password → Cambiar contraseña del usuario autenticado. Form fields: current_password, new_password, csrf_token. Respuestas: {status:"ok"} o {error}.
- POST /api/admin/users → Crear usuario (sólo admin). Form fields: username, password, role?, csrf_token. Respuestas: {status:"ok"} o {error}.
 - POST /api/flows/sla → Ejecuta flujo de SLA. FormData: file, mes, anio, csrf_token. Responde enlaces /reports/*.docx[.pdf].
 - POST /api/flows/repetitividad → Ejecuta flujo de Repetitividad. FormData: file, mes, anio, csrf_token.
 - POST /api/flows/comparador-fo → Placeholder (501) hasta implementar.

Respuesta típica de /api/chat/message:

```json
{
  "reply": "string",
  "intent": "Consulta|Acción|Otros",
  "confidence": 0.0,
  "provider": "heuristic|ollama|openai"
}
```

## Frontend (Vite + TypeScript)

- El bundle se copia a /static/assets con nombre estable `assets/main.js`.
- La plantilla `web/templates/index.html` inyecta variables globales:
  - `window.API_BASE` (default `http://192.168.241.28:8080`).
  - `window.CSRF_TOKEN` (token actual de sesión).
- El cliente TS envía `credentials: 'include'` y adjunta `csrf_token` en POST al chat.

## Variables de entorno

- `NLP_INTENT_URL` (default: `http://nlp_intent:8100`)
- `LOG_RAW_TEXT` ("true"/"false")
- `WEB_SECRET_KEY` (secreto para la cookie de sesión; obligatorio en prod)
- `API_BASE` (opcional; base usada por la plantilla para el frontend)

## Docker/Compose

- Servicio `web` expuesto en `8080:8080`.
- `api` remapeado a `8001:8000` para evitar conflicto en la VM.
- Por defecto, la UI y `nlp_intent` usan Ollama externo vía `http://host.docker.internal:11434` (se añade `extra_hosts` al compose).
- Alternativa: ejecutar `./Start --with-internal-ollama` para levantar un servicio `ollama` interno al stack.
 - El servicio `web` expone `/reports` como estático para descargar los resultados.

## Conectividad y troubleshooting

- Acceso por IP privada: la política por defecto usa `http://192.168.241.28:8080` como URL de la UI. Si desde el propio host puedes hacer `curl http://localhost:8080/health` pero falla `curl http://192.168.241.28:8080/health`, revisa:
  - Reglas de firewall (ufw/iptables/nftables) permitiendo inbound a 8080/8001 en la interfaz de la VM.
  - Modo de red de Docker (bridge por defecto expone en 0.0.0.0; verificar con `ss -ltnp | grep 8080`).
  - Que la IP privada sea la correcta (`ip -4 addr`). Si cambia, actualiza `API_BASE` en `.env` y recompila el servicio web.
  - Si hay proxy/restricciones en tu red corporativa.

- Nota: la aplicación server-side no necesita conocer la IP privada para escuchar; Docker mapea `0.0.0.0:8080->8080`. La variable `API_BASE` se usa para que el frontend sepa a qué host hablar.

## Seguridad

- SessionMiddleware con cookie firmada (`WEB_SECRET_KEY`).
- CSRF por token de sesión inyectado en la plantilla.
- Rate limiting básico en login (5/min) y chat (30/min) por sesión.
- Roles: admin/user. Endpoints admin exigen role "admin".
 - Roles soportados: Admin, OwnerGroup, Invitado (se almacenan en minúsculas: admin/ownergroup/invitado). Endpoints admin exigen role "admin".

## Próximos pasos

- Agregar página Admin (UI) para crear usuarios y cambiar contraseña.
- Conectar botones a flujos SLA/Repetitividad/Comparador FO.
- WebSocket/streaming con Ollama y feedback de progreso.
- Tests de integración adicionales y documentación de uso.
