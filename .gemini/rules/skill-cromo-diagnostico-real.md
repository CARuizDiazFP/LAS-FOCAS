# Nombre de archivo: skill-cromo-diagnostico-real.md
# Ubicación de archivo: .gemini/rules/skill-cromo-diagnostico-real.md
# Descripción: Regla Gemini portable migrada desde .github/skills/cromo-diagnostico-real/SKILL.md
---
name: "skill-cromo-diagnostico-real"
description: "Usar antes de escribir o confiar en código de parseo/ingesta de Cromo Red: valida contra la API o la DB real en vez de asumir que el diseño documentado describe el comportamiento actual"
source: ".agentes-comunes/skills/cromo-diagnostico-real/SKILL.md"
triggers:
  - "cromo-diagnostico-real"
  - "cromo"
  - "las-focas"
  - "diagnostico"
  - "parseo"
  - "ingesta"
  - "api"
  - "validar"
  - "diseno"
  - "documentado"
globs:
  - "core/services/cromo/**"
  - "scripts/cromo_sonda.py"
  - "scripts/cromo_backfill_geo.py"
commands:
  []
---

# Regla Skill: cromo-diagnostico-real

> Fuente original: `.github/skills/cromo-diagnostico-real/SKILL.md`. Usar esta regla cuando Gemini/Codex IDE detecte los triggers o globs declarados.

# Skill: Diagnóstico real contra Cromo Red

## Por qué existe esta skill

Durante las 8 etapas del módulo de ingesta Cromo (2026-08-05/07), **cada asunción tomada del diseño
privado (`docs/Doc Privada/ingesta_cromo.md`) sin validarla contra el sistema real resultó
incorrecta al menos una vez**, y sólo se detectó al correr contra el Cromo real o contra
`lasfocasdev-postgres` con datos reales — nunca con tests unitarios (que usan fakes/mocks, no pueden
detectar un desajuste con la realidad de un sistema externo). Casos reales:

| Asunción documentada | Realidad encontrada | Cómo se detectó |
|---|---|---|
| Autenticación Basic Auth | OAuth2 `grant_type=password` vía api-gateway | Prueba directa contra el manual + Cromo real |
| Respuesta JSON válida | Pseudo-JSON (claves sin comillas) | Error de parseo al primer fetch real |
| Fusiones embebidas en `botella.inner[]` | 0/11.100 botellas con clave `inner`; fusiones son colección propia (`filter=132`) | `SELECT count(*) FROM app.cromo_fusiones` = 0 pese a corrida completa |
| Geo en clave `"ll"` (lat/lon directo) | 0/11.100 con `"ll"`; geo real en `"pts"` (Gauss-Krüger Faja 5, sin reproyectar) | `payload_raw ? 'll'` = 0; inspección directa de `pts_raw` |
| `jerarquia` con 3 valores (Acceso/Troncal/Subtroncal) | 10 valores reales distintos | `SELECT DISTINCT jerarquia FROM app.cromo_cables` |
| Pelo matcheado a servicio → `tipo_asociacion="LIBRE"` | Semánticamente invertido: matcheado debería ser `"CLIENTE"` | Conteo exacto: 43.737 LIBRE = 43.737 filas en `cromo_servicio_match` |

**Regla general**: el diseño documentado es la mejor hipótesis disponible al momento de escribirlo,
no una garantía. Antes de escribir una fase de ingesta, un parser, o un fix basado en "el documento
dice que...", corré un diagnóstico acotado y de sólo lectura.

## Cómo diagnosticar

### 1. Reusar o extender `scripts/cromo_sonda.py`

Ya existe un script de sondeo de sólo lectura (`scripts/cromo_sonda.py`) que valida supuestos
puntuales contra la API real y escribe un reporte Markdown en `devs/output/cromo_sonda_<timestamp>.md`.
Patrón a seguir para agregar una sección nueva:

```python
async def _sondear_mi_supuesto(cliente: CromoClient) -> SeccionSonda:
    seccion = SeccionSonda("N. Descripción corta del supuesto a validar")
    respuesta = await cliente.get_coleccion("<clase>", psize=5, show=["SHOW", "TIME"])
    datos = respuesta.get("data") or respuesta.get("response") or []
    # ... inspeccionar datos, agregar líneas con seccion.agregar(...)
    return seccion
```

Registrarla en `ejecutar_sonda()` (lista de `(titulo, corutina, args)`), correr con:

```bash
source .venv/bin/activate
python -m scripts.cromo_sonda
```

Para un chequeo de una sola vez que no amerita quedar en el script permanente (más rápido), un
fetch directo acotado sirve igual — mismo patrón que se usó para confirmar que `filter=132` es
fetcheable como colección propia:

```python
import asyncio
from core.services.cromo.client import CromoClient
from core.services.cromo.config import get_cromo_config

async def main():
    async with CromoClient(config=get_cromo_config()) as cliente:
        resp = await cliente.get_coleccion("132", psize=5, show=["SHOW", "TIME"])
        print(resp)

asyncio.run(main())
```

### 2. Contra datos ya ingeridos: consultar `lasfocasdev-postgres` directo

Si la pregunta es sobre datos **ya guardados** (no sobre el comportamiento de la API), es más rápido
consultar la DB real de dev directo — ver la regla `skill-db-mcp-postgres` sección "Inventario
Cromo Red". Ejemplo real usado para descartar el bug de `tipo_asociacion`:

```sql
SELECT tipo_asociacion, count(*) FROM app.cromo_pelos GROUP BY 1;
SELECT count(*) FROM app.cromo_servicio_match;  -- comparar contra el count de "LIBRE" de arriba
```

### 3. Confirmar sistemas de coordenadas con direcciones reales conocidas, no de memoria

Para el caso de reproyección geográfica (Gauss-Krüger → lat/lon), no asumir el EPSG por la magnitud
de los números — probar 2-3 candidatos (`EPSG:22195`, `EPSG:22185`, `EPSG:5347` para Argentina Faja 5)
contra 2-3 direcciones reales conocidas del dataset y quedarse con el que caiga en el punto correcto:

```python
from pyproj import Transformer
for epsg in ("EPSG:22195", "EPSG:22185", "EPSG:5347"):
    t = Transformer.from_crs(epsg, "EPSG:4326", always_xy=True)
    print(epsg, t.transform(5646459.588986, 6171230.830909))  # comparar contra Google Maps
```

## Reglas

1. **Sólo lectura, siempre** — nunca escribir/modificar objetos en Cromo. Confirmar con `CromoConfigError`
   temprano si faltan credenciales antes de intentar nada.
2. **No declarar una fase de ingesta "correcta" sin al menos un diagnóstico contra la API real** —
   los fakes de `tests/` prueban que el código hace lo que el código dice que hace, no que el código
   dice lo correcto.
3. **Si el diagnóstico contradice el diseño privado**, actualizar `docs/Doc Privada/ingesta_cromo.md`
   con el hallazgo (sección "Notas de implementación") antes de cerrar la tarea — el documento debe
   reflejar la realidad verificada, no quedar desactualizado silenciosamente.
4. **Preferir un fetch acotado (`psize` chico, una clase) antes que un barrido completo** para
   diagnosticar — no hace falta correr una ingesta real para confirmar la forma de un payload.

## Documentación relacionada

- `docs/Doc Privada/ingesta_cromo.md` §12 (Puntos abiertos) y §13 (Notas de implementación por etapa)
  — historial completo de hallazgos reales de esta naturaleza.
- `.github/skills/cromo-inventario/SKILL.md` — para trabajar sobre los datos ya ingeridos.
- `scripts/cromo_sonda.py`, `scripts/cromo_backfill_geo.py` — scripts reales de esta familia.
