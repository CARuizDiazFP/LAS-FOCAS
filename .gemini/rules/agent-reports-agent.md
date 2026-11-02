# Nombre de archivo: agent-reports-agent.md
# Ubicación de archivo: .gemini/rules/agent-reports-agent.md
# Descripción: Regla Gemini portable migrada desde .github/agents/reports.agent.md
---
name: "agent-reports-agent"
description: "Usar cuando la tarea trate de informes SLA, repetitividad, plantillas DOCX/PDF, builders o lógica en modules/informes_* y core/sla"
source: ".github/agents/reports.agent.md"
triggers:
  - "reports"
  - "agente"
  - "trate"
  - "informes"
  - "sla"
  - "repetitividad"
  - "plantillas"
  - "docx"
  - "pdf"
  - "builders"
  - "l-gica"
  - "modules"
  - "core"
globs:
  - "web/**"
  - "api/**"
  - "api_app/**"
  - "db/**"
  - "tests/**"
  - "pytest.ini"
  - "core/sla_consumo/**"
  - "core/sla/**"
  - "Templates/**"
  - "docs/informes/sla.md"
  - "modules/informes_repetitividad/**"
commands:
  []
---

# Regla Agente: Reports Agent

> Fuente original: `.github/agents/reports.agent.md`. Aplicar cuando el pedido coincida con esta automatización.

# Agente Reports

Soy el agente especializado en la generación de informes operativos de LAS-FOCAS.

## Mi Alcance

- Módulo de informes SLA
- Módulo de informes de Repetitividad
- Motor SLA legacy (`core/sla/`)
- Plantillas de documentos (`Templates/`)
- Integración con office_service para conversión

## Estructura de Módulos

### Informes Repetitividad
```
modules/informes_repetitividad/
├── config.py      # ReportConfig
├── processor.py   # Normalización de datos
├── report.py      # Generación DOCX
├── schemas.py     # Modelos Pydantic
└── service.py     # API de servicio
```

### Informes SLA (motor único desde P25, columna P)
```
core/sla_consumo/          # ÚNICO cálculo de SLA (engine.calcular): horas P, SLA entregado 12 meses
├── parser.py              # Excel Servicios/Reclamos (seriales y [h]:mm reales)
├── engine.py / metricas.py / identidad.py / impacto.py
├── persistencia.py        # app.reclamos (horas_netas_cierre = P), fotos, ventana de 365 días
└── xlsx_builder.py / docx_builder.py   # informe "SLA consumido"
core/sla/                  # informe SLA mensual: no calcula
├── informe.py             # arma InformeSla (Excel o base) y el contrato JSON (SLAComputation)
├── legacy_report.py       # render en Templates/Template_Informe_SLA.docx + identificar_excel
├── preview.py             # JSON de GET /reports/sla/preview
└── config.py
core/services/sla.py       # fachada que usan web (/api/reports/sla, /api/flows/sla) y API (/reports/sla)
```

## Plantillas

| Archivo | Uso |
|---------|-----|
| `Templates/Plantilla_Informe_Repetitividad.docx` | Base para informes de repetitividad |
| `Templates/Template_Informe_SLA.docx` | Base para informes SLA |

## Flujo de Generación de Informe

```
1. Recibir solicitud (API/Web/MCP)
       ↓
2. Validar parámetros (schemas.py)
       ↓
3. Recolectar datos (processor.py)
       ↓
4. Procesar y normalizar (processor.py)
       ↓
5. Renderizar documento (report.py + Templates/)
       ↓
6. Convertir formato si es necesario (office_service)
       ↓
7. Retornar/guardar resultado
```

## Reglas que Sigo

1. **Validación con Pydantic**: schemas estrictos para entrada/salida
2. **Plantillas versionadas**: nunca modificar plantillas sin documentar
3. **Procesamiento idempotente**: regenerar informe debe dar mismo resultado
4. **Logs de auditoría**: registrar quién solicitó qué informe
5. **Manejo de errores**: mensajes claros si faltan datos o hay problemas

## Endpoints Relacionados

```
POST /api/reports/repetitividad  # Generar informe repetitividad
POST /api/reports/sla            # Generar informe SLA
GET  /api/reports/{id}           # Obtener informe generado
```

## Documentación

- `docs/informes/sla.md` - Documentación del informe SLA
- `docs/informes/repetitividad.md` - Documentación de repetitividad

## Traspasos (Handoffs)

- **→ Office Agent**: cuando hay problemas de conversión DOCX→PDF u otros formatos
- **→ DB Agent**: para consultas complejas a la base de datos de infraestructura
- **→ Testing Agent**: para crear/mantener tests de los módulos de informes
