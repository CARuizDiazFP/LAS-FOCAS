---
name: "las-focas-cromo-inventario"
description: "Usar para consultar, explotar o construir features sobre los datos de infraestructura FO ya ingeridos desde Cromo Red (app.cromo_*) — no para tocar la ingesta en sí"
metadata:
  short-description: "Usar para consultar, explotar o construir features sobre los datos de infraestructura FO ya ingeridos desde Cromo..."
  source: ".github/skills/cromo-inventario/SKILL.md"
  triggers:
    - "cromo-inventario"
    - "cromo"
    - "las-focas"
    - "consultar"
    - "explotar"
    - "construir"
    - "features"
    - "infraestructura"
    - "ingeridos"
    - "inventario"
    - "app"
  globs:
    - "core/services/cromo/**"
    - "db/models/cromo.py"
    - "docs/modulo_ingesta_cromo.md"
  commands:
    []
---

# Nombre de archivo: SKILL.md
# Ubicación de archivo: .codex-skills/skills/las-focas-cromo-inventario/SKILL.md
# Descripción: Skill portable Codex migrada desde .github/skills/cromo-inventario/SKILL.md

# Skill portable: cromo-inventario

> Fuente original: `.github/skills/cromo-inventario/SKILL.md`. Copia portable generada porque `.codex/` está montado como solo lectura en esta sesión.

# Skill: Inventario Cromo Red (datos ya ingeridos)

Esta skill es para trabajar **sobre datos ya ingeridos** por el módulo de ingesta Cromo (búsquedas,
reportes, nuevas vistas de inventario). Para tocar la ingesta misma (fases, parser, worker) o para
validar un supuesto contra el sistema real, ver `cromo-diagnostico-real` y
`docs/modulo_ingesta_cromo.md`.

## Mapa del esquema (`app.cromo_*`)

```
cromo_cables          — clase 51, jerarquía de red (Acceso/Troncal/Subtroncal/Distribución/...)
  └─ cromo_tubos       — clase 129, agrupan pelos dentro de un cable
      └─ cromo_pelos   — clase 130, unidad mínima; tipo_asociacion clasifica su uso
          └─ cromo_servicio_match — matching pelo↔número de servicio (hoy sólo REGEX_EXACTO)
cromo_botellas         — clases 68/121/122/123/125, empalmes/derivaciones; geo real
cromo_fusiones         — clase 132, fetch propio (NO viene embebido en botella.inner[] a escala real)
cromo_ingesta_corridas — historial de corridas (estado, params, eventos SSE)
cromo_ingesta_config   — fila única, config del scheduler automático (Etapa 7)
```

Relación jerárquica real: cable → tubo → pelo → (match a servicio). Botellas y fusiones son nodos de
empalme, relacionados por referencia (`n_id`) más que por FK estricta — el verificador (`verificador.py`)
es **tolerante a referencias colgadas**: un `n_id` referenciado sin fila propia no es un error, es
un estado válido observado en datos reales.

### Columnas que importa conocer antes de construir algo nuevo

- `payload_raw` / `pts_raw` (JSONB) en cada tabla: la respuesta cruda de Cromo, **siempre** guardada
  completa, incluso si el parseo de columnas estructuradas falla o queda incompleto — es la fuente
  para cualquier backfill futuro sin tener que re-consultar Cromo.
- `latitud`/`longitud` (botellas, y extremos de cable): resultado de reproyectar `pts` (Gauss-Krüger
  Faja 5, `EPSG:22185`) con `pyproj` — **no** vienen directo de Cromo como lat/lon.
- `tipo_asociacion` en `cromo_pelos`: `CLIENTE` (matcheado a un servicio), `LIBRE` (sin asignar),
  `INDETERMINADO` (mayoría del dataset — la inferencia de `TRUNK_DWDM`/`OLT_LASER`/`INFRA` desde
  `at.61` todavía no está implementada, requiere mirar una muestra real primero).
  `jerarquia` en `cromo_cables`: texto libre real con ~10 valores — usar `ILIKE`, nunca igualdad
  exacta, para cualquier filtro que reciba input de usuario.
- `cromo_cables.extremo_a_nombre`/`extremo_b_nombre` (crudos, de `at.34`/`at.37`): **no confiables para
  el extremo B**. Cromo nunca manda `at.37` (0/32.782 cables) — ambos nombres viajan concatenados en el
  único atributo `at.34`. Resolver siempre vía `LEFT JOIN app.cromo_botellas` por `extremo_a_n_id`/
  `extremo_b_n_id` (con `COALESCE` a la columna cruda como único fallback, para referencia colgada) —
  ver `inventario.py`/`verificador.py`/`detalle.py` como plantilla ya aplicada.

## Patrón para nuevas consultas/endpoints de sólo lectura

Seguir `core/services/cromo/inventario.py` (búsqueda paginada), `core/services/cromo/verificador.py`
(resolución puntual) o `core/services/cromo/detalle.py` (detalle jerárquico de un objeto con hijos, ver
abajo) como plantilla, no reinventar el estilo:

- SQL crudo con `sqlalchemy.text()`, no el ORM — mismo estilo ya establecido en todo `core/services/cromo/`
  para joins de varias tablas.
- **Filtros opcionales que pueden venir todos `NULL` a la vez**: castear explícito,
  `CAST(:param AS text)` / `CAST(:param AS boolean)`. Sin esto, `asyncpg` tira
  `AmbiguousParameterError` al no poder inferir el tipo del bind parameter cuando el caso "sin
  ningún filtro puesto" ocurre — el bug más común de este esquema, y el único que ningún test
  unitario con sesión fake puede detectar (hace falta el driver real).
- Filtros de texto libre (`jerarquia`, `propietario`, nombres): `ILIKE` con `%...%`, no exacto.
- **Filtro que agrega un `WHERE` sobre un listado grande (30.000+ cables) vía join a otra tabla**:
  usar `columna IN (subquery NO correlacionada)`, nunca `EXISTS (subquery correlacionada a la fila
  externa, ej. `WHERE p.cable_n_id = c.n_id`)`. El `WHERE` de un listado paginado se evalúa dos veces
  por request (COUNT + SELECT) sobre las filas candidatas *antes* de `LIMIT/OFFSET` — un `EXISTS`
  correlacionado obliga a Postgres a re-ejecutar el join una vez por fila candidata; un `IN` no
  correlacionado permite resolverlo como "hashed subplan" (el join corre una sola vez por statement).
  Ejemplo real en el repo: filtro `servicio` de `inventario.py::_FILTROS_SQL` (Etapa 9). No es el
  mismo caso que un subselect correlacionado sobre las filas *ya paginadas* (ej. `cantidad_servicios`
  en el `SELECT` de `inventario.py`) — ese sí es correcto tal cual está, corre sobre ≤200 filas.
- Conteo de servicios por cable/tubo/pelo: reusar el join ya existente en
  `verificador.servicios_por_cable` (`cromo_pelos` → `cromo_servicio_match`), no reimplementarlo.
- **Detalle jerárquico de un objeto con hijos (cable→tubos→pelos, o similar) sin N+1**: una query por
  nivel de la jerarquía (no una por hijo), agrupando en Python por la FK del nivel anterior. Plantilla
  real: `core/services/cromo/detalle.py::obtener_detalle_cable` — 3 queries fijas sin importar cuántos
  tubos/pelos tenga el cable. Extender el criterio de "referencia colgada tolerante" (`verificador.py`)
  a cada nivel nuevo: un hijo referenciado sin fila propia en su tabla no es "no encontrado", aparece
  igual con su metadata en `None`.
- Endpoints de sólo consulta van con `_require_auth` (no `_require_admin`) en `web/app/main.py` —
  ver la convención ya usada en `/api/infra/cromo/cables`, `/api/infra/cromo/cables/{n_id}/detalle` y
  `/api/infra/cromo/verificar`.

## Antes de confiar en un dato o construir una vista nueva

1. Verificar contra `lasfocasdev-postgres` real (ver la skill `las-focas-db-mcp-postgres` sección
   "Inventario Cromo Red") que el volumen/distribución de datos es el esperado — no asumir a partir
   de la documentación de columnas.
2. Si el dato depende de una columna derivada (geo, `tipo_asociacion`, capacidad), confirmar que ya
   pasó por el fix/backfill correspondiente (ver `docs/Doc Privada/ingesta_cromo.md` §13.6) — filas
   ingeridas antes de un fix de parser **no se actualizan retroactivamente** (`_upsert_versionado`
   no reescribe columnas en el camino `SIN_CAMBIOS`).
3. Para features geográficos (mapas, polilíneas de cable), el backfill de `pts_raw`→lat/lon hoy sólo
   corrió sobre `cromo_botellas` — `cromo_cables` todavía no tiene el suyo (fuera de alcance de la
   Etapa 8, pendiente).

## Documentación relacionada

- `docs/modulo_ingesta_cromo.md` — contexto estructural público, dónde vive cada pieza de código.
- `docs/Doc Privada/ingesta_cromo.md` (gitignored) — modelo de datos completo, diccionario de
  atributos Cromo, notas de implementación por etapa.
- `.github/skills/cromo-diagnostico-real/SKILL.md` — metodología para validar contra el sistema real
  antes de escribir código nuevo de ingesta/parseo.
