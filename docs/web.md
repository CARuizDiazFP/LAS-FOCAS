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
      assets/styles/   ← tokens CSS globales del panel
      api/client.ts    ← cliente HTTP compartido con credenciales + CSRF
      composables/     ← lógica reactiva desacoplada de vistas
    dist/              ← build Vite (generado, no en git)
    vite.config.ts
    index.html
  Dockerfile           ← multi-stage: Node 20 build → Python serve
```

### Shell y navegación modular

- El SPA ahora usa un **App Shell compartido** en `web/frontend/src/components/app-shell/AppShell.vue` para panel y admin.
- La navegación lateral se organiza por módulos y apunta a rutas dedicadas: `/`, `/infra`, `/servicios`, `/servicios/ID/:idServicio`, `/repetitividad`, `/toolkit/vlan`, `/fo`, `/dwdm/ciena`, `/sla` y `/reports-history`.
- El header horizontal legacy fue eliminado para ampliar el área de trabajo. Los controles fijos de sesión viven arriba del sidebar: configuración y perfil de usuario.
- La esquina superior derecha del área principal queda reservada para acciones dinámicas de módulo, sin botones estáticos.
- El contenedor `#dynamic-module-actions` permite que una vista inyecte acciones con `Teleport`; el mismo bloque expone el slot `module-actions` para usos futuros donde el shell se componga directamente.
- La ruta `/` renderiza el Home/Chat limpio mediante `PanelView.vue`; los módulos operativos ya no viven como tabs internas del panel.

### Lazy loading

- `web/frontend/src/router/index.ts` carga `Login`, `Panel`, `SLA`, `Reportes`, `Cámara Detail` y vistas admin mediante `import()` dinámico.
- Los módulos migrados desde las tabs legacy se cargan como rutas dedicadas y conservan lazy loading por componente.
- Se mantiene compatibilidad con `/?tab=infra|rep|repetitividad|vlan|fo|ciena` mediante redirects hacia las rutas nuevas.
- La administración incorpora `/admin/ingesta` como **hub de navegación** con dos sub-módulos:
  - `/admin/ingesta/servicios` → carga del Excel de Servicios SLA con barra de progreso.
  - `/admin/ingesta/camaras` → ingesta masiva de cámaras críticas desde Excel (col B, sin cabecera) con modal de motivo de baneo y baneo administrativo masivo. Desde el refactor de baneos (2026-08-24) suma un "Revisor Manual": los alias que no matchearon contra el inventario se listan con selección múltiple, para descartarlos (marcar revisado en lote) o asociarlos a mano a una Cámara/Botella existente vía typeahead — la ingesta ya no crea `Camara` nuevas por su cuenta. Detalle completo en `docs/infra.md`, sección "Ingesta Excel de cámaras baneadas".

> **CRITICAL — Arquitectura del router admin**: Existe el archivo `web/frontend/src/admin/router/index.ts` y `web/frontend/src/admin/main.ts`, pero ambos son **código huérfano**. El SPA tiene un único entry point (`src/main.ts` → monta en `#app`) y usa `src/router/index.ts` como router unificado. Las rutas `/admin/*` son **children anidadas** de `{ path: '/admin', component: AppShell }` dentro de ese router. Toda ruta admin nueva debe agregarse en `src/router/index.ts`, no en `src/admin/router/index.ts`.

### Tokens y estilos compartidos

- Los tokens visuales viven en `web/frontend/src/assets/styles/tokens.css`.
- `panel.css` y `admin.css` consumen estos tokens en lugar de redeclarar su propia paleta base.
- El objetivo de la capa es concentrar identidad cromática, spacing, radios y layout en variables CSS nativas (`--color-*`, `--space-*`, `--layout-*`).

**Sistema de diseño Nocturne (2026-07-29).** `tokens.css` implementa el sistema Nocturne:
fondo `#161826`, superficie `#232532`, texto `#e9e9ed`, acento blurple `#9184d9`, rampas
tonales `--color-neutral-100..900` / `--color-accent-100..900` en OKLCH, tipografía Inter
(400/500, nunca más de 500 en títulos), espaciado con densidad 0.70× y tres niveles de
elevación (`--shadow-sm/md/lg`) basados en hairline + oscuridad ambiente — nunca sombras
apiladas. Los estados semánticos (`--color-state-ok/warn/error/idle`) se derivaron en OKLCH
a la misma luminosidad/croma que el acento porque Nocturne es monocromo y no trae
verde/ámbar/rojo saturados. Los alias legacy cortos (`--bg`, `--surface`, `--text`,
`--primary`, `--border`, `--muted`, `--radius`, `--color-bg-*`, `--shadow-card`,
`--shadow-focus`) se conservan apuntando a los tokens nuevos para no romper `panel.css`,
`admin.css` ni las pantallas todavía sin rediseñar (`/toolkit/vlan`, `/fo`, `/dwdm/ciena`,
`/infra/Camaras/:id`, `/admin`). Iconografía: `@phosphor-icons/web`, importado en `main.ts`;
reemplaza los emojis del sidebar, la toolbar principal de Infra FO y las tarjetas de
servicio/cámara. Detalle completo del rediseño en `docs/PR/2026-07-29.md`.

El contenedor se lanza con:
```
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

## Autenticación y sesión

- Cookie de sesión (`starlette.middleware.sessions.SessionMiddleware`).
- Flags explícitos: `HttpOnly`, `SameSite=Lax`, `max_age` configurable y `Secure` configurable por entorno.
- Keys de sesión: `username`, `role`, `csrf`.
- **No hay rutas HTML de login**: el SPA usa los endpoints JSON de autenticación.

### Endpoints de autenticación

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/api/auth/session` | Devuelve estado de sesión actual (sin auth requerida). Respuesta: `{authenticated, username, role, csrf}` |
| `POST` | `/api/auth/login` | Login vía JSON `{username, password}`. Rate limit en memoria por IP + usuario, default 5 intentos/min. Respuesta: `{ok, username, role, csrf}` o `{ok:false, error}` |
| `POST` | `/api/auth/logout` | Cierra sesión. Respuesta: `{ok: true}` |
| `GET` | `/logout` | Compatibilidad hacia atrás — limpia sesión y redirige a `/` (el SPA detecta sesión vacía y muestra login) |

### CSRF

El token CSRF se incluye en la respuesta de `/api/auth/session` y `/api/auth/login`. El composable `useSession.ts` lo almacena en estado reactivo y sincroniza un fallback `window.CSRF_TOKEN` solo por compatibilidad con superficies legacy aún no migradas.
Todos los endpoints POST que mutan datos validan el CSRF token.

### Cliente HTTP y composables

- `web/frontend/src/api/client.ts` centraliza `fetch` same-origin con `credentials: 'include'`, serialización JSON/FormData, inyección de CSRF y normalización de errores.
- `web/frontend/src/composables/useSla.ts` contiene el flujo reactivo del informe SLA y corrige el manejo de archivos seleccionados, que antes no era reactivo en la vista.
- `web/frontend/src/composables/useCiena.ts` desacopla el procesamiento del CSV de alarmas Ciena y la descarga del XLSX resultante.
- Esta capa es la base para seguir extrayendo lógica desde `RepetitividadTab`, `VlanTab` e `InfraTab`.

### Superficies legacy del frontend

- `web/frontend/src/chat/main.ts` sigue existiendo como cliente standalone heredado para WebSocket, pero **no forma parte del bundle actual del SPA** porque `index.html` solo entra por `src/main.ts`.
- Si se reactiva ese cliente en el futuro, debe sanearse el uso de `innerHTML` antes de volver a exponerlo en runtime.

## Build Dev del frontend

La validación del frontend debe ejecutarse **solo** en el stack Dev. El comando operativo para rebuild explícito del servicio web es:

```bash
docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev up -d --build web
```

Ese flujo recompila los assets Vite dentro del `Dockerfile` multi-stage del servicio `web` y actualiza `/app/frontend/dist` dentro del contenedor dev.

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
- `GET /api/reports/history` → histórico persistente de reportes. Devuelve `items` con estado, usuario, período, fuente, duración, metadata segura y salidas; conserva `files` como compatibilidad básica. Requiere auth. Filtros: `type`, `status`, `username`, `month`, `year`, `limit`, `offset`.
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
- `GET /api/infra/camaras/{id}` → resumen operativo de una cámara para la vista dedicada.
- `GET /api/infra/camaras/{id}/aliases` → alias conocidos de una cámara.
- `GET /api/infra/camaras/{id}/registros` → históricos parciales de auditoría manual y baneos relacionados.
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
- `POST /api/servicios/ingest` → proxy autenticado (admin + CSRF) hacia API interna para ingesta masiva de servicios SLA.
- `GET /api/servicios/search` → proxy autenticado para búsqueda multipropósito con `limit/offset` (scroll infinito en `/servicios`).
- `GET /api/servicios/detail?id=...` → proxy autenticado de detalle que resuelve el ID origen canónico para navegación histórica en `/servicios/ID/:idServicio`.

En la iteración actual, la vista `/servicios/ID/:idServicio` hace primeras integraciones operativas:

- **RECLAMOS** consume resumen de ejecuciones recientes desde `GET /api/reports/history` (tipos `sla` y `repetitividad`) y enlaza a módulos de operación.
- **FO** consume `GET /api/infra/servicios/{servicio_id}/rutas` y `GET /api/infra/rutas/{ruta_id}/tracking` para mostrar conteo real de rutas/cámaras/cables y puntas A/B.

Los endpoints same-origin de baneos del servicio `web` también disparan el aviso inmediato a Slack y reenvían el reporte actualizado de cámaras baneadas usando la configuración persistida en `app.config_servicios` (`slack_baneo_notifier`).

### InfraTab — Tarjeta resumida y detalle por cámara

La grilla principal de `InfraTab.vue` fue simplificada para operar como tablero de consulta rápida:

- Cada tarjeta muestra solo `Nombre canon`, `ID` numérico interno y `estado` con su color actual.
- El identificador visible ahora es `camara.id`; `fontine_id` sigue existiendo en backend pero ya no se usa como dato primario de la tarjeta.
- El CTA de la tarjeta pasó de **Editar estado** a **Detalle** y navega a `/infra/Camaras/:id`.

La vista dedicada `CamaraDetailView.vue` cuelga del router principal y carga en paralelo, vía `Promise.all`, tres fuentes same-origin:

- `GET /api/infra/camaras/{id}` para el header operativo y servicios/rutas asociados.
- `GET /api/infra/camaras/{id}/aliases` para alias conocidos.
- `GET /api/infra/camaras/{id}/registros` para auditoría manual y baneos relacionados.

En el header de detalle se reubica el botón **Editar estado** solo para admin, reutilizando el endpoint `GET/POST /api/infra/camaras/{id}/estado` y el mismo flujo de CSRF.

Debajo del header se expone un dashboard de tres tarjetas clickeables con modales aislados:

- **Alias Conocidos**
- **Registros**
- **Servicios Asociados**

La tarjeta **Servicios Asociados** ahora muestra únicamente la lista de IDs de servicio asociados a la cámara, ordenados de mayor a menor. Al hacer clic sobre un ID se abre un segundo `dialog` modal real superpuesto con `TrackingDetail.vue`, para asegurar el apilado correcto por delante del modal padre. Se conserva la secuencia óptica (`punta A → empalmes/cables → punta B`) y la descarga del TXT actual mediante `GET /api/infra/tracking/{rutaId}/download`.

La tarjeta **Registros** ahora se divide en dos pestañas internas:

- **Ingresos**: queda estructurada sobre un arreglo reactivo vacío, preparada para hidratar desde backend y sin generar listados fake largos. La plantilla del detalle ya reserva el campo `Técnico solicitante` para la futura integración.
- **Baneos**: ordena el historial por `fecha_inicio` descendente y lo presenta como accordions retraídos por defecto mediante transiciones nativas de Vue 3 sobre `AccordionItem.vue`. Cada encabezado muestra solo el rango `inicio - fin` y, si el baneo sigue activo, `En curso`.

Dentro de la pestaña **Baneos** también se conserva una sección compacta de auditoría manual de estado para no perder trazabilidad operativa ya disponible.

El modal **Editar estado** en la vista dedicada recupera el mismo modo oscuro y jerarquía visual del panel actual; mantiene `credentials: 'include'` para lectura y usa `csrf_token` desde `useSession.ts` al persistir cambios.

### InfraTab — Baneos Activos (gestión de incidentes)

El botón **Baneos activos** (icono `ph-lock-key`) en el encabezado, junto a "Protocolo Protección", muestra un badge numérico cuando hay incidentes abiertos. Al hacer clic abre el modal de gestión:

**Carga**: Al abrir, hace `GET /api/infra/ban/active` y lista las tarjetas de incidentes.
**Botón ↻ Actualizar**: recarga la lista sin cerrar el modal.

Cada tarjeta de incidente muestra:
- Ticket asociado (o `—` si no se registró)
- Duración transcurrida (badge naranja, en minutos u horas)
- Servicios: `Afectado → Protegido`
- Ruta protegida (si aplica)
- Motivo del corte
- Fecha/hora de inicio, cantidad de cámaras afectadas, usuario ejecutor

**Acción "📧 Dar Aviso"** — Abre un sub-modal con formulario de email enriquecido:
- **Destinatarios persistidos**: los campos "Para" y "CC" se restauran automáticamente desde `localStorage` (`focas_baneo_to` / `focas_baneo_cc`). Se guardan al hacer clic en "Enviar Aviso" o "Descargar EML".
- **Plantilla autocompletada**: el asunto se precarga como `[AVISO] BANEO de Camaras`; el cuerpo se genera con los datos del incidente (ticket, servicios, cámaras, fecha/hora, motivo) usando la plantilla estándar. Si el backend tiene una plantilla guardada en el incidente (`GET /api/infra/ban/{id}`), se usa en su lugar.
- El textarea del cuerpo es **editable** — el usuario puede modificar el texto antes de enviar.
- Checkboxes: adjuntar resumen XLS y/o tracking TXT.
- **Botón "📥 Descargar EML"**: genera y descarga un archivo `.eml` listo para abrir en el cliente de correo, llamando a `POST /api/infra/notify/download-eml` (multipart/form-data con `incident_id`, `recipients`, `subject`, `html_body`). También guarda los destinatarios en localStorage.
- **Botón "📧 Enviar Aviso"**: llama a `POST /api/infra/notify/email` con payload `{ to, cc?, subject, body, incidente_ids, include_xls, include_txt }`.
- Muestra toast de éxito con conteo de destinatarios (o error detallado).

**Acción "🔓 Levantar Baneo"** — Pide confirmación nativa (`window.confirm`) con datos del incidente. Al confirmar:
- Llama a `POST /api/infra/ban/lift` con `{ incidente_id }`
- El backend restaura las cámaras, notifica en Slack vía `slack_baneo_notifier`
- Recarga la lista de baneos y (si hay búsqueda activa) refresca la grilla de cámaras
- Muestra toast de éxito

### InfraTab — Leyenda de estados (atajos de filtrado)

Los cinco elementos de la barra de leyenda (`LIBRE`, `OCUPADA`, `BANEADA`, `DETECTADA`, `TRACKING`) son botones interactivos que aplican un filtro rápido sobre la grilla de cámaras:

- **Clic en un atajo sin resultados previos**: dispara automáticamente `searchCamaras()` con `terms: []` (trae todas las cámaras) y luego filtra por estado. No requiere clic en "Buscar".
- **Clic en un atajo con resultados cargados**: filtra la grilla al instante via computed, sin nueva llamada a la API.
- **Clic en el mismo atajo activo**: limpia el filtro (toggle).
- **Clic en la `×` del chip**: llama `clearStateFilter()`. Si no había términos de texto, resetea la grilla al estado vacío inicial; si había términos, solo quita el filtro de estado.
- **`TRACKING`**: muestra sólo cámaras que tienen al menos una ruta/servicio asociado.
- **Botón "Buscar"**: habilitado si hay términos de texto O si hay un filtro de estado activo (`searchTerms.length > 0 || activeStateFilter !== null`).
- El botón **Limpiar** resetea filtro de estado, términos de búsqueda y vacía la grilla.

Al activar un filtro aparece un **chip removible** junto al área de búsqueda indicando el estado activo. El chip usa la misma paleta de colores que los dots de la leyenda.

### InfraTab — Protocolo de Protección (Wizard 3 pasos)

El botón **Protocolo Protección** (icono `ph-shield-warning`) abre un wizard guiado de 3 pasos con stepper visual:

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
- Botón **"🚨 EJECUTAR BANEO"** (rojo) — deshabilitado hasta marcar el checkbox. Tras una respuesta exitosa del backend, el modal se cierra automáticamente y el wizard queda reiniciado.

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

**Zona de upload — Drag & Drop**: El botón "Subir tracking" (icono `ph-folder-simple-plus`, sin emoji) acepta tanto clic (selector nativo) como arrastre de archivos `.txt` directamente. Al arrastrar, el borde cambia al acento Nocturne (`.drag-over`). Se valida extensión `.txt` antes de disparar el análisis.

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
  app-shell/
    AppShell.vue       ← shell compartido con controles fijos en sidebar y toolbar dinámica vacía
views/
  LoginView.vue        ← formulario de login
  PanelView.vue        ← Home/Chat limpio
  CamaraDetailView.vue ← detalle dedicado de cámara FO
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
  (resto de admin Vue)
```

### Rutas Vue Router

| Ruta | Componente | Auth | Admin |
|------|------------|------|-------|
| `/login` | LoginView | No | No |
| `/` | AppShell + PanelView | Sí | No |
| `/infra` | AppShell + InfraTab | Sí | No |
| `/infra/Camaras/:id` | AppShell + CamaraDetailView | Sí | No |
| `/repetitividad` | AppShell + RepetitividadTab | Sí | No |
| `/toolkit/vlan` | AppShell + VlanTab | Sí | No |
| `/fo` | AppShell + FoTab | Sí | No |
| `/dwdm/ciena` | AppShell + CienaTab | Sí | No |
| `/sla` | AppShell + SlaView | Sí | No |
| `/reports-history` | AppShell + ReportsHistoryView | Sí | No |
| `/servicios` | AppShell + ServiciosView | Sí | No |
| `/servicios/ID/:idServicio` | AppShell + ServicioDetalleView | Sí | No |
| `/admin` | AppShell + AdminDashboard | Sí | Sí |
| `/admin/usuarios` | AppShell + AdminUsuarios | Sí | Sí |
| `/admin/servicios` | AppShell + AdminServicios | Sí | Sí |
| `/admin/Servicios/Baneos` | AppShell + AdminBaneos | Sí | Sí |

> **Nota (2026-08-24):** `AdminBaneos.vue` es hoy un contenedor de 3 tabs — Baneos Activos
> (`BaneosActivosPanel.vue`, listado agrupado por Cámara padre + liberación/desbaneo masivo),
> Configuración (`BaneosConfigPanel.vue`, worker de notificaciones Slack) y Revisión
> (`BaneosRevisionPanel.vue`, Cámaras Pendientes de Revisión + Ingresos sin match) — ya no es la vista
> monolítica que era antes. Misma ruta, mismo componente raíz.

El **navigation guard** llama a `ensureSession()` en cada navegación. Si no hay sesión redirige a `/login`. Si la ruta requiere admin y el rol no es `admin`, redirige a `/`. Si la ruta es `/login` y ya hay sesión autenticada, redirige a `/` (evita ver el formulario estando logueado).
Las URLs legacy `/?tab=...` se redirigen antes de resolver la vista protegida para preservar marcadores antiguos sin reintroducir tabs en el Home.

### Composable `useSession`

Singleton module-level. Expone `{state, csrf(), fetchSession(), ensureSession(), setSession(), clearSession()}`.  
Tras cada actualización de estado setea `window.CSRF_TOKEN` para compatibilidad con `chat/main.ts` (widget de chat embebible, superficie legacy separada del SPA principal). El mini-SPA admin viejo (`admin/main.ts`, `admin/router/index.ts`, `admin/App.vue`, `admin/components/AdminLayout.vue`, que montaba en `#admin-app`) se eliminó por código muerto: las vistas admin viven hoy en el router unificado (`router/index.ts`).

## Variables de entorno

- `WEB_SECRET_KEY` → secreto para cookie de sesión (**obligatorio en prod**).
- `WEB_SESSION_HTTPS_ONLY` → agrega flag `Secure` a la cookie (`false` en dev HTTP; usar `true` detrás de HTTPS/proxy).
- `WEB_SESSION_MAX_AGE` → vida máxima de la sesión en segundos (default: 28800).
- `WEB_LOGIN_RATE_LIMIT_MAX` → intentos de login permitidos por ventana (default: 5).
- `WEB_LOGIN_RATE_LIMIT_WINDOW` → ventana del rate limit en segundos (default: 60).
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
