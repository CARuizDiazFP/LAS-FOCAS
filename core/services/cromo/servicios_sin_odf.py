# Nombre de archivo: servicios_sin_odf.py
# Ubicación de archivo: core/services/cromo/servicios_sin_odf.py
# Descripción: Detección y categorización de Servicios Activos verificables sin ODF Cromo resuelta — corazón del gestor de asociación manual Servicio↔ODF

"""Universo "Servicios Activos verificables sin ODF resuelta" + por qué cada uno quedó sin ODF.

Diagnóstico real que motiva el módulo: de los 5731 Servicios Activos verificables de dev, **2891
(50%) no tienen ODF resuelta** — ése es el universo vigente y el número que citan el resto de este
módulo y `docs/decisiones.md`. El diagnóstico inicial (entrada del 2026-09-07 de
`docs/decisiones.md`) había medido 2939: es el mismo universo ANTES del catch-up de
`fase_servicios`, no otra definición ni una medición contradictoria.

Este módulo los lista paginados, le pone a cada uno una causa probable a partir del equipo/nodo de
última milla que trajo PROV, y — cuando el dato ya lo permite — sugiere la ODF de un "hermano" del
mismo (nodo, equipo) que sí está resuelto. **Nada se auto-aplica**: la sugerencia es un dato para
que el operador confirme a mano (ver
`core/services/cromo/servicio_odf_override_service.py`).

Qué NO hace este módulo, a propósito:

- No reimplementa el matching Servicio↔ODF. Lo invierte: el patrón por texto
  (`servicio_resuelto = servicio_id OR = numero_primer_servicio OR = ANY(alias_ids)`) es
  literalmente el mismo de `core/services/cromo/odf_conectores.py::conectores_de_odf`, acá dentro
  de un `NOT EXISTS`. Nunca pasa por `cromo_servicio_match` para decidir "tiene ODF" (esa tabla es
  el inventario general de pelos, no la resolución de ODF).
- No reimplementa el criterio anti-ambigüedad de identidad de Servicios: es el mismo
  `NOT EXISTS` de `core/services/cromo/ingesta.py::_SQL_BUSCAR_SERVICIO` (excluye una fila cuya
  identidad ya fue absorbida como alias de otra), sólo reescrito a contención de arrays por
  performance — ver `_SUBQUERY_ANTI_AMBIGUEDAD`.
- No distingue "SW de frontera" de "SW con FO dedicada al cliente" dentro de
  `SWITCH_COMPARTIDO_REVISAR` — ver el TODO en `categorizar()`.

## Performance: los dos índices y los dos rewrites que esta query necesita

La query de listado es un anti-join de `app.servicios` contra dos tablas grandes y contra sí misma.
Arrancó en ~23.9s y quedó en **~0.15s**. Los tres pasos, todos verificados con
`EXPLAIN ANALYZE` real contra `lasfocasdev-postgres` y todos con universo IDÉNTICO (2891 filas):

1. `ix_cromo_odf_conectores_servicio_resuelto` (btree parcial, migración `20260908_01`) — sin él,
   `Seq Scan` sobre las 204.840 filas de la tabla (sólo el 5,36% tiene `servicio_resuelto` no nulo).
2. `ix_servicios_alias_ids_gin` (GIN, migración `20260908_02`), que **sólo sirve junto con** el
   rewrite a contención de `_SUBQUERY_ANTI_AMBIGUEDAD`: la opclass `array_ops` de GIN indexa
   `@>`/`<@`/`&&`/`=`, nunca `escalar = ANY(columna_array)`. Con los dos, el self-join pasa de
   `Seq Scan on servicios v2` (41M filas descartadas por `Join Filter`) a `Bitmap Heap Scan` con un
   `BitmapOr` de dos `Bitmap Index Scan`. Medido: ~23.9s → ~11.6s.
3. El `NOT EXISTS` de "no tiene ODF resuelta" **sin** CTE `MATERIALIZED` y desarmado por De Morgan
   en tres `NOT EXISTS` independientes — ver `_SQL_NO_TIENE_ODF_RESUELTA`. Medido: ~11.6s → ~0.15s
   (145.6 ms de `Execution Time`; el índice del punto 1 pasa a usarse TRES veces, una por subquery).

La lección de las tres, para quien toque esta query: **el cost-estimate del planner no
correlaciona con el tiempo real** en ninguno de los tres casos. El plan original de este gestor
descartó el GIN por mirar el cost (~483 de ~37.828) y se equivocó, y la CTE `MATERIALIZED` también
venía de un cost-estimate. Medir con `EXPLAIN (ANALYZE, TIMING OFF)` sobre el universo real, no
estimar. `tests/test_cromo_servicios_sin_odf_real_db.py` tiene una regresión automática que falla
si alguien dropea cualquiera de los dos índices o revierte cualquiera de los dos rewrites.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    # Público a propósito (2026-09-10): lo importa `camino_optico_service` para elegir el pelo
    # semilla de `/path`. Ya hay tres copias del patrón de identidades en el repo y una causó un
    # bug real (los pelos matcheados contra la fila perdedora, ver `ingesta.py`); una cuarta copia
    # divergente es el modo de falla conocido de este predicado.
    "IDENTIDADES_DEL_SERVICIO_SQL",
    "CATEGORIA_EQUIPO_DOMICILIO_CLIENTE",
    "CATEGORIA_OLT_PON_COMPARTIDO",
    "CATEGORIA_SIN_SENAL_PROV",
    "CATEGORIA_SWITCH_COMPARTIDO_REVISAR",
    "CATEGORIAS_POR_PRIORIDAD",
    "SUBCATEGORIA_AUSENTE_RED_CROMO",
    "SUBCATEGORIA_BAJA_LOGICA_HEREDADA",
    "SUBCATEGORIA_PELO_SIN_CONECTOR_ODF",
    "ExtremoUltimaMilla",
    "ResultadoListadoSinOdf",
    "ServicioSinOdf",
    "SugerenciaOdf",
    "categorizar",
    "categorizar_extremos",
    "listar_servicios_sin_odf",
    "subcategoria_sin_senal_prov",
    "sugerencia_odf_para_servicio",
]

# ─────────────────────────────────────────────────────────────────────────────
# Vocabulario — mismos literales que los CHECK de `app.cromo_servicio_odf_override`
# (migración `20260908_01`). Constantes y no un Enum a propósito: el CHECK de Postgres es la
# fuente de verdad del vocabulario y agregar un valor allá es un DROP/ADD CONSTRAINT, no un
# ALTER TYPE — un Enum de Python acá sólo agregaría un segundo lugar donde desincronizarse.
# ─────────────────────────────────────────────────────────────────────────────

CATEGORIA_OLT_PON_COMPARTIDO = "OLT_PON_COMPARTIDO"
CATEGORIA_EQUIPO_DOMICILIO_CLIENTE = "EQUIPO_DOMICILIO_CLIENTE"
CATEGORIA_SWITCH_COMPARTIDO_REVISAR = "SWITCH_COMPARTIDO_REVISAR"
CATEGORIA_SIN_SENAL_PROV = "SIN_SENAL_PROV"

SUBCATEGORIA_PELO_SIN_CONECTOR_ODF = "PELO_SIN_CONECTOR_ODF"
SUBCATEGORIA_AUSENTE_RED_CROMO = "AUSENTE_RED_CROMO"
SUBCATEGORIA_BAJA_LOGICA_HEREDADA = "BAJA_LOGICA_HEREDADA"

# Orden de "cuánta señal aporta la categoría", de más a menos — usado por
# `categorizar_extremos()` para elegir entre los dos extremos de un Servicio con última milla
# doble. Es el mismo orden en que `categorizar()` evalúa sus reglas, no una lista independiente.
CATEGORIAS_POR_PRIORIDAD = (
    CATEGORIA_OLT_PON_COMPARTIDO,
    CATEGORIA_EQUIPO_DOMICILIO_CLIENTE,
    CATEGORIA_SWITCH_COMPARTIDO_REVISAR,
    CATEGORIA_SIN_SENAL_PROV,
)

# Prefijos de la taxonomía, confirmados contra datos reales de dev (ver el plan de este gestor):
# `equipo ILIKE 'OLT%'` aísla limpio la red PON (25 equipos, 1552 servicios) y `nodo LIKE 'CLI\_%'`
# aísla equipos en domicilio del cliente (confiabilidad confirmada por el usuario). Son PREFIJOS,
# no substrings: `"VOLTA_1"` es un switch, no un OLT, y `"CLIENTE_algo"` no es `"CLI_"`.
_PREFIJO_EQUIPO_OLT = "OLT"
_PREFIJO_NODO_CLIENTE = "CLI_"


# ─────────────────────────────────────────────────────────────────────────────
# Dataclasses
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class ExtremoUltimaMilla:
    """Un extremo de última milla de un Servicio, tal como lo trajo PROV
    (`app.servicios_equipos_ultima_milla`). Un Servicio tiene 1 o 2."""

    extremo: Optional[int]
    nodo: Optional[str]
    equipo: Optional[str]


@dataclass(slots=True)
class ServicioSinOdf:
    """Un Servicio Activo verificable sin ODF resuelta, con su causa probable ya categorizada.

    `subcategoria` es siempre `None` en el listado paginado: la cascada de `SIN_SENAL_PROV`
    (`subcategoria_sin_senal_prov`) cuesta **1 o 2 queries por fila** (la segunda sólo si los pasos
    1/2 no cortaron antes) y se calcula sólo on-demand en el endpoint de detalle.

    `nodo`/`equipo` son los del extremo que ganó la categorización (ver `categorizar_extremos`),
    no necesariamente el extremo 1. `extremos` trae **todos** los extremos, sin filtrar: la
    prioridad de categorización nunca debe ocultarle información al operador — un Servicio con
    `SW_x` en el extremo 1 y un OLT en el extremo 2 se categoriza como OLT, pero la UI tiene que
    poder mostrar los dos. `extremos` está vacía cuando no hay fila PROV (4 servicios reales en
    dev).

    `indice_extremo_categorizado` es la posición en `extremos` del que ganó (`None` si no hay
    ninguno), para que la UI pueda marcarlo — `extremos[indice_extremo_categorizado]`. Hace falta
    porque `nodo`/`equipo` vienen normalizados (`.strip()`, ver `_texto_util`) y `extremos` trae el
    valor crudo de PROV, así que identificar al ganador comparando valores no es confiable.
    """

    id: int
    servicio_id: str
    numero_primer_servicio: Optional[str]
    nombre_cliente: Optional[str]
    categoria_causa: str
    subcategoria: Optional[str]
    nodo: Optional[str]
    equipo: Optional[str]
    extremos: list[ExtremoUltimaMilla] = field(default_factory=list)
    indice_extremo_categorizado: Optional[int] = None


@dataclass(slots=True)
class ResultadoListadoSinOdf:
    """`total` es el tamaño del conjunto **ya filtrado** (por `categoria`/`q`) antes de cortar por
    `limit`/`offset` — nunca el del universo sin filtrar, para que el paginador de la UI no
    prometa páginas que no existen.

    `conteos_por_categoria` tiene las 4 categorías de `CATEGORIAS_POR_PRIORIDAD` SIEMPRE presentes
    (0 cuando ninguna fila cae ahí) y se calcula sobre el conjunto filtrado por `q` pero **antes**
    del filtro `categoria`: son los números de los chips de la UI, que tienen que seguir mostrando
    el conteo de las otras categorías mientras una está seleccionada. Va en el mismo resultado, y
    no en un request por categoría, porque la categorización ya está hecha en esta misma pasada —
    ver el docstring de `listar_servicios_sin_odf`.
    """

    total: int
    limit: int
    offset: int
    items: list[ServicioSinOdf] = field(default_factory=list)
    conteos_por_categoria: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class SugerenciaOdf:
    """ODF de un Servicio hermano del mismo (nodo, equipo) que sí quedó resuelto.

    Es un dato para mostrar, NUNCA una asociación aplicada — el operador confirma explícitamente.

    `cantidad_candidatas` es cuántas ODFs distintas cumplen la condición de hermano resuelto para
    este Servicio, no cuántas se devuelven (siempre se devuelve UNA, la mejor rankeada por
    `_SQL_SUGERENCIA_ODF`). Existe porque presentar "la" sugerencia cuando hay varias candidatas le
    esconde al operador que estaba eligiendo entre opciones: medido real 2026-09-09, de los 1057
    Servicios `OLT_PON_COMPARTIDO` sin ODF que tienen al menos una candidata, **88 tienen más de
    una** (969 con 1, 35 con 2, 53 con 4). Siempre `>= 1` cuando hay sugerencia.
    """

    odf_n_id: int
    nombre: Optional[str]
    cantidad_candidatas: int


# ─────────────────────────────────────────────────────────────────────────────
# Categorización — funciones puras, sin DB
# ─────────────────────────────────────────────────────────────────────────────


def _texto_util(valor: Optional[str]) -> Optional[str]:
    """`None` para lo que no aporta señal: `None`, `""` y sólo-espacios se tratan igual.

    PROV puede devolver un campo vacío en vez de omitirlo; "equipo vacío" es semánticamente "sin
    señal PROV", no "un equipo cualquiera que no es OLT" (que caería en
    `SWITCH_COMPARTIDO_REVISAR` y le mentiría al operador diciéndole que hay un switch).
    """
    if valor is None:
        return None
    limpio = valor.strip()
    return limpio or None


def categorizar(equipo: Optional[str], nodo: Optional[str]) -> tuple[str, Optional[str]]:
    """Causa probable de que este Servicio no tenga ODF, a partir de su última milla PROV.

    Función PURA: recibe `equipo`/`nodo` ya leídos de `app.servicios_equipos_ultima_milla`, no
    ejecuta ninguna query. Devuelve `(categoria_causa, subcategoria)`; la subcategoría es siempre
    `None` acá — la única categoría que tiene subcategorías es `SIN_SENAL_PROV`, y su cascada
    (`subcategoria_sin_senal_prov`) necesita DB y se resuelve on-demand, nunca en el listado.

    Las 4 reglas, en este orden (la primera que aplica gana):

    1. `equipo` con prefijo `"OLT"` → `OLT_PON_COMPARTIDO`. Es la señal más fuerte y la única que
       habilita `sugerencia_odf_para_servicio`, así que gana incluso sobre un `nodo` `CLI_`.
    2. `nodo` con prefijo `"CLI_"` → `EQUIPO_DOMICILIO_CLIENTE` (equipo en el domicilio del
       cliente, la ODF de red no es donde termina el servicio).
    3. Cualquier otro `equipo` → `SWITCH_COMPARTIDO_REVISAR`.
    4. Sin `equipo` utilizable → `SIN_SENAL_PROV` (no hay fila PROV, o vino sin equipo).

    TODO(pendiente de criterio del usuario): `SWITCH_COMPARTIDO_REVISAR` mezcla hoy dos casos
    operativamente distintos — un "SW de frontera" (el servicio pasa por ahí pero el switch no dice
    nada sobre su ODF: coincidencia irrelevante) y un "SW con FO dedicada al cliente" (señal útil,
    la ODF del switch probablemente ES la del servicio). Distinguirlos requiere un criterio o una
    lista de equipos que el usuario todavía no entregó; está explícitamente FUERA de alcance de
    este gestor y **no se inventa la regla acá**. Hasta que llegue ese criterio, ambos casos caen
    en el mismo bucket y el operador los revisa a mano.
    """
    equipo_util = _texto_util(equipo)
    nodo_util = _texto_util(nodo)

    if equipo_util is not None and equipo_util.upper().startswith(_PREFIJO_EQUIPO_OLT):
        return CATEGORIA_OLT_PON_COMPARTIDO, None
    if nodo_util is not None and nodo_util.upper().startswith(_PREFIJO_NODO_CLIENTE):
        return CATEGORIA_EQUIPO_DOMICILIO_CLIENTE, None
    if equipo_util is not None:
        return CATEGORIA_SWITCH_COMPARTIDO_REVISAR, None
    return CATEGORIA_SIN_SENAL_PROV, None


def categorizar_extremos(
    extremos: Sequence[tuple[Optional[str], Optional[str]]],
) -> tuple[str, Optional[str], Optional[str], Optional[str], Optional[int]]:
    """Categoría de un Servicio a partir de TODOS sus extremos de última milla.

    Devuelve `(categoria_causa, subcategoria, nodo, equipo, indice_ganador)` — `nodo`/`equipo` son
    los del extremo que ganó, para que la fila del listado muestre el dato que justifica la
    categoría, e `indice_ganador` es su posición en `extremos` (`None` si la secuencia está vacía).

    El índice hace falta porque `nodo`/`equipo` salen normalizados por `_texto_util()` mientras la
    secuencia de entrada trae los valores crudos: sin el índice, un consumidor no puede identificar
    cuál extremo ganó comparando valores (`"  OLT2  "` vs `"OLT2"` no son iguales).

    Por qué existe: `ServicioSinOdf` tiene un solo `nodo`/`equipo`, pero
    `app.servicios_equipos_ultima_milla` guarda 1 **o 2** extremos por Servicio, y cuando hay 2 los
    dos suelen caer en categorías DISTINTAS. Medido real 2026-09-09, con el alcance explícito
    porque son dos universos distintos y los dos números circulan: **368 servicios con 2 extremos
    en toda la tabla, 206 de ellos con categorías divergentes**; **364 con 2 extremos dentro del
    universo "sin ODF resuelta" que lista este módulo, 204 divergentes** (los otros 4 ya tienen ODF
    y quedan fuera del listado). `docs/decisiones.md`/`docs/PR/2026-09-09.md` citan los 364/204
    porque hablan del gestor.

    Tomar siempre el extremo 1 sería arbitrario y tendría un costo funcional
    concreto: un Servicio con `SW_x` en el extremo 1 y un OLT en el extremo 2 quedaría como
    `SWITCH_COMPARTIDO_REVISAR` y **nunca** se le ofrecería la sugerencia de ODF del grupo OLT
    (Task 5 sólo la pide para `OLT_PON_COMPARTIDO`), pese a que
    `sugerencia_odf_para_servicio` sí la encontraría (esa query no filtra por extremo).

    Por eso gana el extremo con la categoría más informativa (`CATEGORIAS_POR_PRIORIDAD`), con
    empate resuelto por orden de extremo (determinista). No reimplementa la regla: aplica
    `categorizar()` a cada extremo y elige entre los resultados.

    `extremos` es una secuencia de `(equipo, nodo)` — mismo orden de argumentos que `categorizar`
    — ya ordenada por `extremo` ascendente.
    """
    if not extremos:
        return (*categorizar(None, None), None, None, None)

    def prioridad(indice_y_extremo: tuple[int, tuple[Optional[str], Optional[str]]]) -> tuple[int, int]:
        indice, (equipo, nodo) = indice_y_extremo
        return CATEGORIAS_POR_PRIORIDAD.index(categorizar(equipo, nodo)[0]), indice

    indice_ganador, (equipo_ganador, nodo_ganador) = min(enumerate(extremos), key=prioridad)
    categoria, subcategoria = categorizar(equipo_ganador, nodo_ganador)
    return (
        categoria,
        subcategoria,
        _texto_util(nodo_ganador),
        _texto_util(equipo_ganador),
        indice_ganador,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Listado paginado
# ─────────────────────────────────────────────────────────────────────────────

# Criterio anti-ambigüedad de identidad de Servicios, heredado tal cual de
# `core/services/cromo/ingesta.py::_SQL_BUSCAR_SERVICIO`: descarta una fila `s` cuya identidad ya
# fue absorbida como alias de otra fila `v2` (bug real 2026-08-31, ver docs/decisiones.md) — si no,
# el listado mostraría dos veces el mismo servicio real bajo dos numeraciones.
#
# Reescrito de `s.servicio_id = ANY(v2.alias_ids)` a `v2.alias_ids @> ARRAY[s.servicio_id]`: es la
# forma equivalente que el GIN `ix_servicios_alias_ids_gin` (migración `20260908_02`) SÍ puede
# usar. Semánticamente idéntico, verificado real: ambas formas dan las mismas 40 filas ambiguas
# sobre las 14.147 de `app.servicios` en dev, y el mismo universo de 2891 Servicios sin ODF.
#
# Sin CAST explícito a propósito, no por omisión: `alias_ids` es `varchar(64)[]` y
# `servicio_id`/`numero_primer_servicio` son `varchar(64)`, así que `ARRAY[<columna>]` ya resuelve
# a `character varying[]` y `@>` (que es `anyarray @> anyarray`) matchea sin ayuda — confirmado
# contra Postgres 16.13 real. Un `::text[]`/`::varchar[]` acá además impediría que el planner use
# el índice.
#
# `numero_primer_servicio IS NULL` se preserva igual que en la forma original: `alias_ids @>
# ARRAY[NULL]` da `false` y `NULL @> ARRAY[x]` da `NULL`, y ninguno de los dos es TRUE — el
# `EXISTS` decide lo mismo que con `NULL = ANY(...)`.
_SUBQUERY_ANTI_AMBIGUEDAD = """
      NOT EXISTS (
          SELECT 1 FROM app.servicios v2
          WHERE v2.id <> s.id
            AND (
              v2.alias_ids @> ARRAY[s.servicio_id]
              OR v2.alias_ids @> ARRAY[s.numero_primer_servicio]
            )
      )
"""

# "No tiene ODF resuelta" — el mismo patrón de matching textual de
# `odf_conectores.py::conectores_de_odf`, invertido.
#
# Desarmado por De Morgan en TRES `NOT EXISTS` independientes en vez de UNO con tres `OR` adentro:
# `NOT EXISTS(P1 OR P2 OR P3)` ≡ `NOT EXISTS(P1) AND NOT EXISTS(P2) AND NOT EXISTS(P3)` cuando los
# tres predicados corren sobre la misma tabla (es la misma equivalencia que
# `EXISTS(P1 OR P2 OR P3)` ≡ `EXISTS(P1) OR EXISTS(P2) OR EXISTS(P3)`, negada).
#
# No es cosmético: con los tres `OR` juntos el planner no puede usar
# `ix_cromo_odf_conectores_servicio_resuelto` para sondear, y arma un anti-join que descarta ~46
# MILLONES de filas por `Join Filter` (~11.4s). Separados, hace tres sondeos por índice — un
# `Merge Anti Join` y dos `Index Only Scan` parametrizados sobre ese mismo índice — y baja a ~90ms.
# Medido real contra dev, mismo universo (2891) en las dos formas.
#
# También se sacó la CTE `resueltos AS MATERIALIZED` que tenía la versión anterior: materializar
# obligaba a re-escanear la lista completa de `servicio_resuelto` por cada fila candidata, que es
# exactamente el anti-join de 46M filas. El índice sólo puede ayudar si el predicado le llega a la
# tabla, no a una CTE ya materializada.
#
# Sin `servicio_resuelto IS NOT NULL` explícito a propósito: `c.servicio_resuelto = <valor>` nunca
# es TRUE con NULL, y Postgres además prueba solo que esa igualdad implica el `WHERE` del índice
# PARCIAL, así que lo usa igual (confirmado en el plan real). Agregarlo no cambiaría el resultado.
_SQL_NO_TIENE_ODF_RESUELTA = """
    NOT EXISTS (
        SELECT 1 FROM app.cromo_odf_conectores c WHERE c.servicio_resuelto = v.servicio_id
    )
    AND NOT EXISTS (
        SELECT 1 FROM app.cromo_odf_conectores c WHERE c.servicio_resuelto = v.numero_primer_servicio
    )
    AND NOT EXISTS (
        SELECT 1 FROM app.cromo_odf_conectores c WHERE c.servicio_resuelto = ANY(v.alias_ids)
    )
"""

# Búsqueda libre opcional. Se inyecta en la CTE `verificables` (no en el `WHERE` final) para
# recortar el set de candidatos lo antes posible. La CLÁUSULA es dinámica (está o no está), pero el
# VALOR siempre viaja como bind param `:patron` — nunca interpolado. Se hace así, y no con un
# `:q IS NULL OR ...`, porque un bind comparado contra NULL obliga a un `CAST(:q AS text)` que en
# `text()` de SQLAlchemy arrastra el gotcha del espacio antes del `::` y además le esconde al
# planner que el filtro no aplica.
#
# `ESCAPE '\'` + `_escapar_like()`: sin eso, los metacaracteres de LIKE que el operador escriba en
# el buscador actúan como wildcards — `q="_"` matchearía TODO y `q="100%"` sería el prefijo "100".
# No es inyección (el valor va como bind), pero sí un resultado incorrecto y visible en la UI.
_FILTRO_BUSQUEDA_LIBRE = r"""
          AND (s.servicio_id ILIKE :patron ESCAPE '\'
               OR s.nombre_cliente ILIKE :patron ESCAPE '\')
"""

# `con_override` es CRÍTICO, no cosmético: sin él, un Servicio recién asociado a mano por un
# operador seguiría apareciendo en el listado después de confirmarlo. `DISTINCT` porque
# `cromo_servicio_odf_override` no tiene `UNIQUE (servicio_id)` a propósito (cada fila es un evento
# de asociación, permite reasociar sin perder historial).
#
# El LATERAL trae TODOS los extremos agregados en tres arrays paralelos ordenados por `extremo`, no
# sólo el extremo 1: la elección de extremo la hace `categorizar_extremos()` en Python, para no
# duplicar la regla de categorización en SQL, y los tres se exponen enteros en
# `ServicioSinOdf.extremos`. `array_agg` sobre cero filas devuelve `NULL`, que se traduce a "sin
# fila PROV".
#
# Sin `LIMIT`/`OFFSET` en SQL a propósito: `categoria_causa` no existe como columna (la calcula
# `categorizar_extremos()` en Python), así que cortar en SQL daría un `total` y unas páginas
# incorrectas en cuanto se filtra por categoría. Ver `listar_servicios_sin_odf`.
_PLANTILLA_LISTADO = """
    WITH verificables AS (
        SELECT s.id, s.servicio_id, s.numero_primer_servicio, s.alias_ids, s.nombre_cliente
        FROM app.servicios s
        WHERE s.estado_servicio ILIKE 'activo'
          AND s.es_verificable = true
          AND s.numero_primer_servicio IS NOT NULL
{filtro_busqueda}          AND {anti_ambiguedad}
    ),
    con_override AS (
        SELECT DISTINCT servicio_id FROM app.cromo_servicio_odf_override
    )
    SELECT
        v.id, v.servicio_id, v.numero_primer_servicio, v.nombre_cliente,
        e.extremos, e.nodos, e.equipos
    FROM verificables v
    LEFT JOIN LATERAL (
        SELECT
            array_agg(eq.extremo ORDER BY eq.extremo) AS extremos,
            array_agg(eq.nodo ORDER BY eq.extremo) AS nodos,
            array_agg(eq.equipo ORDER BY eq.extremo) AS equipos
        FROM app.servicios_equipos_ultima_milla eq
        WHERE eq.servicio_id = v.id
    ) e ON true
    WHERE {no_tiene_odf}
    AND v.id NOT IN (SELECT servicio_id FROM con_override)
    ORDER BY v.nombre_cliente NULLS LAST, v.id
"""

_SQL_LISTADO_SIN_ODF = text(
    _PLANTILLA_LISTADO.format(
        filtro_busqueda="",
        anti_ambiguedad=_SUBQUERY_ANTI_AMBIGUEDAD,
        no_tiene_odf=_SQL_NO_TIENE_ODF_RESUELTA,
    )
)
_SQL_LISTADO_SIN_ODF_CON_BUSQUEDA = text(
    _PLANTILLA_LISTADO.format(
        filtro_busqueda=_FILTRO_BUSQUEDA_LIBRE,
        anti_ambiguedad=_SUBQUERY_ANTI_AMBIGUEDAD,
        no_tiene_odf=_SQL_NO_TIENE_ODF_RESUELTA,
    )
)


def _escapar_like(texto: str) -> str:
    r"""Neutraliza los metacaracteres de `LIKE` para que la búsqueda sea literal.

    El `\` va primero, si no se re-escaparían las barras que agregan los otros dos reemplazos.
    Se usa junto con `ESCAPE '\'` en `_FILTRO_BUSQUEDA_LIBRE`.
    """
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _extremos_de_arrays(
    extremos: Optional[Sequence[Optional[int]]],
    nodos: Optional[Sequence[Optional[str]]],
    equipos: Optional[Sequence[Optional[str]]],
) -> list[ExtremoUltimaMilla]:
    """Los extremos de última milla, a partir de los tres arrays paralelos del LATERAL.

    Tolera que alguno venga `NULL` (Servicio sin fila PROV) y que tengan largos distintos — no
    debería pasar (el mismo `array_agg ORDER BY extremo` sobre las mismas filas), pero un `zip`
    estricto acá haría fallar el listado COMPLETO por una sola fila anómala, y esta función corre
    sobre datos de una tabla que reescribe otra ingesta.
    """
    lista_extremos = list(extremos or [])
    lista_nodos = list(nodos or [])
    lista_equipos = list(equipos or [])
    cantidad = max(len(lista_extremos), len(lista_nodos), len(lista_equipos))

    def en(lista, indice):
        return lista[indice] if indice < len(lista) else None

    return [
        ExtremoUltimaMilla(
            extremo=en(lista_extremos, i), nodo=en(lista_nodos, i), equipo=en(lista_equipos, i)
        )
        for i in range(cantidad)
    ]


async def listar_servicios_sin_odf(
    sesion: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    categoria: Optional[str] = None,
    q: Optional[str] = None,
) -> ResultadoListadoSinOdf:
    r"""Página del universo "Servicios Activos verificables sin ODF resuelta", ya categorizada.

    Excluye los que ya tienen una asociación manual en `app.cromo_servicio_odf_override`.

    Filtros:

    - `q`: búsqueda libre por `servicio_id` o `nombre_cliente`, en **SQL** (`ILIKE '%q%'`) — son
      columnas reales, así que filtrar allá recorta el set de candidatos antes de traerlo. El texto
      se busca **literal**: los metacaracteres de `LIKE` (`%`, `_`, `\`) van escapados, así que
      buscar `"100%"` no se comporta como el prefijo `"100"`.

    `offset`/`limit` negativos levantan `ValueError` (un `offset` negativo devolvería una página
    del final en silencio). `limit=0` es válido: devuelve lista vacía con el `total` real, útil para
    pedir sólo el conteo.
    - `categoria`: uno de `CATEGORIAS_POR_PRIORIDAD`, en **Python**. Va acá y no en SQL porque
      `categoria_causa` NO existe como columna: la calculan `categorizar()`/`categorizar_extremos()`,
      que quedan como única fuente de verdad de la taxonomía. Un `CASE WHEN upper(equipo) LIKE
      'OLT%' ...` en SQL duplicaría la regla (y también la prioridad entre extremos) y driftaría.
      Levanta `ValueError` con una categoría desconocida — mejor un error explícito que un listado
      vacío que parezca "no hay servicios de esta categoría".

    `total` es el tamaño del conjunto **ya filtrado**, y `limit`/`offset` se aplican DESPUÉS de
    filtrar, así que la paginación es correcta con y sin filtros.

    Límite conocido, aceptado a esta escala: trae TODOS los candidatos del universo en cada request
    (2891 filas hoy, ~90ms) y corta en Python. Es lo que permite que `categorizar_extremos()` sea la
    única fuente de verdad. Si el universo "sin ODF" crece 10x o más, esto se vuelve derrochador
    (memoria y ancho de banda por request) y habría que mover la categorización a SQL —
    materializándola como columna generada o en una vista, no duplicándola a mano— para poder
    volver a paginar y filtrar del lado del motor.

    Cada fila se categoriza con `categorizar_extremos()` sobre los extremos que trajo el LATERAL:
    barato, sin query por fila. `subcategoria` queda en `None` — la cascada de `SIN_SENAL_PROV` es
    on-demand (`subcategoria_sin_senal_prov`), nunca en el paginado, para no hacer N+1.

    Y como esa categorización ya se hizo para TODAS las filas candidatas (no sólo para la página),
    el resultado trae también `conteos_por_categoria` — las 4 categorías con su conteo real sobre
    el mismo conjunto filtrado por `q`, antes de aplicar `categoria`. Es el dato de los chips de la
    UI, y sale gratis de esta pasada: pedirlo con un request `limit=0` por categoría costaba 4
    ejecuciones EXTRA de esta misma query (la más cara de la feature) para devolver 4 enteros.
    """
    if categoria is not None and categoria not in CATEGORIAS_POR_PRIORIDAD:
        raise ValueError(
            f"categoria desconocida: {categoria!r}. Válidas: {', '.join(CATEGORIAS_POR_PRIORIDAD)}"
        )
    # Mismo criterio explícito que `categoria`: un `offset` negativo con el slice de Python
    # devolvería una página del FINAL en silencio (`items[-3:-1]`), que es un resultado plausible
    # pero equivocado — el peor tipo de bug para un paginador.
    if offset < 0:
        raise ValueError(f"offset no puede ser negativo: {offset}")
    if limit < 0:
        raise ValueError(f"limit no puede ser negativo: {limit}")

    busqueda = q.strip() if q else ""
    if busqueda:
        filas = (
            await sesion.execute(
                _SQL_LISTADO_SIN_ODF_CON_BUSQUEDA,
                {"patron": f"%{_escapar_like(busqueda)}%"},
            )
        ).all()
    else:
        filas = (await sesion.execute(_SQL_LISTADO_SIN_ODF)).all()

    items: list[ServicioSinOdf] = []
    # Los conteos de los chips salen de ESTA pasada, no de 4 requests extra: la categoría de cada
    # fila ya está calculada acá abajo, así que sumarla a un contador es gratis. Antes el frontend
    # pedía `limit=0` una vez por categoría, y cada uno de esos requests volvía a correr la query
    # completa del universo (~2891 filas, 145-275 ms) para devolver un entero — 5 ejecuciones
    # concurrentes de la query más cara de la feature por cada búsqueda, montaje, refresco y
    # asociación.
    conteos: dict[str, int] = {nombre: 0 for nombre in CATEGORIAS_POR_PRIORIDAD}
    for fila in filas:
        extremos = _extremos_de_arrays(fila.extremos, fila.nodos, fila.equipos)
        categoria_causa, subcategoria, nodo, equipo, indice_ganador = categorizar_extremos(
            [(e.equipo, e.nodo) for e in extremos]
        )
        # Antes del filtro por categoría a propósito: los chips muestran el conteo de las 4
        # categorías incluso con una seleccionada.
        conteos[categoria_causa] = conteos.get(categoria_causa, 0) + 1
        if categoria is not None and categoria_causa != categoria:
            continue
        items.append(
            ServicioSinOdf(
                id=fila.id,
                servicio_id=fila.servicio_id,
                numero_primer_servicio=fila.numero_primer_servicio,
                nombre_cliente=fila.nombre_cliente,
                categoria_causa=categoria_causa,
                subcategoria=subcategoria,
                nodo=nodo,
                equipo=equipo,
                extremos=extremos,
                indice_extremo_categorizado=indice_ganador,
            )
        )

    return ResultadoListadoSinOdf(
        total=len(items),
        limit=limit,
        offset=offset,
        # `limit == 0` es válido y significa "sólo quiero el total": lista vacía, `total` real.
        items=items[offset : offset + limit] if limit > 0 else [],
        conteos_por_categoria=conteos,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Cascada de subcategoría para SIN_SENAL_PROV — on-demand, NUNCA en el listado
# ─────────────────────────────────────────────────────────────────────────────

# Un pelo de Cromo "es de este Servicio" si su match apunta a la fila por FK, o si el número que
# el regex le sacó a la descripción del pelo coincide con CUALQUIERA de las tres identidades del
# Servicio. Es el mismo criterio de identidad de `ingesta.py::_SQL_BUSCAR_SERVICIO` y del listado
# de este módulo — la constraint global del plan: el matching Servicio↔Cromo es siempre por las
# tres identidades, nunca por una sola.
#
# Por qué importa (bug real corregido en la review de la Tarea 3): keyear sólo por UN número
# etiquetaba `AUSENTE_RED_CROMO` ("Cromo no conoce este Servicio") a un Servicio cuyos pelos SÍ
# están en Cromo pero bajo su otra numeración o bajo un alias. Un diagnóstico falso mostrado al
# operador es peor que no mostrar ninguno.
#
# `m.servicio_id = s.id` primero, y no sólo los tres números: es el vínculo ya resuelto por
# `fase_servicios` y cubre el caso en que `alias_ids` cambió DESPUÉS de que se registró el match.
# Además hace la función consistente consigo misma — el paso 3 de la cascada
# (`_SQL_HERMANO_DE_BAJA_CON_PELO`) ya keyeaba por esta misma FK.
#
# `= ANY(s.alias_ids)` y no `@>`: acá el escalar es de `cromo_servicio_match` y el array es de la
# fila candidata de `servicios` — la dirección inversa al self-join anti-ambigüedad, donde el GIN
# sí aplica. Misma asimetría deliberada que en `_SQL_NO_TIENE_ODF_RESUELTA`.
IDENTIDADES_DEL_SERVICIO_SQL = """
             m.servicio_id = s.id
          OR m.servicio_numero = s.servicio_id
          OR m.servicio_numero = s.numero_primer_servicio
          OR m.servicio_numero = ANY(s.alias_ids)
"""

# Cuántos pelos de Cromo son de este Servicio, y cuántos de esos están efectivamente cableados a un
# conector de ODF. Las dos cuentas en una sola query: distinguen "Cromo no conoce el Servicio" de
# "lo conoce pero el pelo no llega a ninguna patchera".
_SQL_PELOS_Y_CONECTORES = text(
    f"""
    SELECT
        (SELECT COUNT(*) FROM app.cromo_servicio_match m
          WHERE {IDENTIDADES_DEL_SERVICIO_SQL}) AS pelos_matcheados,
        (SELECT COUNT(*) FROM app.cromo_servicio_match m
          JOIN app.cromo_odf_conectores c ON c.pelo_n_id = m.pelo_n_id
          WHERE {IDENTIDADES_DEL_SERVICIO_SQL}) AS pelos_con_conector
    FROM app.servicios s
    WHERE s.id = :servicio_id
    """
)

# Hermano lógico: mismo cliente y misma dirección, dado de Baja, y que sí tiene pelo en Cromo — el
# patrón de "la fibra física existe pero quedó colgada del servicio viejo que se dio de baja".
#
# "de Baja" es igualdad exacta case-insensitive con espacios recortados, NO `ILIKE '%baja%'`: es el
# mismo criterio ya canónico en
# `core/services/servicios_consolidacion_service.py::es_verificable_por_tipo_y_estado`
# (`estado_servicio.strip().lower() == "baja"`). Con `%baja%` entrarían las 6 filas reales de dev
# en `'SOL BAJA'` (solicitud de baja), que todavía no son una baja.
#
# `nombre_cliente`/`direccion` se comparan con `=` (no `IS NOT DISTINCT FROM`) a propósito: si al
# Servicio actual le falta cualquiera de los dos, no hay identidad suficiente para afirmar
# "hermano" y la query no devuelve nada — que es la respuesta correcta, no un falso positivo por
# `NULL = NULL`.
_SQL_HERMANO_DE_BAJA_CON_PELO = text(
    """
    SELECT 1
    FROM app.servicios actual
    JOIN app.servicios hermano
      ON hermano.id <> actual.id
     AND hermano.nombre_cliente = actual.nombre_cliente
     AND hermano.direccion = actual.direccion
    WHERE actual.id = :servicio_id
      AND btrim(hermano.estado_servicio) ILIKE 'baja'
      AND EXISTS (
          SELECT 1 FROM app.cromo_servicio_match m WHERE m.servicio_id = hermano.id
      )
    LIMIT 1
    """
)


async def subcategoria_sin_senal_prov(
    sesion: AsyncSession, servicio_id: int
) -> Optional[str]:
    """Subcausa de un Servicio categorizado `SIN_SENAL_PROV`, o `None` si ninguna aplica.

    **Sólo on-demand** (endpoint de detalle). NUNCA se llama desde `listar_servicios_sin_odf`:
    son 1 o 2 queries por Servicio (la segunda, `_SQL_HERMANO_DE_BAJA_CON_PELO`, sólo cuando los
    pasos 1/2 no cortaron antes) y el listado tiene cientos de filas por página.

    `servicio_id` es la **PK** de `app.servicios` (`servicios.id`), no un número de servicio. Es el
    único argumento a propósito: las tres identidades del Servicio (`servicio_id`,
    `numero_primer_servicio`, `alias_ids`) las resuelve la query sola, por
    `IDENTIDADES_DEL_SERVICIO_SQL`. Antes recibía además un `numero` y keyeaba sólo por él, y eso
    dejaba que el llamador eligiera UNA identidad y obtuviera respuestas distintas según cuál
    eligiera — con `AUSENTE_RED_CROMO` (un diagnóstico FALSO) para un Servicio cuyos pelos están en
    Cromo bajo otra de sus numeraciones. Sin ese parámetro, ese error ya no se puede cometer.

    Cascada, en este orden:

    1. Cromo conoce el Servicio (hay pelos matcheados por cualquiera de sus identidades) pero
       ninguno de esos pelos está cableado a un conector de ODF → `PELO_SIN_CONECTOR_ODF`.
    2. Cromo no lo conoce en absoluto (ningún pelo matchea ninguna de sus identidades) →
       `AUSENTE_RED_CROMO`.
    3. Hay un Servicio hermano (mismo cliente + misma dirección) dado de Baja que sí tiene pelo →
       `BAJA_LOGICA_HEREDADA` (la fibra física quedó asociada al servicio viejo).
    4. Ninguna aplica → `None`.

    Los pasos 1 y 2 son ramas excluyentes de la misma query; el 3 sólo se evalúa cuando el Servicio
    sí tiene pelos Y esos pelos sí llegan a conectores (o sea: la fibra está en Cromo, pero la ODF
    no quedó resuelta bajo la identidad de ESTE Servicio).

    Devuelve `None` también si `servicio_id` no existe: sin fila no hay evidencia de nada, y es
    preferible a una excepción para el caso de carrera "el Servicio se borró entre el 404 del
    endpoint y esta consulta".
    """
    fila = (
        await sesion.execute(_SQL_PELOS_Y_CONECTORES, {"servicio_id": servicio_id})
    ).first()
    if fila is None:
        return None
    if fila.pelos_matcheados == 0:
        return SUBCATEGORIA_AUSENTE_RED_CROMO
    if fila.pelos_con_conector == 0:
        return SUBCATEGORIA_PELO_SIN_CONECTOR_ODF

    hermano = (
        await sesion.execute(_SQL_HERMANO_DE_BAJA_CON_PELO, {"servicio_id": servicio_id})
    ).first()
    if hermano is not None:
        return SUBCATEGORIA_BAJA_LOGICA_HEREDADA

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Sugerencia de ODF por grupo OLT/PON
# ─────────────────────────────────────────────────────────────────────────────

# Un hermano del mismo (nodo, equipo) que sí tiene ODF resuelta. El JOIN contra
# `cromo_odf_conectores` usa el patrón de matching por texto EXACTO de
# `odf_conectores.py::conectores_de_odf` — nunca `cromo_servicio_match`.
#
# No filtra por `extremo`: un Servicio con última milla doble puede tener el OLT en el extremo 2, y
# el grupo (nodo, equipo) es el mismo concepto en ambos casos. Coherente con
# `categorizar_extremos()`, que tampoco privilegia el extremo 1.
#
# Se devuelve UNA sola ODF (`LIMIT 1`) porque la UI muestra una sugerencia, pero el `LIMIT` va
# SIEMPRE con `ORDER BY` explícito y la fila trae además cuántas candidatas había:
#
# - **`ORDER BY` determinista, no cosmético.** La versión anterior era un `SELECT DISTINCT ...
#   LIMIT 1` SIN `ORDER BY`, y eso no le pide a Postgres ninguna fila en particular: devuelve la
#   que el plan alcanza primero, y ese "primero" puede cambiar con el plan, con el orden del heap
#   tras una ingesta o con un scan paralelo. Medido real 2026-09-09 sobre los 94 Servicios con
#   varias candidatas: la forma vieja resultó ESTABLE en dev hoy (8 repeticiones × 11 variantes de
#   plan forzadas con `enable_hashjoin`/`enable_hashagg`/`enable_nestloop`/paralelismo/
#   `join_collapse_limit` — siempre la misma ODF), así que el flapping es un riesgo LATENTE, no un
#   bug observado. Lo que falta es la garantía: con `ORDER BY` el resultado es estable por
#   definición y no depende de que el planner siga eligiendo el mismo plan.
# - **Criterio de orden:** `hermanos_resueltos DESC` primero — la ODF a la que ya se resolvieron
#   MÁS Servicios hermanos del mismo (nodo, equipo) es la más corroborada por los datos — y
#   `odf_n_id` como desempate estable (nunca `nombre`: 217 ODFs comparten nombre con otra, ver
#   I2/`ModalAsociarOdf.vue`). Verificado real: con este orden las 94 sugerencias multi-candidata
#   de dev dan la MISMA ODF que devolvía la forma vieja (en todos esos grupos `hermanos_resueltos`
#   empata en 1 y gana el desempate por `odf_n_id`), así que el cambio agrega garantía sin mover
#   ninguna sugerencia existente.
# - **`cantidad_candidatas`** sale de la misma CTE (`(SELECT COUNT(*) FROM candidatas)`), sin una
#   segunda ida a la base: es el dato que la UI necesita para no presentar como única una elección
#   entre 2-4 opciones. Medido: 88 de 1057.
#
# El `JOIN app.cromo_odfs` va DENTRO de la CTE a propósito (igual que en la forma vieja): una ODF
# sin fila propia en `cromo_odfs` no es ofrecible — mismo criterio estricto que exige
# `crear_override` — así que tampoco debe contarse como candidata.
#
# `GROUP BY c.odf_n_id, o.nombre` y no sólo por `c.odf_n_id`: la detección de dependencia funcional
# de Postgres sólo aplica cuando se agrupa por la PK de la propia tabla (`o.n_id`), no por una
# columna igualada de otra tabla. Como `cromo_odfs.n_id` es PK, agrupar por el par da exactamente
# los mismos grupos.
#
# `COUNT(DISTINCT s_hermano.id)` y no `COUNT(*)`: un mismo hermano puede llegar a la misma ODF por
# varios conectores (o por más de una de sus tres identidades), y eso inflaría la corroboración de
# una ODF con un solo hermano muy cableado.
_SQL_SUGERENCIA_ODF = text(
    """
    WITH candidatas AS (
        SELECT c.odf_n_id, o.nombre, COUNT(DISTINCT s_hermano.id) AS hermanos_resueltos
        FROM app.servicios_equipos_ultima_milla e_actual
        JOIN app.servicios_equipos_ultima_milla e_hermano
          ON e_hermano.nodo = e_actual.nodo AND e_hermano.equipo = e_actual.equipo
          AND e_hermano.servicio_id <> e_actual.servicio_id
        JOIN app.servicios s_hermano ON s_hermano.id = e_hermano.servicio_id
        JOIN app.cromo_odf_conectores c
          ON c.servicio_resuelto = s_hermano.servicio_id
          OR c.servicio_resuelto = s_hermano.numero_primer_servicio
          OR c.servicio_resuelto = ANY(s_hermano.alias_ids)
        JOIN app.cromo_odfs o ON o.n_id = c.odf_n_id
        WHERE e_actual.servicio_id = :servicio_id
        GROUP BY c.odf_n_id, o.nombre
    )
    SELECT
        odf_n_id,
        nombre,
        hermanos_resueltos,
        (SELECT COUNT(*) FROM candidatas) AS cantidad_candidatas
    FROM candidatas
    ORDER BY hermanos_resueltos DESC, odf_n_id
    LIMIT 1
    """
)


async def sugerencia_odf_para_servicio(
    sesion: AsyncSession, servicio_id: int
) -> Optional[SugerenciaOdf]:
    """ODF de un hermano del mismo (nodo, equipo) que sí quedó resuelto, o `None`.

    Pensada para la categoría `OLT_PON_COMPARTIDO` — el caso de uso real es el grupo
    `ElRincon842_Pilar`/`OLT2_Pilar` de dev: 618 servicios, uno solo con ODF resuelta, que alcanza
    para sugerirle esa ODF a los otros 617. La query no chequea la categoría por sí misma (quien
    llama ya la conoce y no hace falta recalcularla), pero para un switch de frontera el "hermano"
    puede ser una coincidencia irrelevante — de ahí que sea una **sugerencia** que el operador
    confirma, nunca una asociación automática.

    Devuelve la candidata mejor rankeada por `_SQL_SUGERENCIA_ODF` (más hermanos ya resueltos a esa
    ODF, desempate por `odf_n_id`) junto con `cantidad_candidatas` — cuántas había en total. Quien
    muestre la sugerencia tiene que exponer ese número cuando es `> 1`: presentar una sola ODF sin
    decir que había 4 le esconde al operador que estaba eligiendo entre opciones.

    `servicio_id` es la PK de `app.servicios`.
    """
    fila = (await sesion.execute(_SQL_SUGERENCIA_ODF, {"servicio_id": servicio_id})).first()
    if fila is None:
        return None
    return SugerenciaOdf(
        odf_n_id=int(fila.odf_n_id),
        nombre=fila.nombre,
        cantidad_candidatas=int(fila.cantidad_candidatas),
    )
