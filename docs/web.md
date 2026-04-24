# Nombre de archivo: web.md
# Ubicación de archivo: docs/web.md
# Descripción: Documentación del microservicio Web (UI + FastAPI)

# Web (UI) — LAS-FOCAS

## Resumen

Servicio FastAPI que expone:
- UI dark-style con Panel (Chat por defecto y tabs: Repetitividad, Comparador VLAN, Comparador FO) y una vista independiente `/sla`.
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
- POST /api/reports/sla → Endpoint del microservicio `web` empleado por la vista `/sla`. FormData: `mes`, `anio`, `periodo_mes?`, `periodo_anio?`, `pdf_enabled?`, `use_db?`, `files*` (exactamente dos `.xlsx` cuando `use_db=false`: “Servicios Fuera de SLA” y “Reclamos SLA”), `csrf_token`. El backend clasifica y valida cada Excel (columnas obligatorias), genera el DOCX siguiendo la plantilla legacy y devuelve errores legibles (`error: "Faltan columnas en Excel de servicios: SLA"`) si falta contenido. Respuesta `{ ok, message, report_paths: {docx, pdf?}, source }`.
- POST /api/flows/sla → Ejecuta flujo SLA completo reutilizando `core.services.sla`. FormData: `file?`, `mes`, `anio`, `usar_db?`, `incluir_pdf?`, `eventos?`, `conclusion?`, `propuesta?`, `csrf_token`. Cuando `usar_db=true` se ignora el archivo y se consulta la base. Responde JSON con enlaces `/reports/*.docx[.pdf]`, indicador `source` y métricas básicas del período.
- POST /api/flows/repetitividad → Ejecuta flujo de Repetitividad reutilizando los servicios compartidos (`generar_informe_desde_excel` / `generar_informe_desde_dataframe`). FormData: `file?`, `mes`, `anio`, `include_pdf?`, `csrf_token`, `with_geo?`, `use_db?`. Respuesta JSON con `docx`, `pdf?`, `map_images` (lista de PNGs), `assets` (alias de `map_images`), `map_image` (primer PNG), `stats`, `source` y flags `pdf_requested`/`with_geo`.
- POST /api/flows/comparador-fo → Placeholder (501) hasta implementar.
- POST /api/tools/compare-vlans → Herramienta para auditar configuraciones trunk. Cuerpo JSON `{ text_a, text_b, csrf_token }`; el backend busca comandos `switchport trunk allowed vlan[ add]`, expande rangos (1-6 → 1..6), depura valores fuera de 1-4094 y devuelve listas `only_a`, `only_b`, `common`, además de los totales (`total_a`, `total_b`) y las listas completas (`vlans_a`, `vlans_b`). Errores: 400 si no se detectan VLANs en alguna interfaz, 403 CSRF inválido.

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
- El cliente principal (`/static/panel.js`) maneja los tabs activos (Chat, Repetitividad, Comparador VLAN, Comparador FO, Alarmas Ciena, **Infra/Cámaras**) y coordina envíos al backend, incluido el Chat HTTP (`/api/chat/message`), uploads (`/api/chat/uploads`) y la nueva herramienta de comparación vía `POST /api/tools/compare-vlans`.
- La vista `/sla` usa `web/templates/sla.html` + `/static/sla.js`, con drag&drop, validación estricta de dos archivos (Servicios + Reclamos), alternancia Excel/DB, validación de período y mensajes accesibles que muestran los enlaces devueltos por `POST /api/reports/sla`.

### Dashboard de Infraestructura (Cámaras)

Nueva sección en el panel que permite visualizar y gestionar la infraestructura de fibra óptica con búsqueda avanzada:

**Características:**
- **Search Builder con Tags:** Sistema de filtros combinables que permite agregar múltiples criterios de búsqueda:
  - Selector de tipo de filtro (Dirección, Servicio ID, Estado, Cable, Origen).
  - Input de valor con botón "+" neón para agregar filtros.
  - Tags visuales que muestran filtros activos con posibilidad de eliminar individualmente.
  - Lógica AND: todos los filtros se aplican simultáneamente (intersección).
- **Quick Filters:** Atajos para agregar filtros de estado/origen rápidamente.
- **Zona de upload drag & drop:** Permite arrastrar archivos `.txt` de tracking para procesarlos automáticamente.
- **Grid de tarjetas:** Cada cámara se muestra como una tarjeta con:
  - Indicador de estado (icono de color neón según estado).
  - Nombre/dirección de la cámara.
  - Chips con los IDs de servicios que pasan por esa cámara.
  - Metadatos opcionales (coordenadas, origen de datos, fontine_id).
  - Borde punteado para cámaras con origen TRACKING (provisorias).
- **Toasts de notificación:** Feedback visual al completar o fallar operaciones de upload.

**Tipos de filtro disponibles:**
| Campo | Descripción |
|-------|-------------|
| `address` | Busca por nombre o dirección de cámara (contains) |
| `service_id` | Busca cámaras por donde pasa un servicio específico |
| `status` | Estado: LIBRE, OCUPADA, BANEADA, DETECTADA |
| `cable` | Busca cámaras asociadas a un cable por nombre |
| `origen` | Origen de datos: MANUAL, TRACKING, SHEET |

**Estilo visual:**
- Tema "Hacker/Dark Mode" con acentos neón verde (#00ff88).
- Tags de filtros con borde semitransparente y efecto glow.
- Bordes con glow suave en elementos interactivos.
- Fuentes monoespaciadas para IDs y datos técnicos.
- Responsive: grid adapta columnas según ancho de pantalla.

**Endpoints consumidos:**
- `POST /api/infra/search` - Búsqueda avanzada con filtros AND (nuevo).
- `GET /api/infra/camaras?q=<query>&estado=<estado>` - Búsqueda simple (legacy).
- `POST /api/infra/upload_tracking` - Carga de archivos de tracking.

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

## Protocolo de Protección (Baneo de Cámaras)

Sistema de emergencia para proteger la infraestructura de fibra óptica cuando se detectan amenazas físicas en cámaras subterráneas.

### Propósito

Cuando se identifica actividad sospechosa (intento de robo, vandalismo) en una cámara, el operador puede "banear" todas las rutas que pasan por ella, documentando el incidente con un ticket asociado. Esto permite:

- Registrar rápidamente qué rutas están comprometidas.
- Notificar equipos de campo con un listado claro.
- Auditar el historial de incidentes por cámara.
- Exportar listados filtrados para análisis.

### Componentes Frontend

#### 1. Botón Pánico (🚨 Protocolo Protección)

- **Ubicación:** Cabecera del tab "Infra/Cámaras" junto al badge de baneos activos.
- **Estilo:** Rojo intenso (#ff4444) con efecto glow y animación de pulso suave.
- **Acción:** Abre el wizard de 3 pasos para registrar un nuevo incidente.

#### 2. Badge de Baneos Activos

- **Muestra:** Número de cámaras actualmente baneadas.
- **Se actualiza:** Al cargar la sección Infra y después de crear/remover un baneo.
- **Clic:** Expande listado resumido de baneos activos.

#### 3. Wizard de Baneo (3 Pasos)

**Paso 1 – Identificación:**
- Campo de texto para buscar cámara (por nombre, dirección, ID).
- Autocompletado con resultados de la API.
- Selección visual con preview de la cámara elegida.

**Paso 2 – Selección:**
- Toggle para elegir alcance: "Todas las rutas" o "Seleccionar rutas específicas".
- Listado con checkboxes de las rutas/servicios que pasan por la cámara.
- Campo para número de ticket obligatorio.
- Semáforo de tracking (🔴→🟡→🟢) mostrando progreso del proceso.

**Paso 3 – Confirmación:**
- Resumen del incidente: cámara afectada, rutas seleccionadas, ticket.
- Checkbox de confirmación obligatorio.
- Botón "Ejecutar Protocolo" que envía `POST /api/infra/ban/create`.

#### 4. Indicadores Visuales en Tarjetas

Las tarjetas de cámara con estado `BANEADA` muestran:

- **Borde rojo brillante** con efecto glow pulsante.
- **Icono de candado** (🔒) en la esquina superior derecha con animación.
- **Número de ticket** visible debajo de los servicios, con prefijo 🎫.

```css
.infra-camara-card[data-estado="BANEADA"] {
  border-color: #ff4444;
  box-shadow: 0 0 20px rgba(255, 68, 68, 0.3);
}
```

Además, cuando el estado persistido de la cámara no coincide con el estado sugerido por el
contexto operativo, la tarjeta muestra una alerta amarilla con el estado actual, el sugerido
y la cantidad de incidentes activos que justifican la discrepancia.

#### 5. Edición Manual de Estado

- **Permiso:** solo usuarios con rol `admin`.
- **Acción:** cada tarjeta editable expone un botón `Editar estado`.
- **Modal:** permite ver contexto operativo, incidentes activos relacionados, estado sugerido y guardar un override manual con motivo obligatorio.
- **Auditoría:** cada cambio exitoso se registra en `app.camaras_estado_auditoria`.
- **Regla operativa:** el override manual puede dejar una cámara en un estado distinto al sugerido, incluso si existe un baneo activo; la interfaz lo muestra explícitamente como inconsistencia.

#### 6. Dropdown de Exportación

Menú desplegable junto al botón "Limpiar servicio" con las opciones:

| Opción | Formato | Filtro |
|--------|---------|--------|
| Exportar todas (XLSX) | Excel | Sin filtro |
| Exportar todas (CSV) | CSV | Sin filtro |
| Solo baneadas (CSV) | CSV | estado=BANEADA |
| Solo con ingreso (CSV) | CSV | estado=OCUPADA |

Cada opción llama a `GET /api/infra/export/cameras?filter=X&format=Y`.

#### 7. Botón de Notificaciones

- **Icono:** Campana (🔔) con badge numérico.
- **Función (mock):** Abre modal con listado de baneos activos.
- **Futuro:** Integrará con sistema de alertas push o Telegram.

### Endpoints Consumidos

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/api/infra/camaras/{id}/estado` | GET | Devuelve el contexto operativo de una cámara para edición manual |
| `/api/infra/camaras/{id}/estado` | POST | Aplica override manual del estado (admin + CSRF) |
| `/api/infra/ban/create` | POST | Crea incidente de baneo |
| `/api/infra/ban/active` | GET | Lista baneos activos |
| `/api/infra/ban/{id}/remove` | DELETE | Remueve un baneo |
| `/api/infra/servicios/{id}/rutas` | GET | Lista rutas de un servicio |
| `/api/infra/export/cameras` | GET | Exporta cámaras con filtros |

`GET /api/infra/ban/active` devuelve ahora dos nociones distintas:
- `camaras_count`: cámaras cubiertas topológicamente por cada incidente activo.
- `camaras_baneadas_count` y `total_camaras_baneadas`: cámaras efectivamente persistidas con estado `BANEADA`.

El badge del panel usa el conteo efectivo para evitar falsos positivos cuando un administrador normaliza manualmente discrepancias.

### Modelo de Datos

Ver `docs/db.md` para el esquema completo de `app.incidentes_baneo`.

Campos principales:
- `camara_id` / `servicio_id`: FK a la entidad afectada.
- `ticket_baneo`: Número de ticket asociado (obligatorio).
- `motivo_baneo`: Descripción del incidente.
- `rutas_afectadas`: JSON con lista de rutas comprometidas.
- `estado_baneo`: ACTIVO / RESUELTO / CANCELADO.
- `usuario_baneo`: Usuario que ejecutó el protocolo.
- `fecha_baneo` / `fecha_resolucion`: Timestamps.

### Flujo de Usuario

```
1. Operador detecta amenaza en cámara física
2. Click en "🚨 Protocolo Protección"
3. Wizard Paso 1: Busca y selecciona la cámara
4. Wizard Paso 2: Elige rutas + ingresa ticket
5. Wizard Paso 3: Confirma y ejecuta
6. Sistema:
   - Crea registro en app.incidentes_baneo
   - Actualiza estado de cámara a BANEADA
   - Incrementa contador en badge
   - Muestra tarjeta con indicadores visuales
7. Operador puede exportar listado para equipos de campo
```

### Estilos CSS Clave

```css
/* Botón pánico */
.infra-panic-btn {
  background: linear-gradient(135deg, #ff4444, #cc3333);
  box-shadow: 0 0 15px rgba(255, 68, 68, 0.4);
  animation: panicPulse 2s ease-in-out infinite;
}

/* Tarjeta baneada */
.infra-camara-card[data-estado="BANEADA"]::after {
  content: '🔒';
  position: absolute;
  animation: lockPulse 2s ease-in-out infinite;
}

/* Ticket en tarjeta */
.infra-ban-ticket {
  background: rgba(255, 68, 68, 0.15);
  border: 1px solid rgba(255, 68, 68, 0.3);
  color: #ff6b6b;
}
```

## Próximos pasos

- Conectar botones a flujos SLA/Repetitividad/Comparador FO.
- WebSocket/streaming con Ollama y feedback de progreso.
- Tests de integración adicionales y documentación de uso.

## Panel Admin — SPA Vue 3

### Arquitectura

El panel admin usa un **SPA Vue 3** con Vue Router, compilado por Vite como un segundo entry point (`assets/admin.js`). FastAPI sirve un shell HTML mínimo (`admin_shell.html`) que inyecta CSRF y monta el SPA. La sesión y el control de acceso siguen siendo responsabilidad del backend (server-side), sin depender de guards client-side como única barrera.

### Rutas

| Ruta | Descripción |
|------|-------------|
| `GET /admin` | Dashboard principal — acceso a módulos Usuarios y Servicios |
| `GET /admin/usuarios` | Gestión de usuarios — crear cuenta y cambiar contraseña |
| `GET /admin/servicios` | Grid de servicios configurables (tarjetas) |
| `GET /admin/Servicios/Baneos` | Configuración del worker de notificaciones Slack |

Todas estas rutas requieren `role == "admin"` en sesión. Sin sesión redirigen a `/login`; con rol insuficiente redirigen a `/`.

### Endpoint de sesión (usado por Vue Router guard)

- `GET /api/admin/me` — Devuelve `{username, role}` si la sesión es admin. Devuelve HTTP 401/403 en caso contrario. El navigation guard del router llama a este endpoint antes de cada navegación y redirige a `/login` si falla.

### Endpoints JSON de configuración

- `GET /api/admin/servicios/baneos/config` — Devuelve configuración del worker como JSON (admin+sesión).
- `POST /api/admin/servicios/baneos` — Actualiza configuración (admin + CSRF), valida formato de destinos Slack y dispara recarga en caliente del worker. Redirige a `/admin/Servicios/Baneos` (303) al completar.
- `GET /api/admin/servicios/baneos/health` — Proxy al health check del worker (`http://slack_baneo_worker:8095/health`). Incluye campo `listener_activo: bool`.
- `POST /api/admin/servicios/baneos/worker/start` — Inicia el contenedor del worker via Docker SDK si está detenido (admin + CSRF).
- `POST /api/admin/servicios/baneos/trigger` — Dispara una ejecución manual inmediata del job de notificación (admin + CSRF).
- `GET /api/admin/servicios/baneos/listener` — Devuelve `{activo, canal_id, ultimo_error}` del monitor de ingresos (admin+sesión).
- `POST /api/admin/servicios/baneos/listener` — Actualiza `activo` y `canal_id` del listener (admin + CSRF); invoca `/reload` en el worker. Form fields: `activo`, `canal_id`, `csrf_token`.

### Estructura del frontend (Vite dual entry)

```
web/frontend/src/
├── chat/main.ts              ← Chat WebSocket client (compilado → assets/main.js)
└── admin/
    ├── main.ts               ← Entry point del SPA (compilado → assets/admin.js)
    ├── App.vue               ← RouterView + AdminLayout
    ├── admin.css             ← Dark theme (vars reutilizadas de styles.css)
    ├── router/index.ts       ← Rutas + navigation guard
    ├── api/admin.ts          ← Fetch wrappers tipados
    ├── components/
    │   ├── AdminLayout.vue   ← Topbar con navegación
    │   └── ServiceCard.vue   ← Tarjeta reutilizable de servicio
    └── views/
        ├── AdminDashboard.vue   ← /admin — menú central
        ├── AdminUsuarios.vue    ← /admin/usuarios
        ├── AdminServicios.vue   ← /admin/servicios — grid de tarjetas
        └── AdminBaneos.vue      ← /admin/Servicios/Baneos
```

### Módulos de servicios

El grid de `/admin/servicios` está diseñado para crecer. Para agregar un nuevo servicio se crea un componente en `views/` y se añade un `<ServiceCard>` en `AdminServicios.vue`. La primera tarjeta disponible es **Baneos** (`/admin/Servicios/Baneos`).

### Configuración del worker de Baneos

| Campo | Descripción |
|-------|-------------|
| Intervalo (horas) | Cada cuántas horas se envía el reporte Slack (mín. 1) |
| Canales o IDs Slack | Destinos separados por coma. Acepta `#nombre-canal` y IDs tipo `C08UB8ML3LP`. Para canales privados o reinstalaciones del bot, usar ID. |
| Hora de inicio (GMT-3) | Ancla el primer ciclo (0-23); `null` = arrancar de inmediato. |
| Servicio activo | Toggle on/off |
| ▶ Iniciar Worker | Arranca el contenedor si está detenido (Docker SDK). |
| 📤 Enviar Aviso Ahora | Dispara una ejecución manual fuera de ciclo. |
| Verificar Estado | Consulta el health check del worker y muestra estado visual (verde/rojo). El campo `listener_activo` indica si el Socket Mode está corriendo. |

Al guardar, se invoca `POST /reload` al worker para que el nuevo intervalo y destinos tomen efecto de inmediato sin reiniciar el contenedor.

### Monitor de Ingresos (Socket Mode)

Card adicional en `/admin/Servicios/Baneos` que controla el `IngresoListener`.

| Campo | Descripción |
|-------|-------------|
| Canal de Slack | ID (`C...`) o `#nombre` del canal a monitorear |
| Activar monitor | Toggle on/off. Se usa la fila `slack_ingreso_listener` en `app.config_servicios`. |

El listener se ejecuta como daemon thread dentro del proceso `slack_baneo_worker`. Requiere `SLACK_APP_TOKEN` configurado en el entorno; si falta, el thread no arranca y el worker continúa operando normalmente.

**Funcionamiento:** cada mensaje del canal configurado que contenga el campo `Cámara: <nombre>` desencadena:
1. Búsqueda fuzzy del nombre (unidecode + abreviaturas + cascada ILIKE/tokens).
2. Consulta de `camara.estado` en DB.
3. Respuesta en el mismo hilo (`thread_ts`) con uno de los tres estados: no encontrada / libre / baneada (con número de incidente y ticket).

### Templates legacy (mantenidos)

- `web/templates/admin.html` — **deprecado**, supersedido por el SPA. Se mantiene como fallback hasta validación en producción.
- `web/templates/servicios_baneos.html` — **deprecado**, idem.
