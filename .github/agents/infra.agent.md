# Nombre de archivo: infra.agent.md
# Ubicación de archivo: .github/agents/infra.agent.md
# Descripción: Agente especializado en infraestructura interna de Metrotel

---
name: Infra Agent
description: "Usar cuando la tarea trate de infraestructura FO, cámaras, rutas, servicios, trackings o lógica de infra en core/services y db/models"
argument-hint: "Describe flujo o entidad de infraestructura, por ejemplo: corregir búsqueda de cámaras por servicio"
tools: [read, edit, search, execute]
---

# Agente Infra

Soy el agente especializado en la infraestructura interna de Metrotel en LAS-FOCAS.

## Mi Alcance

- Modelos de infraestructura (cámaras, rutas, servicios)
- Parsers de datos de red
- Servicios de búsqueda de infraestructura
- Consultas a tablas `app.camaras` y `app.ruta_servicio`
- Comparador de trazas de fibra óptica
- Inventario FO externo ingerido desde Cromo Red (`app.cromo_*`) — ver `docs/modulo_ingesta_cromo.md`,
  `core/services/cromo/` (ingesta, parser, verificador, inventario) y las skills
  `cromo-inventario`/`cromo-diagnostico-real`. Worker dedicado propio (`modules/cromo_worker/`), no
  corre dentro de `api`/`web`.

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

> **Nota de vigencia (2026-08-10)**: los bloques `app.camaras`/`app.rutas_servicio` de abajo fueron
> corregidos contra el modelo real (`db/models/infra.py`) durante el cierre de la sesión que construyó
> la jerarquía Cámara→Botellas y el Protocolo de Protección — ver sección dedicada más abajo. El resto
> del archivo (`InfraSearchService`, `core/parsers/alarmas_ciena.py`, `core/maps/static_map.py`) **no
> se verificó** en esa sesión — puede seguir sin corresponder a la estructura real del repo. Antes de
> confiar en esos bloques, confirmar contra el código real (mismo criterio que la skill
> `cromo-diagnostico-real`: no declarar un doc de agente "vigente" sin diagnóstico contra el sistema
> real).

### app.camaras (real, `db/models/infra.py::Camara`)

Columnas reales: `id` (PK), `fontine_id` (String, unique, opcional), `nombre` (String, requerido),
`direccion`, `latitud`/`longitud` (Float), `estado` (Enum `camara_estado`: `LIBRE`/`OCUPADA`/`BANEADA`/
`DETECTADA`/`PENDIENTE_REVISION`), `origen_datos` (Enum `camara_origen_datos`: `MANUAL`/`TRACKING`/
`SHEET`/`INFERIDO`), `camara_padre_id` (FK auto-referencial nullable a `app.camaras.id`, jerarquía de
2 niveles — ver sección "Jerarquía Cámara→Botellas" abajo), `last_update`. Sin columnas `tipo`/`zona`.
Esquema completo en `docs/db.md`.

### app.rutas_servicio (real, `db/models/infra.py::RutaServicio` — no `app.ruta_servicio`)

Columnas reales: `id` (PK), `servicio_id` (FK a `app.servicios.id`), `nombre` (String, default
"Principal"), `tipo` (Enum `ruta_tipo`). Sin columnas `cliente`/`tecnologia`/`traza`/`camaras_ids[]` —
las cámaras de una ruta se resuelven vía `RutaServicio → Empalme → Camara` (tabla de asociación
`ruta_empalme_association`), no un array de IDs.

### Jerarquía Cámara→Botellas y Protocolo de Protección (Baneos) — 2026-08-10

Muchas filas de `app.camaras` no son cámaras físicas distintas — son "Botellas" (cajas de empalme)
dentro de la MISMA cámara física, diferenciadas por sufijo "Bot N" en `nombre` (ej. "Cra 14 de Julio
240 CF" / "Cra 14 de Julio 240 Bot 2 CF"). Modelado con `camara_padre_id` auto-referencial (2 niveles).

- `core/services/camara_hierarchy_service.py` — detección del sufijo "Bot N" (reusa
  `modules/slack_baneo_notifier/camara_search.py::RE_BOT_SUFIJO`), `resolver_o_crear_padre()` para
  altas en vivo (conectado a los 6 caminos reales de alta de `Camara`).
- `core/services/camara_estado_service.py::aplicar_estado_a_grupo()` — único punto que debe escribir
  `Camara.estado` directamente; cascada bidireccional completa (banear cualquier miembro del grupo
  banea a todos). `create_ban`/`lift_ban` (`core/services/protection_service.py`, el "Protocolo de
  Protección") y `override_camara_estado_manual` lo usan en vez de asignar `.estado` a mano.
- `core/services/botellas_unificadas_service.py` — listado unificado (submódulo "Botellas" del
  sidebar) que combina `app.camaras` (legado) con `app.cromo_botellas` (Cromo Red, esquema homónimo
  SIN relación real — ver `docs/infra.md` sección "Jerarquía Cámara → Botellas" y "Submódulo
  Botellas").
- Skill dedicada para probar cascadas de baneo/desbaneo contra datos reales sin causar drift no
  controlado: `.github/skills/baneo-qa-real/SKILL.md`.
- Doc completa: `docs/infra.md`.

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
