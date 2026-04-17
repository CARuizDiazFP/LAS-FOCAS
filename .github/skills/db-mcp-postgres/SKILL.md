# Nombre de archivo: SKILL.md
# Ubicación de archivo: .github/skills/db-mcp-postgres/SKILL.md
# Descripción: Skill para consultar PostgreSQL de LAS-FOCAS mediante servidor MCP

---
name: db-mcp-postgres
description: "Usar cuando haya que consultar PostgreSQL vía MCP para depurar infraestructura, revisar migraciones Alembic o auditar tablas del esquema app"
argument-hint: "Describe tabla o consulta, por ejemplo: revisar incidentes_baneo y relaciones con camaras"
---

# Skill: MCP PostgreSQL para LAS-FOCAS

Esta habilidad te proporciona las reglas para utilizar el servidor MCP `mcp_postgres` y consultar el estado real de la base de datos compartida del proyecto.

## 🔧 Configuración del Servidor MCP

Para habilitar este skill, configura el servidor MCP en VS Code. Agrega en tu archivo `mcp.json` (accesible desde la paleta de comandos → "MCP: Edit Configuration"):

```json
{
  "servers": {
    "mcp_postgres": {
      "command": "npx",
      "args": ["-y", "mcp-postgres"],
      "env": {
        "DATABASE_URL": "postgresql://lasfocas:cambiar-este-password@127.0.0.1:5432/lasfocas"
      }
    }
  }
}
```

> **Nota**: Ajusta las credenciales según tu `.env` local. El puerto `5432` debe estar expuesto en `deploy/compose.yml` con `ports: - "127.0.0.1:5432:5432"`.

### Requisitos Previos

1. **Node.js 18+** instalado en el sistema
2. **PostgreSQL accesible** desde localhost:5432 (ver configuración en compose.yml)
3. **Reiniciar VS Code** después de modificar `mcp.json`

## 🎯 Reglas de Consulta (Importante)

1. **Esquema Principal**: Todas las tablas del negocio están bajo el esquema `app`:
   - `app.camaras` - Cámaras de fibra óptica
   - `app.ruta_servicio` - Rutas de servicios
   - `app.cables`, `app.empalmes` - Infraestructura de red
   - `app.servicios` - Servicios de clientes
   - `app.users` - Usuarios del sistema
   - `app.chat_sessions`, `app.chat_messages` - Historial de chat
   - `app.incidentes_baneo` - Protocolo de protección
   - `app.reports` - Informes generados

2. **Solo Lectura (Read-Only)**: Utiliza el MCP **estrictamente para consultas `SELECT`**. Si necesitas modificaciones:
   - Cambios de esquema → Migraciones Alembic (`db/alembic/`)
   - Cambios de datos → Scripts en código o endpoints API

3. **Optimización de Contexto**: Limita resultados con `LIMIT 10` al explorar datos nuevos para no saturar la ventana de contexto del agente.

4. **No Exponer Secretos**: Nunca incluir resultados de queries que contengan passwords, tokens o datos sensibles en las respuestas.

## 🛠️ Flujos de Depuración Específicos

### 1. Depuración de Infraestructura FO (Cámaras y Servicios)

Si el usuario reporta que las tarjetas de cámaras perdieron servicios o hay fallos en los correos de protección:

```sql
-- Ver cámaras baneadas actualmente
SELECT id, nombre, estado, baneada_en 
FROM app.camaras 
WHERE estado = 'BANEADA'
LIMIT 20;

-- Verificar incidentes de baneo activos
SELECT id, servicio_afectado, motivo, creado_en, activo
FROM app.incidentes_baneo
WHERE activo = true
ORDER BY creado_en DESC
LIMIT 10;

-- Cruzar cámaras con rutas de servicio
SELECT c.nombre, c.estado, rs.servicio, rs.cliente
FROM app.camaras c
JOIN app.ruta_servicio rs ON c.id = ANY(rs.camaras_ids)
WHERE c.estado = 'BANEADA'
LIMIT 20;
```

**Archivos de código relacionados:**
- `core/parsers/tracking_parser.py` - Parser de archivos de tracking
- `core/services/infra_sync.py` - Sincronización con Google Sheets
- `core/services/email_service.py` - Manejo de notificaciones

### 2. Verificación de Ingesta y Reportes (SLA/Repetitividad)

Si hay dudas sobre normalización de horas (HH:MM vs minutos) o mapeo de Excel:

```sql
-- Ver últimos informes generados
SELECT id, tipo, fecha_generacion, estado, parametros
FROM app.reports
ORDER BY fecha_generacion DESC
LIMIT 10;

-- Verificar datos geoespaciales de cámaras
SELECT id, nombre, latitud, longitud, zona
FROM app.camaras
WHERE latitud IS NOT NULL AND longitud IS NOT NULL
LIMIT 10;

-- Auditar reclamos ingresados (si existe la tabla)
SELECT numero_reclamo, fecha_inicio, horas_netas_minutos, servicio
FROM app.reclamos
ORDER BY fecha_inicio DESC
LIMIT 10;
```

**Archivos de código relacionados:**
- `modules/informes_repetitividad/processor.py` - Normalización de datos
- `modules/informes_sla/processor.py` - Procesamiento SLA
- `core/utils/timefmt.py` - Formateo de horas

### 3. Auditoría de Usuarios y Sesiones

```sql
-- Usuarios activos
SELECT id, username, role, is_active, created_at
FROM app.users
WHERE is_active = true;

-- Últimas sesiones de chat
SELECT id, user_id, created_at, message_count
FROM app.chat_sessions
ORDER BY created_at DESC
LIMIT 10;
```

### 4. Verificación de Migraciones

```sql
-- Ver estado de migraciones Alembic
SELECT version_num FROM alembic_version;

-- Listar tablas del esquema app
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'app'
ORDER BY table_name;

-- Ver columnas de una tabla específica
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'app' AND table_name = 'camaras'
ORDER BY ordinal_position;
```

## ⚠️ Consideraciones de Seguridad

1. **Nunca ejecutar**:
   - `DELETE`, `UPDATE`, `DROP`, `TRUNCATE`
   - Queries sin `LIMIT` en tablas grandes
   - Queries que expongan `hashed_password` u otros campos sensibles

2. **Siempre**:
   - Usar `LIMIT` al explorar datos nuevos
   - Verificar el contexto antes de mostrar resultados al usuario
   - Sugerir migraciones Alembic para cambios de esquema

## 🔗 Integración con Agentes

Este skill está referenciado en:
- `.github/agents/db.agent.md` - Agente de base de datos
- `.github/agents/infra.agent.md` - Agente de infraestructura

### Ejemplo de Uso

```
@db ¿puedes usar el skill db-mcp-postgres para contar cuántas cámaras están BANEADAS actualmente?
```

El agente ejecutará:
```sql
SELECT COUNT(*) as total_baneadas FROM app.camaras WHERE estado = 'BANEADA';
```
