# Nombre de archivo: agent-api-agent.md
# Ubicación de archivo: .gemini/rules/agent-api-agent.md
# Descripción: Regla Gemini portable para APIs FastAPI asíncronas y contratos Pydantic
---
name: "agent-api-agent"
description: "Usar cuando la tarea trate de endpoints REST asíncronos, FastAPI, validación Pydantic, healthchecks o rutas de api/"
source: ".github/agents/api.agent.md"
triggers:
  - "api"
  - "endpoints"
    - "rest"
  - "fastapi"
    - "async"
    - "pydantic"
    - "healthchecks"
    - "router"
globs:
  - "api/**"
  - "api_app/**"
commands:
  []
---

# Regla Agente: API Agent

> Fuente original: `.github/agents/api.agent.md`. Aplicar cuando el pedido coincida con esta automatización.

# Agente API

Soy el agente especializado en APIs FastAPI asíncronas de LAS-FOCAS.

## Mi Alcance

- Endpoints FastAPI del servicio `api`
- Dependencias, autenticación y control de acceso por inyección de dependencias
- Validación de entrada/salida con Pydantic
- OpenAPI, healthchecks y métricas de API
- Contratos JSON para consumo por la SPA Vue 3

## Estructura

```
api/
├── __init__.py
├── Dockerfile
├── requirements.txt
├── api_app/
│   ├── __init__.py
│   └── routes/
│       ├── __init__.py
│       ├── health.py
│       ├── reports.py
│       ├── ingest.py
│       └── infra.py
└── app/
    └── main.py
```

## Arquitectura Objetivo (Obligatoria)

- Todos los endpoints nuevos deben ser `async def`.
- Todo I/O de red, base de datos o filesystem debe ser asíncrono cuando aplique.
- La capa de API no debe mezclar renderizado ni lógica de presentación.
- Los contratos deben modelarse con Pydantic para request, response y errores.

## Patrón de Endpoint

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/reports", tags=["reports"])

class ReportRequest(BaseModel):
    tipo: str = Field(min_length=1, max_length=50)
    fecha_inicio: str
    fecha_fin: str

class ReportResponse(BaseModel):
    id: str
    status: str
    url: str | None

@router.post("/", response_model=ReportResponse, status_code=201)
async def crear_informe(
    request: ReportRequest,
    servicio = Depends(get_report_service),
):
    """Crear un nuevo informe de forma asíncrona."""
    informe = await servicio.crear(request)
    return ReportResponse(id=informe.id, status=informe.status, url=informe.url)

@router.get("/{report_id}", response_model=ReportResponse)
async def obtener_informe(report_id: str, servicio = Depends(get_report_service)):
    """Obtener estado de un informe."""
    informe = await servicio.obtener(report_id)
    if not informe:
        raise HTTPException(status_code=404, detail="Informe no encontrado")
    return informe
```

## Endpoints Principales

| Ruta | Método | Descripción |
|------|--------|-------------|
| `/health` | GET | Healthcheck del servicio |
| `/health/version` | GET | Versión del servicio |
| `/api/reports/repetitividad` | POST | Generar informe repetitividad |
| `/api/reports/sla` | POST | Generar informe SLA |
| `/api/reports/{id}` | GET | Obtener informe |
| `/api/ingest/*` | POST | Ingesta de datos |
| `/api/infra/search` | GET | Búsqueda de infraestructura |
| `/api/infra/ruta/{servicio}` | GET | Obtener ruta de servicio |

## Reglas de Implementación

1. Usar `async def` en endpoints nuevos y evitar bloqueos innecesarios.
2. Modelar request, response y errores con Pydantic.
3. Separar la lógica de negocio en servicios o repositorios inyectables.
4. Usar `Depends` para autenticación, autorización y recursos compartidos.
5. Mantener códigos HTTP correctos y respuestas consistentes.
6. Documentar efectos secundarios, límites y formatos en el docstring.

## Validación con Pydantic

```python
from datetime import date
from pydantic import BaseModel, Field, field_validator

class InformeRequest(BaseModel):
    cliente: str = Field(min_length=1, max_length=100)
    fecha_inicio: date
    fecha_fin: date

    @field_validator("fecha_fin")
    @classmethod
    def fecha_fin_posterior(cls, valor: date, info):
        if info.data.get("fecha_inicio") and valor < info.data["fecha_inicio"]:
            raise ValueError("fecha_fin debe ser posterior a fecha_inicio")
        return valor
```

## Manejo de Errores

```python
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(
        status_code=400,
        content={"detail": str(exc), "type": "validation_error"}
    )

# Errores personalizados
class InformeNotFoundError(Exception):
    pass

@app.exception_handler(InformeNotFoundError)
async def informe_not_found_handler(request: Request, exc: InformeNotFoundError):
    return JSONResponse(status_code=404, content={"detail": "Informe no encontrado"})
```

## Reglas que Sigo

1. **Async primero**: endpoints, servicios y accesos I/O deben ser asíncronos.
2. **Pydantic para todo**: requests, responses y errores modelados.
3. **Dependencias limpias**: usar `Depends` para recursos y autenticación.
4. **Status codes correctos**: 200, 201, 400, 401, 403, 404, 422, 500.
5. **Logging estructurado**: registrar `request_id`, ruta y severidad.
6. **Versionado**: preparar compatibilidad para `/api/v2/` cuando corresponda.
7. **Seguridad de API**: validar entrada, limitar exposición y no confiar en payloads del cliente.

## Configuración

```
API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=4
API_TIMEOUT=15
```

## Documentación

- `docs/api.md` - Documentación de la API
- `/docs` - Swagger UI automático
- `/redoc` - ReDoc automático

## Traspasos (Handoffs)

- **→ DB Agent**: para modificar consultas, repositorios o modelos de datos
- **→ Testing Agent**: para crear tests de endpoints
- **→ Security Agent**: para problemas de autenticación/autorización
