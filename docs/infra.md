# Nombre de archivo: infra.md
# Ubicación de archivo: docs/infra.md
# Descripción: Documentación del módulo Infraestructura FO (fibra óptica)

# Infraestructura FO — LAS-FOCAS

## Resumen

El módulo **Infraestructura FO** permite la gestión de cámaras de fibra óptica, trackings de servicio y el **Protocolo de Protección** (baneo de cámaras). Parte del panel web (`/` > tab "Infra/Cámaras").

## Funcionalidades principales

### Búsqueda de cámaras
- **Smart Search**: búsqueda libre por servicio, dirección, cámara, cable
- **Filtros rápidos**: por estado (Libre, Ocupada, Baneada, Detectada, Tracking)
- **Upload de tracking**: carga archivos `.txt` de tracking para asociar cámaras a servicios

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

- `web/templates/panel.html` - Template HTML del panel
- `web/static/panel.js` - Lógica JavaScript del módulo
- `web/static/styles.css` - Estilos CSS
- `web/app/main.py` - Endpoints web
- `api/app/routes/infra.py` - Endpoints API
- `core/services/protection_service.py` - Lógica de negocio del Protocolo de Protección
- `db/models/infra.py` - Modelos de base de datos

## Historial de cambios

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

---

## Entorno de Desarrollo (Dev)

Stack Docker Compose independiente (`lasfocasdev`) que corre en paralelo al productivo sin interferencia.

### Puertos

| Servicio             | Producción                    | Dev                     |
|----------------------|-------------------------------|-------------------------|
| PostgreSQL           | `127.0.0.1:5432`              | `127.0.0.1:5433`        |
| API (docs: `/docs`)  | `:8001`                       | `:8011`                 |
| Web (panel)          | `192.168.241.28:8080`         | `127.0.0.1:8090`        |
| pgAdmin (profile)    | `:5050`                       | `:5051`                 |
| NLP / Office / Slack | interno (sin exposición)      | interno (sin exposición) |

El panel dev está vinculado a `127.0.0.1:8090`. Para acceso desde una máquina remota usar SSH tunneling:

```bash
ssh -L 8090:localhost:8090 usuario@192.168.241.28
```

### Inicio rápido

```bash
# Primera vez: crear .env.dev desde la plantilla
cp deploy/env.dev.sample .env.dev
# Editar credenciales — en especial SLACK_BOT_TOKEN y SLACK_APP_TOKEN (app Slack de dev separada)
nano .env.dev

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

| Variable              | Producción                       | Dev                          |
|-----------------------|----------------------------------|------------------------------|
| `POSTGRES_DB`         | `FOCALDB`                        | `focas_dev`                  |
| `API_BASE`            | `http://192.168.241.28:8080`     | `http://localhost:8090`      |
| `WEB_INFERRED_ORIGIN` | `http://192.168.241.28:8080`     | `http://localhost:8090`      |
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
- `scripts/start_dev.sh` — Script de inicio con healthchecks y clonado opcional de DB

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
