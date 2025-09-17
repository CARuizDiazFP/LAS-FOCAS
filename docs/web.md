# Nombre de archivo: web.md
# Ubicación de archivo: docs/web.md
# Descripción: Documentación del microservicio Web (UI + FastAPI)

# Web (UI) — LAS-FOCAS

## Resumen

Servicio FastAPI que expone:
- UI dark-style con barra de botones (SLA, Repetitividad, Comparador FO).
- Chat REST que integra `nlp_intent` para clasificación de intención.

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
  - `window.API_BASE` (default `http://localhost:8080`).
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
