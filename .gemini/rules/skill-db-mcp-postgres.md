# Nombre de archivo: skill-db-mcp-postgres.md
# Ubicación de archivo: .gemini/rules/skill-db-mcp-postgres.md
# Descripción: Regla Gemini portable migrada desde .github/skills/db-mcp-postgres/SKILL.md
---
name: "skill-db-mcp-postgres"
description: "Usar cuando haya que consultar PostgreSQL vía MCP para depurar infraestructura, revisar migraciones Alembic o auditar tablas del esquema app"
source: ".github/skills/db-mcp-postgres/SKILL.md"
triggers:
  - "db-mcp-postgres"
  - "mcp"
  - "postgresql"
  - "las-focas"
  - "consultar"
  - "v-a"
  - "depurar"
  - "infraestructura"
  - "migraciones"
  - "alembic"
  - "auditar"
  - "tablas"
  - "esquema"
  - "app"
  - "cromo"
globs:
  - "db/**"
  - "deploy/**"
commands:
  []
---

# Regla Skill: db-mcp-postgres

> Fuente original: `.github/skills/db-mcp-postgres/SKILL.md`. Usar esta regla cuando Gemini/Codex IDE detecte los triggers o globs declarados.

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
   - `app.camaras` - Cámaras de fibra óptica. Desde 2026-08-10 tiene `camara_padre_id` (FK
     auto-referencial nullable, jerarquía Cámara→Botella de 2 niveles) — ver sección 4b más abajo.
   - `app.rutas_servicio` - Rutas de servicios (nombre real en plural, no `app.ruta_servicio`)
   - `app.cables`, `app.empalmes` - Infraestructura de red
   - `app.servicios` - Servicios de clientes
   - `app.users` - Usuarios del sistema
   - `app.chat_sessions`, `app.chat_messages` - Historial de chat
   - `app.incidentes_baneo` - Protocolo de protección
   - `app.camaras_estado_auditoria` - Auditoría de todo cambio de `Camara.estado` — única fuente de
     verdad para reconstruir el estado previo real de una cámara, ver sección 4b.
   - `app.reports` - Informes generados
   - `app.cromo_*` - Inventario FO ingerido desde Cromo Red (cables, botellas, tubos, pelos, fusiones,
     corridas de ingesta, config de scheduler) — ver sección 4 más abajo

2. **Solo Lectura (Read-Only)**: Utiliza el MCP **estrictamente para consultas `SELECT`**. Si necesitas modificaciones:
   - Cambios de esquema → Migraciones Alembic (`db/alembic/`)
   - Cambios de datos → Scripts en código o endpoints API

3. **Optimización de Contexto**: Limita resultados con `LIMIT 10` al explorar datos nuevos para no saturar la ventana de contexto del agente.

4. **No Exponer Secretos**: Nunca incluir resultados de queries que contengan passwords, tokens o datos sensibles en las respuestas.

## 🛠️ Flujos de Depuración Específicos

### 1. Depuración de Infraestructura FO (Cámaras y Servicios)

Si el usuario reporta que las tarjetas de cámaras perdieron servicios o hay fallos en los correos de protección:

```sql
-- Ver cámaras baneadas actualmente (Camara no tiene columna "baneada_en" — el momento del baneo vive
-- en incidentes_baneo.fecha_inicio o en camaras_estado_auditoria.created_at, no en la fila misma)
SELECT id, nombre, estado, camara_padre_id
FROM app.camaras
WHERE estado = 'BANEADA'
LIMIT 20;

-- Verificar incidentes de baneo activos (columnas reales: servicio_afectado_id, fecha_inicio)
SELECT id, ticket_asociado, servicio_afectado_id, servicio_protegido_id, motivo, fecha_inicio, activo
FROM app.incidentes_baneo
WHERE activo = true
ORDER BY fecha_inicio DESC
LIMIT 10;

-- Cruzar cámaras con rutas de servicio (no existe app.ruta_servicio.camaras_ids — la relación real es
-- Servicio → RutaServicio → Empalme → Camara)
SELECT c.nombre, c.estado, s.servicio_id
FROM app.camaras c
JOIN app.empalmes e ON e.camara_id = c.id
JOIN app.ruta_empalme_association rea ON rea.empalme_id = e.id
JOIN app.rutas_servicio rs ON rs.id = rea.ruta_id
JOIN app.servicios s ON s.id = rs.servicio_id
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

-- Verificar datos geoespaciales de cámaras (Camara no tiene columna "zona")
SELECT id, nombre, latitud, longitud
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

### 4. Inventario Cromo Red (planta externa FO)

Tablas pobladas por el módulo de ingesta Cromo (ver `docs/modulo_ingesta_cromo.md` y la regla
`skill-cromo-inventario` para el detalle completo). Datos reales, no de prueba:

```sql
-- Cables por jerarquía (ojo: jerarquia tiene ~10 valores reales distintos, no sólo
-- "Acceso"/"Troncal"/"Subtroncal" — usar ILIKE, nunca comparación exacta)
SELECT jerarquia, count(*) FROM app.cromo_cables GROUP BY 1 ORDER BY 2 DESC;

-- Última corrida de ingesta y su estado
SELECT id, estado, iniciada_at, finalizada_at, ultimo_error
FROM app.cromo_ingesta_corridas ORDER BY id DESC LIMIT 5;

-- Configuración del scheduler automático (fila única)
SELECT habilitado, intervalo_horas, hora_inicio, psize, clases, ultima_ejecucion, ultimo_error
FROM app.cromo_ingesta_config;
```

**Gotcha real de `asyncpg`** (encontrado en `core/services/cromo/inventario.py`): si escribís un
`WHERE` con varios filtros opcionales que pueden venir todos `NULL` a la vez, `asyncpg` no puede
inferir el tipo del bind parameter y tira `AmbiguousParameterError`. Desde el MCP (que ejecuta SQL
literal, sin bind params) esto no aplica — pero si estás **escribiendo código** con `sqlalchemy.text()`
y parámetros opcionales, casteá explícito: `CAST(:param AS text)`, no el atajo `:param::text`
(SQLAlchemy interpreta mal el `::` pegado al bind parameter).

**Archivos de código relacionados:**
- `core/services/cromo/inventario.py` - Inventario navegable (búsqueda + paginación)
- `core/services/cromo/verificador.py` - Qué servicios pasan por un cable/tubo/botella puntual
- `core/services/cromo/ingesta.py` - Fases del barrido periódico

### 4b. Jerarquía Cámara→Botella y auditoría de estado (2026-08-10)

```sql
-- Grupo completo de una Cámara (ella + todas sus Botellas)
SELECT id, nombre, estado, camara_padre_id
FROM app.camaras
WHERE id = 2663 OR camara_padre_id = 2663;

-- Última transición a BANEADA de una cámara — única forma de saber su estado REAL previo
SELECT camara_id, usuario, motivo, estado_anterior, estado_nuevo, created_at
FROM app.camaras_estado_auditoria
WHERE camara_id = 753 AND estado_nuevo = 'BANEADA'
ORDER BY created_at DESC LIMIT 1;
```

**Archivos de código relacionados:**
- `core/services/camara_hierarchy_service.py` - Detección de sufijo "Bot N", resolución de padre
- `core/services/camara_estado_service.py` - `aplicar_estado_a_grupo()`, `obtener_ultima_transicion_a_baneada()`
- `core/services/protection_service.py` - Protocolo de Protección con cascada de grupo
- `core/services/botellas_unificadas_service.py` - Listado unificado Cromo + legado
- `.gemini/rules/skill-baneo-qa-real.md` - Metodología para probar cascadas de baneo sin causar drift

### 5. Verificación de Migraciones

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
