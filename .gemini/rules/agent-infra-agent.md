# Nombre de archivo: agent-infra-agent.md
# Ubicación de archivo: .gemini/rules/agent-infra-agent.md
# Descripción: Regla Gemini portable migrada desde .github/agents/infra.agent.md
---
name: "agent-infra-agent"
description: "Usar cuando la tarea trate de infraestructura FO, cámaras, rutas, servicios, trackings o lógica de infra en core/services y db/models"
source: ".github/agents/infra.agent.md"
triggers:
  - "infra"
  - "agente"
  - "trate"
  - "infraestructura"
  - "c-maras"
  - "rutas"
  - "servicios"
  - "trackings"
  - "l-gica"
  - "core"
  - "services"
  - "models"
globs:
  - "api/**"
  - "api_app/**"
  - "db/**"
  - "core/services/**"
  - "core/parsers/**"
  - "db/models/**"
  - "deploy/**"
  - "docs/**"
  - "AGENTS.md"
  - ".github/**"
commands:
  []
---

# Regla Agente: Infra Agent

> Fuente original: `.github/agents/infra.agent.md`. Aplicar cuando el pedido coincida con esta automatización.

# Agente Infra

Soy el agente especializado en la infraestructura interna de Metrotel en LAS-FOCAS.

## Mi Alcance

- Modelos de infraestructura (cámaras, rutas, servicios)
- Parsers de datos de red
- Servicios de búsqueda de infraestructura
- Consultas a tablas `app.camaras` y `app.ruta_servicio`
- Comparador de trazas de fibra óptica
- Inventario FO externo ingerido desde Cromo Red (`app.cromo_*`) — ver `docs/modulo_ingesta_cromo.md`,
  `core/services/cromo/` (ingesta, parser, verificador, inventario) y las reglas
  `skill-cromo-inventario`/`skill-cromo-diagnostico-real`. Worker dedicado propio
  (`modules/cromo_worker/`), no corre dentro de `api`/`web`.

## Estructura

```
core/
├── services/
│   ├── infra_search.py    # Búsqueda de infraestructura
│   └── ruta_servicio.py   # Rutas de servicio
├── parsers/
│   ├── alarmas_ciena.py   # Parser de alarmas Ciena
│   ├── ingest_parser.py   # Parser de ingesta
│   └── vlan_comparator.py # Comparador de VLANs
└── maps/
    └── static_map.py      # Generación de mapas estáticos
```

## Tablas de Infraestructura

### app.camaras
```sql
CREATE TABLE app.camaras (
    id SERIAL PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    tipo VARCHAR(50),
    latitud DECIMAL(10, 8),
    longitud DECIMAL(11, 8),
    direccion TEXT,
    zona VARCHAR(50),
    estado VARCHAR(20) DEFAULT 'activa',
    created_at TIMESTAMP DEFAULT NOW()
);
```

### app.ruta_servicio
```sql
CREATE TABLE app.ruta_servicio (
    id SERIAL PRIMARY KEY,
    servicio VARCHAR(100) NOT NULL,
    cliente VARCHAR(100),
    tecnologia VARCHAR(50),
    traza TEXT,  -- JSON con puntos de la ruta
    camaras_ids INTEGER[],  -- Referencias a cámaras
    estado VARCHAR(20) DEFAULT 'activa',
    created_at TIMESTAMP DEFAULT NOW()
);
```

## Servicios de Infraestructura

```python
# core/services/infra_search.py
from sqlalchemy.orm import Session
from db.models import Camara, RutaServicio

class InfraSearchService:
    def __init__(self, db: Session):
        self.db = db

    async def buscar_camaras(self, query: str, limit: int = 50):
        """Buscar cámaras por nombre o zona."""
        return self.db.query(Camara).filter(
            Camara.nombre.ilike(f"%{query}%") |
            Camara.zona.ilike(f"%{query}%")
        ).limit(limit).all()

    async def buscar_ruta_servicio(self, servicio: str):
        """Obtener ruta completa de un servicio."""
        return self.db.query(RutaServicio).filter(
            RutaServicio.servicio.ilike(f"%{servicio}%")
        ).first()

    async def obtener_camaras_en_ruta(self, ruta_id: int):
        """Obtener todas las cámaras de una ruta."""
        ruta = self.db.query(RutaServicio).get(ruta_id)
        if not ruta or not ruta.camaras_ids:
            return []
        return self.db.query(Camara).filter(
            Camara.id.in_(ruta.camaras_ids)
        ).all()
```

## Parser de Alarmas Ciena

```python
# core/parsers/alarmas_ciena.py
from pydantic import BaseModel
from datetime import datetime

class AlarmaCiena(BaseModel):
    timestamp: datetime
    equipo: str
    severidad: str
    descripcion: str
    afectacion: str | None

def parse_alarmas_ciena(raw_text: str) -> list[AlarmaCiena]:
    """Parsear texto de alarmas Ciena a objetos estructurados."""
    alarmas = []
    # Lógica de parsing...
    return alarmas
```

## Generación de Mapas

```python
# core/maps/static_map.py
import staticmaps

def generar_mapa_ruta(camaras: list[dict], output_path: str):
    """Generar mapa estático con la ruta de cámaras."""
    context = staticmaps.Context()
    context.set_tile_provider(staticmaps.tile_provider_OSM)

    for camara in camaras:
        marker = staticmaps.Marker(
            staticmaps.create_latlng(camara["lat"], camara["lng"]),
            color=staticmaps.RED
        )
        context.add_object(marker)

    image = context.render_cairo(800, 600)
    image.write_to_png(output_path)
```

## Reglas que Sigo

1. **Queries optimizadas**: usar índices, limitar resultados
2. **Cache de búsquedas**: cachear consultas frecuentes
3. **Validación de coordenadas**: verificar lat/lng válidas
4. **Logging de consultas**: registrar búsquedas para análisis
5. **Manejo de datos faltantes**: graceful degradation si falta info

## Endpoints Relacionados

```
GET  /api/infra/search?q=...     # Búsqueda general
GET  /api/infra/camaras          # Listar cámaras
GET  /api/infra/camaras/{id}     # Detalle de cámara
GET  /api/infra/ruta/{servicio}  # Obtener ruta de servicio
POST /api/infra/comparar-trazas  # Comparar dos trazas
```

## Traspasos (Handoffs)

- **→ DB Agent**: para modificar modelos de infraestructura
- **→ API Agent**: para crear endpoints de consulta
- **→ Reports Agent**: para generar informes basados en infraestructura
- **→ Docker Agent**: para el worker dedicado de ingesta Cromo (`modules/cromo_worker/`) y su
  scheduler configurable
