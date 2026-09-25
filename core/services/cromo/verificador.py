# Nombre de archivo: verificador.py
# Ubicación de archivo: core/services/cromo/verificador.py
# Descripción: Consultas de sólo lectura sobre el inventario Cromo ya ingerido — qué servicios pasan por un cable/tubo/botella

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session


class ObjetoNoEncontrado(RuntimeError):
    """El cable/tubo/botella consultado no existe en el inventario ya ingerido."""


@dataclass(slots=True)
class ServicioEncontrado:
    """Un servicio de `app.servicios` alcanzado a través de un pelo con match (`cromo_servicio_match`)
    — o, sólo en `servicios_por_odf`, a través de una asociación manual confirmada por un operador
    (`app.cromo_servicio_odf_override`, Tarea 4 del gestor "Servicios sin ODF")."""

    servicio_id: int
    servicio_id_externo: str
    numero_primer_servicio: Optional[str]
    nombre_cliente: Optional[str]
    cliente: Optional[str]
    estado_servicio: Optional[str]
    categoria: Optional[int]
    tipo_servicio: Optional[str]
    # `Optional` (y no `int`) desde la Tarea 4: un Servicio alcanzado por override manual puede no
    # tener `pelo_n_id` pineado ("asociado a la ODF en general", ver `CromoServicioOdfOverride`) —
    # sigue siendo siempre un `int` real para las filas de matching automático (`servicios_por_cable/
    # tubo/botella`), este cambio de tipo no les afecta.
    pelo_n_id: Optional[int]
    servicio_numero_match: str
    metodo: str
    # Distingue de dónde vino la fila: "automatico" (matching por texto vía `cromo_servicio_match`/
    # `servicio_resuelto`, el único origen hasta la Tarea 4) u "override_manual" (asociación manual
    # confirmada por un operador, sólo posible en `servicios_por_odf`). Default para no romper la
    # forma de `servicios_por_cable/tubo/botella` (y de `detalle.py`, y de los tests que construyen
    # `ServicioEncontrado` a mano): ninguno de esos call-sites pasa `origen`, y todos siguen
    # obteniendo "automatico" como antes de este campo existir.
    origen: str = "automatico"


@dataclass(slots=True)
class ResultadoCable:
    cable_n_id: int
    nombre: Optional[str]
    capacidad: Optional[str]
    extremo_a_nombre: Optional[str]
    extremo_b_nombre: Optional[str]
    servicios: list[ServicioEncontrado]


@dataclass(slots=True)
class ResultadoTubo:
    tubo_n_id: int
    cable_n_id: Optional[int]  # None si el tubo sólo se conoce por referencia colgada (sin fila propia)
    orden: Optional[int]
    nombre_color: Optional[str]
    servicios: list[ServicioEncontrado]


@dataclass(slots=True)
class CableDeBotella:
    """Un cable que tiene esta botella como uno de sus extremos, para la tarjeta de "Cables
    asociados" del detalle de Botella en el Verificador — no expone tubos/pelos (para eso está
    `detalle.py`/`CableDetalleCromoView.vue`), sólo identidad + conteo de servicios."""

    n_id: int
    nombre: Optional[str]
    cantidad_servicios: int


@dataclass(slots=True)
class ResultadoBotella:
    botella_n_id: int
    nombre: Optional[str]
    clase: Optional[int]  # None si la botella sólo se conoce por referencia colgada (sin fila propia)
    localidad: Optional[str]
    servicios: list[ServicioEncontrado]
    cables: list[CableDeBotella] = field(default_factory=list)
    # Empalmes (fusiones internas de la botella) ya expuestos, pero por un módulo/endpoint propio
    # (`core/services/cromo/empalmes.py`, `GET /api/infra/cromo/botellas/{n_id}/empalmes`) — no acá,
    # porque tienen su propia vista dedicada (`/infra/cromo/verificador?...&n_id=.../empalmes`) en
    # vez de una tarjeta más del detalle de Botella.


@dataclass(slots=True)
class ResultadoOdf:
    """Servicios y cables asociados a un ODF (Tarea 4 del plan ODFs) — mismo espíritu que
    `ResultadoBotella`, pero atravesando `cromo_odfs.cables_asociados` (JSONB de n_ids de cable) en
    vez de `extremo_a_n_id`/`extremo_b_n_id`. Reusa `ServicioEncontrado`/`CableDeBotella` tal cual:
    ambas ya tienen la forma exacta que necesita esta vista ("servicio matcheado" y "cable + cantidad
    de servicios", respectivamente)."""

    odf_n_id: int
    nombre: Optional[str]
    tipo_elemento: str
    localidad: Optional[str]
    servicios: list[ServicioEncontrado]
    cables: list[CableDeBotella] = field(default_factory=list)


@dataclass(slots=True)
class ServicioUnico:
    """Un servicio de `app.servicios` alcanzado por al menos un pelo con match, agregado por
    `s.id` — una fila por SERVICIO, no una por pelo (a diferencia de `ServicioEncontrado`, que es
    una fila por pelo↔match). Producida por `servicios_unicos_por_cable`/`_por_tubo` (Task 1 del
    plan "Corrección ingresos + Servicios", 2026-09-23), consumida por el comando de Slack
    `Servicios <cable>` (Task 8) y por las rutas REST `/servicios-unicos` (Task 10).

    Dataclass propio y no campos nuevos en `ServicioEncontrado`: la semántica es distinta (por-
    servicio vs. por-pelo) y `ServicioEncontrado` está compartido con `detalle.py:156-183`, con
    `_serializar_servicio_encontrado` (5 call-sites) y con la interfaz TS `CromoServicioEncontrado`
    (4 tipos de respuesta) — tocarlo propaga a todo eso sin necesidad.

    `numeros_en_pelo` en plural y no un solo valor: con varios pelos, cada uno puede traer un
    `servicio_numero` distinto (el viejo en uno, el nuevo en otro — el gotcha real de los 85 pares
    `(pelo_n_id, servicio_id)` con dos filas en `cromo_servicio_match`, índice único sobre
    `(pelo_n_id, servicio_numero)`). Quedarse con uno solo sería elegir arbitrariamente.
    """

    servicio_id: int  # PK de app.servicios
    servicio_id_externo: str  # el ID vigente
    numero_primer_servicio: Optional[str]
    nombre_cliente: Optional[str]
    cliente: Optional[str]
    estado_servicio: Optional[str]
    tipo_servicio: Optional[str]
    pelos_n_ids: list[int]  # todos los pelos por los que pasa
    cantidad_pelos: int
    numeros_en_pelo: list[str]  # servicio_numero distintos, para contrastar con el vigente
    metodos: list[str]


@dataclass(slots=True)
class ResultadoServiciosUnicos:
    """Bundle de `ServicioUnico` que devuelven `servicios_unicos_por_cable`/`_por_tubo` (y sus
    gemelas `_sync`) — exactamente uno de `cable_n_id`/`tubo_n_id` queda en `None` según qué eje se
    haya consultado, mismo criterio de "identidad de lo consultado" que ya usan `ResultadoCable`/
    `ResultadoTubo` más arriba en este módulo."""

    cable_n_id: Optional[int]
    tubo_n_id: Optional[int]
    servicios: list[ServicioUnico]


# Columnas de `app.servicios` + `cromo_pelos`/`cromo_servicio_match` comunes a las tres consultas,
# en el mismo orden que espera `_fila_a_servicio` — evita repetir el SELECT completo tres veces.
_COLUMNAS_SERVICIO = """
    s.id, s.servicio_id, s.numero_primer_servicio, s.nombre_cliente, s.cliente,
    s.estado_servicio, s.categoria, s.tipo_servicio, p.n_id, m.servicio_numero, m.metodo
"""

# extremo_a_nombre/extremo_b_nombre vía JOIN a cromo_botellas, no las columnas crudas de cromo_cables
# (at.34/at.37 del payload Cromo) — hallazgo real (Etapa 9c): at.37 nunca existe, Cromo manda ambos
# nombres concatenados en at.34 únicamente. Ver el mismo comentario, más extenso, en inventario.py.
#
# Un extremo puede terminar en una ODF (`app.cromo_odfs`, clase 69) en vez de una Botella — tabla
# separada desde el submódulo ODFs (2026-08-28), posterior a este JOIN. Ver inventario.py para el
# conteo real de cables afectados.
_SQL_CABLE_POR_N_ID = text(
    """
    SELECT c.n_id, c.nombre, c.capacidad,
           COALESCE(ba.nombre, oa.nombre, c.extremo_a_nombre) AS extremo_a_nombre,
           COALESCE(bb.nombre, ob.nombre, c.extremo_b_nombre) AS extremo_b_nombre
    FROM app.cromo_cables c
    LEFT JOIN app.cromo_botellas ba ON ba.n_id = c.extremo_a_n_id
    LEFT JOIN app.cromo_botellas bb ON bb.n_id = c.extremo_b_n_id
    LEFT JOIN app.cromo_odfs oa ON oa.n_id = c.extremo_a_n_id
    LEFT JOIN app.cromo_odfs ob ON ob.n_id = c.extremo_b_n_id
    WHERE c.n_id = :n_id
    """
)

# Un cable/tubo/botella puede tener servicios matcheados aunque su fila propia todavía no se haya
# ingerido — es la misma "referencia colgada" que audita la fase de reconciliación (REF_COLGADA):
# un tubo/pelo puede bajar en una página de la Fase 3 (dentro de una botella) mientras el cable al
# que pertenece todavía no bajó en su propia página de la Fase 2. Confirmado con datos reales: dos
# cables con servicio matcheado en sus pelos, sin fila en `cromo_cables` (ver docs/Doc Privada/
# ingesta_cromo.md §13.3). Por eso el chequeo de "no encontrado" no se apoya sólo en la fila propia.
_SQL_EXISTE_CABLE_POR_PELOS = text("SELECT 1 FROM app.cromo_pelos WHERE cable_n_id = :cable_n_id LIMIT 1")
_SQL_EXISTE_TUBO_POR_PELOS = text("SELECT 1 FROM app.cromo_pelos WHERE tubo_n_id = :tubo_n_id LIMIT 1")
_SQL_EXISTE_BOTELLA_POR_CABLES = text(
    "SELECT 1 FROM app.cromo_cables WHERE extremo_a_n_id = :botella_n_id OR extremo_b_n_id = :botella_n_id LIMIT 1"
)

_SQL_SERVICIOS_POR_CABLE = text(
    f"""
    SELECT DISTINCT {_COLUMNAS_SERVICIO}
    FROM app.cromo_pelos p
    JOIN app.cromo_servicio_match m ON m.pelo_n_id = p.n_id
    JOIN app.servicios s ON s.id = m.servicio_id
    WHERE p.cable_n_id = :cable_n_id
    ORDER BY s.id
    """
)

_SQL_TUBO_POR_N_ID = text(
    "SELECT n_id, cable_n_id, orden, nombre_color FROM app.cromo_tubos WHERE n_id = :n_id"
)

_SQL_SERVICIOS_POR_TUBO = text(
    f"""
    SELECT DISTINCT {_COLUMNAS_SERVICIO}
    FROM app.cromo_pelos p
    JOIN app.cromo_servicio_match m ON m.pelo_n_id = p.n_id
    JOIN app.servicios s ON s.id = m.servicio_id
    WHERE p.tubo_n_id = :tubo_n_id
    ORDER BY s.id
    """
)

# Columnas agregadas por servicio (Task 1, plan "Corrección ingresos + Servicios", 2026-09-23), en
# el mismo orden que espera `_fila_a_servicio_unico`. Subconjunto de `_COLUMNAS_SERVICIO` (sin
# `s.categoria`: `ServicioUnico` no lo pide) más los cuatro `array_agg`/`count` que resuelven "un
# servicio, aunque ocupe varios pelos" en una sola pasada de `GROUP BY s.id`.
#
# `GROUP BY s.id` a secas alcanza: es la PK de `app.servicios` y Postgres resuelve la dependencia
# funcional del resto de las columnas de `s`.
#
# Deliberadamente NO se resuelve con un CTE que haga JOIN de vuelta a `cromo_servicio_match` por un
# pelo representativo: el índice único de esa tabla es `ux_cromo_match_pelo_nro (pelo_n_id,
# servicio_numero)`, no `(pelo_n_id, servicio_id)` — hay pares `(pelo, servicio)` con dos filas,
# porque la descripción del pelo menciona el ID viejo y el nuevo del mismo servicio (85 pares
# medidos real contra `lasfocasdev-postgres`, ej. pelo 6848348 → servicio 26179 vía "108013" y
# "66041"). Un re-join volvería a multiplicar esas filas; el `GROUP BY` de una sola pasada lo evita
# por construcción — por eso `numeros_en_pelo` es `array_agg(DISTINCT m.servicio_numero)` y no un
# escalar.
_COLUMNAS_SERVICIO_UNICO = """
    s.id, s.servicio_id, s.numero_primer_servicio, s.nombre_cliente, s.cliente,
    s.estado_servicio, s.tipo_servicio,
    array_agg(DISTINCT p.n_id ORDER BY p.n_id)  AS pelos_n_ids,
    count(DISTINCT p.n_id)                      AS cantidad_pelos,
    array_agg(DISTINCT m.servicio_numero)       AS numeros_en_pelo,
    array_agg(DISTINCT m.metodo)                AS metodos
"""

_SQL_SERVICIOS_UNICOS_POR_CABLE = text(
    f"""
    SELECT {_COLUMNAS_SERVICIO_UNICO}
    FROM app.cromo_pelos p
    JOIN app.cromo_servicio_match m ON m.pelo_n_id = p.n_id
    JOIN app.servicios s ON s.id = m.servicio_id
    WHERE p.cable_n_id = :cable_n_id
    GROUP BY s.id
    ORDER BY s.id
    """
)

_SQL_SERVICIOS_UNICOS_POR_TUBO = text(
    f"""
    SELECT {_COLUMNAS_SERVICIO_UNICO}
    FROM app.cromo_pelos p
    JOIN app.cromo_servicio_match m ON m.pelo_n_id = p.n_id
    JOIN app.servicios s ON s.id = m.servicio_id
    WHERE p.tubo_n_id = :tubo_n_id
    GROUP BY s.id
    ORDER BY s.id
    """
)

_SQL_BOTELLA_POR_N_ID = text(
    "SELECT n_id, nombre, clase, localidad FROM app.cromo_botellas WHERE n_id = :n_id"
)

# Subselect correlacionado para `cantidad_servicios`, mismo patrón (y misma justificación de
# rendimiento) que `inventario.py::_SQL_BUSCAR`: acá corre sólo sobre los cables de UNA botella
# (siempre pocos), no sobre miles de filas candidatas antes de paginar — un JOIN normal a
# `cromo_pelos`/`cromo_servicio_match` multiplicaría filas por pelo y obligaría a un DISTINCT sobre
# todas las columnas de cable en vez de sólo sobre `servicio_id`.
_SQL_CABLES_DE_BOTELLA = text(
    """
    SELECT c.n_id, c.nombre,
        (
            SELECT count(DISTINCT m.servicio_id)
            FROM app.cromo_pelos p
            JOIN app.cromo_servicio_match m ON m.pelo_n_id = p.n_id
            WHERE p.cable_n_id = c.n_id AND m.servicio_id IS NOT NULL
        ) AS cantidad_servicios
    FROM app.cromo_cables c
    WHERE c.extremo_a_n_id = :botella_n_id OR c.extremo_b_n_id = :botella_n_id
    ORDER BY c.nombre NULLS LAST, c.n_id
    """
)

_SQL_SERVICIOS_POR_BOTELLA = text(
    f"""
    SELECT DISTINCT {_COLUMNAS_SERVICIO}
    FROM app.cromo_cables c
    JOIN app.cromo_pelos p ON p.cable_n_id = c.n_id
    JOIN app.cromo_servicio_match m ON m.pelo_n_id = p.n_id
    JOIN app.servicios s ON s.id = m.servicio_id
    WHERE c.extremo_a_n_id = :botella_n_id OR c.extremo_b_n_id = :botella_n_id
    ORDER BY s.id
    """
)

_SQL_ODF_POR_N_ID = text(
    "SELECT n_id, nombre, tipo_elemento, localidad FROM app.cromo_odfs WHERE n_id = :n_id"
)

# `cables_asociados` puede NO ser un array JSONB. `parser.parse_odf` deja `None` a propósito cuando
# el payload de Cromo no trae `tp` en absoluto (distinto de `[]`, que es "vino `tp` pero ningún item
# era un cable"), y hasta 2026-09-19 la columna serializaba ese `None` de Python como el escalar JSON
# `'null'` — 176 de 7.916 filas reales de dev, exactamente las que no tienen `tp` en `payload_raw`.
#
# `COALESCE(o.cables_asociados, '[]'::jsonb)` NO alcanza como guard: sólo cubre SQL NULL, así que el
# escalar `'null'` pasa entero y `jsonb_array_elements_text` corta la query con
# `InvalidParameterValueError: cannot extract elements from a scalar` (reproducido real contra
# `lasfocasdev-postgres`). El `CASE` sobre `jsonb_typeof` cubre todos los casos de una — SQL NULL
# (`jsonb_typeof` devuelve NULL), el escalar `'null'`, y cualquier número/string/objeto que Cromo
# llegara a mandar — y garantiza que el desenrollado siempre reciba un array.
#
# El origen quedó cortado con `none_as_null=True` en `CromoOdf.cables_asociados` (un `None` nuevo ya
# se guarda como SQL NULL), pero las filas viejas siguen en la tabla: este guard es el que las hace
# inofensivas, y por eso va en los cuatro usos, no sólo en el que disparó el bug.
#
# Alias `o` porque los cuatro usos (dos acá, dos en `odf_inventario.py`) nombran así a
# `app.cromo_odfs`. Se comparte como constante justamente para que no puedan divergir de nuevo.
CABLES_ASOCIADOS_ARRAY_SQL = (
    "CASE WHEN jsonb_typeof(o.cables_asociados) = 'array' THEN o.cables_asociados ELSE '[]'::jsonb END"
)

# `cables_asociados` es JSONB (lista de n_ids de cable, sin FK dura — ver docstring de `CromoOdf`),
# no una columna que se pueda usar directo en un JOIN: se unnest con `jsonb_array_elements_text` en
# un subquery correlacionado al propio ODF. A diferencia de `_SQL_SERVICIOS_POR_BOTELLA`
# (extremo_a_n_id/extremo_b_n_id son columnas normales de `cromo_cables`), acá no hay una columna de
# `cromo_cables`/`cromo_pelos` que apunte "hacia" el ODF — el vínculo vive únicamente en el JSONB del
# ODF, atravesado en sentido ODF → cables_asociados → cable_n_id.
_SQL_SERVICIOS_POR_ODF = text(
    f"""
    SELECT DISTINCT {_COLUMNAS_SERVICIO}
    FROM app.cromo_pelos p
    JOIN app.cromo_servicio_match m ON m.pelo_n_id = p.n_id
    JOIN app.servicios s ON s.id = m.servicio_id
    WHERE p.cable_n_id IN (
        SELECT (jsonb_array_elements_text({CABLES_ASOCIADOS_ARRAY_SQL}))::bigint
        FROM app.cromo_odfs o
        WHERE o.n_id = :odf_n_id
    )
    ORDER BY s.id
    """
)

# Mismo subselect correlacionado para `cantidad_servicios` que `_SQL_CABLES_DE_BOTELLA` — acá corre
# sólo sobre los cables que este ODF referencia en `cables_asociados` (siempre pocos), no sobre todo
# `cromo_cables`.
_SQL_CABLES_DE_ODF = text(
    f"""
    SELECT c.n_id, c.nombre,
        (
            SELECT count(DISTINCT m.servicio_id)
            FROM app.cromo_pelos p
            JOIN app.cromo_servicio_match m ON m.pelo_n_id = p.n_id
            WHERE p.cable_n_id = c.n_id AND m.servicio_id IS NOT NULL
        ) AS cantidad_servicios
    FROM app.cromo_cables c
    WHERE c.n_id IN (
        SELECT (jsonb_array_elements_text({CABLES_ASOCIADOS_ARRAY_SQL}))::bigint
        FROM app.cromo_odfs o
        WHERE o.n_id = :odf_n_id
    )
    ORDER BY c.nombre NULLS LAST, c.n_id
    """
)

# Datos de `app.servicios` para los Servicios alcanzados sólo por override manual (Tarea 4) — batch
# por `id` (la PK, la misma identidad que `CromoServicioOdfOverride.servicio_id`), nunca uno por
# fila: `servicios_por_odf` puede sumar varios en la misma llamada. Subconjunto de columnas de
# `_COLUMNAS_SERVICIO` (sin `p.n_id`/`m.servicio_numero`/`m.metodo`: esos vienen del JOIN a
# `cromo_servicio_match`, que un override no tiene). `::integer[]` con espacio antes del cast —
# gotcha real de este repo con `text()` + psycopg3 (ver docstrings de otras queries `ANY(...)` acá
# mismo, ej. `_SQL_SERVICIO_IDS_POR_CAMARAS`).
_SQL_SERVICIOS_POR_IDS = text(
    """
    SELECT id, servicio_id, numero_primer_servicio, nombre_cliente, cliente,
           estado_servicio, categoria, tipo_servicio
    FROM app.servicios
    WHERE id = ANY(:ids ::integer[])
    """
)

# Versión batcheada de `_SQL_EXISTE_BOTELLA_POR_CABLES` para N n_ids en una sola query — usada por el
# dashboard de duplicados (`AdminBotellasViewer.vue`) para marcar cuál de varias `CromoBotella`
# candidatas de un grupo es la "operativa" (tiene cables reales asociados), sin una query por miembro.
_SQL_TIENE_CABLES_BATCH = text(
    """
    SELECT extremo_a_n_id AS n_id FROM app.cromo_cables WHERE extremo_a_n_id = ANY(:ids ::bigint[])
    UNION
    SELECT extremo_b_n_id AS n_id FROM app.cromo_cables WHERE extremo_b_n_id = ANY(:ids ::bigint[])
    """
)

# Camino inverso de `_SQL_SERVICIOS_POR_BOTELLA` (servicio → botellas Cromo → camara_id, en vez de
# botella → servicios) — usado por `ProtectionService.get_camaras_for_servicio`
# (`core/services/protection_service.py`, Etapa Refactor baneos 2026-08-23) para resolver qué cámaras
# banear cuando la infraestructura de un servicio sólo se conoce por la ingesta de Cromo Red (sin
# trackings legacy cargados) — antes de esto, esos servicios devolvían `[]` y no se podían banear.
# Filtra `b.camara_id IS NOT NULL` porque una `CromoBotella` puede no tener todavía resuelto su
# vínculo a la jerarquía Cámara/Botella (`core/services/cromo/camara_padre_service.py`).
_SQL_CAMARA_IDS_POR_SERVICIO = text(
    """
    SELECT DISTINCT b.camara_id
    FROM app.cromo_servicio_match m
    JOIN app.cromo_pelos p ON p.n_id = m.pelo_n_id
    JOIN app.cromo_cables c ON c.n_id = p.cable_n_id
    JOIN app.cromo_botellas b ON b.n_id = c.extremo_a_n_id OR b.n_id = c.extremo_b_n_id
    WHERE m.servicio_id = :servicio_id AND b.camara_id IS NOT NULL
    """
)

# Inversa de `_SQL_CAMARA_IDS_POR_SERVICIO` (cámaras → servicios) — usada por
# `ProtectionService._camara_tiene_otro_baneo_activo` para cerrar el mismo gap: detectar que otro
# incidente activo protege un servicio cuya infraestructura sólo se conoce por Cromo (sin empalme/ruta
# legacy que conecte ese servicio al grupo de cámaras evaluado).
_SQL_SERVICIO_IDS_POR_CAMARAS = text(
    """
    SELECT DISTINCT s.servicio_id
    FROM app.cromo_botellas b
    JOIN app.cromo_cables c ON c.extremo_a_n_id = b.n_id OR c.extremo_b_n_id = b.n_id
    JOIN app.cromo_pelos p ON p.cable_n_id = c.n_id
    JOIN app.cromo_servicio_match m ON m.pelo_n_id = p.n_id
    JOIN app.servicios s ON s.id = m.servicio_id
    WHERE b.camara_id = ANY(:camara_ids ::integer[])
    """
)


def _fila_a_servicio(fila: tuple) -> ServicioEncontrado:
    (
        servicio_id,
        servicio_id_externo,
        numero_primer_servicio,
        nombre_cliente,
        cliente,
        estado_servicio,
        categoria,
        tipo_servicio,
        pelo_n_id,
        servicio_numero_match,
        metodo,
    ) = fila
    return ServicioEncontrado(
        servicio_id=servicio_id,
        servicio_id_externo=servicio_id_externo,
        numero_primer_servicio=numero_primer_servicio,
        nombre_cliente=nombre_cliente,
        cliente=cliente,
        estado_servicio=estado_servicio,
        categoria=categoria,
        tipo_servicio=tipo_servicio,
        pelo_n_id=pelo_n_id,
        servicio_numero_match=servicio_numero_match,
        metodo=metodo,
    )


def _fila_a_servicio_unico(fila: tuple) -> ServicioUnico:
    (
        servicio_id,
        servicio_id_externo,
        numero_primer_servicio,
        nombre_cliente,
        cliente,
        estado_servicio,
        tipo_servicio,
        pelos_n_ids,
        cantidad_pelos,
        numeros_en_pelo,
        metodos,
    ) = fila
    return ServicioUnico(
        servicio_id=servicio_id,
        servicio_id_externo=servicio_id_externo,
        numero_primer_servicio=numero_primer_servicio,
        nombre_cliente=nombre_cliente,
        cliente=cliente,
        estado_servicio=estado_servicio,
        tipo_servicio=tipo_servicio,
        pelos_n_ids=list(pelos_n_ids),
        cantidad_pelos=cantidad_pelos,
        numeros_en_pelo=list(numeros_en_pelo),
        metodos=list(metodos),
    )


def _fila_a_servicio_desde_override(fila: tuple, pelo_n_id: Optional[int]) -> ServicioEncontrado:
    """Arma un `ServicioEncontrado` a partir de una fila de `_SQL_SERVICIOS_POR_IDS` (columnas
    propias de `app.servicios`, sin pelo/match) + el `pelo_n_id` del override (puede ser `None` — el
    operador asoció "a la ODF en general", sin pinear una posición física).

    `servicio_numero_match`/`metodo` no tienen un equivalente real acá (no hubo regex ni pelo que
    matcheara): se completan con la propia identidad del Servicio y un método explícito
    (`"OVERRIDE_MANUAL"`) en vez de dejarlos vacíos, para que el campo nunca sea un string vacío
    engañoso. `origen="override_manual"` es el campo que de verdad distingue esta fila — ver
    `ServicioEncontrado`.
    """
    (
        servicio_id,
        servicio_id_externo,
        numero_primer_servicio,
        nombre_cliente,
        cliente,
        estado_servicio,
        categoria,
        tipo_servicio,
    ) = fila
    return ServicioEncontrado(
        servicio_id=servicio_id,
        servicio_id_externo=servicio_id_externo,
        numero_primer_servicio=numero_primer_servicio,
        nombre_cliente=nombre_cliente,
        cliente=cliente,
        estado_servicio=estado_servicio,
        categoria=categoria,
        tipo_servicio=tipo_servicio,
        pelo_n_id=pelo_n_id,
        servicio_numero_match=servicio_id_externo,
        metodo="OVERRIDE_MANUAL",
        origen="override_manual",
    )


async def servicios_por_cable(sesion: AsyncSession, cable_n_id: int) -> ResultadoCable:
    """Servicios que pasan por un cable entero (cualquiera de sus tubos/pelos).

    "No encontrado" se decide por si el `cable_n_id` aparece en algún lado (fila propia en
    `cromo_cables` o al menos un pelo que lo referencia) — no sólo por la fila propia, que puede
    faltar por una referencia colgada real (ver `_SQL_EXISTE_CABLE_POR_PELOS`).
    """
    cable = (await sesion.execute(_SQL_CABLE_POR_N_ID, {"n_id": cable_n_id})).first()
    filas = (await sesion.execute(_SQL_SERVICIOS_POR_CABLE, {"cable_n_id": cable_n_id})).all()

    if cable is None and not filas:
        existe = (await sesion.execute(_SQL_EXISTE_CABLE_POR_PELOS, {"cable_n_id": cable_n_id})).first()
        if existe is None:
            raise ObjetoNoEncontrado(f"No existe un cable con n_id={cable_n_id} en el inventario ingerido.")

    return ResultadoCable(
        cable_n_id=cable_n_id,
        nombre=cable[1] if cable else None,
        capacidad=cable[2] if cable else None,
        extremo_a_nombre=cable[3] if cable else None,
        extremo_b_nombre=cable[4] if cable else None,
        servicios=[_fila_a_servicio(f) for f in filas],
    )


async def servicios_por_tubo(sesion: AsyncSession, tubo_n_id: int) -> ResultadoTubo:
    """Servicios que pasan por un tubo/buffer específico dentro de un cable.

    Mismo criterio de "no encontrado" tolerante a referencias colgadas que `servicios_por_cable`.
    """
    tubo = (await sesion.execute(_SQL_TUBO_POR_N_ID, {"n_id": tubo_n_id})).first()
    filas = (await sesion.execute(_SQL_SERVICIOS_POR_TUBO, {"tubo_n_id": tubo_n_id})).all()

    if tubo is None and not filas:
        existe = (await sesion.execute(_SQL_EXISTE_TUBO_POR_PELOS, {"tubo_n_id": tubo_n_id})).first()
        if existe is None:
            raise ObjetoNoEncontrado(f"No existe un tubo con n_id={tubo_n_id} en el inventario ingerido.")

    return ResultadoTubo(
        tubo_n_id=tubo_n_id,
        cable_n_id=tubo[1] if tubo else None,
        orden=tubo[2] if tubo else None,
        nombre_color=tubo[3] if tubo else None,
        servicios=[_fila_a_servicio(f) for f in filas],
    )


def servicios_por_tubo_sync(session: Session, tubo_n_id: int) -> ResultadoTubo:
    """Gemela síncrona de `servicios_por_tubo` — mismas queries (`text()` funciona igual sobre
    `Session` que sobre `AsyncSession`, sólo cambia el `await`), para el comando de Slack
    "Verificar cable <nombre> B<N>" (`modules/slack_baneo_notifier/cable_info.py`), que corre dentro
    de un callback síncrono de Slack Bolt."""
    tubo = session.execute(_SQL_TUBO_POR_N_ID, {"n_id": tubo_n_id}).first()
    filas = session.execute(_SQL_SERVICIOS_POR_TUBO, {"tubo_n_id": tubo_n_id}).all()

    if tubo is None and not filas:
        existe = session.execute(_SQL_EXISTE_TUBO_POR_PELOS, {"tubo_n_id": tubo_n_id}).first()
        if existe is None:
            raise ObjetoNoEncontrado(f"No existe un tubo con n_id={tubo_n_id} en el inventario ingerido.")

    return ResultadoTubo(
        tubo_n_id=tubo_n_id,
        cable_n_id=tubo[1] if tubo else None,
        orden=tubo[2] if tubo else None,
        nombre_color=tubo[3] if tubo else None,
        servicios=[_fila_a_servicio(f) for f in filas],
    )


async def servicios_unicos_por_cable(sesion: AsyncSession, cable_n_id: int) -> ResultadoServiciosUnicos:
    """Servicios únicos que pasan por un cable entero — un `ServicioUnico` por servicio (agregado
    por `s.id`, `GROUP BY` de una sola pasada, ver `_COLUMNAS_SERVICIO_UNICO`), no una fila por
    pelo como `servicios_por_cable` (intacta, sigue sirviendo la tabla del Verificador con su
    columna "Pelo"). Medido real contra `lasfocasdev-postgres`: el cable `FO-FL-1003`
    (n_id=6610203) tiene 141 filas pelo↔servicio para sólo 118 servicios distintos.

    Mismo criterio de "no encontrado" tolerante a referencias colgadas que `servicios_por_cable`
    (`_SQL_EXISTE_CABLE_POR_PELOS`): un cable puede tener pelos con servicio matcheado aunque su
    fila propia todavía no se haya ingerido. A diferencia de `servicios_por_cable`, esta consulta
    no toca `cromo_cables` (no hay metadata de cable que devolver acá), así que "encontrado" se
    reduce a "hubo al menos una fila agregada, o al menos un pelo que lo referencia sin servicio
    matcheado todavía".
    """
    filas = (await sesion.execute(_SQL_SERVICIOS_UNICOS_POR_CABLE, {"cable_n_id": cable_n_id})).all()
    if not filas:
        existe = (await sesion.execute(_SQL_EXISTE_CABLE_POR_PELOS, {"cable_n_id": cable_n_id})).first()
        if existe is None:
            raise ObjetoNoEncontrado(f"No existe un cable con n_id={cable_n_id} en el inventario ingerido.")

    return ResultadoServiciosUnicos(
        cable_n_id=cable_n_id,
        tubo_n_id=None,
        servicios=[_fila_a_servicio_unico(f) for f in filas],
    )


def servicios_unicos_por_cable_sync(session: Session, cable_n_id: int) -> ResultadoServiciosUnicos:
    """Gemela síncrona de `servicios_unicos_por_cable` — mismo patrón que `servicios_por_tubo_sync`
    (misma `text()`, sólo cambia el `await`), para el comando de Slack `Servicios <cable>` (Task 8),
    que corre dentro de un callback síncrono de Slack Bolt."""
    filas = session.execute(_SQL_SERVICIOS_UNICOS_POR_CABLE, {"cable_n_id": cable_n_id}).all()
    if not filas:
        existe = session.execute(_SQL_EXISTE_CABLE_POR_PELOS, {"cable_n_id": cable_n_id}).first()
        if existe is None:
            raise ObjetoNoEncontrado(f"No existe un cable con n_id={cable_n_id} en el inventario ingerido.")

    return ResultadoServiciosUnicos(
        cable_n_id=cable_n_id,
        tubo_n_id=None,
        servicios=[_fila_a_servicio_unico(f) for f in filas],
    )


async def servicios_unicos_por_tubo(sesion: AsyncSession, tubo_n_id: int) -> ResultadoServiciosUnicos:
    """Servicios únicos que pasan por un tubo/buffer específico — mismo espíritu que
    `servicios_unicos_por_cable`, acotado a `p.tubo_n_id` en vez de `p.cable_n_id` (mismo eje que
    distingue `servicios_por_tubo` de `servicios_por_cable`). Mismo criterio de "no encontrado"
    tolerante a referencias colgadas (`_SQL_EXISTE_TUBO_POR_PELOS`)."""
    filas = (await sesion.execute(_SQL_SERVICIOS_UNICOS_POR_TUBO, {"tubo_n_id": tubo_n_id})).all()
    if not filas:
        existe = (await sesion.execute(_SQL_EXISTE_TUBO_POR_PELOS, {"tubo_n_id": tubo_n_id})).first()
        if existe is None:
            raise ObjetoNoEncontrado(f"No existe un tubo con n_id={tubo_n_id} en el inventario ingerido.")

    return ResultadoServiciosUnicos(
        cable_n_id=None,
        tubo_n_id=tubo_n_id,
        servicios=[_fila_a_servicio_unico(f) for f in filas],
    )


def servicios_unicos_por_tubo_sync(session: Session, tubo_n_id: int) -> ResultadoServiciosUnicos:
    """Gemela síncrona de `servicios_unicos_por_tubo` — mismo patrón que `servicios_por_tubo_sync`,
    para el comando de Slack `Servicios <cable> B<N>` (Task 8)."""
    filas = session.execute(_SQL_SERVICIOS_UNICOS_POR_TUBO, {"tubo_n_id": tubo_n_id}).all()
    if not filas:
        existe = session.execute(_SQL_EXISTE_TUBO_POR_PELOS, {"tubo_n_id": tubo_n_id}).first()
        if existe is None:
            raise ObjetoNoEncontrado(f"No existe un tubo con n_id={tubo_n_id} en el inventario ingerido.")

    return ResultadoServiciosUnicos(
        cable_n_id=None,
        tubo_n_id=tubo_n_id,
        servicios=[_fila_a_servicio_unico(f) for f in filas],
    )


async def servicios_por_botella(sesion: AsyncSession, botella_n_id: int) -> ResultadoBotella:
    """Servicios que pasan por los cables que tienen esta botella como uno de sus extremos.

    No sigue fusiones dentro de la botella (capítulo 8.2 del diseño lo deja para un "impacto de tocar
    una botella" más amplio, fuera de esta etapa) — sólo resuelve la pregunta literal "qué servicios
    pasan por esta botella" vía los cables que la usan como extremo A o B. Mismo criterio de "no
    encontrado" tolerante a referencias colgadas que `servicios_por_cable`.
    """
    botella = (await sesion.execute(_SQL_BOTELLA_POR_N_ID, {"n_id": botella_n_id})).first()
    filas = (await sesion.execute(_SQL_SERVICIOS_POR_BOTELLA, {"botella_n_id": botella_n_id})).all()

    if botella is None and not filas:
        existe = (await sesion.execute(_SQL_EXISTE_BOTELLA_POR_CABLES, {"botella_n_id": botella_n_id})).first()
        if existe is None:
            raise ObjetoNoEncontrado(f"No existe una botella con n_id={botella_n_id} en el inventario ingerido.")

    filas_cables = (await sesion.execute(_SQL_CABLES_DE_BOTELLA, {"botella_n_id": botella_n_id})).all()

    return ResultadoBotella(
        botella_n_id=botella_n_id,
        nombre=botella[1] if botella else None,
        clase=botella[2] if botella else None,
        localidad=botella[3] if botella else None,
        servicios=[_fila_a_servicio(f) for f in filas],
        cables=[CableDeBotella(n_id=f[0], nombre=f[1], cantidad_servicios=f[2]) for f in filas_cables],
    )


async def servicios_por_odf(sesion: AsyncSession, odf_n_id: int) -> ResultadoOdf:
    """Servicios que pasan por los cables que este ODF referencia en `cables_asociados`, más el
    listado de esos cables (id, nombre, cantidad de servicios) — mismo formato de tarjeta "Cables
    asociados" que ya expone `servicios_por_botella`.

    A diferencia de `servicios_por_cable/tubo/botella`, no hay tolerancia a "referencia colgada": un
    ODF sólo existe si tiene fila propia en `cromo_odfs` (nada más lo referencia como parent). Si no
    hay fila, levanta `ObjetoNoEncontrado`.

    Es un estado degradado esperado, no un error, que `servicios`/`cables` vuelvan vacíos mientras el
    volumen real de `cables_asociados` poblado sea bajo (ver brief de la Tarea 4 del plan ODFs,
    2026-08-28 — plan distinto del que agrega los overrides, ver el párrafo siguiente).

    Desde la Tarea 4 del gestor "Servicios sin ODF" (2026-09-09), además suma los Servicios con una
    asociación manual VIGENTE a esta ODF (`app.cromo_servicio_odf_override`, ver
    `servicio_odf_override_service.py`) que el matching automático de arriba no haya encontrado —
    cada uno de esos con `ServicioEncontrado.origen="override_manual"` (las filas de matching
    automático quedan con el default `"automatico"`, sin cambios de comportamiento para ellas). Un
    Servicio con override Y match automático a esta MISMA ODF no se duplica: gana la fila
    automática (trae `pelo_n_id`/`servicio_numero_match`/`metodo` reales de la resolución por
    texto; el override sólo confirma la misma conclusión a la que ya había llegado el matching) y el
    override se descarta en silencio para ese Servicio puntual — no es un error, es el caso
    esperado de "el operador confirmó algo que el detector ya había resuelto solo".
    """
    odf = (await sesion.execute(_SQL_ODF_POR_N_ID, {"n_id": odf_n_id})).first()
    if odf is None:
        raise ObjetoNoEncontrado(f"No existe un ODF con n_id={odf_n_id} en el inventario ingerido.")

    filas_servicios = (await sesion.execute(_SQL_SERVICIOS_POR_ODF, {"odf_n_id": odf_n_id})).all()
    filas_cables = (await sesion.execute(_SQL_CABLES_DE_ODF, {"odf_n_id": odf_n_id})).all()

    servicios = [_fila_a_servicio(f) for f in filas_servicios]

    # Import diferido (no a nivel de módulo) a propósito: `servicio_odf_override_service` importa
    # `ObjetoNoEncontrado` DE ESTE módulo a nivel de módulo (mismo criterio que ya usa
    # `odf_conectores.py` para "no encontrado"). Si acá arriba se importara
    # `servicio_odf_override_service` a nivel de módulo también, cualquiera de los dos que se
    # importe primero fallaría con un ciclo (`ImportError: cannot import name ... from partially
    # initialized module`). Se resuelve difiriendo UNO de los dos lados nada más — este, porque
    # `verificador.py` es el módulo más "de base" del paquete (varios otros ya le importan
    # `ObjetoNoEncontrado` a nivel de módulo) y no conviene invertir esa dirección.
    from core.services.cromo.servicio_odf_override_service import overrides_vigentes_por_odf

    overrides = await overrides_vigentes_por_odf(sesion, odf_n_id)
    ids_automaticos = {s.servicio_id for s in servicios}
    ids_override_nuevos = [o.servicio_id for o in overrides if o.servicio_id not in ids_automaticos]
    if ids_override_nuevos:
        filas_override_servicio = (
            await sesion.execute(_SQL_SERVICIOS_POR_IDS, {"ids": ids_override_nuevos})
        ).all()
        pelo_por_servicio = {o.servicio_id: o.pelo_n_id for o in overrides}
        servicios.extend(
            _fila_a_servicio_desde_override(fila, pelo_por_servicio.get(fila.id))
            for fila in filas_override_servicio
        )
        # Mismo orden (`ORDER BY s.id`) que ya tenía la lista puramente automática — re-ordenar sólo
        # cuando de verdad se agregó algo, para no tocar el resultado en el caso (hoy mayoritario)
        # sin overrides.
        servicios.sort(key=lambda s: s.servicio_id)

    return ResultadoOdf(
        odf_n_id=odf_n_id,
        nombre=odf[1],
        tipo_elemento=odf[2],
        localidad=odf[3],
        servicios=servicios,
        cables=[CableDeBotella(n_id=f[0], nombre=f[1], cantidad_servicios=f[2]) for f in filas_cables],
    )


def tiene_cables_asociados_batch_sync(session: Session, n_ids: list[int]) -> set[int]:
    """Gemela síncrona BATCHEADA de `_SQL_EXISTE_BOTELLA_POR_CABLES` — una sola query para N n_ids en
    vez de una por objeto (mismo espíritu que `servicios_por_tubo_sync`, adaptado a lote). Sólo tiene
    sentido para Cromo: `extremo_a_n_id`/`extremo_b_n_id` no existen del lado de la jerarquía legado.
    Devuelve el subconjunto de `n_ids` que aparece como extremo de al menos un cable."""
    if not n_ids:
        return set()
    filas = session.execute(_SQL_TIENE_CABLES_BATCH, {"ids": n_ids}).all()
    return {f[0] for f in filas}


def camara_ids_por_servicio_sync(session: Session, servicio_id: int) -> set[int]:
    """Cámaras (`Camara.id`, vía `CromoBotella.camara_id`) que son extremo de algún cable por el que
    pasa `servicio_id` (el PK integer de `app.servicios`, NO el `servicio_id` string) — join inverso
    de `_SQL_SERVICIOS_POR_BOTELLA`.

    Alimenta `ProtectionService.get_camaras_for_servicio`: cierra el gap real de servicios cuya
    infraestructura sólo se conoce por Cromo Red, que antes de esto devolvían `[]` (no baneables) por
    depender únicamente del camino legacy `Servicio→RutaServicio→Empalme.camara_id→Camara`.
    """
    filas = session.execute(_SQL_CAMARA_IDS_POR_SERVICIO, {"servicio_id": servicio_id}).all()
    return {f[0] for f in filas}


def servicio_ids_por_camaras_sync(session: Session, camara_ids: list[int]) -> set[str]:
    """Inversa de `camara_ids_por_servicio_sync`: servicios (`servicio_id` string, de
    `app.servicios.servicio_id`) que tocan alguna `CromoBotella` cuyo `camara_id` esté en
    `camara_ids` (PKs de `app.camaras`).

    Alimenta `ProtectionService._camara_tiene_otro_baneo_activo`, por el mismo motivo: detectar que
    otro incidente activo protege un servicio cuyo único vínculo al grupo de cámaras evaluado es vía
    Cromo, no vía empalme/ruta legacy — sin esto, `lift_ban` podía restaurar de más una cámara que en
    realidad seguía protegida.
    """
    if not camara_ids:
        return set()
    filas = session.execute(_SQL_SERVICIO_IDS_POR_CAMARAS, {"camara_ids": camara_ids}).all()
    return {f[0] for f in filas}


__all__ = [
    "ObjetoNoEncontrado",
    "ServicioEncontrado",
    "ResultadoCable",
    "ResultadoTubo",
    "CableDeBotella",
    "ResultadoBotella",
    "ResultadoOdf",
    "ServicioUnico",
    "ResultadoServiciosUnicos",
    "servicios_por_cable",
    "servicios_por_tubo",
    "servicios_por_tubo_sync",
    "servicios_por_botella",
    "servicios_por_odf",
    "servicios_unicos_por_cable",
    "servicios_unicos_por_cable_sync",
    "servicios_unicos_por_tubo",
    "servicios_unicos_por_tubo_sync",
    "tiene_cables_asociados_batch_sync",
    "camara_ids_por_servicio_sync",
    "servicio_ids_por_camaras_sync",
]
