# Nombre de archivo: infra.md
# Ubicación de archivo: docs/infra.md
# Descripción: Documentación del módulo Infraestructura FO para la SPA Vue 3 y la API asociada

# Infraestructura FO — LAS-FOCAS

## Resumen

El módulo **Infraestructura FO** permite la gestión de cámaras de fibra óptica, trackings de servicio y el **Protocolo de Protección** (baneo de cámaras). Vive en la SPA Vue 3 del panel web y consume endpoints JSON del backend.

## Funcionalidades principales

### Búsqueda de cámaras
- **Smart Search**: búsqueda libre por servicio, dirección, cámara, cable
- **Filtros rápidos**: por estado (Libre, Ocupada, Baneada, Detectada, Tracking)
- **Upload de tracking**: carga archivos `.txt` de tracking para asociar cámaras a servicios

### Vista principal y detalle dedicado
- **Tarjeta principal resumida**: cada cámara muestra solo nombre canon, ID numérico interno y estado.
- **Vista dedicada por cámara**: `GET /infra/Camaras/:id` dentro de la SPA Vue 3.
- **Dashboard de detalle**: tarjetas clickeables para alias, registros y servicios asociados.
- **Edición de estado reubicada**: el botón `Editar estado` sale de la tarjeta principal y vive en el header del detalle.

### Detalle operativo por cámara
La vista dedicada realiza carga paralela contra endpoints same-origin del servicio `web`:

- `GET /api/infra/camaras/{id}`
- `GET /api/infra/camaras/{id}/aliases`
- `GET /api/infra/camaras/{id}/registros`
- `GET/POST /api/infra/camaras/{id}/estado` para edición admin con CSRF

En esta iteración, **Registros** muestra solo la lógica operativa ya existente:

- pestaña **Ingresos** estructurada sobre un arreglo reactivo vacío, lista para futura hidratación desde backend
- pestaña **Baneos** con historial ordenado por fecha de inicio descendente y accordions retraídos por defecto
- auditoría manual de cambios de estado (`app.camaras_estado_auditoria`) como trazabilidad complementaria dentro de la pestaña de baneos

La tarjeta **Servicios Asociados** muestra la lista de IDs de servicio asociados ordenada de mayor a menor. Cada ID abre un segundo `dialog` modal superpuesto con el tracking detallado del servicio, reutilizando `TrackingDetail.vue` y la descarga del TXT actual.

Para el detalle fino de la UX web y del apilado de modales, la referencia principal queda en `docs/web.md`.

### Contratos y seguridad

- La vista usa contratos JSON del backend y no duplica lógica de negocio en el frontend.
- Las ediciones de estado requieren sesión válida y CSRF.
- Los listados se renderizan desde datos tipados; no se debe introducir DOM directo ni plantillas legacy.

### Protocolo de Protección (Baneo)
Sistema para proteger cámaras durante afectaciones de servicio, impidiendo trabajos en ellas hasta resolución.

#### Flujo de baneo
1. Click en **🚨 Protocolo Protección**
2. Wizard guiado: ticket, servicio afectado, servicio protegido, motivo
3. Confirmación y ejecución del baneo
4. Las cámaras cambian a estado `BANEADA`

#### Gestión de baneos activos
- **Badge indicador**: muestra cantidad de baneos activos en el header
- **Indicador de cámaras**: total de cámaras restringidas en el header
- **Modal de baneos activos**: click en el badge abre el modal con todos los baneos

### Notificaciones de baneo (Dar Aviso)

> **Cambio importante (2026-04-17)**: El botón "Dar Aviso" fue movido del header principal al modal de baneos activos.

#### Flujo anterior (deprecado)
El botón global "Dar Aviso" solo permitía notificar el primer baneo activo, causando que al tener múltiples baneos, solo se pudiera enviar aviso de uno.

#### Flujo actual
1. Click en el badge **🔒 N ACTIVOS** para abrir el modal
2. Cada baneo tiene su propio botón **📧 Dar Aviso**
3. Click en el botón abre el editor de correo con datos específicos de ese baneo
4. Enviar correo o descargar como EML

**Beneficios:**
- Independencia de avisos: cada baneo se notifica individualmente
- No hay mezcla de datos entre baneos
- El usuario puede enviar avisos de múltiples baneos consecutivamente

### Indicador global de cámaras afectadas

En el header de Infraestructura FO se muestra un indicador con el total de cámaras baneadas sumando todos los protocolos activos:

```
📷 29 cámaras restringidas
```

Este indicador:
- Aparece solo cuando hay baneos activos
- Suma las cámaras de todos los baneos
- Se actualiza al crear/levantar baneos

## Componentes UI

### Header principal
```
[🔒 2 ACTIVOS] [📷 29 cámaras restringidas] [🚨 PROTOCOLO PROTECCIÓN] [🔌 FO INFRA]
```

### Modal de baneos activos
```
┌─────────────────────────────────────────────┐
│ 🔒 Baneos Activos                        ✕  │
├─────────────────────────────────────────────┤
│ Cámaras protegidas por el Protocolo...      │
│                                             │
│ ┌─────────────────────────────────────────┐ │
│ │ MKT-1253765              ⏱️ 3.87h       │ │
│ │ Afectado: 52547 → Protegido: 52547      │ │
│ │ 📅 10/3/2026, 11:06:15                  │ │
│ │ [📧 Dar Aviso] [🔓 Levantar Baneo]      │ │
│ └─────────────────────────────────────────┘ │
│                                             │
│ ┌─────────────────────────────────────────┐ │
│ │ MKT-1241208              ⏱️ 3.88h       │ │
│ │ Afectado: 93152 → Protegido: 93155      │ │
│ │ 📅 10/3/2026, 11:05:04                  │ │
│ │ Corte de FO                             │ │
│ │ [📧 Dar Aviso] [🔓 Levantar Baneo]      │ │
│ └─────────────────────────────────────────┘ │
│                                             │
│ ☐ Enviar aviso por correo al desbanear     │
│                                  [Cerrar]   │
└─────────────────────────────────────────────┘
```

## API Endpoints

### GET /api/infra/camaras/{camara_id}
Obtiene el resumen operativo base de una cámara para la vista dedicada. Incluye nombre, ID, estado, editabilidad y servicios/rutas asociados.

### GET /api/infra/rutas/{ruta_id}/tracking
Obtiene la secuencia de tracking de una ruta FO (`punta_a`, `tracking[]`, `punta_b`) para el modal de servicios de la vista dedicada.

### GET /api/infra/tracking/{ruta_id}/download
Descarga el TXT actual de una ruta. La vista dedicada lo usa desde la tarjeta **Servicios Asociados** para mantener paridad con el flujo productivo.

### GET /api/infra/camaras/{camara_id}/aliases
Obtiene los alias conocidos de una cámara desde `app.camara_alias`.

### GET /api/infra/camaras/{camara_id}/registros
Obtiene registros operativos parciales: auditoría manual de estado, baneos relacionados y placeholders de ingresos/egresos.

### GET /api/infra/ban/active
Lista todos los incidentes de baneo activos con conteo de cámaras.

**Response:**
```json
{
  "status": "ok",
  "total": 2,
  "incidentes": [
    {
      "id": 42,
      "ticket_asociado": "MKT-1253765",
      "servicio_afectado_id": "52547",
      "servicio_protegido_id": "52547",
      "ruta_protegida_id": 15,
      "usuario_ejecutor": "operador1",
      "motivo": "Afectación de servicio",
      "fecha_inicio": "2026-03-10T11:06:15+00:00",
      "activo": true,
      "duracion_horas": 3.87,
      "camaras_count": 29
    }
  ]
}
```

### GET /api/infra/ban/{incidente_id}
Obtiene detalle de un incidente específico para componer el correo.

### POST /api/infra/ban/create
Crea un nuevo baneo (Protocolo de Protección).

### POST /api/infra/ban/lift
Levanta un baneo y restaura el estado de las cámaras.

### POST /api/infra/notify/email
Envía notificación por correo de un baneo específico.

### POST /api/infra/notify/download-eml
Genera archivo EML para descargar y abrir en Outlook.

## Archivos relacionados

- `web/frontend/src/views/tabs/InfraTab.vue` - Tab principal de Infraestructura FO
- `web/frontend/src/views/CamaraDetailView.vue` - Vista dedicada por cámara
- `web/frontend/src/components/infra/` - Modales aislados de alias, servicios, registros y edición de estado
- `web/frontend/src/router/index.ts` - Ruta SPA `/infra/Camaras/:id`
- `web/app/main.py` - Endpoints web same-origin para listado y detalle
- `api/app/routes/infra.py` - Endpoints API base y búsquedas de infraestructura
- `core/services/camara_estado_service.py` - Lógica de contexto y auditoría de estado
- `core/services/protection_service.py` - Lógica de negocio del Protocolo de Protección
- `db/models/infra.py` - Modelos de cámaras, alias, auditoría e incidentes

## Historial de cambios

### 2026-05-13 - Refactor de tarjetas FO y vista dedicada por cámara
- **Corregido**: la grilla principal vuelve a mostrar el `id` numérico real de cámara en lugar de depender de `fontine_id`.
- **Modificado**: las tarjetas principales se simplifican a `Nombre canon + ID + Estado`, removiendo detalle operativo inline.
- **Agregado**: ruta SPA `/infra/Camaras/:id` con vista dedicada `CamaraDetailView.vue`.
- **Agregado**: endpoints web same-origin `GET /api/infra/camaras/{id}`, `GET /api/infra/camaras/{id}/aliases` y `GET /api/infra/camaras/{id}/registros`.
- **Agregado**: modales aislados para alias conocidos, servicios asociados, registros y edición manual de estado.
- **Recuperado**: la tarjeta `Servicios Asociados` vuelve a exponer la secuencia de tracking productiva con tabs por ruta y descarga del TXT actual.
- **Corregido**: el modal `Editar estado` de la vista dedicada vuelve a usar el estilo dark coherente con el dashboard.
- **Diseño**: la tarjeta `Registros` se divide en tabs `Ingresos/Baneos`; los baneos usan accordions ordenados por fecha y los ingresos quedan maquetados hasta contar con backend dedicado.

### 2026-04-17 - Refactor de avisos individuales y conteo de cámaras
- **Eliminado**: Botón global "Dar Aviso" del header principal
- **Agregado**: Botón "Dar Aviso" individual en cada fila del modal de baneos
- **Agregado**: Indicador global de cámaras restringidas en el header
- **Modificado**: Endpoint `/api/infra/ban/active` ahora incluye `camaras_count`
- **Beneficio**: Soporte correcto para múltiples baneos activos simultáneos

### 2026-04-17 - Worker de notificaciones Slack para baneos
- **Agregado**: Nuevo contenedor `slack_baneo_worker` que envía periódicamente un reporte de cámaras baneadas a canales de Slack
- **Agregado**: Tabla `app.config_servicios` para configuración dinámica del worker (intervalo, canales, estado)
- **Agregado**: Panel admin en `/admin/Servicios/Baneos` para gestionar la configuración y verificar el health del worker
- **Componentes**: `modules/slack_baneo_notifier/` (worker + notifier), `deploy/docker/slack_baneo_worker.Dockerfile`
- **Tecnología**: APScheduler para periodicidad, `slack_sdk` para envío, health check HTTP embebido (puerto 8095)
- **Característica**: Reconfiguración dinámica sin reinicio — el worker relee la config de la DB en cada ejecución y reprograma el scheduler si el intervalo cambió
- **Logs**: Se centralizan en `Logs/slack_baneo_worker.log` vía `LOGS_DIR=/app/Logs` y además permanecen accesibles por `docker compose logs`

### 2026-04-20 - Normalización manual de estados de cámaras
- **Agregado**: Servicio `core/services/camara_estado_service.py` para calcular estado sugerido, detectar inconsistencias y auditar overrides manuales
- **Agregado**: Tabla `app.camaras_estado_auditoria` + migración `20260420_01_camaras_estado_auditoria.py`
- **Agregado**: Endpoints web `GET/POST /api/infra/camaras/{id}/estado` con restricción a `admin` y validación CSRF
- **Agregado**: Modal de edición de estado en tarjetas de Infra/Cámaras con motivo obligatorio e incidentes activos relacionados
- **Modificado**: `GET /api/infra/ban/active` ahora expone `camaras_baneadas_count` y `total_camaras_baneadas`
- **Beneficio**: permite corregir discrepancias operativas sin perder trazabilidad y elimina falsos positivos en el conteo visual de cámaras baneadas

### 2026-04-21 - Hot reload del worker Slack y correcciones UX del editor de cámaras
- **Modificado**: `slack_baneo_worker` expone `POST /reload` para releer `app.config_servicios` y reprogramar el scheduler sin esperar la próxima ejecución.
- **Modificado**: el panel admin de baneos acepta IDs de canal Slack (ej: `C08UB8ML3LP`) además de nombres con `#`.
- **Corregido**: el editor de estado de cámaras usa endpoints same-origin del servicio `web` en lugar de `API_BASE`, eliminando `404` al abrir el modal cuando el frontend apunta a `:8001`.
- **Corregido**: las tarjetas muestran `Editar estado` a usuarios `admin` aunque un payload legacy no incluya `editable`, manteniendo la autorización real en backend.

### 2026-04-24 - Listener de ingresos técnicos via Slack Socket Mode
- **Agregado**: `modules/slack_baneo_notifier/camara_search.py` — búsqueda fuzzy de cámaras: normalización unidecode, expansión de abreviaturas (cra, av, clle, pje, bv, dr), cascada ILIKE → tokens AND → retry sin números.
- **Agregado**: `modules/slack_baneo_notifier/listener.py` — `IngresoListener` (slack_bolt Socket Mode) que escucha mensajes con `Cámara: <nombre>` en un canal configurado y responde en hilo con estado de baneo (libre / baneada con #incidente / no encontrada).
- **Modificado**: `worker.py` — arranca `IngresoListener` como daemon thread si `SLACK_APP_TOKEN` está disponible; expone `listener_activo: bool` en `/health`.
- **Dependencias**: `slack_bolt>=1.22,<2` y `unidecode>=1.3.8` añadidos a `modules/slack_baneo_notifier/requirements.txt`; `slack_bolt>=1.22,<2` añadido a `requirements-dev.txt` para resolución local.
- **Variable de entorno nueva**: `SLACK_APP_TOKEN` (xapp-...) en `deploy/env.sample` — ya estaba declarado; no requiere cambio de compose.
- **Sin migración**: el listener usa `app.config_servicios` con una nueva fila `slack_ingreso_listener` creada en primer arranque; sin cambios de esquema.
- **Panel admin**: nueva card "🎧 Monitor de Ingresos" en `/admin/Servicios/Baneos` (toggle activo + canal ID + guardar).
- **Tests**: `tests/test_slack_ingreso_listener.py` — 15/15 pasan.

### 2026-04-27 - Correcciones `unaccent` y zona horaria GMT-3
- **Corregido**: error `function unaccent(text) does not exist` al buscar cámaras desde el listener. Causa: extensión `unaccent` no instalada en PostgreSQL. Solución: migración `20260427_01_unaccent_extension.py` + `CREATE EXTENSION IF NOT EXISTS unaccent;` en `db/init.sql` para nuevos entornos.
- **Corregido**: logs del worker mostraban hora UTC en lugar de GMT-3. Solución tripartita:
  1. `core/logging.py` — nuevo `_ArgTzFormatter` con `converter()` basado en `zoneinfo.ZoneInfo(APP_TIMEZONE)`.
  2. `deploy/compose.yml` — variables `TZ=America/Argentina/Buenos_Aires` y `APP_TIMEZONE=America/Argentina/Buenos_Aires` en el servicio `slack_baneo_worker`.
  3. `deploy/docker/slack_baneo_worker.Dockerfile` — instalación de `tzdata` + `ENV TZ=America/Argentina/Buenos_Aires`.
- **Corregido**: `BlockingScheduler()` instanciado sin `timezone`, lo que podía causar offsetting incorrecto en el scheduler. Ahora: `BlockingScheduler(timezone=TZ_ARG)` donde `TZ_ARG = ZoneInfo("America/Argentina/Buenos_Aires")`.
- **Resultado verificado en logs**: `Next wakeup is due at 2026-04-28 07:00:00-03:00` — offset explícito `-03:00`; timestamps de inicio del worker en hora local Argentina.

### 2026-04-28 - Entorno de Desarrollo (Dev) aislado
- **Agregado**: `deploy/docker-compose.dev.yml` — stack Docker Compose paralelo con nombre de proyecto `lasfocasdev`, puertos alternativos y red propia `lasfocas_dev_net`.
- **Agregado**: `deploy/env.dev.sample` — plantilla de variables para entorno dev; DB apunta a `focas_dev`, LLM en modo `heuristic`, web en `localhost:8090`.
- **Agregado**: `scripts/start_dev.sh` — script bash con flags `--clone-db`, `--no-build`, `--down`; incluye espera de Postgres, migraciones Alembic y healthchecks.
- **Sin impacto en producción**: el stack prod (`compose.yml`, `.env`) no fue modificado.

### 2026-04-29 - Imagen base focas-base:latest con multi-stage build
- **Agregado**: `common-requirements.txt` — 22 paquetes Python comunes a todos los servicios (FastAPI, SQLAlchemy, pandas, etc.).
- **Agregado**: `deploy/docker/base.Dockerfile` — patrón multi-stage: stage `builder` compila wheels con `build-essential/gcc/libpq-dev`; stage `runtime` instala solo los wheels pre-compilados sin herramientas de compilación.
- **Agregado**: `scripts/build_base.sh` — construye `focas-base:latest` con detección de cambios vía hash SHA-256 de `common-requirements.txt` para evitar rebuilds innecesarios.
- **Modificado**: `api/Dockerfile`, `web/Dockerfile`, `deploy/docker/bot.Dockerfile`, `deploy/docker/nlp_intent.Dockerfile`, `deploy/docker/slack_baneo_worker.Dockerfile`, `deploy/docker/repetitividad_worker.Dockerfile` — reemplazado `FROM python:3.11-slim*` por `FROM focas-base:latest`.
- **Modificado**: `api/requirements.txt`, `web/requirements.txt`, `bot_telegram/requirements.txt`, `nlp_intent/requirements.txt`, `modules/slack_baneo_notifier/requirements.txt` — eliminados los 22 paquetes comunes (ya en la imagen base).
- **Actualizado**: `Start` y `scripts/start_dev.sh` — llaman a `build_base.sh` automáticamente antes de levantar el stack.
- **Excluido**: `office_service/Dockerfile` queda sin cambios (usa fastapi 0.111.1/pydantic 2.8.2/uvicorn 0.30.1 + LibreOffice, incompatible con la base común).
- **Armonización de versiones**: `SQLAlchemy` 2.0.32→2.0.36, `psycopg[binary]` 3.1.19→3.2.1 en `requirements.txt` raíz y `slack_baneo_notifier/requirements.txt`.

### 2026-05-12 - Restauración de avisos Slack en Protocolo de Protección
- **Corregido**: los baneos ejecutados desde el panel Vue 3 entran por `web/app/main.py`; esa ruta persistía el incidente pero no disparaba el aviso inmediato a Slack ni el reporte actualizado.
- **Corregido**: `POST /api/infra/ban/create` y `POST /api/infra/ban/lift` del servicio `web` ahora reutilizan `modules.slack_baneo_notifier.eventos` igual que `api`, manteniendo el aviso puntual y el reenvío del reporte de cámaras baneadas.
- **Agregado**: `slack_sdk==3.33.5` en `web/requirements.txt`, porque el contenedor `web` no incluía la dependencia necesaria para ejecutar ese flujo.
- **UX**: el modal del wizard de Protocolo de Protección se cierra automáticamente tras un alta exitosa y reinicia su estado interno.

---

## Entorno de Desarrollo (Dev)

Stack Docker Compose independiente (`lasfocasdev`) que corre en paralelo al productivo sin interferencia.

### Puertos

| Servicio             | Producción                    | Dev                     |
|----------------------|-------------------------------|-------------------------|
| PostgreSQL           | `127.0.0.1:5432`              | `127.0.0.1:5433`        |
| API (docs: `/docs`)  | `:8001`                       | `:8011`                 |
| Web (panel)          | `172.18.208.162:8080`         | `127.0.0.1:8090`        |
| pgAdmin (profile)    | `:5050`                       | `:5051`                 |
| NLP / Office / Slack | interno (sin exposición)      | interno (sin exposición) |

El panel dev está vinculado a `127.0.0.1:8090`. Para acceso desde una máquina remota usar SSH tunneling:

### Secretos dev adicionales

- `api_key_v1` (dev: `.secrets/Dev_api_key_v1.txt`; prod: `.secrets/api_key_v1.txt`): API key interna para proteger rutas sensibles del servicio `api`.
- `web_secret_key_v1` (dev: `.secrets/Dev_web_secret_key_v1.txt`; prod: `.secrets/web_secret_key_v1.txt`): firma de cookie de sesión del panel web.
- `scripts/setup_local_secrets.sh` genera los archivos `Dev_*.txt` de forma idempotente para dev/CI; en producción, `deploy/compose.yml` usa el mismo mecanismo de Docker Compose Secrets pero con archivos sin prefijo (ver `docs/Seguridad.md`).

```bash
ssh -L 8090:localhost:8090 usuario@172.18.208.162
```

### Inicio rápido

```bash
# Primera vez: crear .env.dev desde la plantilla
cp deploy/env.dev.sample .env.dev
# Editar valores no sensibles y placeholders de compatibilidad
nano .env.dev

# Crear Docker Secrets locales de desarrollo
./scripts/setup_local_secrets.sh

# Levantar stack dev (build + migraciones + healthchecks)
./scripts/start_dev.sh

# Levantar con clonado de base de datos de prod → dev
./scripts/start_dev.sh --clone-db

# Levantar sin rebuild (iteración rápida)
./scripts/start_dev.sh --no-build
```

### Detener el stack dev

```bash
docker compose -f deploy/docker-compose.dev.yml down
```

### Variables de entorno

`deploy/env.dev.sample` → copiar a `.env.dev` en la raíz. Diferencias clave respecto a `.env`:

En dev, las credenciales reales se leen primero desde Docker Secrets montados en
`/run/secrets/*`, cuyos archivos fuente en `.secrets/` usan el prefijo `Dev_`
(ej. `Dev_db_password_v1.txt`). En producción se usa el mismo mecanismo con
archivos sin prefijo (ej. `.secrets/db_password_v1.txt`), ya implementado en
`deploy/compose.yml`. Si falta un archivo, el código cae a `.env`/`.env.dev`
para mantener compatibilidad durante la transición. Si se cambia
`db_password_v1.txt` (o `Dev_db_password_v1.txt`) sobre un volumen PostgreSQL
ya inicializado, el valor debe coincidir exactamente con la contraseña vigente
del rol — cambiarlo sin actualizar el rol o recrear el volumen rompe la
autenticación (ver `docs/Seguridad.md`).

| Variable              | Producción                       | Dev                          |
|-----------------------|----------------------------------|------------------------------|
| `POSTGRES_DB`         | `FOCALDB`                        | `focas_dev`                  |
| `API_BASE`            | `http://172.18.208.162:8080`     | `http://localhost:8090`      |
| `WEB_INFERRED_ORIGIN` | `http://172.18.208.162:8080`     | `http://localhost:8090`      |
| `SLACK_BOT_TOKEN`     | token de app Slack prod          | token de app Slack dev       |
| `SLACK_APP_TOKEN`     | token de app Slack prod          | token de app Slack dev       |
| `LLM_PROVIDER`        | `openai`                         | `heuristic` (sin costo/API)  |
| `LOG_LEVEL`           | `INFO`                           | `DEBUG`                      |

### Clonar DB de producción a dev

```bash
./scripts/start_dev.sh --clone-db
```

Requisito: el contenedor `lasfocas-postgres` (prod) debe estar corriendo. El script hace `pg_dump` del esquema prod y lo restaura en `focas_dev` con `--clean --if-exists`.

### Limitación conocida: panel admin y docker.sock

El servicio `web` monta `/var/run/docker.sock` para permitir al panel admin controlar el `slack_baneo_worker`. En producción el panel busca el contenedor `lasfocas-slack-baneo-worker`. En dev, el contenedor se llama `lasfocasdev-slack-baneo-worker`, por lo que el toggle del panel dev no controlará el worker dev vía socket. El worker dev funciona correctamente de forma autónoma; solo el control desde la UI admin queda limitado en este entorno.

### Archivos relacionados

- `deploy/docker-compose.dev.yml` — Stack Docker Compose dev
- `deploy/env.dev.sample` — Plantilla de variables de entorno dev
- `.secrets/` — Secretos locales dev ignorados por Git
- `scripts/setup_local_secrets.sh` — Bootstrap idempotente de secretos dev/CI
- `scripts/check_no_plaintext_secrets.sh` — Control preventivo anti-secretos
- `scripts/start_dev.sh` — Script de inicio con healthchecks y clonado opcional de DB

### Purga local de secretos históricos

Antes de publicar una rama reescrita, coordinar ventana de trabajo, partir de un
árbol limpio y conservar un backup del repo. En esta VM `git filter-repo` debe
estar instalado previamente.

```bash
cat > /tmp/las-focas-replacements.txt <<'EOF'
<password_db_historico_prod>==>***REMOVED***
<password_db_historico_dev>==>***REMOVED***
<password_default_historico>==>***REMOVED***
<hash_bcrypt_admin_historico>==>***REMOVED***
EOF

git filter-repo --replace-text /tmp/las-focas-replacements.txt --force
git grep -n "<patron_historico_a_validar>" $(git rev-list --all)
```

Después de validar, publicar con `git push --force-with-lease origin dev` y
avisar al equipo que debe resincronizar sus clones.

---

## Imagen base Docker: `focas-base:latest`

Imagen multi-stage compartida por todos los servicios Python del proyecto (excepto `office_service`).

### Qué incluye

22 paquetes Python directos y todas sus dependencias transitivas, pre-compilados como wheels en el stage `builder` e instalados en el stage `runtime` sin herramientas de compilación:

| Grupo | Paquetes |
|-------|----------|
| FastAPI stack | `fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`, `httpx`, `orjson` |
| Web extras | `jinja2`, `itsdangerous`, `python-multipart`, `bcrypt` |
| DB / ORM | `SQLAlchemy`, `psycopg[binary]`, `alembic` |
| Data | `pandas`, `openpyxl`, `python-docx`, `Unidecode` |
| Geo / Maps | `matplotlib`, `Pillow`, `staticmap`, `contextily`, `pyproj` |

Además incluye en runtime: `curl`, `libpq5`, `libexpat1`, `tzdata`, `ca-certificates`.

### Patrón multi-stage

```
builder (python:3.11-slim-bookworm)
  └─ apt: build-essential gcc libpq-dev libffi-dev libssl-dev
  └─ pip wheel --wheel-dir /wheels -r common-requirements.txt
        ↓ wheels de todos los paquetes + transitive deps
runtime (python:3.11-slim-bookworm)  ← imagen final
  └─ apt: curl libpq5 libexpat1 tzdata ca-certificates
  └─ pip install --no-index --find-links=/wheels ...
  └─ rm -rf /wheels  ← limpia en el mismo layer
```

### Cuándo reconstruir

`build_base.sh` detecta automáticamente si `common-requirements.txt` cambió (hash SHA-256) y solo reconstruye cuando es necesario.

Casos que requieren rebuild manual:
- Se agrega o actualiza un paquete en `common-requirements.txt`
- Se cambia la versión base de Python

### Comandos

```bash
# Build automático (detecta cambios)
./scripts/build_base.sh

# Forzar rebuild aunque no haya cambios
./scripts/build_base.sh --force

# Build manual directo
docker build -t focas-base:latest -f deploy/docker/base.Dockerfile .
```

`Start` y `scripts/start_dev.sh` llaman a `build_base.sh` automáticamente antes de levantar el stack.

### Excepción: office_service

`office_service/Dockerfile` usa `fastapi==0.111.1`, `pydantic==2.8.2` y `uvicorn==0.30.1` (versiones distintas a las de `focas-base`) además de `python3-uno` y LibreOffice instalados desde apt. No hereda de `focas-base`.

### Archivos relacionados

- `common-requirements.txt` — 22 paquetes comunes (fuente de verdad de la imagen base)
- `deploy/docker/base.Dockerfile` — Dockerfile multi-stage
- `scripts/build_base.sh` — Script de build con detección de cambios
