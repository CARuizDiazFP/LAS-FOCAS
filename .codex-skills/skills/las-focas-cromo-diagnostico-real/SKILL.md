---
name: "las-focas-cromo-diagnostico-real"
description: "Usar antes de escribir o confiar en código de parseo/ingesta de Cromo Red: valida contra la API o la DB real en vez de asumir que el diseño documentado describe el comportamiento actual"
metadata:
  short-description: "Usar antes de escribir o confiar en código de parseo/ingesta de Cromo Red: valida contra la API o la DB real..."
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
    - |
      source .venv/bin/activate
      python -m scripts.cromo_sonda
---

# Nombre de archivo: SKILL.md
# Ubicación de archivo: .codex-skills/skills/las-focas-cromo-diagnostico-real/SKILL.md
# Descripción: Skill portable Codex migrada desde .github/skills/cromo-diagnostico-real/SKILL.md

# Skill portable: cromo-diagnostico-real

> Fuente original: `.agentes-comunes/skills/cromo-diagnostico-real/SKILL.md`. Copia portable generada porque `.codex/` está montado como solo lectura en esta sesión.

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
consultar la DB real de dev directo — ver `.github/skills/db-mcp-postgres/SKILL.md` sección "Inventario
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
5. **El mismo objeto tiene forma distinta según el endpoint. Verificar SIEMPRE contra los dos**
   antes de escribir un parser. Asimetrías reales medidas (2026-09-17, clases 133/134):
   - El **barrido de colección** (`get_coleccion`, `show=ALL`) trae `parent` como **entero** en cada
     hijo de `inner[]`; `GET /db/objects/{id}/inner` **no trae `parent` en absoluto**. Un parser que
     dependa de `parent` deja el objeto huérfano según de dónde haya llegado — el vínculo lo tiene
     que aportar el recorrido del árbol, que siempre sabe de quién cuelga.
   - Un **fetch directo** (`get_objeto_con_topologia`) trae `parent` como **diccionario**
     (`{"id":…, "class":…}`), no como entero. Pasárselo crudo al parser produce basura silenciosa
     (un `tubo_n_id` que es un dict). Mismo hallazgo, 2026-09-17.
   - El atributo `at.62` (id de servicio) **sólo** viaja en `/inner`, nunca en el barrido — ya
     documentado para conectores de ODF (2026-08-28) y confirmado igual para puertos de splitter.
     Consecuencia: un campo vacío puede significar "no se preguntó" o "está libre", y el parser **no
     puede distinguirlo**. Que la procedencia la declare el llamador con un flag explícito; si no,
     los dos estados colapsan y la distinción queda sólo en la documentación.
6. **Antes de reemplazar una heurística por un dato real, medir cuánto se equivoca.** Receta usada
   dos veces con resultado accionable: tomar una **muestra al azar** de objetos reales
   (`ORDER BY random() LIMIT 30`), correr la heurística y el dato de Cromo sobre cada uno, y
   clasificar en coincide / falso positivo / falso negativo / valor distinto. Sin ese número la
   discusión es de opinión; con él se decide y queda en el commit. Ejemplo real: la heurística de
   fan-out de `empalmes.py` acertó en 18 de 30 y **nunca** devolvió el ratio correcto cuando el
   splitter existía (ver `docs/decisiones.md`, 2026-09-17).

7. **Un barrido truncado NO es un total, y `stats[].count` puede mentir con 0.** Real (2026-09-19):
   medí la clase 133 con un barrido acotado a 16 páginas y reporté "~800 splitters"; el total real,
   paginando hasta que el cursor se agota, es **20.238** (405 páginas) y el de la clase 134 es
   **154.284** (3.086). Un error de 25x que se coló en el plan y en la estimación de duración.
   La trampa de fondo: para esas dos clases `stats[].count` devuelve **0** aunque la colección
   pagine perfecto, así que no hay señal que avise que estás mirando una fracción.
   - Para dimensionar, paginar hasta el final con `show=["BASIC"]` (barato) y contar, o leer
     `cromo_clases.count_cromo`, que desde 2026-09-19 guarda esa medición con su fecha.
   - Un `count` de 0 sobre una colección que devuelve filas es la firma de este bug, no un dato:
     tratarlo como "no sé", nunca como "no hay".
   - Nunca escribir en el catálogo un número que salga de un barrido acotado.

8. **`parent` no es una referencia confiable: ni su forma ni su id.** Ampliación de la regla 5, con
   tres defectos reales medidos el 2026-09-19 sobre 60 objetos de cada clase, todos de *basura
   silenciosa* (nadie falla, la fila se escribe, el dato queda inservible):
   - **La forma cambia por endpoint.** En el barrido de la colección 133, `parent` es un
     **diccionario** en 60/60; en el `inner[]` de una botella es un **entero**. Pasarle el dict
     crudo al modelo deja un `{'class': 138, 'id': …}` dentro de una columna de id.
   - **Puede apuntar a otra cosa.** En el barrido de la clase 134, `parent` es el **contenedor PON**
     (138/137/139 en 60/60), no el splitter; el splitter viaja en `extra.parent` (clase 133 en
     60/60) y su `n_id` coincide con `at.71`.
   - **Su `id` es de versión, no de linaje.** En 4 de 60 objetos `container.id != container.n_id`, y
     ahí `parent.id` tampoco coincide — el mismo "ID dual" ya documentado para cables y botellas.
   Receta: preferir `extra.container.n_id` / `extra.parent.n_id` (presentes en 60/60), caer a
   `parent` sólo como respaldo, y **normalizar con un helper** que acepte int o dict y devuelva
   siempre un entero. Antes de escribir el parser, medir la distribución de `type(parent)` y de la
   clase del padre sobre ≥50 objetos reales del endpoint que se va a usar.

9. **Un "X no pertenece a Y" con ranking truncado se diagnostica replicando el ranking en SQL, no
   leyendo el validador.** Real (2026-09-21, Servicio 559 / ID histórico 41579): el ticket atribuía
   un `400 El pelo 6754728 no pertenece al Servicio 559` a un problema de mapeo entre el ID
   histórico de la URL y la PK interna. **La premisa era falsa y se refutó con una sola query**: el
   pelo matchea *precisamente* por el histórico (`prioridad_identidad = 1`), o sea que el mapeo que
   el ticket culpaba era lo que lo hacía pertenecer. La causa era que el validador consultaba una
   lista truncada en 20 y el pelo caía en el puesto 31 de 95.

   Receta, antes de tocar el validador — reproducir su `ORDER BY` con `row_number()` y ubicar la
   posición real del elemento rechazado:

   ```sql
   WITH base AS (  -- copiar el SELECT/JOIN del código, sin el LIMIT
     SELECT DISTINCT ON (m.pelo_n_id) m.pelo_n_id, m.confianza,
            EXISTS (SELECT 1 FROM app.cromo_odf_conectores c WHERE c.pelo_n_id = m.pelo_n_id) AS tiene_conector_odf,
            CASE WHEN m.servicio_numero = s.servicio_id            THEN 0
                 WHEN m.servicio_numero = s.numero_primer_servicio THEN 1
                 ELSE 2 END AS prioridad_identidad
     FROM app.servicios s
     JOIN app.cromo_servicio_match m ON (/* IDENTIDADES_DEL_SERVICIO_SQL */)
     JOIN app.cromo_pelos p ON p.n_id = m.pelo_n_id AND p.vigente = true
     WHERE s.id = :servicio_id
     ORDER BY m.pelo_n_id, prioridad_identidad, tiene_conector_odf, m.confianza DESC NULLS LAST
   )
   SELECT pelo_n_id, tiene_conector_odf, prioridad_identidad,
          row_number() OVER (ORDER BY prioridad_identidad, tiene_conector_odf,
                             COALESCE(confianza,0) DESC, pelo_n_id) AS pos
   FROM base WHERE pelo_n_id = :pelo_n_id;
   ```

   `pos > limite` confirma la causa en una pasada y descarta las hipótesis de mapeo/identidad. Si
   además `prioridad_identidad` es 1 o 2, el elemento pertenece **por un alias histórico**, lo que
   suele ser justo lo que el ticket señala como culpable. Cerrar midiendo también el total
   (`contar_semillas`) y un elemento de control inexistente, para probar que el guard sigue vivo.
   Ver `[[feedback-lista-truncada-no-es-fuente-de-verdad]]` y `docs/decisiones.md` (2026-09-21).

10. **Un cambio a la búsqueda de cámaras (`camara_search.py`, `camara_botella_busqueda.py`,
   `nodos_catalogo.py`) se acepta sólo con DOS arneses read-only contra `lasfocasdev-postgres`**, con
   el código de `dev` y el de la rama sobre la MISMA muestra:
   - **Auto-recuperación**: N nombres del inventario (`ORDER BY id` + seed fija) buscados tal cual;
     criterio "cámara incorrecta ≤ `dev`".
   - **Transiciones**: entradas derivadas del inventario con verdad conocida (todos los nombres con
     `-` o "CRITICA" + muestra al azar de Cámaras y Botellas, pasadas por `limpiar_ruido_operativo`
     como hace el listener), comparando la raíz resuelta contra la verdadera; criterio "**0 entradas
     que pasen a una cámara INCORRECTA**" (sin match/ambiguo → incorrecta, o correcta → incorrecta).
   El primero solo **no alcanza**. Real (2026-09-28): una versión que pasaba la auto-recuperación
   (1444 contra 1341, incorrectos 7 = 7) tenía 8 transiciones a cámara incorrecta —gemelas
   "CRITICA", el "2" de "Bot 2" satisfecho con "P2", recortes antes del guion que perdían la botella—,
   que sólo encontró una revisión adversarial con el segundo arnés. Resolver una cámara incorrecta es
   peor que no resolver: registra el ingreso donde no es y puede disparar avisos de baneo. Sumar los
   casos reales de `ingresos_sin_match` (dev y prod tienen el inventario casi idéntico: medir en dev).
   Método y cifras: `docs/relevamiento_ingresos_sin_match_2026-09-28.md`.

11. **`tp[]` es una lista y casi nunca tiene un solo elemento que importe: nunca `tp[0]` a ciegas.**
   Real (2026-09-29, `track 42351` daba 1 `.txt` con 2 hilos): una posición de patchera (clase 136)
   une **dos** pelos, uno de cada cable que llega a ella, y `parse_odf_conectores` guardaba el
   primero, que era de un cable de tercero no ingerido (F-CRZ-FB, clase 59). Medido en dev: 67
   conectores con dos pelos, en 53 el guardado no existía localmente. `tp[]` también mezcla clases
   (130 pelo, 136 conector↔conector, 141 fusión de ODF). Receta antes de leer un id de `tp[]`:
   - Medir la distribución real: `jsonb_array_elements(payload_raw->'tp')` agrupado por
     `e->>'class'` y por cantidad de elementos, sobre la tabla ya ingerida.
   - Filtrar por clase y, si quedan varios, elegir con un criterio de dominio explícito (hoy:
     `resolver_servicio_conectores` prefiere el pelo de un cable propio, 51), nunca por posición.
   - Si ningún id de `tp[]` existe localmente, preguntar a Cromo por el objeto
     (`get_objeto_con_topologia`) y mirar la **clase de su `parent`**: así apareció que el faltante
     eran cables de clases que la ingesta no barría.

12. **Cables de terceros (52 varios, 59 Telefónica, 60 Telecom): el `/path` los trae, el árbol de
   botella no.** El tracking `.txt` los incluye porque sale del `/path` en vivo, así que "el `.txt`
   está bien" no prueba que el inventario local los tenga. Sus pelos llegan sólo por
   `fase_cables_terceros` (desde 2026-09-29), porque van cámara↔ODF u ODF↔ODF y ningún árbol de
   botella los contiene. Ante un pelo del camino que no existe en `cromo_pelos`, sospechar primero de
   una clase de cable no barrida antes que de un bug de parseo.

13. **Para validar código todavía no integrado contra Cromo y la base real, superponerlo en `/tmp/wt`
   del contenedor web de dev, nunca en `/app`.** El host no tiene la config de Cromo y los
   contenedores corren la imagen de `dev`, no la del worktree. Se copia `core db modules` con
   `tar | docker exec -i lasfocasdev-web tar xf - -C /tmp/wt`, el script de prueba hace
   `sys.path.insert(0, "/tmp/wt")` y **verifica que importó el código nuevo**
   (`assert modulo.__file__.startswith("/tmp/wt")`). Si no lo verifica, puede validar la imagen
   vieja sin darse cuenta. Al terminar, `rm -rf /tmp/wt`. Es lo que mostró, antes de integrar, que el
   94673 daba 2 caminos y que 42351/93154 tenían 34/63 pelos huérfanos (2026-10-05).
   Dos trampas reales del 2026-10-22:
   - **Heredoc sin `-i`**: `docker exec -w /tmp/wt lasfocasdev-web python - <<'PY'` sin `-i` no
     ejecuta nada y sale con código 0 y salida vacía (una declaración "aplicada" no existía en la
     base). Con heredoc, siempre `docker exec -i`; si el script imprime algo, una salida vacía es un
     fallo, no un éxito.
     Lo mismo al **copiar un archivo suelto**: `docker exec lasfocasdev-web sh -c 'cat > /tmp/wt/x.py'
     < x.py` sin `-i` deja `x.py` **vacío** y sale con código 0. Real (2026-10-26): el bench importó un
     módulo vacío y falló recién con `AttributeError`. Después de copiar, verificar el contenido
     (`docker exec … grep -c <símbolo nuevo> <archivo>`).
   - **Un solo `asyncio.run` por script si se usa `db.session.AsyncSessionLocal`**: su pool queda
     atado al primer event loop y un segundo `asyncio.run` revienta en el checkout
     (`Exception terminating connection` / `different loop`). Hacer todo dentro de un único
     `main()` o sacar los datos previos con `psql`. Las funciones que ya abren su propio engine con
     `NullPool` (p. ej. `tracking_servicio.generar_trackings`) sí se pueden llamar en serie.

14. **Toda regla que decida qué camino es tramo (`tracking_service.clasificar_caminos`) se mide
   contra los servicios testigo antes de fijarla, no después.** Esperado hoy: 102452 → 6 tramos
   (3 segmentos, ODF Nodo KORN y Dixon), 42351/93154/94673 → 2 cada uno (pk de dev 1168, 567, 17 y
   1066). La regla escrita en el plan falló dos veces contra datos reales: "un extremo en ODF
   alcanza" daba 10/3/7/2 (2026-10-16), y "toca una ODF confirmada ⇒ tramo" llevó el 102452 de 6 a
   12 con las ODF que confirmó un usuario en pruebas (2026-10-18). Medir con el patrón de la regla 13
   (código del worktree en `/tmp/wt`, `trackings_del_servicio` sin auditar) e imprimir por camino:
   pelos, extremos (tipo, ODF, clase) y si tiene par. Mirar también si el servicio tiene ODF
   confirmadas (`app.servicio_odf_confirmada`): cambian el resultado.
   Desde 2026-10-22 también siembran las posiciones de ODF del servicio (roles VIGENTE/ADICIONAL,
   `servicio_posicion_vigente`), así que los testigos suman: **93150** (pk 4) sin declarar → 2 tramos
   (6799280/81) + 2 adicionales completos (6822050/51, pelos con etiqueta 44649) y `full` = 4; con
   O-1252871-1:1,2 declarada (`app.servicio_posicion_vigente`) → vigentes 7028862/63 y el camino
   nuevo como adicional. **42352** (pk 568) → sigue sin semilla (no toma los caminos del 42351).
   **102452** → sin adicionales (sus jumpers de 1 pelo entre racks del Nodo Dixon caen por el umbral
   del 25 %). Antes de fijar una regla sobre caminos de posición, imprimir también la etiqueta de los
   pelos del camino: el hilo 2 del 93150 tiene 4 de 49 pelos con etiqueta 61972 (otro servicio
   Activo), ruido que un filtro de "cualquier pelo ajeno" convertía en falso negativo.
   Desde 2026-10-23 se suma **83693** (pk 620): 2 tramos Córdoba 3016 ↔ Pilar, los dos completados
   con `projview=2` (regla 15); sin el reintento, cada uno termina en el pelo FL-CTB-330:2. En 93154,
   un residual (7670697) se completa con `projview=1` sin cambiar los 2 tramos.

15. **Un tracking que termina en un pelo suelto se diagnostica comparando `projview`, no leyendo
   el parser.** `/path` sin `projview` (= `0`, "red completa") **corta** el camino en un pelo con más
   de una continuación: con la fusión a desinstalar (`stp=31`) y la proyectada (`stp=1`) visibles a la
   vez, Cromo no elige. `projview=1` sigue la de desinstalación y `projview=2` la proyectada (= el
   toggle "Red proyectada" de la UI). Real (2026-10-23, `track 47838`): el extremo faltante era el de
   **Córdoba 3016**, no el de Pilar como decía el reporte. El de Pilar ya estaba al final del `.txt`, y
   Slack muestra sólo el principio. Receta, sólo lectura:
   - Pedir `/path` del pelo semilla con `None`, `1` y `2`, y comparar con `_construir_lado` el final
     de cada lado (las tres respuestas comparten el tramo inicial).
   - Mirar el `tp[]` del pelo terminal: si tiene destinos que no están en la secuencia, es un corte
     por proyecto (`detectar_cortes`). Si tiene un único `tp`, el camino termina ahí de verdad (4 de
     4 casos medidos) y ningún `projview` lo cambia.
   - No asumir que gana la red proyectada: en el 105553 la proyectada se fue por otra rama, más
     corta, y la que completaba era la actual. Por eso el tracking exige que el reintento
     **extienda** el camino (`extiende_camino`).
   - `stp` medido: 30 en servicio, 31 a desinstalar, 1 proyectado. Apareció también un `21` (camino
     del 105553) sin interpretar: no marcarlo hasta medirlo.
   Medición de referencia: `docs/decisiones.md` (2026-10-23), 30 Activos al azar + 83693.

16. **Un refactor de rendimiento sobre la ingesta o la resolución de Cámaras se acepta con un arnés viejo
   contra nuevo sobre el mismo input real, dentro de una transacción con `ROLLBACK`.** Real (P05,
   2026-10-26, `docs/PR/2026-10-26.md`): precarga por lote en `ingesta.py` y resolución de Cámara
   padre, donde los tests con fakes pasaban aunque la precarga viera todo como inexistente.
   - Montar `git show origin/dev:<archivo>` como módulo `*_viejo` junto al nuevo en `/tmp/wt` (regla 13),
     o dos árboles (`/tmp/wt2` = `git archive origin/dev`, `/tmp/wt3` = worktree), y correr ambos
     sobre el mismo input: payload de Cromo bajado **una vez** a un JSON, o nombres reales de la base.
   - Contar queries con `event.listen(engine, "before_cursor_execute", …)` (en async:
     `async_engine.sync_engine`). Al comparar, tener en cuenta que el autoflush por `sesion.get()`
     multiplica los `UPDATE`: menos `UPDATE` no significa otro resultado.
   - La huella del resultado se lee **de la base**, antes del rollback:
     `md5(string_agg((to_jsonb(t) - 'ultima_ingesta' - 'ultima_modificacion')::text, '|' order by n_id))`
     por tabla, filtrando `ultima_ingesta >= t0`, más la secuencia de eventos de la corrida. No sale
     del `identity_map`: es débil y los eventos ya flusheados desaparecen (huella vacía, falso OK).
   - Para detectar "creó una fila", no usar `obj in session.new`: si la función hace `flush()`
     adentro, el objeto ya es persistente y la creación pasa por reuso (falso DIF). Comparar
     `obj.id > max(id)` leído antes de empezar.
   - `CREATE EXTENSION` y `CREATE INDEX` son transaccionales en Postgres: un índice candidato
     (p. ej. GIN trigram) se mide con `EXPLAIN ANALYZE` dentro de `BEGIN … ROLLBACK`, sin dejarlo
     creado. Verificar después en `pg_extension`/`pg_indexes`. Antes de proponerlo, comprobar que la
     consulta real use la columna desnuda: `unaccent(lower(nombre)) ILIKE` no usa un GIN sobre `nombre`.

17. **Validar un cambio de la ingesta con una corrida acotada antes/después, en el `cromo-worker`.**
   Real (P21, 2026-10-27): `ejecutar_ingesta(cliente, sesion, usuario=..., psize=50, max_paginas=1,
   modo="SOLO_ODF")` re-barre 50 ODF reales en ~1 min, casi todas `SIN_CAMBIOS`. Se corre dos veces
   con el mismo script: "antes" con `-w /app -e PYTHONPATH=/app` (la imagen de `dev`: verificar con
   `docker image inspect … --format '{{.Created}}'` contra la fecha de `origin/dev` y con
   `diff -rq /app/core /tmp/wt/core`) y "después" con el código del worktree en `/tmp/wt` (regla 13).
   Comparar los contadores de la fila de la corrida y `count(*) GROUP BY accion` de sus eventos.
   - Escribe en `focas_dev` como cualquier ingesta, y cada corrida `COMPLETA`/`SOLO_ODF`/
     `SOLO_PELOS_INNER` dispara `detectar_post_ingesta`: aparece una corrida
     `detector-inconsistencias` entre las tuyas. Es esperable; no es otra sesión.
   - Un `DELETE` masivo sobre una tabla de la ingesta no achica el disco: el espacio queda para la
     propia tabla. Para recuperarlo hace falta `VACUUM (FULL, ANALYZE)` (lock exclusivo; en dev,
     1,2 s para `cromo_ingesta_eventos`: 61 → 45 MB). Chequear antes que no haya corridas `EN_CURSO`.

## Documentación relacionada

- `docs/Doc Privada/ingesta_cromo.md` §12 (Puntos abiertos) y §13 (Notas de implementación por etapa)
  — historial completo de hallazgos reales de esta naturaleza.
- `.github/skills/cromo-inventario/SKILL.md` — para trabajar sobre los datos ya ingeridos.
- `scripts/cromo_sonda.py`, `scripts/cromo_backfill_geo.py` — scripts reales de esta familia.
