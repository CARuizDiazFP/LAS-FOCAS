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

## Performance: los dos índices y el rewrite que esta query necesita

La query de listado es un anti-join de `app.servicios` contra dos tablas grandes y contra sí misma.
Dos fixes de índice, ambos verificados con `EXPLAIN ANALYZE` real contra `lasfocasdev-postgres`:

1. `ix_cromo_odf_conectores_servicio_resuelto` (btree parcial, migración `20260908_01`) — la CTE
   `resueltos` pasó de `Seq Scan` sobre 204.840 filas a `Index Only Scan` (cost 31923 → 6736).
2. `ix_servicios_alias_ids_gin` (GIN, migración `20260908_02`) — **sólo sirve junto con el rewrite
   a contención de `_SUBQUERY_ANTI_AMBIGUEDAD`**: la opclass `array_ops` de GIN indexa `@>`/`<@`/
   `&&`/`=`, nunca `escalar = ANY(columna_array)`. Con los dos, el self-join pasa de
   `Seq Scan on servicios v2` (41M filas descartadas por `Join Filter`) a `Bitmap Heap Scan` con un
   `BitmapOr` de dos `Bitmap Index Scan`. Medido: ~23.9s → ~11.6s.

Queda un tercer cuello de botella **no resuelto acá** (fuera del alcance de esta tarea, evidencia y
número real en
`.superpowers/sdd/tambiem-validemos-domicilios-extraidos-robust-swing/task-3-report.md`): el
anti-join contra la CTE `resueltos AS MATERIALIZED` descarta ~46M filas por `Join Filter`, porque
materializar la CTE obliga a re-escanearla completa por cada fila candidata y el índice del punto 1
sólo acelera *construirla*, no recorrerla. Es la mitad del tiempo restante.
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
class ServicioSinOdf:
    """Un Servicio Activo verificable sin ODF resuelta, con su causa probable ya categorizada.

    `subcategoria` es siempre `None` en el listado paginado: la cascada de `SIN_SENAL_PROV`
    (`subcategoria_sin_senal_prov`) cuesta 3 queries por fila y se calcula sólo on-demand en el
    endpoint de detalle. `nodo`/`equipo` son los del extremo de última milla que ganó la
    categorización (ver `categorizar_extremos`), no necesariamente el extremo 1.
    """

    id: int
    servicio_id: str
    numero_primer_servicio: Optional[str]
    nombre_cliente: Optional[str]
    categoria_causa: str
    subcategoria: Optional[str]
    nodo: Optional[str]
    equipo: Optional[str]


@dataclass(slots=True)
class ResultadoListadoSinOdf:
    """`total` es el tamaño del universo COMPLETO (no de la página): se calcula con
    `COUNT(*) OVER ()` en la misma pasada, para no pagar dos veces el anti-join."""

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

# `resueltos AS MATERIALIZED`: fuerza a Postgres a construir la lista de `servicio_resuelto` una
# sola vez (vía `ix_cromo_odf_conectores_servicio_resuelto`) en vez de re-planificar el `NOT
# EXISTS` inline. Ver la nota de performance del docstring del módulo: materializar acelera
# *construirla* pero obliga a re-escanearla por cada fila candidata (~46M filas descartadas por
# `Join Filter`), y ése es el cuello de botella que queda abierto.
#
# `con_override` es CRÍTICO, no cosmético: sin él, un Servicio recién asociado a mano por un
# operador seguiría apareciendo en el listado después de confirmarlo. `DISTINCT` porque
# `cromo_servicio_odf_override` no tiene `UNIQUE (servicio_id)` a propósito (cada fila es un evento
# de asociación, permite reasociar sin perder historial).
#
# El LATERAL trae TODOS los extremos agregados en dos arrays paralelos ordenados por `extremo`, no
# el extremo 1: la elección de extremo la hace `categorizar_extremos()` en Python, para no duplicar
# la regla de categorización en SQL. `array_agg` sobre cero filas devuelve `NULL`, que se traduce a
# "sin fila PROV".
_SQL_LISTADO_SIN_ODF = text(
    f"""
    WITH verificables AS (
        SELECT s.id, s.servicio_id, s.numero_primer_servicio, s.alias_ids, s.nombre_cliente
        FROM app.servicios s
        WHERE s.estado_servicio ILIKE 'activo'
          AND s.es_verificable = true
          AND s.numero_primer_servicio IS NOT NULL
          AND {_SUBQUERY_ANTI_AMBIGUEDAD}
    ),
    resueltos AS MATERIALIZED (
        SELECT servicio_resuelto
        FROM app.cromo_odf_conectores
        WHERE servicio_resuelto IS NOT NULL
    ),
    con_override AS (
        SELECT DISTINCT servicio_id FROM app.cromo_servicio_odf_override
    )
    SELECT
        v.id, v.servicio_id, v.numero_primer_servicio, v.nombre_cliente,
        e.nodos, e.equipos,
        COUNT(*) OVER () AS total
    FROM verificables v
    LEFT JOIN LATERAL (
        SELECT
            array_agg(eq.nodo ORDER BY eq.extremo) AS nodos,
            array_agg(eq.equipo ORDER BY eq.extremo) AS equipos
        FROM app.servicios_equipos_ultima_milla eq
        WHERE eq.servicio_id = v.id
    ) e ON true
    WHERE NOT EXISTS (
        SELECT 1 FROM resueltos c
        WHERE c.servicio_resuelto = v.servicio_id
           OR c.servicio_resuelto = v.numero_primer_servicio
           OR c.servicio_resuelto = ANY(v.alias_ids)
    )
    AND v.id NOT IN (SELECT servicio_id FROM con_override)
    ORDER BY v.nombre_cliente NULLS LAST, v.id
    LIMIT :limit OFFSET :offset
    """
)


def _extremos_de_arrays(
    nodos: Optional[Sequence[Optional[str]]], equipos: Optional[Sequence[Optional[str]]]
) -> list[tuple[Optional[str], Optional[str]]]:
    """`(equipo, nodo)` por extremo, a partir de los dos arrays paralelos del LATERAL.

    Tolera que uno de los dos venga `NULL` (Servicio sin fila PROV) y que tengan largos
    distintos — no debería pasar (el mismo `array_agg ORDER BY extremo` sobre las mismas filas),
    pero un `zip` estricto acá haría fallar el listado completo por una fila anómala, y esta
    función corre sobre datos de una tabla que reescribe otra ingesta.
    """
    lista_nodos = list(nodos or [])
    lista_equipos = list(equipos or [])
    total = max(len(lista_nodos), len(lista_equipos))
    return [
        (
            lista_equipos[i] if i < len(lista_equipos) else None,
            lista_nodos[i] if i < len(lista_nodos) else None,
        )
        for i in range(total)
    ]


async def listar_servicios_sin_odf(
    sesion: AsyncSession, *, limit: int = 50, offset: int = 0
) -> ResultadoListadoSinOdf:
    """Página del universo "Servicios Activos verificables sin ODF resuelta", ya categorizada.

    Excluye los que ya tienen una asociación manual en `app.cromo_servicio_odf_override`. `total`
    es el universo completo, no el largo de la página.

    Cada fila se categoriza en Python con `categorizar_extremos()` sobre los extremos que trajo el
    LATERAL — barato (no hay query por fila) y sin duplicar la regla en SQL. `subcategoria` queda
    en `None`: la cascada de `SIN_SENAL_PROV` es on-demand (`subcategoria_sin_senal_prov`), nunca
    en el paginado, para no hacer N+1 sobre cientos de filas.
    """
    filas = (
        await sesion.execute(_SQL_LISTADO_SIN_ODF, {"limit": limit, "offset": offset})
    ).all()

    items: list[ServicioSinOdf] = []
    for fila in filas:
        categoria, subcategoria, nodo, equipo = categorizar_extremos(
            _extremos_de_arrays(fila.nodos, fila.equipos)
        )
        items.append(
            ServicioSinOdf(
                id=fila.id,
                servicio_id=fila.servicio_id,
                numero_primer_servicio=fila.numero_primer_servicio,
                nombre_cliente=fila.nombre_cliente,
                categoria_causa=categoria,
                subcategoria=subcategoria,
                nodo=nodo,
                equipo=equipo,
            )
        )

    return ResultadoListadoSinOdf(
        total=int(filas[0].total) if filas else 0,
        limit=limit,
        offset=offset,
        items=items,
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
