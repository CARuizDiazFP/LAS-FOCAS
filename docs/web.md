# Nombre de archivo: web.md
# Ubicación de archivo: docs/web.md
# Descripción: Documentación del microservicio Web (UI + FastAPI)

# Web (UI) — LAS-FOCAS

## Resumen

Servicio FastAPI que expone:
- UI dark-style con Panel (Chat por defecto y tabs: Repetitividad, Comparador FO) y una vista independiente `/sla`.
- Chat REST que integra `nlp_intent` para clasificación de intención y persistencia de conversación.

## Estructura y archivo principal

La implementación única de la aplicación vive en `web/web_app/main.py` y el contenedor la lanza con:
```
uvicorn web_app.main:app --host 0.0.0.0 --port 8080
```
Se sirve estático en `/static` y se monta el directorio de reportes en `/reports`. El listado histórico se sirve en `/reports-history` (evita colisión con el mount estático de `/reports`).

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
- GET /sla → vista minimalista con dropzone (1-2 `.xlsx`), selector de período y opciones básicas (PDF, usar DB).
- GET /reports-history → listado HTML de archivos generados (enlaces directos a /reports/*).
- GET /reports/index → redirección a /reports-history (compatibilidad).
- POST /api/chat/message → clasifica texto usando NLP. Requiere CSRF si hay sesión. Rate limit: 30/min por sesión. Devuelve `conversation_id` y `history` (≤6 últimos mensajes) cuando hay sesión.
- GET /api/chat/history?limit=N → devuelve últimos N (máx 100) mensajes y `conversation_id` del usuario autenticado.
- GET /api/chat/metrics → métricas simples en memoria (`intent_counts`). Uso interno/debug, se reinicia al reiniciar el contenedor.
- POST /api/users/change-password → Cambiar contraseña del usuario autenticado. Form fields: current_password, new_password, csrf_token. Respuestas: {status:"ok"} o {error}.
- POST /api/admin/users → Crear usuario (sólo admin). Form fields: username, password, role?, csrf_token. Respuestas: {status:"ok"} o {error}.
- POST /api/reports/sla → Endpoint del microservicio `web` empleado por la vista `/sla`. FormData: `mes`, `anio`, `periodo_mes?`, `periodo_anio?`, `pdf_enabled?`, `use_db?`, `files*` (0–2 `.xlsx`), `csrf_token`. Si `use_db=true` se ignoran adjuntos; si se adjuntan dos archivos se combinan en memoria antes de delegar en `core.services.sla`. Devuelve `{ ok, message, report_paths: {docx, pdf?}, source }`.
- POST /api/flows/sla → Ejecuta flujo SLA completo reutilizando `core.services.sla`. FormData: `file?`, `mes`, `anio`, `usar_db?`, `incluir_pdf?`, `eventos?`, `conclusion?`, `propuesta?`, `csrf_token`. Cuando `usar_db=true` se ignora el archivo y se consulta la base. Responde JSON con enlaces `/reports/*.docx[.pdf]`, indicador `source` y métricas básicas del período.
- POST /api/flows/repetitividad → Ejecuta flujo de Repetitividad reutilizando los servicios compartidos (`generar_informe_desde_excel` / `generar_informe_desde_dataframe`). FormData: `file?`, `mes`, `anio`, `include_pdf?`, `csrf_token`, `with_geo?`, `use_db?`. Respuesta JSON con `docx`, `pdf?`, `map_images` (lista de PNGs), `assets` (alias de `map_images`), `map_image` (primer PNG), `stats`, `source` y flags `pdf_requested`/`with_geo`.
- POST /api/flows/comparador-fo → Placeholder (501) hasta implementar.

Respuesta típica de /api/chat/message (nuevo pipeline):

```json
{
  "reply": "texto placeholder o pregunta",
  "intention_raw": "Consulta|Acción|Otros",
  "intention": "Consulta/Generico|Solicitud de acción|Otros",
  "confidence": 0.88,
  "provider": "openai",
  "normalized_text": "...",
  "need_clarification": false,
  "clarification_question": null,
  "next_action": null,
  "action_code": "repetitividad_report|unsupported|null",
  "action_supported": true,
  "action_reason": "keyword:repetitividad,verb:accion",
  "answer": "(si es consulta)",
  "answer_source": "faq|openai|ollama|heuristic|disabled",
  "domain_confidence": 0.9,
  "schema_version": 2,
  "conversation_id": 12,
  "history": [ {"role":"user", "text":"hola"}, {"role":"assistant", "text":"¿Podrías ampliar?"} ]
}
```

Respuesta típica de `/api/flows/repetitividad` (modo Excel + GEO):

```json
{
  "status": "ok",
  "source": "excel",
  "pdf_requested": true,
  "with_geo": true,
  "docx": "/reports/repetitividad_202407.docx",
  "pdf": "/reports/repetitividad_202407.pdf",
  "map_images": [
    "/reports/repetitividad_202407_servicio_a.png",
    "/reports/repetitividad_202407_servicio_b.png"
  ],
  "map_image": "/reports/repetitividad_202407_servicio_a.png",
  "assets": [
    "/reports/repetitividad_202407_servicio_a.png",
    "/reports/repetitividad_202407_servicio_b.png"
  ],
  "stats": {
    "filas": 42,
    "repetitivos": 7,
    "periodos": ["2024-06", "2024-07"]
  }
}
```

  Notas clave del flujo:
  - El DOCX resultante reemplaza la portada con el período solicitado, elimina columnas Lat/Lon y muestra Horas Netas formateadas como `HH:MM`.
  - Los mapas `.png` se generan por servicio cuando hay coordenadas válidas y se escalan para no superar media hoja A4 al incrustarse en el informe.
  - La API complementa la respuesta con headers `X-Source`, `X-With-Geo`, `X-PDF-*`, `X-Map-*`, `X-Maps-Count` y `X-Total-*` para trazabilidad en el panel.

## Frontend (JS estático)

- La plantilla `web/templates/panel.html` inyecta variables globales:
  - `window.API_BASE` (default `http://192.168.241.28:8080`).
  - `window.CSRF_TOKEN` (token actual de sesión).
- El cliente principal (`/static/panel.js`) maneja los tabs activos (Chat, Repetitividad, Comparador FO) y coordina envíos al backend, incluido el Chat HTTP (`/api/chat/message`) y uploads (`/api/chat/uploads`).
- La vista `/sla` usa `web/templates/sla.html` + `/static/sla.js`, con drag&drop (hasta 2 `.xlsx`), alternancia Excel/DB, validación de período y mensajes accesibles que muestran los enlaces devueltos por `POST /api/reports/sla`.

## Variables de entorno

- `NLP_INTENT_URL` (default: `http://nlp_intent:8100`)
- `LOG_RAW_TEXT` ("true"/"false")
- `WEB_SECRET_KEY` (secreto para la cookie de sesión; obligatorio en prod)
- `API_BASE` (opcional; base usada por la plantilla para el frontend)
- `TEMPLATES_DIR` (ruta interna a las plantillas de informes; por convención apuntar a `Templates/` en la raíz del repo o al volumen montado en Docker).
- `REPORTS_API_BASE` (base del servicio API para `POST /reports/*`; default `http://api:8000`).
- `REPORTS_API_TIMEOUT` (timeout en segundos para la consulta al servicio de reportes; default `60`).

### Nota sobre OpenAI (clasificación de intención)
### Memoria conversacional (persistencia)

El endpoint `/api/chat/message` persiste mensajes (rol `user` y `assistant`) en las tablas `app.conversations` y `app.messages` reutilizando un pseudo-id derivado del `username` (hash sha256 truncado). Esto permite en iteraciones futuras:
- Recuperar contexto para generación de respuestas.
- Auditar interacciones.
- Extender a analíticas (tiempo entre turnos, intents frecuentes).

El payload ahora incluye `conversation_id` y `history` (últimos ≤6 mensajes) cuando el usuario está autenticado. `conversation_id` permite correlación y posteriores recuperaciones vía `/api/chat/history`.

Sanitización: antes de enviar el texto al servicio NLP se filtran caracteres de control Unicode (categoría C) excepto salto de línea y tabulaciones para reducir ruido y riesgos de logs corruptos.

Métricas: contador en memoria `INTENT_COUNTER` incrementa por intención mapeada y se expone en `/api/chat/metrics` (reinicia en cada despliegue; persistencia futura pendiente).
Persistencia de métricas (MVP): si `METRICS_PERSIST_PATH` está definido (default `data/intent_metrics.json`) se guarda el JSON tras cada incremento mediante reemplazo atómico (archivo `.tmp`).

El servicio `nlp_intent` ahora arranca con `LLM_PROVIDER=openai` por defecto. Esto implica:
- Debe definirse `OPENAI_API_KEY` en `.env` / secretos antes de levantar el contenedor.
- Si la clave falta, el servicio falla en el arranque (fail-fast) para evitar clasificaciones inconsistentes.
- Para pruebas sin costo o sin conectividad se puede exportar temporalmente `LLM_PROVIDER=heuristic` o `LLM_PROVIDER=auto` (con fallback a heurística) siempre que se ajusten los tests a esa configuración.
- `OLLAMA_URL` sigue presente para futura generación local o fallback manual, pero no se usa mientras `LLM_PROVIDER=openai`.

## Docker/Compose

- Servicio `web` expuesto en `8080:8080`.
- `api` remapeado a `8001:8000` para evitar conflicto en la VM.
- Por defecto, la UI y `nlp_intent` usan Ollama externo vía `http://host.docker.internal:11434` (se añade `extra_hosts` al compose).
- Alternativa: ejecutar `./Start --with-internal-ollama` para levantar un servicio `ollama` interno al stack.
- El servicio `web` expone `/reports` como estático para descargar los resultados y `/reports-history` como listado HTML.
- `web` monta `../Templates:/app/Templates:ro` para consumir las plantillas oficiales al invocar la API de reportes.
- Las imágenes `api`, `web` y `bot` instalan `gdal-bin`, `libgdal-dev`, `libproj-dev`, `libgeos-dev` y `build-essential` para soportar `matplotlib/contextily/pyproj` en la generación de mapas PNG.

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
