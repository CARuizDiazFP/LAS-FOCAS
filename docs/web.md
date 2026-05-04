# Nombre de archivo: web.md
# Ubicación de archivo: docs/web.md
# Descripción: Documentación del microservicio Web (SPA Vue 3 + FastAPI REST)

# Web (UI) — LAS-FOCAS

## Resumen

Servicio FastAPI que sirve un **SPA Vue 3** (Vite) y expone endpoints REST JSON.  
El backend **no usa Jinja2 ni archivos estáticos legacy** (`web/templates/` y `web/static/` fueron eliminados).  
El frontend SPA vive en `web/frontend/` y se compila a `web/frontend/dist/` que el contenedor copia en `/app/frontend/dist`.

## Arquitectura SPA

```
[Cliente]  <──HTTP──>  [FastAPI web:8080]
                          │
                          ├─ /assets/*       → Vite build assets (JS/CSS/fonts)
                          ├─ /reports/*      → archivos de reportes generados
                          ├─ /api/**         → endpoints REST JSON
                          └─ /{path:path}    → SPA catch-all → index.html
```

El **catch-all** `GET /{path:path}` sirve `frontend/dist/index.html` para todas las rutas que no coincidan con las montadas antes. Esto permite que Vue Router maneje el routing del lado cliente, incluyendo recargas de página.

> **IMPORTANTE**: El catch-all siempre se define como ÚLTIMA ruta en `main.py`. Si se agregasen rutas nuevas, deben ir ANTES del catch-all.

## Estructura y archivo principal

```
web/
  app/main.py          ← FastAPI app: API REST + SPA serving
  frontend/
    src/               ← código fuente Vue 3 + TypeScript
    dist/              ← build Vite (generado, no en git)
    vite.config.ts
    index.html
  Dockerfile           ← multi-stage: Node 20 build → Python serve
```

El contenedor se lanza con:
```
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

## Autenticación y sesión

- Cookie de sesión (`starlette.middleware.sessions.SessionMiddleware`).
- Keys de sesión: `username`, `role`, `csrf`.
- **No hay rutas HTML de login**: el SPA usa los endpoints JSON de autenticación.

### Endpoints de autenticación

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/api/auth/session` | Devuelve estado de sesión actual (sin auth requerida). Respuesta: `{authenticated, username, role, csrf}` |
| `POST` | `/api/auth/login` | Login vía JSON `{username, password}`. Rate limit: 5 intentos/min. Respuesta: `{ok, username, role, csrf}` o `{ok:false, error}` |
| `POST` | `/api/auth/logout` | Cierra sesión. Respuesta: `{ok: true}` |
| `GET` | `/logout` | Compatibilidad hacia atrás — limpia sesión y redirige a `/` (el SPA detecta sesión vacía y muestra login) |

### CSRF

El token CSRF se incluye en la respuesta de `/api/auth/session` y `/api/auth/login`. El composable `useSession.ts` lo almacena y lo inyecta en `window.CSRF_TOKEN` para compatibilidad con el código admin existente.  
Todos los endpoints POST que mutan datos validan el CSRF token.

## Logging

Centralizado vía `core.logging.setup_logging`.

- Formato: `timestamp service=<servicio> level=<nivel> msg=<mensaje>`.
- Variable `LOG_LEVEL` (ej: DEBUG, INFO, WARNING) controla el nivel base.
- En `ENV=development` se escribe además a `Logs/web.log` (rotativo 5MB x3). En otros entornos sólo stdout.
- Archivos ignorados por git (`Logs/`).
- Eventos clave:
  - `action=api_login result=success|fail|error ...`
  - Errores de bcrypt / DB → nivel ERROR / stacktrace con `logger.exception`.

## Endpoints de datos

- `GET /health` → status simple.
- `GET /reports/index` → redirección a `/reports-history` (compatibilidad).
- `GET /api/reports/history` → JSON `{files: [{name, size, mtime, href}]}` — lista de reportes. Requiere auth.
- `POST /api/chat/message` → clasifica texto usando NLP. Requiere CSRF si hay sesión. Rate limit: 30/min.
- `GET /api/chat/history?limit=N` → últimos N (máx 100) mensajes. Devuelve `conversation_id` y `history`.
- `GET /api/chat/metrics` → métricas simples en memoria.
- `POST /api/users/change-password` → Form: `current_password, new_password, csrf_token`.
- `POST /api/admin/users` → Crear usuario (admin). Form: `username, password, role?, csrf_token`.
- `POST /api/reports/sla` → informe SLA. FormData: `mes, anio, periodo_mes?, periodo_anio?, pdf_enabled?, use_db?, files*, csrf_token`. Respuesta: `{ok, message, report_paths: {docx, pdf?}, source}`.
- `POST /api/flows/sla` → flujo SLA completo. FormData: `file?, mes, anio, usar_db?, incluir_pdf?, eventos?, conclusion?, propuesta?, csrf_token`.
- `POST /api/flows/repetitividad` → flujo Repetitividad. FormData: `file?, mes, anio, include_pdf?, csrf_token, with_geo?, use_db?`. Responde: `{docx, pdf?, map_images, stats, source}`.
- `POST /api/flows/comparador-fo` → Placeholder (501).
- `POST /api/tools/compare-vlans` → JSON `{text_a, text_b, csrf_token}`. Devuelve `{only_a, common, only_b, vlans_a, vlans_b, total_a, total_b}`.
- `POST /api/tools/alarmas-ciena` → multipart con archivo CSV. Devuelve Excel como blob.
- `GET /api/infra/camaras` → búsqueda simple de cámaras (legacy, query params).
- `POST /api/infra/smart-search` → búsqueda avanzada `{terms, limit, offset}`.
- `GET/POST /api/infra/camaras/{id}/estado` → estado de cámara (admin).
- `GET /api/infra/servicios/{svcId}/rutas` → rutas de un servicio.
- `GET /api/infra/rutas/{rutaId}/tracking` → tracking de una ruta.
- `GET /api/infra/tracking/{rutaId}/download` → descarga de tracking.
- `POST /api/infra/trackings/analyze` → analiza archivo `.txt` (multipart). Devuelve `AnalyzeResult` con `status`: `NEW`, `IDENTICAL`, `CONFLICT`, `POTENTIAL_UPGRADE`, `NEW_STRAND`, `ERROR`.
- `POST /api/infra/trackings/resolve` → ejecuta la acción seleccionada. JSON body: `{action, content, filename, target_ruta_id?, new_ruta_name?, new_ruta_tipo?, old_service_id?}`.
- `GET /api/infra/export/cameras` → exporta cámaras. Params: `format=xlsx|csv`, `filter_status=ALL|BANEADA|OCUPADA|...`, `servicio_id?`.
- `POST /api/infra/ban/create` → Crear baneo. JSON body: `{ticket_asociado?, servicio_afectado_id, servicio_protegido_id, ruta_protegida_id?, motivo?, usuario_ejecutor?}`. Responde con `{success, incidente_id, camaras_baneadas, ...}`.
- `POST /api/infra/ban/lift` → Levantar baneo. JSON body: `{incidente_id, motivo_cierre?, usuario_ejecutor?}`.
- `GET /api/infra/ban/active` → Listado de baneos activos.

### InfraTab — Baneos Activos (gestión de incidentes)

El botón **🔒 Baneos Activos** en la toolbar (junto a "Protocolo Protección") muestra un badge numérico cuando hay incidentes abiertos. Al hacer clic abre el modal de gestión:

**Carga**: Al abrir, hace `GET /api/infra/ban/active` y lista las tarjetas de incidentes.
**Botón ↻ Actualizar**: recarga la lista sin cerrar el modal.

Cada tarjeta de incidente muestra:
- Ticket asociado (o `—` si no se registró)
- Duración transcurrida (badge naranja, en minutos u horas)
- Servicios: `Afectado → Protegido`
- Ruta protegida (si aplica)
- Motivo del corte
- Fecha/hora de inicio, cantidad de cámaras afectadas, usuario ejecutor

**Acción "📧 Dar Aviso"** — Abre un sub-modal con formulario de email:
- Destinatarios (To) y CC, separados por coma
- Asunto y cuerpo (precargados desde `GET /api/infra/ban/{id}` si el incidente tiene plantilla guardada)
- Checkboxes: adjuntar resumen XLS y/o tracking TXT
- Llama a `POST /api/infra/notify/email` con payload `{ to, cc?, subject, body, incidente_ids, include_xls, include_txt }`
- Muestra toast de éxito con conteo de destinatarios

**Acción "🔓 Levantar Baneo"** — Pide confirmación nativa (`window.confirm`) con datos del incidente. Al confirmar:
- Llama a `POST /api/infra/ban/lift` con `{ incidente_id }`
- El backend restaura las cámaras, notifica en Slack vía `slack_baneo_notifier`
- Recarga la lista de baneos y (si hay búsqueda activa) refresca la grilla de cámaras
- Muestra toast de éxito

### InfraTab — Leyenda de estados (atajos de filtrado)

Los cinco elementos de la barra de leyenda (`LIBRE`, `OCUPADA`, `BANEADA`, `DETECTADA`, `TRACKING`) son botones interactivos que aplican un filtro rápido sobre la grilla de cámaras ya cargada:

- **Clic en un atajo**: filtra la grilla al instante, sin nueva llamada a la API.
- **Clic en el mismo atajo activo**: limpia el filtro (toggle).
- **Clic en la `×` del chip**: también limpia el filtro.
- **`TRACKING`**: muestra sólo cámaras que tienen al menos una ruta/servicio asociado.
- El botón **Limpiar** también resetea el filtro activo junto a los términos de búsqueda.

Al activar un filtro aparece un **chip removible** junto al área de búsqueda indicando el estado activo. El chip usa la misma paleta de colores que los dots de la leyenda.

### InfraTab — Protocolo de Protección (Wizard 3 pasos)

El botón **🔴 Protocolo Protección** abre un wizard guiado de 3 pasos con stepper visual:

**Paso 1 — Identificación**:
- Ticket del incidente (opcional)
- Servicio afectado — ID del servicio que sufrió el corte (obligatorio)
- Motivo (opcional)

**Paso 2 — Selección del objetivo**:
- Dos tabs: **"Proteger el mismo servicio"** (modo `same`) o **"Otro servicio — redundancia cruzada"** (modo `other`)
- En modo `same`: se cargan automáticamente las rutas del servicio afectado.
- En modo `other`: input para ingresar el ID del servicio a proteger + botón "Buscar rutas".
- Grilla de tarjetas de ruta: opción "Todas las rutas activas" (equivale a `ruta_protegida_id = null`) + una tarjeta por ruta del servicio.
- **Alerta de tracking ausente** (`hash_contenido === null`): muestra aviso naranja con dos botones: "📄 Descargar TXT" y "⬆ Actualizar Tracking" (cierra el wizard y abre el flujo de upload).

**Paso 3 — Confirmación**:
- Resumen: ticket, servicio afectado, servicio protegido, ruta seleccionada, empalmes estimados, motivo.
- Checkbox de confirmación explícita (obligatorio para habilitar el botón de ejecución).
- Botón **"🚨 EJECUTAR BANEO"** (rojo) — deshabilitado hasta marcar el checkbox.

**Payload enviado a `/api/infra/ban/create`**:

```json
{
  "ticket_asociado": "INC0012345",
  "servicio_afectado_id": "52547",
  "servicio_protegido_id": "52548",
  "ruta_protegida_id": 42,      // null = todas las rutas activas
  "motivo": "Corte en Av. Corrientes",
  "usuario_ejecutor": null
}
```

### InfraTab — Subir Tracking (Portero de Archivos)

El flujo de carga de trackings opera en 2 fases:

**Fase 1 — Análisis (`/analyze`)**: Se sube el `.txt`; la API responde con el `status` del archivo y, si corresponde, lista de rutas existentes (`rutas_existentes`).

**Fase 2 — Resolución (`/resolve`)**: El usuario elige la acción y se envía el JSON con `action` + extras según la tabla:

| Acción UI | `action` enviado | Extras |
|---|---|---|
| Crear nuevo servicio | `CREATE_NEW` | — |
| Merge empalmes | `MERGE_APPEND` | `target_ruta_id` |
| Reemplazar ruta | `REPLACE` | `target_ruta_id` |
| **Crear Camino** | `BRANCH` | `new_ruta_name`, `new_ruta_tipo: "ALTERNATIVA"` |
| **Nuevo Pelo** | `ADD_STRAND` | `target_ruta_id` |
| Confirmar upgrade | `CONFIRM_UPGRADE` | `old_service_id` |
| Agregar pelo (auto-detect) | `ADD_STRAND` | `target_ruta_id` (de `strand_info.ruta_id`) |

> **Nota de nomenclatura**: La acción `BRANCH` se presenta como **"Crear Camino"** en la UI (caminos alternativos/redundantes de FO). La opción **"Nuevo Pelo"** es visible tanto cuando el status es `NEW_STRAND` como dentro del modal `CONFLICT`, permitiendo al usuario agregar manualmente un pelo adicional a un camino existente.

**Zona de upload — Drag & Drop**: La zona "📁 Subir Tracking" acepta tanto clic (selector nativo) como arrastre de archivos `.txt` directamente. Al arrastrar, el borde cambia a azul (`--drag-over`). Se valida extensión `.txt` antes de disparar el análisis.

El flujo de carga de trackings opera en 2 fases:

**Fase 1 — Análisis (`/analyze`)**: Se sube el `.txt`; la API responde con el `status` del archivo y, si corresponde, lista de rutas existentes (`rutas_existentes`).

**Fase 2 — Resolución (`/resolve`)**: El usuario elige la acción y se envía el JSON con `action` + extras según la tabla:

| Acción UI | `action` enviado | Extras |
|---|---|---|
| Crear nuevo servicio | `CREATE_NEW` | — |
| Merge empalmes | `MERGE_APPEND` | `target_ruta_id` |
| Reemplazar ruta | `REPLACE` | `target_ruta_id` |
| **Crear Camino** | `BRANCH` | `new_ruta_name`, `new_ruta_tipo: "ALTERNATIVA"` |
| **Nuevo Pelo** | `ADD_STRAND` | `target_ruta_id` |
| Confirmar upgrade | `CONFIRM_UPGRADE` | `old_service_id` |
| Agregar pelo (auto-detect) | `ADD_STRAND` | `target_ruta_id` (de `strand_info.ruta_id`) |

> **Nota de nomenclatura**: La acción `BRANCH` se presenta como **"Crear Camino"** en la UI (caminos alternativos/redundantes de FO). La opción **"Nuevo Pelo"** es visible tanto cuando el status es `NEW_STRAND` como dentro del modal `CONFLICT`, permitiendo al usuario agregar manualmente un pelo adicional a un camino existente.

**Zona de upload — Drag & Drop**: La zona "📁 Subir Tracking" acepta tanto clic (selector nativo) como arrastre de archivos `.txt` directamente. Al arrastrar, el borde cambia a azul (`--drag-over`). Se valida extensión `.txt` antes de disparar el análisis.

## Frontend SPA (Vue 3)

El SPA usa **Vue 3 + Vite 5 + TypeScript + Vue Router 4**.

### Estructura `web/frontend/src/`

```
main.ts                ← entry point (createApp + router)
App.vue                ← root component (<RouterView />)
router/index.ts        ← rutas + navigation guard
composables/
  useSession.ts        ← estado global de sesión (singleton)
api/
  auth.ts              ← wrappers fetch: getSession, login, logout
components/
  PanelLayout.vue      ← topbar con nav, usuario y logout
views/
  LoginView.vue        ← formulario de login
  PanelView.vue        ← panel con tabs
  SlaView.vue          ← vista independiente /sla
  ReportsHistoryView.vue ← historial de reportes
  tabs/
    ChatTab.vue        ← chat HTTP
    RepetitividadTab.vue ← informe repetitividad
    VlanTab.vue        ← comparador VLAN
    FoTab.vue          ← comparador FO (placeholder)
    CienaTab.vue       ← alarmas Ciena
    InfraTab.vue       ← dashboard cámaras
admin/
  components/
    AdminLayout.vue    ← layout admin con RouterView
  (resto de admin Vue)
```

### Rutas Vue Router

| Ruta | Componente | Auth | Admin |
|------|------------|------|-------|
| `/login` | LoginView | No | No |
| `/` | PanelView (en PanelLayout) | Sí | No |
| `/sla` | SlaView (en PanelLayout) | Sí | No |
| `/reports-history` | ReportsHistoryView (en PanelLayout) | Sí | No |
| `/admin` | AdminLayout + children | Sí | Sí |
| `/admin/usuarios` | AdminLayout + children | Sí | Sí |
| `/admin/servicios` | AdminLayout + children | Sí | Sí |
| `/admin/Servicios/Baneos` | AdminLayout + children | Sí | Sí |

El **navigation guard** llama a `ensureSession()` en cada navegación. Si no hay sesión redirige a `/login`. Si la ruta requiere admin y el rol no es `admin`, redirige a `/`.

### Composable `useSession`

Singleton module-level. Expone `{state, csrf(), fetchSession(), ensureSession(), setSession(), clearSession()}`.  
Tras cada actualización de estado setea `window.CSRF_TOKEN` para compatibilidad con el código `admin.ts` existente.

## Variables de entorno

- `WEB_SECRET_KEY` → secreto para cookie de sesión (**obligatorio en prod**).
- `LOG_LEVEL` → nivel de logging (default: INFO).
- `NLP_INTENT_URL` → URL del servicio NLP (default: `http://nlp_intent:8100`).
- `API_BASE` → base de la API externa (default: `http://localhost:8001`).
- `TEMPLATES_DIR` → ruta interna a plantillas de informes DOCX (default: `Templates/`).
- `REPORTS_API_BASE` → base del servicio API para reportes (default: `http://api:8000`).
- `REPORTS_API_TIMEOUT` → timeout en segundos (default: 60).
- `DB_DSN` → conexión PostgreSQL.

## Docker / Build

El `web/Dockerfile` usa **multi-stage**:

```dockerfile
# Stage 1: build Vite
FROM node:20.12.2-slim AS web-build
WORKDIR /frontend
COPY web/frontend/... ./
RUN npm ci && npm run build   # genera /frontend/dist/

# Stage 2: Python runtime
FROM focas-base:latest
COPY web/app /app/app
COPY --from=web-build /frontend/dist /app/frontend/dist
# (+ core, modules, db, tools)
```

Los Vite assets (`dist/assets/`) se sirven en `/assets`. El `DIST_DIR` en `main.py` es `/app/frontend/dist`.

## Memoria conversacional y métricas

El endpoint `/api/chat/message` persiste mensajes en `app.conversations` / `app.messages`. El payload incluye `conversation_id` y `history` (≤6 mensajes) cuando el usuario está autenticado.

Métricas: `INTENT_COUNTER` en memoria expuesto en `/api/chat/metrics`. Si `METRICS_PERSIST_PATH` está definido, se persiste a JSON atómicamente.

## Compose

- Servicio `web` expuesto en `8080:8080`.
- `api` remapeado a `8001:8000`.
- El servicio `web` expone `/reports` como estático para descargar resultados.
- `web` monta `../Templates:/app/Templates:ro` para las plantillas de informes.
