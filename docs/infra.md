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
- `web/web_app/main.py` - Endpoints web
- `api/api_app/routes/infra.py` - Endpoints API
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
