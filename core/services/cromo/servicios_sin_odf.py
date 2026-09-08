# Nombre de archivo: servicios_sin_odf.py
# Ubicación de archivo: core/services/cromo/servicios_sin_odf.py
# Descripción: Detección y categorización de Servicios Activos verificables sin ODF Cromo resuelta — corazón del gestor de asociación manual Servicio↔ODF

"""Universo "Servicios Activos verificables sin ODF resuelta" + por qué cada uno quedó sin ODF.

Diagnóstico real que motiva el módulo: 2939 de 5731 Servicios Activos verificables de dev (51%) no
tienen ODF resuelta. Este módulo los lista paginados, le pone a cada uno una causa probable a
partir del equipo/nodo de última milla que trajo PROV, y — cuando el dato ya lo permite — sugiere
la ODF de un "hermano" del mismo (nodo, equipo) que sí está resuelto. **Nada se auto-aplica**: la
sugerencia es un dato para que el operador confirme a mano (ver
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
Arrancó en ~23.9s y quedó en **~0.1s**. Los cuatro cambios, todos verificados con
`EXPLAIN ANALYZE` real contra `lasfocasdev-postgres` y todos con universo IDÉNTICO (2891 filas):

1. `ix_cromo_odf_conectores_servicio_resuelto` (btree parcial, migración `20260908_01`) — sin él,
   `Seq Scan` sobre las 204.840 filas de la tabla (sólo el 5,36% tiene `servicio_resuelto` no nulo).
2. `ix_servicios_alias_ids_gin` (GIN, migración `20260908_02`), que **sólo sirve junto con** el
   rewrite a contención de `_SUBQUERY_ANTI_AMBIGUEDAD`: la opclass `array_ops` de GIN indexa
   `@>`/`<@`/`&&`/`=`, nunca `escalar = ANY(columna_array)`. Con los dos, el self-join pasa de
   `Seq Scan on servicios v2` (41M filas descartadas por `Join Filter`) a `Bitmap Heap Scan` con un
   `BitmapOr` de dos `Bitmap Index Scan`. Medido: ~23.9s → ~11.6s.
3. El `NOT EXISTS` de "no tiene ODF resuelta" **sin** CTE `MATERIALIZED` y desarmado por De Morgan
   en tres `NOT EXISTS` independientes — ver `_SQL_NO_TIENE_ODF_RESUELTA`. Medido: ~11.6s → ~0.09s.

La lección de las tres, para quien toque esta query: **el cost-estimate del planner no
correlaciona con el tiempo real** en ninguno de los tres casos. El plan original de este gestor
descartó el GIN por mirar el cost (~483 de ~37.828) y se equivocó, y la CTE `MATERIALIZED` también
venía de un cost-estimate. Medir con `EXPLAIN (ANALYZE, TIMING OFF)` sobre el universo real, no
estimar. `tests/test_cromo_servicios_sin_odf_real_db.py` tiene una regresión automática que falla
si alguien dropea cualquiera de los dos índices o revierte el rewrite del punto 2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
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
    (`subcategoria_sin_senal_prov`) cuesta 3 queries por fila y se calcula sólo on-demand en el
    endpoint de detalle.

    `nodo`/`equipo` son los del extremo que ganó la categorización (ver `categorizar_extremos`),
    no necesariamente el extremo 1. `extremos` trae **todos** los extremos, sin filtrar: la
    prioridad de categorización nunca debe ocultarle información al operador — un Servicio con
    `SW_x` en el extremo 1 y un OLT en el extremo 2 se categoriza como OLT, pero la UI tiene que
    poder mostrar los dos. `extremos` está vacía cuando no hay fila PROV (4 servicios reales en
    dev).
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


@dataclass(slots=True)
class ResultadoListadoSinOdf:
    """`total` es el tamaño del conjunto **ya filtrado** (por `categoria`/`q`) antes de cortar por
    `limit`/`offset` — nunca el del universo sin filtrar, para que el paginador de la UI no
    prometa páginas que no existen."""

    total: int
    limit: int
    offset: int
    items: list[ServicioSinOdf] = field(default_factory=list)


@dataclass(slots=True)
class SugerenciaOdf:
    """ODF de un Servicio hermano del mismo (nodo, equipo) que sí quedó resuelto.

    Es un dato para mostrar, NUNCA una asociación aplicada — el operador confirma explícitamente.
    """

    odf_n_id: int
    nombre: Optional[str]


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
) -> tuple[str, Optional[str], Optional[str], Optional[str]]:
    """Categoría de un Servicio a partir de TODOS sus extremos de última milla.

    Devuelve `(categoria_causa, subcategoria, nodo, equipo)` — `nodo`/`equipo` son los del extremo
    que ganó, para que la fila del listado muestre el dato que justifica la categoría.

    Por qué existe: `ServicioSinOdf` tiene un solo `nodo`/`equipo`, pero
    `app.servicios_equipos_ultima_milla` guarda 1 **o 2** extremos por Servicio (368 servicios con
    2 extremos en dev) y en **206 de esos 368** los dos extremos caen en categorías DISTINTAS
    (medido real). Tomar siempre el extremo 1 sería arbitrario y tendría un costo funcional
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
        return (*categorizar(None, None), None, None)

    def prioridad(indice_y_extremo: tuple[int, tuple[Optional[str], Optional[str]]]) -> tuple[int, int]:
        indice, (equipo, nodo) = indice_y_extremo
        return CATEGORIAS_POR_PRIORIDAD.index(categorizar(equipo, nodo)[0]), indice

    _, (equipo_ganador, nodo_ganador) = min(enumerate(extremos), key=prioridad)
    categoria, subcategoria = categorizar(equipo_ganador, nodo_ganador)
    return categoria, subcategoria, _texto_util(nodo_ganador), _texto_util(equipo_ganador)


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
_FILTRO_BUSQUEDA_LIBRE = """
          AND (s.servicio_id ILIKE :patron OR s.nombre_cliente ILIKE :patron)
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
    """Página del universo "Servicios Activos verificables sin ODF resuelta", ya categorizada.

    Excluye los que ya tienen una asociación manual en `app.cromo_servicio_odf_override`.

    Filtros:

    - `q`: búsqueda libre por `servicio_id` o `nombre_cliente`, en **SQL** (`ILIKE '%q%'`) — son
      columnas reales, así que filtrar allá recorta el set de candidatos antes de traerlo.
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
    """
    if categoria is not None and categoria not in CATEGORIAS_POR_PRIORIDAD:
        raise ValueError(
            f"categoria desconocida: {categoria!r}. Válidas: {', '.join(CATEGORIAS_POR_PRIORIDAD)}"
        )

    busqueda = q.strip() if q else ""
    if busqueda:
        filas = (
            await sesion.execute(
                _SQL_LISTADO_SIN_ODF_CON_BUSQUEDA, {"patron": f"%{busqueda}%"}
            )
        ).all()
    else:
        filas = (await sesion.execute(_SQL_LISTADO_SIN_ODF)).all()

    items: list[ServicioSinOdf] = []
    for fila in filas:
        extremos = _extremos_de_arrays(fila.extremos, fila.nodos, fila.equipos)
        categoria_causa, subcategoria, nodo, equipo = categorizar_extremos(
            [(e.equipo, e.nodo) for e in extremos]
        )
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
            )
        )

    return ResultadoListadoSinOdf(
        total=len(items),
        limit=limit,
        offset=offset,
        items=items[offset : offset + limit] if limit > 0 else [],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Cascada de subcategoría para SIN_SENAL_PROV — on-demand, NUNCA en el listado
# ─────────────────────────────────────────────────────────────────────────────

# Cuántos pelos matchean este número en `cromo_servicio_match`, y cuántos de esos pelos están
# efectivamente cableados a un conector de ODF. Las dos cuentas en una sola query: distinguen
# "Cromo no conoce el servicio" de "lo conoce pero el pelo no llega a ninguna patchera".
_SQL_PELOS_Y_CONECTORES = text(
    """
    SELECT
        (SELECT COUNT(*) FROM app.cromo_servicio_match m
          WHERE m.servicio_numero = :numero) AS pelos_matcheados,
        (SELECT COUNT(*) FROM app.cromo_servicio_match m
          JOIN app.cromo_odf_conectores c ON c.pelo_n_id = m.pelo_n_id
          WHERE m.servicio_numero = :numero) AS pelos_con_conector
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
    sesion: AsyncSession, servicio_id: int, numero: Optional[str]
) -> Optional[str]:
    """Subcausa de un Servicio categorizado `SIN_SENAL_PROV`, o `None` si ninguna aplica.

    **Sólo on-demand** (endpoint de detalle). NUNCA se llama desde `listar_servicios_sin_odf`:
    son hasta 3 queries por Servicio y el listado tiene cientos de filas por página.

    `servicio_id` es la PK de `app.servicios` (para buscar el hermano de Baja); `numero` es el
    número de servicio en texto (`servicio_id`/`numero_primer_servicio`) con el que Cromo matchea
    los pelos en `cromo_servicio_match.servicio_numero`.

    Cascada, en este orden:

    1. Cromo conoce el número (hay pelos matcheados) pero ninguno de esos pelos está cableado a un
       conector de ODF → `PELO_SIN_CONECTOR_ODF`.
    2. Cromo no conoce el número en absoluto (sin pelos matcheados) → `AUSENTE_RED_CROMO`.
    3. Hay un Servicio hermano (mismo cliente + misma dirección) dado de Baja que sí tiene pelo →
       `BAJA_LOGICA_HEREDADA` (la fibra física quedó asociada al servicio viejo).
    4. Ninguna aplica → `None`.

    Los pasos 1 y 2 son ramas excluyentes de la misma query; el 3 sólo se evalúa cuando el número
    sí tiene pelos Y esos pelos sí llegan a conectores (o sea: la fibra está en Cromo, pero no bajo
    la identidad de ESTE Servicio).
    """
    if numero is not None and numero.strip():
        fila = (
            await sesion.execute(_SQL_PELOS_Y_CONECTORES, {"numero": numero.strip()})
        ).one()
        if fila.pelos_matcheados == 0:
            return SUBCATEGORIA_AUSENTE_RED_CROMO
        if fila.pelos_con_conector == 0:
            return SUBCATEGORIA_PELO_SIN_CONECTOR_ODF
    else:
        # Sin número no hay forma de preguntarle nada a Cromo: es el caso extremo de "ausente".
        return SUBCATEGORIA_AUSENTE_RED_CROMO

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
# `LIMIT 1` + `DISTINCT`: alcanza con UNA ODF candidata para mostrarla como sugerencia. No se
# auto-aplica nunca — el operador confirma.
_SQL_SUGERENCIA_ODF = text(
    """
    SELECT DISTINCT c.odf_n_id, o.nombre
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

    `servicio_id` es la PK de `app.servicios`.
    """
    fila = (await sesion.execute(_SQL_SUGERENCIA_ODF, {"servicio_id": servicio_id})).first()
    if fila is None:
        return None
    return SugerenciaOdf(odf_n_id=int(fila.odf_n_id), nombre=fila.nombre)
