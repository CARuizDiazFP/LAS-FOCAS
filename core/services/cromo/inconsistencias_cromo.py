# Nombre de archivo: inconsistencias_cromo.py
# Ubicación de archivo: core/services/cromo/inconsistencias_cromo.py
# Descripción: Detector de inconsistencias del inventario de Cromo (fusiones isla, cables sin
# extremo, elementos isla), clasificación AUTO/MANUAL, upsert de casos y corrida sintética

"""Detector de inconsistencias del inventario de Cromo ya ingerido (`app.cromo_*`).

Tres tipos de caso, un caso por `(tipo, objeto_n_id)` en `app.cromo_inconsistencia`:

- `ISLA_FUSION` (objeto = fusión 132): ninguno de sus dos pelos tiene otra unión, y al menos uno
  está en uso. Uniones de un pelo = fusiones vigentes (`pelo_a`/`pelo_b`) + conectores de ODF
  vigentes (`cromo_odf_conectores.pelo_n_id`, incluidos los que llegan por una fusión de ODF 141).
- `CABLE_SIN_EXTREMO` (objeto = cable 51/52/59/60 vigente): algún extremo NULL y pelos en uso.
- `ELEMENTO_ISLA` (objeto = botella u ODF/ODF Nodo vigente): todos sus cables incidentes terminan
  sin otro extremo, con pelos en uso.

"En uso" = el pelo tiene fila en `cromo_servicio_match` (medido 2026-10-17: superconjunto estricto
de `servicio_numero IS NOT NULL` — suma los servicios de at.62 de `/inner` y del atributo del
conector, que también son servicios reales; ver el informe de la Tarea 2).

**Revisión.** Sólo la isla pura es `AUTO` y entra directo en `CUARENTENA`: una `ISLA_FUSION` dentro
de una botella (no ODF/ODF Nodo), con cada cable llegando a esa botella por un extremo y con el
otro NULL, y con eso confirmado contra Cromo en vivo (la versión vigente del cable tiene un solo
extremo en `tp`). Todo lo demás —cualquier ODF/ODF Nodo, cualquier ambigüedad, Cromo caído, tope de
confirmaciones agotado— es `MANUAL` y entra en `PENDIENTE` (falla cerrada).

**Costo.** El detector es SQL agrupado sobre dos tablas temporales indexadas y analizadas (uniones
por pelo, pelos en uso). Con CTEs el planner estimaba 1 fila para `HAVING count(*) = 1` y elegía
nested loops: la misma consulta no terminó en 2 minutos sobre dev. Con temporales tarda ~5 s
(medido 2026-10-17, ver el informe). Las confirmaciones en vivo son una o dos llamadas por cable
candidato, con tope `CROMO_INCONSISTENCIAS_MAX_CONFIRMACIONES` (default 300) y reutilización de la
confirmación previa si la versión local del cable no cambió y tiene menos de 7 días.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Iterable, Mapping, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.cromo import ingesta
from core.services.cromo.client import CromoClient, CromoClientError
from core.services.cromo.inconsistencias_reporte import avisar_casos_nuevos
from core.services.cromo.servicios_sin_odf import IDENTIDADES_DEL_SERVICIO_SQL
from db.models.cromo import CromoIngestaCorrida

logger = logging.getLogger(__name__)

TIPO_ISLA_FUSION = "ISLA_FUSION"
TIPO_CABLE_SIN_EXTREMO = "CABLE_SIN_EXTREMO"
TIPO_ELEMENTO_ISLA = "ELEMENTO_ISLA"
TIPOS: tuple[str, ...] = (TIPO_ISLA_FUSION, TIPO_CABLE_SIN_EXTREMO, TIPO_ELEMENTO_ISLA)

REVISION_AUTO = "AUTO"
REVISION_MANUAL = "MANUAL"
REVISIONES: tuple[str, ...] = (REVISION_AUTO, REVISION_MANUAL)

ESTADO_PENDIENTE = "PENDIENTE"
ESTADO_CUARENTENA = "CUARENTENA"
ESTADO_REPORTADA = "REPORTADA"
ESTADO_CORREGIDA = "CORREGIDA"
ESTADO_ACEPTADA = "ACEPTADA"
ESTADOS: tuple[str, ...] = (
    ESTADO_PENDIENTE,
    ESTADO_CUARENTENA,
    ESTADO_REPORTADA,
    ESTADO_CORREGIDA,
    ESTADO_ACEPTADA,
)
# Estados a los que una persona puede mover un caso (CORREGIDA la pone sólo el detector).
ESTADOS_DESTINO_MANUAL: frozenset[str] = frozenset(
    {ESTADO_CUARENTENA, ESTADO_ACEPTADA, ESTADO_REPORTADA, ESTADO_PENDIENTE}
)
# Estados que el detector nunca cambia al re-detectar (decisión humana).
_ESTADOS_PROTEGIDOS: frozenset[str] = frozenset({ESTADO_ACEPTADA, ESTADO_REPORTADA})

TIPO_CORRIDA_INCONSISTENCIAS = "INCONSISTENCIAS_CROMO"
# Modos de ingesta que dejan el inventario en un estado sobre el que vale la pena re-detectar.
MODOS_POST_INGESTA: frozenset[str] = frozenset({"COMPLETA", "SOLO_ODF", "SOLO_PELOS_INNER"})
USUARIO_DETECTOR = "detector-inconsistencias"

CLASE_FUSION = ingesta.CLASE_FUSION
CLASES_CABLE_DETECCION: tuple[int, ...] = (ingesta.CLASE_CABLE, *ingesta.CLASES_CABLE_TERCEROS)
CLASES_BOTELLA: frozenset[int] = frozenset(ingesta.CLASES_BOTELLA)
CLASES_ODF: frozenset[int] = frozenset(ingesta.CLASES_ODF)

MAX_CONFIRMACIONES_DEFAULT = 300
TTL_CONFIRMACION = timedelta(days=7)
_CONCURRENCIA_CONFIRMACION = 4
# Cromo caído no es un error por cable: tras estos fallos seguidos no se pide nada más.
_MAX_FALLOS_CROMO_SEGUIDOS = 3
_MAX_SERVICIOS_EVIDENCIA = 20


def max_confirmaciones_configurado() -> int:
    """`CROMO_INCONSISTENCIAS_MAX_CONFIRMACIONES` (default 300). Inválido o < 0 cae al default;
    0 es válido y significa "sin llamadas a Cromo" (todo queda MANUAL)."""
    crudo = os.getenv("CROMO_INCONSISTENCIAS_MAX_CONFIRMACIONES")
    if crudo is None or crudo.strip() == "":
        return MAX_CONFIRMACIONES_DEFAULT
    try:
        valor = int(crudo)
    except ValueError:
        valor = -1
    if valor < 0:
        logger.warning(
            "action=cromo_inconsistencias evento=config_invalida "
            "CROMO_INCONSISTENCIAS_MAX_CONFIRMACIONES=%r",
            crudo,
        )
        return MAX_CONFIRMACIONES_DEFAULT
    return valor


# ── Modelo de datos del detector ─────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CableLocal:
    """Un cable tal como lo tiene la base local, con sus extremos y si alguno es ODF/ODF Nodo."""

    n_id: int
    nombre: Optional[str]
    clase: Optional[int]
    version_id: Optional[int]
    extremo_a_n_id: Optional[int]
    extremo_a_clase: Optional[int]
    extremo_b_n_id: Optional[int]
    extremo_b_clase: Optional[int]
    extremo_a_es_odf: bool = False
    extremo_b_es_odf: bool = False

    def a_dict(self) -> dict[str, Any]:
        return {
            "n_id": self.n_id,
            "nombre": self.nombre,
            "clase": self.clase,
            "version_id": self.version_id,
            "extremo_a": self.extremo_a_n_id,
            "extremo_a_clase": self.extremo_a_clase,
            "extremo_b": self.extremo_b_n_id,
            "extremo_b_clase": self.extremo_b_clase,
        }


@dataclass(frozen=True, slots=True)
class FilaIslaFusion:
    """Una fusión isla con uno o dos pelos en uso, y todo lo necesario para clasificarla."""

    fusion_n_id: int
    nombre_par: Optional[str]
    contenedor_n_id: Optional[int]
    contenedor_clase: Optional[int]  # None si el contenedor no está en botellas ni ODFs
    contenedor_nombre: Optional[str]
    contenedor_es_odf: bool
    localidad: Optional[str]
    pelo_a_n_id: int
    pelo_b_n_id: int
    uso_a: bool
    uso_b: bool
    cable_a: Optional[CableLocal]
    cable_b: Optional[CableLocal]
    servicios: tuple[str, ...] = ()
    # Versión vigente local del contenedor: Cromo publica el extremo del cable (`tp[].id_to`) con el
    # id de versión de la botella, no con el n_id de linaje que guarda la base local.
    contenedor_version_id: Optional[int] = None

    def ids_contenedor(self) -> frozenset[int]:
        return frozenset(i for i in (self.contenedor_n_id, self.contenedor_version_id) if i is not None)

    def cables(self) -> list[Optional[CableLocal]]:
        """Los cables distintos de la fusión (uno solo si los dos pelos son del mismo cable)."""
        if self.cable_a is not None and self.cable_b is not None and self.cable_a.n_id == self.cable_b.n_id:
            return [self.cable_a]
        return [self.cable_a, self.cable_b]

    def pelos_en_uso(self) -> tuple[int, ...]:
        salida = []
        if self.uso_a:
            salida.append(self.pelo_a_n_id)
        if self.uso_b and self.pelo_b_n_id not in salida:
            salida.append(self.pelo_b_n_id)
        return tuple(salida)


@dataclass(frozen=True, slots=True)
class ConfirmacionVivo:
    """Lo que dijo Cromo en vivo de un cable: cuántos extremos tiene su versión vigente."""

    cable_n_id: int
    version_local: Optional[int]
    version_vigente: Optional[int]
    extremos: int
    ids_extremos: tuple[int, ...]
    borrado: bool
    confirmado_at: str
    llamadas: int = 0
    reutilizada: bool = False

    @property
    def un_solo_extremo(self) -> bool:
        return not self.borrado and self.extremos == 1

    def a_dict(self) -> dict[str, Any]:
        return {
            "cable_n_id": self.cable_n_id,
            "version_local": self.version_local,
            "version_vigente": self.version_vigente,
            "extremos": self.extremos,
            "ids_extremos": list(self.ids_extremos),
            "borrado": self.borrado,
            "confirmado_at": self.confirmado_at,
        }

    @classmethod
    def desde_dict(cls, datos: Mapping[str, Any]) -> Optional["ConfirmacionVivo"]:
        try:
            return cls(
                cable_n_id=int(datos["cable_n_id"]),
                version_local=datos.get("version_local"),
                version_vigente=datos.get("version_vigente"),
                extremos=int(datos["extremos"]),
                ids_extremos=tuple(int(x) for x in datos.get("ids_extremos") or ()),
                borrado=bool(datos.get("borrado")),
                confirmado_at=str(datos["confirmado_at"]),
                reutilizada=True,
            )
        except (KeyError, TypeError, ValueError):
            return None


@dataclass(slots=True)
class Caso:
    """Un caso detectado, listo para el upsert."""

    tipo: str
    objeto_n_id: int
    objeto_clase: Optional[int]
    nombre: Optional[str]
    localidad: Optional[str]
    revision: str
    evidencia: dict[str, Any]
    pelos: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class EstadoExistente:
    """Lo que el upsert necesita saber de un caso que ya estaba en la tabla."""

    id: int
    estado: str
    revision: str
    actualizado_por: Optional[str]


@dataclass(slots=True)
class ResumenConfirmaciones:
    candidatos: int = 0
    llamadas: int = 0
    confirmados: int = 0
    reutilizados: int = 0
    errores: int = 0
    omitidos_por_tope: int = 0
    sin_cliente: int = 0

    def a_dict(self) -> dict[str, int]:
        return {
            "cables_candidatos": self.candidatos,
            "llamadas": self.llamadas,
            "confirmados": self.confirmados,
            "reutilizados": self.reutilizados,
            "errores": self.errores,
            "omitidos_por_tope": self.omitidos_por_tope,
            "sin_cliente": self.sin_cliente,
        }


@dataclass(slots=True)
class ResumenAplicacion:
    nuevos: int = 0
    actualizados: int = 0
    reabiertos: int = 0
    cerrados: int = 0
    por_estado: dict[str, int] = field(default_factory=dict)
    # Casos creados en esta corrida y cuántos de ellos entraron directo en CUARENTENA (para el aviso).
    nuevos_claves: list[tuple[str, int]] = field(default_factory=list)
    cuarentena_auto: int = 0
    # Casos que ya había antes de esta corrida (0 = primera detección: todo sale como "nuevo").
    casos_previos: int = 0


@dataclass(slots=True)
class ResumenDeteccion:
    """Lo que devuelve `detectar`. `casos` sólo para inspección (scripts de medición)."""

    por_tipo_revision: dict[str, dict[str, int]]
    total: int
    confirmaciones: ResumenConfirmaciones
    aplicado: bool
    nuevos: int = 0
    actualizados: int = 0
    reabiertos: int = 0
    cerrados: int = 0
    por_estado: dict[str, int] = field(default_factory=dict)
    duracion_ms: int = 0
    duracion_sql_ms: int = 0
    casos: list[Caso] = field(default_factory=list, repr=False)
    nuevos_claves: list[tuple[str, int]] = field(default_factory=list, repr=False)
    cuarentena_auto: int = 0
    casos_previos: int = 0

    def a_dict(self) -> dict[str, Any]:
        return {
            "por_tipo_revision": self.por_tipo_revision,
            "total": self.total,
            "aplicado": self.aplicado,
            "nuevos": self.nuevos,
            "actualizados": self.actualizados,
            "reabiertos": self.reabiertos,
            "cerrados": self.cerrados,
            "por_estado": self.por_estado,
            "confirmaciones": self.confirmaciones.a_dict(),
            "duracion_ms": self.duracion_ms,
            "duracion_sql_ms": self.duracion_sql_ms,
        }


# ── Reglas puras ─────────────────────────────────────────────────────────────


def estado_inicial(revision: str) -> str:
    """AUTO entra en cuarentena; MANUAL espera revisión."""
    return ESTADO_CUARENTENA if revision == REVISION_AUTO else ESTADO_PENDIENTE


def _cable_toca_odf(cable: CableLocal) -> bool:
    return (
        cable.extremo_a_es_odf
        or cable.extremo_b_es_odf
        or (cable.extremo_a_clase in CLASES_ODF)
        or (cable.extremo_b_clase in CLASES_ODF)
    )


def motivo_no_candidato_auto(fila: FilaIslaFusion) -> Optional[str]:
    """`None` si la fusión es candidata a isla pura (falta sólo la confirmación en vivo); si no,
    el motivo por el que queda MANUAL."""
    if fila.contenedor_es_odf or fila.contenedor_clase in CLASES_ODF:
        return "contenedor_odf"
    if fila.contenedor_clase not in CLASES_BOTELLA:
        return "contenedor_no_botella"
    for cable in fila.cables():
        if cable is None:
            return "cable_inexistente"
        if _cable_toca_odf(cable):
            return "cable_con_extremo_odf"
        extremos = (cable.extremo_a_n_id, cable.extremo_b_n_id)
        if fila.contenedor_n_id not in extremos:
            return "cable_no_llega_al_contenedor"
        if extremos.count(None) != 1:
            # Los dos en el contenedor (cable en lazo) o los dos con valor: no es una isla pura.
            return "cable_con_otro_extremo"
    return None


def clasificar_isla_fusion(
    fila: FilaIslaFusion, confirmaciones: Mapping[int, ConfirmacionVivo]
) -> tuple[str, str]:
    """`(revision, motivo)`. AUTO sólo si, para cada cable, Cromo en vivo confirma:

    - que la versión vigente es la misma que tiene la base local (`version_local_desactualizada`
      si no: la regla local se evaluó sobre datos viejos);
    - que no está borrado y tiene un solo extremo (`cromo_vivo_con_otro_extremo`,
      `cable_borrado_en_cromo`);
    - que ese único extremo ES el contenedor de la fusión, por n_id o id de versión
      (`extremo_vivo_distinto`: podría ser hoy un ODF/ODF Nodo).

    Vale igual para una confirmación reutilizada. Cualquier falta deja el caso MANUAL (falla
    cerrada)."""
    motivo = motivo_no_candidato_auto(fila)
    if motivo is not None:
        return REVISION_MANUAL, motivo
    for cable in fila.cables():
        assert cable is not None  # garantizado por motivo_no_candidato_auto
        confirmacion = confirmaciones.get(cable.n_id)
        if confirmacion is None:
            return REVISION_MANUAL, "sin_confirmacion_en_vivo"
        if confirmacion.borrado:
            return REVISION_MANUAL, "cable_borrado_en_cromo"
        if (
            confirmacion.version_vigente is None
            or confirmacion.version_vigente != cable.version_id
        ):
            return REVISION_MANUAL, "version_local_desactualizada"
        if not confirmacion.un_solo_extremo:
            return REVISION_MANUAL, "cromo_vivo_con_otro_extremo"
        # `ids_extremos` puede venir vacío aunque `extremos == 1` (evidencia guardada corrupta o
        # reutilizada de una corrida vieja): sin el id no hay cómo confirmar el contenedor, falla
        # cerrada a MANUAL en vez de tirar IndexError y voltear toda la detección.
        if not confirmacion.ids_extremos or confirmacion.ids_extremos[0] not in fila.ids_contenedor():
            return REVISION_MANUAL, "extremo_vivo_distinto"
    return REVISION_AUTO, "isla_pura_confirmada"


def decidir_estado(existente: Optional[EstadoExistente], revision: str) -> tuple[str, bool]:
    """`(estado, reabierto)` de un caso detectado en esta corrida.

    - Nuevo: el estado inicial de su revisión.
    - ACEPTADA / REPORTADA: no se tocan nunca (decisión humana).
    - CORREGIDA que vuelve a aparecer: se reabre con el estado inicial de su revisión.
    - CUARENTENA automática (la puso el detector) que pasó a MANUAL —dejó de confirmarse como isla
      pura—: se levanta a PENDIENTE (falla cerrada).
    - PENDIENTE que pasó a AUTO: entra en CUARENTENA.
    En los dos últimos casos, si el estado lo puso una persona, se respeta.
    """
    if existente is None:
        return estado_inicial(revision), False
    actual = existente.estado
    if actual in _ESTADOS_PROTEGIDOS:
        return actual, False
    if actual == ESTADO_CORREGIDA:
        return estado_inicial(revision), True
    lo_puso_el_detector = existente.actualizado_por in (None, USUARIO_DETECTOR)
    if actual == ESTADO_CUARENTENA and revision == REVISION_MANUAL and lo_puso_el_detector:
        return ESTADO_PENDIENTE, False
    if (
        actual == ESTADO_PENDIENTE
        and revision == REVISION_AUTO
        and existente.revision == REVISION_MANUAL
        and lo_puso_el_detector
    ):
        return ESTADO_CUARENTENA, False
    return actual, False


def motivo_rechazo_transicion(actual: str, destino: str) -> Optional[str]:
    """`None` si una persona puede mover un caso de `actual` a `destino`; si no, el motivo."""
    if destino not in ESTADOS_DESTINO_MANUAL:
        return f"estado destino no permitido: {destino}"
    if actual == ESTADO_CORREGIDA:
        return "el caso ya no se detecta (CORREGIDA)"
    if actual == destino:
        return f"el caso ya está en {destino}"
    return None


def interpretar_cable_vivo(objeto: Mapping[str, Any]) -> tuple[bool, Optional[int], tuple[int, ...]]:
    """`(borrado, id_version_vigente, ids_extremos)` de la respuesta (desenvuelta) de
    `GET /db/objects/{id}`. Los extremos salen de `tp` como en `parser.parse_cable` (nfrom 0/1);
    sólo valen si la respuesta ES la versión vigente (`id_version_vigente == objeto["id"]`)."""
    hist = objeto.get("hist") or []
    ultima = next((h for h in hist if not h.get("next_id")), None)
    if ultima is not None:
        borrado = bool(ultima.get("to") or 0)
        vigente = ultima.get("id")
    else:
        borrado = bool(objeto.get("to") or 0)
        vigente = objeto.get("id")
    extremos: list[int] = []
    vistos: set[int] = set()
    for item in objeto.get("tp") or []:
        lado = item.get("nfrom")
        if lado in (0, 1) and lado not in vistos and item.get("id_to") is not None:
            vistos.add(lado)
            extremos.append(int(item["id_to"]))
    return borrado, vigente, tuple(extremos)


# ── Confirmación en vivo ─────────────────────────────────────────────────────


async def confirmar_cable_en_vivo(
    cliente: CromoClient, cable: CableLocal, *, ahora: datetime
) -> ConfirmacionVivo:
    """Una llamada (dos si la versión local quedó vieja) a `GET /db/objects/{id}`. Levanta
    `CromoClientError` si Cromo falla: el llamador decide (falla cerrada).

    Si la versión local quedó vieja, sigue a la vigente sólo para dejar evidencia de lo que hay hoy:
    `clasificar_isla_fusion` no acepta una confirmación cuya `version_vigente` difiera de la local."""
    pedido = cable.version_id or cable.n_id
    objeto = (await cliente.get_objeto(pedido)).get("response") or {}
    llamadas = 1
    borrado, vigente, extremos = interpretar_cable_vivo(objeto)
    if not borrado and vigente is not None and vigente != objeto.get("id"):
        objeto = (await cliente.get_objeto(vigente)).get("response") or {}
        llamadas += 1
        borrado, vigente, extremos = interpretar_cable_vivo(objeto)
    return ConfirmacionVivo(
        cable_n_id=cable.n_id,
        version_local=cable.version_id,
        version_vigente=vigente,
        extremos=len(extremos),
        ids_extremos=extremos,
        borrado=borrado,
        confirmado_at=ahora.isoformat(),
        llamadas=llamadas,
    )


def _previa_vigente(
    previa: Optional[ConfirmacionVivo], cable: CableLocal, ahora: datetime
) -> bool:
    """Una confirmación guardada se reutiliza sólo si se pidió sobre la misma versión local, si Cromo
    dijo entonces que esa versión era la vigente y si tiene menos de `TTL_CONFIRMACION`. Si no, se
    vuelve a preguntar. Igual pasa después por las mismas reglas de `clasificar_isla_fusion`."""
    if (
        previa is None
        or previa.version_local != cable.version_id
        or previa.version_vigente != cable.version_id
    ):
        return False
    try:
        cuando = datetime.fromisoformat(previa.confirmado_at)
    except ValueError:
        return False
    if cuando.tzinfo is None:
        cuando = cuando.replace(tzinfo=timezone.utc)
    return ahora - cuando <= TTL_CONFIRMACION


async def confirmar_candidatos(
    cliente: Optional[CromoClient],
    filas: Sequence[FilaIslaFusion],
    *,
    previas: Mapping[int, ConfirmacionVivo],
    tope: int,
    ahora: datetime,
) -> tuple[dict[int, ConfirmacionVivo], ResumenConfirmaciones]:
    """Confirma en vivo los cables de las fusiones candidatas a isla pura.

    Reutiliza la confirmación previa del caso si la versión local del cable no cambió y tiene menos
    de `TTL_CONFIRMACION`. Sin cliente, con el tope agotado o con Cromo caído, el cable queda sin
    confirmar y su caso queda MANUAL.
    """
    resumen = ResumenConfirmaciones()
    cables: dict[int, CableLocal] = {}
    for fila in filas:
        if motivo_no_candidato_auto(fila) is None:
            for cable in fila.cables():
                if cable is not None:
                    cables.setdefault(cable.n_id, cable)
    resumen.candidatos = len(cables)
    confirmaciones: dict[int, ConfirmacionVivo] = {}
    pendientes: list[CableLocal] = []
    for n_id in sorted(cables):
        cable = cables[n_id]
        previa = previas.get(n_id)
        if _previa_vigente(previa, cable, ahora):
            confirmaciones[n_id] = previa  # type: ignore[assignment]
            resumen.reutilizados += 1
        else:
            pendientes.append(cable)

    if cliente is None:
        resumen.sin_cliente = len(pendientes)
        return confirmaciones, resumen
    if len(pendientes) > tope:
        resumen.omitidos_por_tope = len(pendientes) - tope
        pendientes = pendientes[:tope]

    semaforo = asyncio.Semaphore(_CONCURRENCIA_CONFIRMACION)
    fallos_seguidos = 0

    async def _uno(cable: CableLocal) -> None:
        nonlocal fallos_seguidos
        async with semaforo:
            if fallos_seguidos >= _MAX_FALLOS_CROMO_SEGUIDOS:
                resumen.errores += 1
                return
            try:
                confirmacion = await confirmar_cable_en_vivo(cliente, cable, ahora=ahora)
            except CromoClientError as exc:
                fallos_seguidos += 1
                resumen.errores += 1
                logger.warning(
                    "action=cromo_inconsistencias evento=confirmacion_fallida cable=%s error=%s",
                    cable.n_id,
                    exc,
                )
                return
            fallos_seguidos = 0
            resumen.llamadas += confirmacion.llamadas
            resumen.confirmados += 1
            confirmaciones[cable.n_id] = confirmacion

    await asyncio.gather(*(_uno(c) for c in pendientes))
    return confirmaciones, resumen


# ── SQL de detección ─────────────────────────────────────────────────────────

# Tablas temporales: uniones por pelo y pelos en uso (con sus números de servicio). Indexadas y
# analizadas, el planner elige hash joins; con CTEs estimaba 1 fila y no terminaba en 2 minutos.
_SQL_TEMPORALES: tuple[str, ...] = (
    "DROP TABLE IF EXISTS pg_temp.t_inc_uniones",
    "DROP TABLE IF EXISTS pg_temp.t_inc_uso",
    """
    CREATE TEMP TABLE t_inc_uniones AS
    SELECT pelo, count(*)::int AS n FROM (
        SELECT pelo_a_n_id AS pelo FROM app.cromo_fusiones
         WHERE vigente AND pelo_a_n_id IS NOT NULL
        UNION ALL
        SELECT pelo_b_n_id FROM app.cromo_fusiones
         WHERE vigente AND pelo_b_n_id IS NOT NULL
        UNION ALL
        SELECT pelo_n_id FROM app.cromo_odf_conectores
         WHERE vigente AND pelo_n_id IS NOT NULL
    ) u
    GROUP BY pelo
    """,
    """
    CREATE TEMP TABLE t_inc_uso AS
    SELECT pelo_n_id AS pelo, array_agg(DISTINCT servicio_numero) AS servicios
    FROM app.cromo_servicio_match
    GROUP BY pelo_n_id
    """,
    "ALTER TABLE t_inc_uniones ADD PRIMARY KEY (pelo)",
    "ALTER TABLE t_inc_uso ADD PRIMARY KEY (pelo)",
    "ANALYZE t_inc_uniones",
    "ANALYZE t_inc_uso",
)
_SQL_BORRAR_TEMPORALES: tuple[str, ...] = (
    "DROP TABLE IF EXISTS pg_temp.t_inc_uniones",
    "DROP TABLE IF EXISTS pg_temp.t_inc_uso",
)

_SQL_ISLAS_FUSION = text(
    """
    WITH islas AS (
        SELECT f.n_id, f.nombre_par, f.botella_n_id,
               pa.n_id AS pelo_a, pb.n_id AS pelo_b,
               pa.cable_n_id AS cable_a, pb.cable_n_id AS cable_b,
               ua.pelo IS NOT NULL AS uso_a, ub.pelo IS NOT NULL AS uso_b,
               COALESCE(ua.servicios, '{}') || COALESCE(ub.servicios, '{}') AS servicios
        FROM app.cromo_fusiones f
        JOIN t_inc_uniones na ON na.pelo = f.pelo_a_n_id AND na.n = 1
        JOIN t_inc_uniones nb ON nb.pelo = f.pelo_b_n_id AND nb.n = 1
        JOIN app.cromo_pelos pa ON pa.n_id = f.pelo_a_n_id AND pa.vigente
        JOIN app.cromo_pelos pb ON pb.n_id = f.pelo_b_n_id AND pb.vigente
        LEFT JOIN t_inc_uso ua ON ua.pelo = pa.n_id
        LEFT JOIN t_inc_uso ub ON ub.pelo = pb.n_id
        WHERE f.vigente AND (ua.pelo IS NOT NULL OR ub.pelo IS NOT NULL)
    )
    SELECT i.n_id, i.nombre_par, i.botella_n_id, i.pelo_a, i.pelo_b, i.uso_a, i.uso_b, i.servicios,
           b.clase AS b_clase, b.nombre AS b_nombre, b.localidad AS b_localidad,
           b.version_id AS b_version,
           o.clase AS o_clase, o.nombre AS o_nombre, o.localidad AS o_localidad,
           c1.n_id AS c1_n_id, c1.nombre AS c1_nombre, c1.clase AS c1_clase,
           c1.version_id AS c1_version, c1.extremo_a_n_id AS c1_ea, c1.extremo_a_clase AS c1_eac,
           c1.extremo_b_n_id AS c1_eb, c1.extremo_b_clase AS c1_ebc,
           o1a.n_id IS NOT NULL AS c1_ea_odf, o1b.n_id IS NOT NULL AS c1_eb_odf,
           c2.n_id AS c2_n_id, c2.nombre AS c2_nombre, c2.clase AS c2_clase,
           c2.version_id AS c2_version, c2.extremo_a_n_id AS c2_ea, c2.extremo_a_clase AS c2_eac,
           c2.extremo_b_n_id AS c2_eb, c2.extremo_b_clase AS c2_ebc,
           o2a.n_id IS NOT NULL AS c2_ea_odf, o2b.n_id IS NOT NULL AS c2_eb_odf
    FROM islas i
    LEFT JOIN app.cromo_botellas b ON b.n_id = i.botella_n_id AND b.vigente
    LEFT JOIN app.cromo_odfs o ON o.n_id = i.botella_n_id AND o.vigente
    LEFT JOIN app.cromo_cables c1 ON c1.n_id = i.cable_a AND c1.vigente
    LEFT JOIN app.cromo_cables c2 ON c2.n_id = i.cable_b AND c2.vigente
    LEFT JOIN app.cromo_odfs o1a ON o1a.n_id = c1.extremo_a_n_id
    LEFT JOIN app.cromo_odfs o1b ON o1b.n_id = c1.extremo_b_n_id
    LEFT JOIN app.cromo_odfs o2a ON o2a.n_id = c2.extremo_a_n_id
    LEFT JOIN app.cromo_odfs o2b ON o2b.n_id = c2.extremo_b_n_id
    ORDER BY i.n_id
    """
)

_SQL_CABLES_SIN_EXTREMO = text(
    """
    WITH cables AS (
        SELECT c.n_id, array_agg(DISTINCT p.n_id) AS pelos,
               array_agg(DISTINCT s.numero) FILTER (WHERE s.numero IS NOT NULL) AS servicios
        FROM app.cromo_cables c
        JOIN app.cromo_pelos p ON p.cable_n_id = c.n_id AND p.vigente
        JOIN t_inc_uso u ON u.pelo = p.n_id
        LEFT JOIN LATERAL unnest(u.servicios) AS s(numero) ON true
        WHERE c.vigente AND c.clase = ANY(:clases)
          AND (c.extremo_a_n_id IS NULL OR c.extremo_b_n_id IS NULL)
        GROUP BY c.n_id
    )
    SELECT c.n_id, c.nombre, c.clase, c.version_id,
           c.extremo_a_n_id, c.extremo_a_clase, c.extremo_b_n_id, c.extremo_b_clase,
           COALESCE(b.nombre, o.nombre) AS elemento_nombre,
           COALESCE(b.localidad, o.localidad) AS localidad,
           (o.n_id IS NOT NULL OR c.extremo_a_clase = ANY(:clases_odf)
               OR c.extremo_b_clase = ANY(:clases_odf)) AS toca_odf,
           x.pelos, x.servicios
    FROM cables x
    JOIN app.cromo_cables c ON c.n_id = x.n_id
    LEFT JOIN app.cromo_botellas b ON b.n_id = COALESCE(c.extremo_a_n_id, c.extremo_b_n_id)
    LEFT JOIN app.cromo_odfs o ON o.n_id = COALESCE(c.extremo_a_n_id, c.extremo_b_n_id)
    ORDER BY c.n_id
    """
)

# Elementos (botellas y ODF/ODF Nodo) cuyos cables incidentes —de cualquier clase— terminan todos
# sin otro extremo. Un cable en lazo (los dos extremos en el mismo elemento) cuenta como "con otro
# extremo": no es isla. Rosetas y cajas PON quedan fuera: un extremo suelto ahí es lo normal.
_SQL_ELEMENTOS_ISLA = text(
    """
    WITH inc AS (
        SELECT n_id AS cable, extremo_a_n_id AS elem, extremo_b_n_id AS otro
          FROM app.cromo_cables WHERE vigente AND extremo_a_n_id IS NOT NULL
        UNION ALL
        SELECT n_id, extremo_b_n_id, extremo_a_n_id
          FROM app.cromo_cables WHERE vigente AND extremo_b_n_id IS NOT NULL
    ), agg AS (
        SELECT elem, array_agg(DISTINCT cable) AS cables
        FROM inc GROUP BY elem HAVING bool_and(otro IS NULL)
    ), elementos AS (
        SELECT a.elem, a.cables, b.clase, b.nombre, b.localidad, false AS es_odf
        FROM agg a JOIN app.cromo_botellas b ON b.n_id = a.elem AND b.vigente
        UNION ALL
        SELECT a.elem, a.cables, o.clase, o.nombre, o.localidad, true
        FROM agg a JOIN app.cromo_odfs o ON o.n_id = a.elem AND o.vigente
    )
    SELECT e.elem, e.clase, e.nombre, e.localidad, e.es_odf, e.cables,
           array_agg(DISTINCT p.n_id) AS pelos,
           array_agg(DISTINCT s.numero) FILTER (WHERE s.numero IS NOT NULL) AS servicios
    FROM elementos e
    CROSS JOIN LATERAL unnest(e.cables) AS cab(n_id)
    JOIN app.cromo_pelos p ON p.cable_n_id = cab.n_id AND p.vigente
    JOIN t_inc_uso u ON u.pelo = p.n_id
    LEFT JOIN LATERAL unnest(u.servicios) AS s(numero) ON true
    GROUP BY e.elem, e.clase, e.nombre, e.localidad, e.es_odf, e.cables
    ORDER BY e.elem
    """
)

_SQL_NOMBRES_CABLES = text(
    "SELECT n_id, nombre FROM app.cromo_cables WHERE n_id = ANY(:ids)"
)


def _servicios(valores: Optional[Iterable[Optional[str]]]) -> list[str]:
    unicos = sorted({v for v in (valores or ()) if v})
    return unicos[:_MAX_SERVICIOS_EVIDENCIA]


def _cable_desde_fila(fila: Any, prefijo: str) -> Optional[CableLocal]:
    n_id = getattr(fila, f"{prefijo}_n_id")
    if n_id is None:
        return None
    return CableLocal(
        n_id=int(n_id),
        nombre=getattr(fila, f"{prefijo}_nombre"),
        clase=getattr(fila, f"{prefijo}_clase"),
        version_id=getattr(fila, f"{prefijo}_version"),
        extremo_a_n_id=getattr(fila, f"{prefijo}_ea"),
        extremo_a_clase=getattr(fila, f"{prefijo}_eac"),
        extremo_b_n_id=getattr(fila, f"{prefijo}_eb"),
        extremo_b_clase=getattr(fila, f"{prefijo}_ebc"),
        extremo_a_es_odf=bool(getattr(fila, f"{prefijo}_ea_odf")),
        extremo_b_es_odf=bool(getattr(fila, f"{prefijo}_eb_odf")),
    )


async def _leer_islas_fusion(sesion: AsyncSession) -> list[FilaIslaFusion]:
    salida: list[FilaIslaFusion] = []
    for fila in (await sesion.execute(_SQL_ISLAS_FUSION)).all():
        es_odf = fila.o_clase is not None
        salida.append(
            FilaIslaFusion(
                fusion_n_id=int(fila.n_id),
                nombre_par=fila.nombre_par,
                contenedor_n_id=fila.botella_n_id,
                contenedor_clase=fila.o_clase if es_odf else fila.b_clase,
                contenedor_nombre=fila.o_nombre if es_odf else fila.b_nombre,
                contenedor_es_odf=es_odf,
                contenedor_version_id=None if es_odf else fila.b_version,
                localidad=fila.o_localidad if es_odf else fila.b_localidad,
                pelo_a_n_id=int(fila.pelo_a),
                pelo_b_n_id=int(fila.pelo_b),
                uso_a=bool(fila.uso_a),
                uso_b=bool(fila.uso_b),
                cable_a=_cable_desde_fila(fila, "c1"),
                cable_b=_cable_desde_fila(fila, "c2"),
                servicios=tuple(_servicios(fila.servicios)),
            )
        )
    return salida


def _casos_cables_sin_extremo(filas: Iterable[Any]) -> list[Caso]:
    casos = []
    for fila in filas:
        casos.append(
            Caso(
                tipo=TIPO_CABLE_SIN_EXTREMO,
                objeto_n_id=int(fila.n_id),
                objeto_clase=fila.clase,
                nombre=fila.nombre,
                localidad=fila.localidad,
                revision=REVISION_MANUAL,
                evidencia={
                    "motivo": "cable_con_extremo_odf" if fila.toca_odf else "cable_sin_extremo",
                    "cable": {
                        "n_id": int(fila.n_id),
                        "nombre": fila.nombre,
                        "clase": fila.clase,
                        "version_id": fila.version_id,
                        "extremo_a": fila.extremo_a_n_id,
                        "extremo_a_clase": fila.extremo_a_clase,
                        "extremo_b": fila.extremo_b_n_id,
                        "extremo_b_clase": fila.extremo_b_clase,
                    },
                    "elemento_conocido": fila.elemento_nombre,
                    "pelos_en_uso": len(fila.pelos or ()),
                    "servicios": _servicios(fila.servicios),
                },
                pelos=tuple(int(p) for p in fila.pelos or ()),
            )
        )
    return casos


def _casos_elementos_isla(filas: Iterable[Any], nombres_cables: Mapping[int, Optional[str]]) -> list[Caso]:
    casos = []
    for fila in filas:
        cables = sorted(int(c) for c in fila.cables or ())
        casos.append(
            Caso(
                tipo=TIPO_ELEMENTO_ISLA,
                objeto_n_id=int(fila.elem),
                objeto_clase=fila.clase,
                nombre=fila.nombre,
                localidad=fila.localidad,
                revision=REVISION_MANUAL,
                evidencia={
                    "motivo": "elemento_odf" if fila.es_odf else "elemento_isla",
                    "cables": [{"n_id": c, "nombre": nombres_cables.get(c)} for c in cables],
                    "pelos_en_uso": len(fila.pelos or ()),
                    "servicios": _servicios(fila.servicios),
                },
                pelos=tuple(sorted(int(p) for p in fila.pelos or ())),
            )
        )
    return casos


def caso_isla_fusion(
    fila: FilaIslaFusion,
    confirmaciones: Mapping[int, ConfirmacionVivo],
    *,
    corrida_id: Optional[int] = None,
) -> Caso:
    revision, motivo = clasificar_isla_fusion(fila, confirmaciones)
    usadas = [
        confirmaciones[c.n_id].a_dict()
        for c in fila.cables()
        if c is not None and c.n_id in confirmaciones
    ]
    nombre = " — ".join(x for x in (fila.contenedor_nombre, fila.nombre_par) if x) or None
    evidencia: dict[str, Any] = {
        "motivo": motivo,
        "contenedor": {
            "n_id": fila.contenedor_n_id,
            "clase": fila.contenedor_clase,
            "nombre": fila.contenedor_nombre,
            "es_odf": fila.contenedor_es_odf,
            "version_id": fila.contenedor_version_id,
        },
        "nombre_par": fila.nombre_par,
        "pelos": [
            {"n_id": fila.pelo_a_n_id, "en_uso": fila.uso_a},
            {"n_id": fila.pelo_b_n_id, "en_uso": fila.uso_b},
        ],
        "cables": [c.a_dict() for c in fila.cables() if c is not None],
        "servicios": list(fila.servicios),
        "confirmaciones": usadas,
    }
    if corrida_id is not None:
        evidencia["corrida_id"] = corrida_id
    return Caso(
        tipo=TIPO_ISLA_FUSION,
        objeto_n_id=fila.fusion_n_id,
        objeto_clase=CLASE_FUSION,
        nombre=nombre,
        localidad=fila.localidad,
        revision=revision,
        evidencia=evidencia,
        pelos=fila.pelos_en_uso(),
    )


@dataclass(slots=True)
class LecturaDeteccion:
    """Lo que sale del SQL, antes de confirmar en vivo."""

    islas: list[FilaIslaFusion]
    cables_sin_extremo: list[Caso]
    elementos_isla: list[Caso]
    duracion_ms: int = 0


async def leer_deteccion(sesion: AsyncSession) -> LecturaDeteccion:
    """Corre el SQL de los tres tipos (sólo lectura + dos tablas temporales que se borran)."""
    inicio = time.monotonic()
    # Sin `finally`: si algo falla la transacción queda abortada y un DROP ahí taparía el error
    # original. El rollback del llamador ya descarta las temporales (su CREATE es transaccional).
    for sql in _SQL_TEMPORALES:
        await sesion.execute(text(sql))
    islas = await _leer_islas_fusion(sesion)
    filas_cables = (
        await sesion.execute(
            _SQL_CABLES_SIN_EXTREMO,
            {"clases": list(CLASES_CABLE_DETECCION), "clases_odf": sorted(CLASES_ODF)},
        )
    ).all()
    filas_elementos = (await sesion.execute(_SQL_ELEMENTOS_ISLA)).all()
    ids_cables = sorted({int(c) for f in filas_elementos for c in (f.cables or ())})
    nombres: dict[int, Optional[str]] = {}
    if ids_cables:
        nombres = {
            int(n): nom
            for n, nom in (await sesion.execute(_SQL_NOMBRES_CABLES, {"ids": ids_cables})).all()
        }
    for sql in _SQL_BORRAR_TEMPORALES:
        await sesion.execute(text(sql))
    return LecturaDeteccion(
        islas=islas,
        cables_sin_extremo=_casos_cables_sin_extremo(filas_cables),
        elementos_isla=_casos_elementos_isla(filas_elementos, nombres),
        duracion_ms=int((time.monotonic() - inicio) * 1000),
    )


# ── Persistencia ─────────────────────────────────────────────────────────────

# Serializa detectores concurrentes (post-ingesta y manual) sobre la tabla de casos.
_LOCK_DETECTOR = 0x494E_434F_4E53  # "INCONS"


async def _tabla_existe(sesion: AsyncSession) -> bool:
    return (
        await sesion.execute(text("SELECT to_regclass('app.cromo_inconsistencia') IS NOT NULL"))
    ).scalar_one()


async def confirmaciones_previas(sesion: AsyncSession) -> dict[int, ConfirmacionVivo]:
    """Confirmaciones en vivo guardadas en la evidencia de las islas ya registradas."""
    if not await _tabla_existe(sesion):
        return {}
    filas = (
        await sesion.execute(
            text(
                "SELECT c.conf FROM app.cromo_inconsistencia i, "
                "jsonb_array_elements(i.evidencia -> 'confirmaciones') AS c(conf) "
                "WHERE i.tipo = :tipo AND jsonb_typeof(i.evidencia -> 'confirmaciones') = 'array'"
            ),
            {"tipo": TIPO_ISLA_FUSION},
        )
    ).all()
    salida: dict[int, ConfirmacionVivo] = {}
    for (conf,) in filas:
        if isinstance(conf, Mapping):
            confirmacion = ConfirmacionVivo.desde_dict(conf)
            if confirmacion is not None:
                previa = salida.get(confirmacion.cable_n_id)
                if previa is None or previa.confirmado_at < confirmacion.confirmado_at:
                    salida[confirmacion.cable_n_id] = confirmacion
    return salida


_SQL_UPSERT = text(
    """
    INSERT INTO app.cromo_inconsistencia AS t
        (tipo, objeto_n_id, objeto_clase, nombre, localidad, revision, estado, evidencia,
         primera_vez, ultima_vez, actualizado_por, actualizado_en)
    SELECT x.tipo, x.objeto_n_id, x.objeto_clase, x.nombre, x.localidad, x.revision, x.estado,
           CAST(x.evidencia AS jsonb), :ahora, :ahora, :usuario, :ahora
    FROM unnest(
        CAST(:tipos AS text[]), CAST(:objetos AS bigint[]), CAST(:clases AS smallint[]),
        CAST(:nombres AS text[]), CAST(:localidades AS text[]), CAST(:revisiones AS text[]),
        CAST(:estados AS text[]), CAST(:evidencias AS text[])
    ) AS x(tipo, objeto_n_id, objeto_clase, nombre, localidad, revision, estado, evidencia)
    ON CONFLICT (tipo, objeto_n_id) DO UPDATE SET
        objeto_clase = EXCLUDED.objeto_clase,
        nombre = EXCLUDED.nombre,
        localidad = EXCLUDED.localidad,
        revision = EXCLUDED.revision,
        evidencia = EXCLUDED.evidencia,
        ultima_vez = EXCLUDED.ultima_vez,
        actualizado_por = CASE WHEN t.estado IS DISTINCT FROM EXCLUDED.estado
                               THEN EXCLUDED.actualizado_por ELSE t.actualizado_por END,
        actualizado_en = CASE WHEN t.estado IS DISTINCT FROM EXCLUDED.estado
                              THEN EXCLUDED.actualizado_en ELSE t.actualizado_en END,
        estado = EXCLUDED.estado
    RETURNING t.id, t.tipo, t.objeto_n_id
    """
)


async def aplicar_casos(
    sesion: AsyncSession,
    casos: Sequence[Caso],
    *,
    ahora: datetime,
    usuario: str = USUARIO_DETECTOR,
) -> ResumenAplicacion:
    """Upsert idempotente de los casos detectados + cierre (CORREGIDA) de los que ya no aparecen.

    No hace commit: lo hace el llamador. Toma un advisory lock transaccional y `FOR UPDATE` sobre
    los casos existentes, así un cambio de estado manual concurrente no se pisa.
    """
    resumen = ResumenAplicacion()
    await sesion.execute(text("SELECT pg_advisory_xact_lock(:clave)"), {"clave": _LOCK_DETECTOR})
    existentes: dict[tuple[str, int], EstadoExistente] = {
        (tipo, int(objeto)): EstadoExistente(int(id_), estado, revision, actualizado_por)
        for id_, tipo, objeto, estado, revision, actualizado_por in (
            await sesion.execute(
                text(
                    "SELECT id, tipo, objeto_n_id, estado, revision, actualizado_por "
                    "FROM app.cromo_inconsistencia FOR UPDATE"
                )
            )
        ).all()
    }
    resumen.casos_previos = len(existentes)
    unicos: dict[tuple[str, int], Caso] = {}
    for caso in casos:
        unicos[(caso.tipo, caso.objeto_n_id)] = caso

    columnas: dict[str, list[Any]] = {
        k: []
        for k in (
            "tipos", "objetos", "clases", "nombres", "localidades", "revisiones", "estados",
            "evidencias",
        )
    }
    for clave, caso in unicos.items():
        existente = existentes.get(clave)
        estado, reabierto = decidir_estado(existente, caso.revision)
        if existente is None:
            resumen.nuevos += 1
            resumen.nuevos_claves.append(clave)
            if estado == ESTADO_CUARENTENA:
                resumen.cuarentena_auto += 1
        else:
            resumen.actualizados += 1
            if reabierto:
                resumen.reabiertos += 1
        columnas["tipos"].append(caso.tipo)
        columnas["objetos"].append(caso.objeto_n_id)
        columnas["clases"].append(caso.objeto_clase)
        columnas["nombres"].append(caso.nombre)
        columnas["localidades"].append(caso.localidad)
        columnas["revisiones"].append(caso.revision)
        columnas["estados"].append(estado)
        columnas["evidencias"].append(json.dumps(caso.evidencia, default=str))

    ids_detectados: list[int] = []
    pares_pelos: tuple[list[int], list[int]] = ([], [])
    if unicos:
        filas = (
            await sesion.execute(_SQL_UPSERT, {**columnas, "ahora": ahora, "usuario": usuario})
        ).all()
        id_por_clave = {(tipo, int(objeto)): int(id_) for id_, tipo, objeto in filas}
        for clave, caso in unicos.items():
            id_caso = id_por_clave[clave]
            ids_detectados.append(id_caso)
            for pelo in sorted(set(caso.pelos)):
                pares_pelos[0].append(id_caso)
                pares_pelos[1].append(pelo)
        await sesion.execute(
            text(
                "DELETE FROM app.cromo_inconsistencia_pelo "
                "WHERE inconsistencia_id = ANY(CAST(:ids AS bigint[]))"
            ),
            {"ids": ids_detectados},
        )
        if pares_pelos[0]:
            await sesion.execute(
                text(
                    "INSERT INTO app.cromo_inconsistencia_pelo (inconsistencia_id, pelo_n_id) "
                    "SELECT * FROM unnest(CAST(:ids AS bigint[]), CAST(:pelos AS bigint[]))"
                ),
                {"ids": pares_pelos[0], "pelos": pares_pelos[1]},
            )

    cerrados = (
        await sesion.execute(
            text(
                "UPDATE app.cromo_inconsistencia SET estado = :corregida, "
                "actualizado_por = :usuario, actualizado_en = :ahora "
                "WHERE estado NOT IN (:corregida, :aceptada) "
                "AND NOT (id = ANY(CAST(:ids AS bigint[]))) RETURNING id"
            ),
            {
                "corregida": ESTADO_CORREGIDA,
                "aceptada": ESTADO_ACEPTADA,
                "usuario": usuario,
                "ahora": ahora,
                "ids": ids_detectados,
            },
        )
    ).all()
    resumen.cerrados = len(cerrados)
    resumen.por_estado = {
        estado: int(n)
        for estado, n in (
            await sesion.execute(
                text("SELECT estado, count(*) FROM app.cromo_inconsistencia GROUP BY estado")
            )
        ).all()
    }
    return resumen


# ── Orquestación ─────────────────────────────────────────────────────────────

AlAvanzar = Callable[[str, dict[str, Any]], Awaitable[None]]


def _contar_por_tipo_revision(casos: Iterable[Caso]) -> dict[str, dict[str, int]]:
    salida: dict[str, dict[str, int]] = {t: {r: 0 for r in REVISIONES} for t in TIPOS}
    for caso in casos:
        salida[caso.tipo][caso.revision] += 1
    return salida


async def detectar(
    sesion: AsyncSession,
    *,
    cliente: Optional[CromoClient] = None,
    corrida_id: Optional[int] = None,
    aplicar: bool = True,
    ahora: Optional[datetime] = None,
    max_confirmaciones: Optional[int] = None,
    al_avanzar: Optional[AlAvanzar] = None,
) -> ResumenDeteccion:
    """Detecta, clasifica y (con `aplicar=True`) registra los casos.

    Hace commit después de la lectura SQL (las confirmaciones en vivo pueden tardar minutos y no
    deben tener una transacción abierta) y, con `aplicar=True`, después del upsert. Con
    `aplicar=False` no escribe nada: es el modo reporte de la medición.
    """
    inicio = time.monotonic()
    ahora = ahora or datetime.now(timezone.utc)
    tope = max_confirmaciones_configurado() if max_confirmaciones is None else max_confirmaciones

    lectura = await leer_deteccion(sesion)
    previas = await confirmaciones_previas(sesion)
    await sesion.commit()
    if al_avanzar is not None:
        await al_avanzar(
            "LECTURA",
            {
                "islas_fusion": len(lectura.islas),
                "cables_sin_extremo": len(lectura.cables_sin_extremo),
                "elementos_isla": len(lectura.elementos_isla),
                "duracion_sql_ms": lectura.duracion_ms,
            },
        )

    confirmaciones, resumen_conf = await confirmar_candidatos(
        cliente, lectura.islas, previas=previas, tope=tope, ahora=ahora
    )
    if al_avanzar is not None:
        await al_avanzar("CONFIRMACION", resumen_conf.a_dict())

    casos: list[Caso] = [
        caso_isla_fusion(f, confirmaciones, corrida_id=corrida_id) for f in lectura.islas
    ]
    casos.extend(lectura.cables_sin_extremo)
    casos.extend(lectura.elementos_isla)
    if corrida_id is not None:
        for caso in casos:
            caso.evidencia.setdefault("corrida_id", corrida_id)

    resumen = ResumenDeteccion(
        por_tipo_revision=_contar_por_tipo_revision(casos),
        total=len(casos),
        confirmaciones=resumen_conf,
        aplicado=aplicar,
        duracion_sql_ms=lectura.duracion_ms,
        casos=casos,
    )
    if aplicar:
        aplicacion = await aplicar_casos(sesion, casos, ahora=ahora)
        await sesion.commit()
        resumen.nuevos = aplicacion.nuevos
        resumen.actualizados = aplicacion.actualizados
        resumen.reabiertos = aplicacion.reabiertos
        resumen.cerrados = aplicacion.cerrados
        resumen.por_estado = aplicacion.por_estado
        resumen.nuevos_claves = aplicacion.nuevos_claves
        resumen.cuarentena_auto = aplicacion.cuarentena_auto
        resumen.casos_previos = aplicacion.casos_previos
        if al_avanzar is not None:
            await al_avanzar(
                "APLICACION",
                {
                    "nuevos": aplicacion.nuevos,
                    "actualizados": aplicacion.actualizados,
                    "reabiertos": aplicacion.reabiertos,
                    "cerrados": aplicacion.cerrados,
                },
            )
    resumen.duracion_ms = int((time.monotonic() - inicio) * 1000)
    logger.info(
        "action=cromo_inconsistencias evento=deteccion corrida_id=%s aplicado=%s total=%d "
        "nuevos=%d cerrados=%d duracion_ms=%d",
        corrida_id,
        aplicar,
        resumen.total,
        resumen.nuevos,
        resumen.cerrados,
        resumen.duracion_ms,
    )
    return resumen


# ── API de casos (Tareas 3-5) ────────────────────────────────────────────────


_ORDEN_LISTADO = "i.ultima_vez DESC, i.id DESC"


async def listar(
    sesion: AsyncSession,
    *,
    tipo: Optional[str] = None,
    estado: Optional[str] = None,
    estados: Optional[Sequence[str]] = None,
    revision: Optional[str] = None,
    localidad: Optional[str] = None,
    servicio: Optional[str] = None,
    servicio_id: Optional[int] = None,
    pagina: int = 1,
    por_pagina: int = 50,
    desplazamiento: Optional[int] = None,
) -> dict[str, Any]:
    """Casos paginados, filtrables por tipo/estado/revisión/localidad (ILIKE) y servicio (número
    exacto de `cromo_servicio_match`, o PK de `app.servicios`, de alguno de sus pelos).

    `estados` (varios) se suma a `estado` (uno) con AND; el reporte lo usa para excluir los cerrados.
    `desplazamiento` (offset) pisa a `pagina` cuando se pasa. Además de los casos devuelve
    `conteos_por_tipo`, con todos los filtros salvo el de tipo (chips del Viewer). Cada ítem lleva
    `pelos` y `servicios` (cantidad de números de servicio distintos de sus pelos)."""
    pagina = max(1, int(pagina))
    por_pagina = min(max(1, int(por_pagina)), 500)
    desde = max(0, int(desplazamiento)) if desplazamiento is not None else (pagina - 1) * por_pagina
    condiciones = ["true"]
    params: dict[str, Any] = {}
    if estado:
        condiciones.append("i.estado = :estado")
        params["estado"] = estado
    if estados:
        condiciones.append("i.estado = ANY(:estados)")
        params["estados"] = [str(e) for e in estados]
    if revision:
        condiciones.append("i.revision = :revision")
        params["revision"] = revision
    if localidad:
        condiciones.append("i.localidad ILIKE :localidad")
        params["localidad"] = f"%{localidad.strip()}%"
    if servicio:
        condiciones.append(
            "EXISTS (SELECT 1 FROM app.cromo_inconsistencia_pelo ip "
            "JOIN app.cromo_servicio_match m ON m.pelo_n_id = ip.pelo_n_id "
            "WHERE ip.inconsistencia_id = i.id AND m.servicio_numero = :servicio)"
        )
        params["servicio"] = servicio.strip()
    if servicio_id is not None:
        condiciones.append(
            "EXISTS (SELECT 1 FROM app.cromo_inconsistencia_pelo ip "
            "JOIN app.cromo_servicio_match m ON m.pelo_n_id = ip.pelo_n_id "
            "JOIN app.servicios s ON s.id = :servicio_id AND (" + IDENTIDADES_DEL_SERVICIO_SQL + ") "
            "WHERE ip.inconsistencia_id = i.id)"
        )
        params["servicio_id"] = int(servicio_id)
    sin_tipo = " AND ".join(condiciones)
    conteos_por_tipo = {
        str(t): int(n)
        for t, n in (
            await sesion.execute(
                text(
                    "SELECT i.tipo, count(*) FROM app.cromo_inconsistencia i "
                    f"WHERE {sin_tipo} GROUP BY i.tipo"
                ),
                params,
            )
        ).all()
    }
    if tipo:
        condiciones.append("i.tipo = :tipo")
        params["tipo"] = tipo
    donde = " AND ".join(condiciones)
    total = (
        await sesion.execute(
            text(f"SELECT count(*) FROM app.cromo_inconsistencia i WHERE {donde}"), params
        )
    ).scalar_one()
    filas = (
        await sesion.execute(
            text(
                "SELECT i.id, i.tipo, i.objeto_n_id, i.objeto_clase, i.nombre, i.localidad, "
                "i.revision, i.estado, i.evidencia, i.primera_vez, i.ultima_vez, "
                "i.actualizado_por, i.actualizado_en, "
                "(SELECT count(*) FROM app.cromo_inconsistencia_pelo ip "
                " WHERE ip.inconsistencia_id = i.id) AS pelos, "
                "(SELECT count(DISTINCT m.servicio_numero) "
                " FROM app.cromo_inconsistencia_pelo ip "
                " JOIN app.cromo_servicio_match m ON m.pelo_n_id = ip.pelo_n_id "
                " WHERE ip.inconsistencia_id = i.id) AS servicios "
                f"FROM app.cromo_inconsistencia i WHERE {donde} "
                f"ORDER BY {_ORDEN_LISTADO} LIMIT :limite OFFSET :desde"
            ),
            {**params, "limite": por_pagina, "desde": desde},
        )
    ).mappings().all()
    return {
        "total": int(total),
        "pagina": pagina,
        "por_pagina": por_pagina,
        "desplazamiento": desde,
        "conteos_por_tipo": conteos_por_tipo,
        "items": [dict(f) for f in filas],
    }


async def resumen_de_servicio(sesion: AsyncSession, servicio_id: int) -> dict[str, Any]:
    """Casos que tocan a un servicio (PK de `app.servicios`), para el aviso del panel Camino.

    `cuarentena`: casos en CUARENTENA (sus pelos no cuentan como uso). `en_revision`: casos
    PENDIENTE o REPORTADA. Cuenta casos, no pelos; sólo lee el uso crudo de `cromo_servicio_match`
    (por eso vive acá, en el módulo permitido)."""
    filas = (
        await sesion.execute(
            text(
                "SELECT i.estado, count(DISTINCT i.id) FROM app.cromo_inconsistencia i "
                "JOIN app.cromo_inconsistencia_pelo ip ON ip.inconsistencia_id = i.id "
                "JOIN app.cromo_servicio_match m ON m.pelo_n_id = ip.pelo_n_id "
                "JOIN app.servicios s ON s.id = :servicio_id AND (" + IDENTIDADES_DEL_SERVICIO_SQL + ") "
                "WHERE i.estado IN ('CUARENTENA', 'PENDIENTE', 'REPORTADA') GROUP BY i.estado"
            ),
            {"servicio_id": int(servicio_id)},
        )
    ).all()
    por_estado = {str(e): int(n) for e, n in filas}
    return {
        "cuarentena": por_estado.get(ESTADO_CUARENTENA, 0),
        "en_revision": por_estado.get(ESTADO_PENDIENTE, 0) + por_estado.get(ESTADO_REPORTADA, 0),
    }


async def ultima_deteccion(sesion: AsyncSession) -> Optional[CromoIngestaCorrida]:
    """Última corrida sintética del detector (la que muestra el Viewer al abrir)."""
    fila = (
        await sesion.execute(
            text(
                "SELECT id FROM app.cromo_ingesta_corridas WHERE params ->> 'tipo' = :tipo "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"tipo": TIPO_CORRIDA_INCONSISTENCIAS},
        )
    ).first()
    return await sesion.get(CromoIngestaCorrida, int(fila[0])) if fila else None


async def cambiar_estado(
    sesion: AsyncSession, ids: Iterable[int], estado: str, usuario: str
) -> dict[str, Any]:
    """Cambio de estado manual. Devuelve `{"actualizados": [ids], "rechazados": [{id, motivo}]}`.

    Transiciones: a CUARENTENA, ACEPTADA, REPORTADA o PENDIENTE, desde cualquier estado salvo
    CORREGIDA. No hace commit: lo hace el endpoint.
    """
    pedidos = sorted({int(i) for i in ids})
    actualizados: list[int] = []
    rechazados: list[dict[str, Any]] = []
    if not pedidos:
        return {"actualizados": actualizados, "rechazados": rechazados}
    actuales = {
        int(id_): est
        for id_, est in (
            await sesion.execute(
                text(
                    "SELECT id, estado FROM app.cromo_inconsistencia "
                    "WHERE id = ANY(CAST(:ids AS bigint[])) FOR UPDATE"
                ),
                {"ids": pedidos},
            )
        ).all()
    }
    for id_caso in pedidos:
        actual = actuales.get(id_caso)
        if actual is None:
            rechazados.append({"id": id_caso, "motivo": "el caso no existe"})
            continue
        motivo = motivo_rechazo_transicion(actual, estado)
        if motivo is not None:
            rechazados.append({"id": id_caso, "motivo": motivo})
            continue
        actualizados.append(id_caso)
    if actualizados:
        await sesion.execute(
            text(
                "UPDATE app.cromo_inconsistencia SET estado = :estado, actualizado_por = :usuario, "
                "actualizado_en = :ahora WHERE id = ANY(CAST(:ids AS bigint[]))"
            ),
            {
                "estado": estado,
                "usuario": usuario,
                "ahora": datetime.now(timezone.utc),
                "ids": actualizados,
            },
        )
    return {"actualizados": actualizados, "rechazados": rechazados}


# ── Corrida sintética (cromo_worker) ─────────────────────────────────────────

_LOCK_CORRIDA = 0x494E_4343_5252  # "INCCRR"


async def deteccion_en_curso(sesion: AsyncSession) -> Optional[int]:
    fila = (
        await sesion.execute(
            text(
                "SELECT id FROM app.cromo_ingesta_corridas "
                "WHERE estado = 'EN_CURSO' AND params ->> 'tipo' = :tipo "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"tipo": TIPO_CORRIDA_INCONSISTENCIAS},
        )
    ).first()
    return int(fila[0]) if fila else None


# Corridas que reescriben el inventario en masa: las ingestas (sin `params.tipo`) y el barrido
# manual de `/inner`. Las sintéticas chicas (repoblar una botella, normalizar...) no bloquean.
_TIPOS_INGESTA_MASIVA: tuple[str, ...] = ("MANUAL_BARRIDO_PELOS_INNER",)


async def ingesta_en_curso(sesion: AsyncSession) -> Optional[int]:
    """Id de una ingesta EN_CURSO, si hay. Detectar sobre un inventario a medio actualizar cerraría
    en masa casos que siguen vivos (CORREGIDA) y los reabriría en la corrida siguiente."""
    fila = (
        await sesion.execute(
            text(
                "SELECT id FROM app.cromo_ingesta_corridas WHERE estado = 'EN_CURSO' "
                "AND (params ->> 'tipo' IS NULL OR params ->> 'tipo' = ANY(:tipos)) "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"tipos": list(_TIPOS_INGESTA_MASIVA)},
        )
    ).first()
    return int(fila[0]) if fila else None


async def iniciar_si_no_hay_otra(
    sesion: AsyncSession,
    *,
    usuario: str,
    origen: str = "MANUAL",
    corrida_origen_id: Optional[int] = None,
) -> tuple[Optional[CromoIngestaCorrida], Optional[int]]:
    """`(corrida nueva, None)` o `(None, id de la corrida que lo impide)`, bajo advisory lock.

    Lo impide otra detección EN_CURSO o una ingesta EN_CURSO (`ingesta_en_curso`). El hook
    post-ingesta corre después del commit que cerró su propia ingesta, así que ésa ya no cuenta; si
    hay OTRA ingesta corriendo se omite, y esa otra dispara su propia detección al terminar.
    """
    await sesion.execute(text("SELECT pg_advisory_xact_lock(:clave)"), {"clave": _LOCK_CORRIDA})
    en_curso = await deteccion_en_curso(sesion)
    motivo = "deteccion_en_curso"
    if en_curso is None:
        en_curso = await ingesta_en_curso(sesion)
        motivo = "ingesta_en_curso"
    if en_curso is not None:
        await sesion.rollback()
        logger.info(
            "action=cromo_inconsistencias evento=inicio_rechazado motivo=%s corrida=%s origen=%s",
            motivo,
            en_curso,
            origen,
        )
        return None, en_curso
    params: dict[str, Any] = {"tipo": TIPO_CORRIDA_INCONSISTENCIAS, "origen": origen}
    if corrida_origen_id is not None:
        params["corrida_origen_id"] = corrida_origen_id
    corrida = await ingesta.iniciar_corrida(
        sesion, usuario=usuario, psize=0, max_paginas=0, clases=(), params_extra=params
    )
    return corrida, None


class _Cancelada(Exception):
    pass


def _sesion_nueva() -> AsyncSession:
    """Sesión independiente para cerrar una corrida cuando la de trabajo quedó inservible."""
    from db.session import AsyncSessionLocal

    return AsyncSessionLocal()


async def cerrar_corrida_fallida(corrida_id: int, motivo: str) -> None:
    """Cierra como FALLIDA una corrida de detección que sigue EN_CURSO, con una sesión nueva (la de
    trabajo pudo perder la conexión). Si quedara EN_CURSO bloquearía toda detección futura hasta
    reiniciar el worker. Best-effort: nunca levanta."""
    try:
        async with _sesion_nueva() as sesion:
            corrida = await sesion.get(CromoIngestaCorrida, corrida_id)
            if corrida is None or corrida.estado != "EN_CURSO":
                return
            corrida.estado = "FALLIDA"
            corrida.finalizada_at = datetime.now(timezone.utc)
            await ingesta.registrar_evento(sesion, corrida_id, None, None, "ERROR", motivo[:500])
            await sesion.commit()
    except Exception:  # noqa: BLE001
        logger.error(
            "action=cromo_inconsistencias evento=cierre_fallida_imposible corrida_id=%s",
            corrida_id,
            exc_info=True,
        )


async def ejecutar_corrida(
    cliente: Optional[CromoClient], sesion: AsyncSession, corrida_id: int
) -> str:
    """Corre la detección como corrida sintética. Nunca levanta: la cierra OK, CANCELADA o
    FALLIDA. Un evento `PAGINA` por fase (LECTURA, CONFIRMACION, APLICACION) con `leidas`/`total`
    para el SSE de corridas; la cancelación se chequea entre fases. Si hasta el cierre falla (p.ej.
    se cortó la conexión), la cierra FALLIDA con una sesión nueva."""
    try:
        return await _ejecutar_corrida(cliente, sesion, corrida_id)
    except Exception as exc:  # noqa: BLE001 - incluido el propio camino de error
        logger.error(
            "action=cromo_inconsistencias evento=corrida_sin_cierre corrida_id=%s error=%s",
            corrida_id,
            exc,
        )
        try:
            await sesion.rollback()
        except Exception:  # noqa: BLE001
            pass
        await cerrar_corrida_fallida(corrida_id, f"Detección interrumpida: {exc}")
        return "FALLIDA"


async def _ejecutar_corrida(
    cliente: Optional[CromoClient], sesion: AsyncSession, corrida_id: int
) -> str:
    corrida = await sesion.get(CromoIngestaCorrida, corrida_id)
    if corrida is None:
        raise ValueError(f"No existe la corrida {corrida_id}")
    fases_total = 3
    paso = 0
    estado_final = "OK"
    resumen: Optional[ResumenDeteccion] = None
    try:
        corrida.total_objetivo = fases_total
        await ingesta.registrar_evento(
            sesion,
            corrida_id,
            None,
            None,
            "INICIO",
            json.dumps({"corrida_id": corrida_id, "tipo": TIPO_CORRIDA_INCONSISTENCIAS}),
        )
        await sesion.commit()

        async def _al_avanzar(fase: str, detalle: dict[str, Any]) -> None:
            nonlocal paso
            paso += 1
            fila = await sesion.get(CromoIngestaCorrida, corrida_id)
            fila.leidas = paso
            await ingesta.registrar_evento(
                sesion,
                corrida_id,
                None,
                None,
                "PAGINA",
                json.dumps(
                    {
                        "fase": TIPO_CORRIDA_INCONSISTENCIAS,
                        "paso": fase,
                        "pagina": paso,
                        "leidas": paso,
                        "total": fases_total,
                        **detalle,
                    },
                    default=str,
                ),
            )
            await sesion.commit()
            if fase != "APLICACION" and await ingesta._fue_cancelada_externamente(
                sesion, corrida_id
            ):
                raise _Cancelada()

        resumen = await detectar(
            sesion, cliente=cliente, corrida_id=corrida_id, aplicar=True, al_avanzar=_al_avanzar
        )
    except _Cancelada:
        await sesion.rollback()
        estado_final = "CANCELADA"
    except Exception as exc:  # noqa: BLE001 - una falla cierra la corrida, no propaga
        await sesion.rollback()
        logger.error(
            "action=cromo_inconsistencias evento=corrida_fallida corrida_id=%s error=%s",
            corrida_id,
            exc,
        )
        await ingesta.registrar_evento(sesion, corrida_id, None, None, "ERROR", str(exc)[:500])
        estado_final = "FALLIDA"

    corrida = await sesion.get(CromoIngestaCorrida, corrida_id)
    corrida.estado = estado_final
    corrida.finalizada_at = datetime.now(timezone.utc)
    corrida.leidas = paso
    if resumen is not None:
        corrida.creadas = resumen.nuevos
        corrida.actualizadas = resumen.actualizados
        corrida.errores = resumen.confirmaciones.errores
    detalle_resumen: dict[str, Any] = {"estado": estado_final, "tipo": TIPO_CORRIDA_INCONSISTENCIAS}
    if resumen is not None:
        detalle_resumen.update(resumen.a_dict())
    await ingesta.registrar_evento(
        sesion, corrida_id, None, None, "RESUMEN", json.dumps(detalle_resumen, default=str)
    )
    await sesion.commit()
    if estado_final == "OK" and resumen is not None and resumen.aplicado:
        # Cubre la corrida manual y la post-ingesta (ambas pasan por acá). Nunca levanta.
        await avisar_casos_nuevos(sesion, resumen, corrida_id=corrida_id)
    return estado_final


async def detectar_post_ingesta(
    cliente: Optional[CromoClient], sesion: AsyncSession, corrida_origen_id: int, modo: str
) -> Optional[str]:
    """Paso posterior al commit de una ingesta COMPLETA/SOLO_ODF/SOLO_PELOS_INNER. Best-effort por
    diseño: nunca levanta ni hace fallar la ingesta. Devuelve el estado de la corrida de detección,
    o `None` si no corrió (modo no aplica, otra detección en curso o error)."""
    if modo not in MODOS_POST_INGESTA:
        return None
    corrida_id: Optional[int] = None
    try:
        corrida, en_curso = await iniciar_si_no_hay_otra(
            sesion,
            usuario=USUARIO_DETECTOR,
            origen="POST_INGESTA",
            corrida_origen_id=corrida_origen_id,
        )
        if corrida is None:
            logger.info(
                "action=cromo_inconsistencias evento=post_ingesta_omitida motivo=otra_corrida "
                "corrida_origen=%s en_curso=%s",
                corrida_origen_id,
                en_curso,
            )
            return None
        corrida_id = corrida.id
        return await ejecutar_corrida(cliente, sesion, corrida_id)
    except Exception as exc:  # noqa: BLE001 - nunca hace fallar la ingesta
        logger.warning(
            "action=cromo_inconsistencias evento=post_ingesta_fallida corrida_origen=%s",
            corrida_origen_id,
            exc_info=True,
        )
        try:
            await sesion.rollback()
        except Exception:  # noqa: BLE001
            pass
        if corrida_id is not None:
            await cerrar_corrida_fallida(corrida_id, f"Detección post-ingesta interrumpida: {exc}")
        return None


__all__ = [
    "cerrar_corrida_fallida",
    "ingesta_en_curso",
    "Caso",
    "CableLocal",
    "ConfirmacionVivo",
    "ESTADOS",
    "ESTADOS_DESTINO_MANUAL",
    "EstadoExistente",
    "FilaIslaFusion",
    "MAX_CONFIRMACIONES_DEFAULT",
    "MODOS_POST_INGESTA",
    "REVISIONES",
    "ResumenDeteccion",
    "TIPOS",
    "TIPO_CORRIDA_INCONSISTENCIAS",
    "USUARIO_DETECTOR",
    "aplicar_casos",
    "avisar_casos_nuevos",
    "cambiar_estado",
    "caso_isla_fusion",
    "clasificar_isla_fusion",
    "confirmar_candidatos",
    "confirmar_cable_en_vivo",
    "decidir_estado",
    "deteccion_en_curso",
    "detectar",
    "detectar_post_ingesta",
    "ejecutar_corrida",
    "estado_inicial",
    "iniciar_si_no_hay_otra",
    "interpretar_cable_vivo",
    "leer_deteccion",
    "listar",
    "max_confirmaciones_configurado",
    "motivo_no_candidato_auto",
    "motivo_rechazo_transicion",
]
