# Nombre de archivo: tracking_service.py
# Ubicación de archivo: core/services/cromo/tracking_service.py
# Descripción: Generación del tracking .txt de un pelo de un Servicio, con caché de 24 h, y tracking
# por tramos: un camino por semilla no cubierta (declaradas, etiquetadas y posiciones), clasificado como VIGENTE, TRAMO, ADICIONAL o RESIDUAL

"""Orquesta caché + resolución + render del tracking de un pelo.

Reparto de responsabilidades: `camino_optico_service` resuelve el camino contra Cromo,
`camino_optico_txt` lo renderiza (funciones puras, sin red ni base), `tracking_cache` guarda el
artefacto con vencimiento, y este módulo los une.

Un Servicio tiene tantos trackings como pelos —1 en PON, 2 o más en FO o con un SW de módulo
bifilar— y cada uno se descarga como su propio archivo `.txt`. Cada request resuelve un pelo, así
que ninguna descarga individual queda colgada esperando a las demás; el frontend pide los que el
operador haya elegido.

El caché es lo que lo hace viable: en frío cada pelo cuesta entre 4,6 s y 14 s contra Cromo, y sin
él bajar seis trackings significaría repetir esa espera seis veces, cada vez.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.cromo import tracking_cache
from core.services.cromo.camino_optico_service import (
    ESTADO_OK,
    TIPO_CONECTOR_ODF,
    CaminoOptico,
    NodoCamino,
    resolver_camino_de_pelo,
    semillas_para_tracking,
)
from core.services.cromo.camino_optico_txt import (
    nombre_archivo_adicional,
    nombre_archivo_tracking,
    nombre_archivo_tramo,
    renderizar_tracking_txt,
    secuencia_para_tracking,
)
from core.services.cromo.client import CromoClient
from core.services.cromo.config import tracking_max_llamadas
from core.services.cromo.servicio_odf_confirmacion import declaraciones_del_servicio
from core.services.cromo.servicio_posicion_vigente import (
    AVISO_CAMINO_INCOMPLETO,
    AVISO_CAMINO_NO_RESUELTO,
    AvisoPosicion,
    PosicionDeclarada,
    PosicionPosible,
    aplicar_retiros,
    decidir_retiro,
    etiqueta_posiciones,
    listar_declaradas,
    pelos_de_otro_servicio_activo,
    pelos_de_posiciones,
    posiciones_posibles,
    validar_camino,
    validar_en_db,
)

logger = logging.getLogger(__name__)

class TrackingNoDisponible(RuntimeError):
    """El camino del pelo no resolvió, así que no hay `.txt` que generar."""

    def __init__(self, motivo: Optional[str], estado: str) -> None:
        super().__init__(motivo or f"El camino no resolvió (estado {estado}).")
        self.motivo = motivo
        self.estado = estado


class DemasiadosPelos(ValueError):
    """Se pidieron más pelos que la cota de una sola descarga."""


ROL_TRAMO = "TRAMO"
ROL_RESIDUAL = "RESIDUAL"
# Con posición vigente declarada: el camino del pelo declarado es el VIGENTE, y los caminos resueltos
# que no son el vigente pero sí un recorrido real del servicio son ADICIONAL (`clasificar_con_posiciones`).
ROL_VIGENTE = "VIGENTE"
ROL_ADICIONAL = "ADICIONAL"

# De dónde sale un camino, por los pelos que recorre (`origen_del_camino`): de un pelo declarado por el
# operador, de una semilla etiquetada con el servicio, o sólo de las posiciones posibles (conectores).
ORIGEN_DECLARADO = "DECLARADO"
ORIGEN_ETIQUETADO = "ETIQUETADO"
ORIGEN_POSICION = "POSICION"


@dataclass(slots=True, frozen=True)
class ExtremoCamino:
    """Primer o último nodo de `secuencia_para_tracking`: dónde empieza o termina el `.txt`.

    En un conector (136) lleva la ODF (`gfather`) con su clase —69 ODF, 86 ODF Nodo—, la patchera
    y el número de conector; en un pelo, sólo tipo, id y clase.
    """

    tipo: str
    id_cromo: int
    clase: Optional[int] = None
    odf_id: Optional[int] = None
    odf_clase: Optional[int] = None
    odf_nombre: Optional[str] = None
    patchera_nombre: Optional[str] = None
    conector_numero: Optional[str] = None
    # At.62 del servicio y pelo que conecta el conector (`NodoCamino`). Sólo en extremos de ODF;
    # las entradas de caché anteriores no los traen y quedan en `None`.
    servicio_at62: Optional[str] = None
    pelo_conectado: Optional[int] = None

    @property
    def es_conector_odf(self) -> bool:
        # Un conector de ODF está en una ODF aunque su `gfather` no haya venido en el payload
        # (`odf_id` None): exigir el id hacía fallar abierta la protección de extremos en ODF.
        return self.tipo == TIPO_CONECTOR_ODF


@dataclass(slots=True, frozen=True)
class ResumenCamino:
    """Lo que hace falta para clasificar un camino sin volver a Cromo. Se cachea en `extremos`.

    `odfs` son todas las ODFs que toca (extremos e intermedias) y `cables` los cables que recorren
    sus pelos: dos hilos del mismo servicio recorren (casi) los mismos cables.

    `botellas` son las botellas de sus fusiones y `botella_inicio`/`botella_fin` la primera y la
    última en el orden del `.txt` (los empalmes extremos). Las usa la auditoría de huérfanos para
    ver si un residual va en paralelo a un tramo. Una entrada de caché anterior a estos campos los
    trae vacíos: la auditoría sólo pierde esas dos señales, nada se rompe.
    """

    inicio: Optional[ExtremoCamino] = None
    fin: Optional[ExtremoCamino] = None
    odfs: tuple[int, ...] = ()
    cables: tuple[int, ...] = ()
    servicio_at62: Optional[str] = None
    botellas: tuple[int, ...] = ()
    botella_inicio: Optional[int] = None
    botella_fin: Optional[int] = None

    @property
    def extremos(self) -> tuple[ExtremoCamino, ...]:
        return tuple(e for e in (self.inicio, self.fin) if e is not None)

    def a_json(self) -> dict[str, Any]:
        return {
            "servicio_at62": self.servicio_at62,
            "inicio": asdict(self.inicio) if self.inicio else None,
            "fin": asdict(self.fin) if self.fin else None,
            "odfs": list(self.odfs),
            "cables": list(self.cables),
            "botellas": list(self.botellas),
            "botella_inicio": self.botella_inicio,
            "botella_fin": self.botella_fin,
        }

    @classmethod
    def desde_json(cls, datos: Any) -> Optional["ResumenCamino"]:
        """Reconstruye el resumen cacheado, o `None` si la fila está corrupta (se trata como miss)."""
        if not isinstance(datos, Mapping):
            return None
        try:
            return cls._desde_json(datos)
        except (TypeError, ValueError):
            logger.warning("action=cromo_tracking evento=extremos_corruptos datos=%r", datos)
            return None

    @classmethod
    def _desde_json(cls, datos: Mapping[str, Any]) -> "ResumenCamino":
        def _extremo(crudo: Any) -> Optional[ExtremoCamino]:
            if not isinstance(crudo, Mapping):
                return None
            campos = {k: crudo.get(k) for k in ExtremoCamino.__dataclass_fields__}
            if campos["tipo"] is None or campos["id_cromo"] is None:
                return None
            campos["id_cromo"] = int(campos["id_cromo"])
            for clave in ("clase", "odf_id", "odf_clase", "pelo_conectado"):
                if campos[clave] is not None:
                    campos[clave] = int(campos[clave])
            return ExtremoCamino(**campos)

        return cls(
            inicio=_extremo(datos.get("inicio")),
            fin=_extremo(datos.get("fin")),
            odfs=tuple(int(x) for x in datos.get("odfs") or ()),
            cables=tuple(int(x) for x in datos.get("cables") or ()),
            servicio_at62=datos.get("servicio_at62"),
            botellas=tuple(int(x) for x in datos.get("botellas") or ()),
            botella_inicio=_entero_o_none(datos.get("botella_inicio")),
            botella_fin=_entero_o_none(datos.get("botella_fin")),
        )


def _entero_o_none(valor: Any) -> Optional[int]:
    return None if valor is None else int(valor)


@dataclass(slots=True)
class TrackingGenerado:
    pelo_n_id: int
    nombre_archivo: str
    contenido: str
    desde_cache: bool
    generado_at: datetime
    duracion_ms: Optional[int]
    # Pelos que recorre el camino, incluido el propio. Vacío sólo en fakes de tests viejos.
    pelos_camino: frozenset[int] = frozenset()
    # Extremos y resumen del camino. `None` sólo en fakes de tests: se clasifica como sin ODF.
    extremos: Optional[ResumenCamino] = None
    # VIGENTE | TRAMO | ADICIONAL | RESIDUAL. Lo asigna `trackings_del_servicio` con
    # `clasificar_con_posiciones`.
    rol: Optional[str] = None


_CLASE_PELO = 130


def _extremo_de_nodo(nodo: NodoCamino) -> ExtremoCamino:
    return ExtremoCamino(
        tipo=nodo.tipo,
        id_cromo=nodo.id_cromo,
        clase=nodo.clase,
        odf_id=nodo.odf_id,
        odf_clase=nodo.odf_clase,
        odf_nombre=nodo.odf_nombre,
        patchera_nombre=nodo.patchera_nombre,
        conector_numero=nodo.conector_numero,
        servicio_at62=nodo.servicio_at62,
        pelo_conectado=nodo.pelo_conectado,
    )


def resumen_del_camino(camino: CaminoOptico) -> ResumenCamino:
    """Extremos (primer y último nodo del `.txt`), ODFs tocadas y cables recorridos. Función pura."""
    secuencia = secuencia_para_tracking(camino)
    nodos = [*camino.lado_a, *camino.lado_b]
    if camino.raiz is not None:
        nodos.append(camino.raiz)
    odfs = sorted({n.odf_id for n in nodos if n.tipo == TIPO_CONECTOR_ODF and n.odf_id})
    cables = sorted({n.cable_id for n in nodos if n.clase == _CLASE_PELO and n.cable_id})
    # Botellas de las fusiones en el orden del `.txt`: la primera y la última son los empalmes
    # extremos del camino.
    botellas_en_orden = [n.botella_id for n in secuencia if n.botella_id]
    return ResumenCamino(
        inicio=_extremo_de_nodo(secuencia[0]) if secuencia else None,
        fin=_extremo_de_nodo(secuencia[-1]) if secuencia else None,
        odfs=tuple(odfs),
        cables=tuple(cables),
        servicio_at62=camino.servicio_at62,
        botellas=tuple(sorted(set(botellas_en_orden))),
        botella_inicio=botellas_en_orden[0] if botellas_en_orden else None,
        botella_fin=botellas_en_orden[-1] if botellas_en_orden else None,
    )


def pelos_del_camino(camino: CaminoOptico) -> frozenset[int]:
    """Pelos (clase 130) que recorre el camino: el consultado más los de `a[]` y `b[]`.

    Es lo que identifica al camino. Dos semillas del mismo hilo —la posición en la ODF de un
    extremo y la de una ODF intermedia— recorren los mismos pelos, y una aparece en el camino de
    la otra."""
    pelos = {n.id_cromo for n in (*camino.lado_a, *camino.lado_b) if n.clase == _CLASE_PELO}
    if camino.pelo_n_id is not None:
        pelos.add(camino.pelo_n_id)
    return frozenset(pelos)


async def obtener_tracking(
    cliente: CromoClient,
    sesion: AsyncSession,
    *,
    servicio_id: Optional[int],
    pelo_n_id: int,
    forzar: bool = False,
) -> TrackingGenerado:
    """Tracking `.txt` de un pelo: del caché si está fresco, o generado y cacheado.

    `forzar=True` saltea la lectura del caché pero igual reescribe la entrada — es la vía para
    regenerar a mano un tracking que quedó viejo antes de vencer.

    `servicio_id` es a quién se atribuye la entrada del caché. `None` para un pelo que no es del
    Servicio por etiqueta ni por declaración (una posición posible, `track odf`): el upsert conserva
    el servicio que ya tuviera la fila (`tracking_cache.guardar`).

    Hace `commit` de la entrada de caché apenas la escribe, para que una descarga de varios pelos
    no pierda lo ya resuelto si un pelo posterior falla.
    """
    if not forzar:
        cacheado = await tracking_cache.leer(sesion, pelo_n_id)
        # Una entrada sin `pelos_camino` o sin `extremos` es anterior a esas columnas: sin la lista
        # no se pueden descartar caminos repetidos y sin los extremos no se puede clasificar el
        # camino como TRAMO o RESIDUAL, así que se regenera (una sola vez, queda guardada).
        # Una fila con `extremos` corruptos (`desde_json` → `None`) también es un miss.
        resumen_cacheado = (
            ResumenCamino.desde_json(cacheado.extremos)
            if cacheado is not None and cacheado.extremos is not None
            else None
        )
        if (
            cacheado is not None
            and cacheado.pelos_camino is not None
            and resumen_cacheado is not None
        ):
            logger.info(
                "action=cromo_tracking origen=cache servicio_id=%s pelo_n_id=%s generado_at=%s",
                servicio_id,
                pelo_n_id,
                cacheado.generado_at,
            )
            return TrackingGenerado(
                pelo_n_id=cacheado.pelo_n_id,
                nombre_archivo=cacheado.nombre_archivo,
                contenido=cacheado.contenido,
                desde_cache=True,
                generado_at=cacheado.generado_at,
                duracion_ms=cacheado.duracion_ms,
                pelos_camino=frozenset(cacheado.pelos_camino),
                extremos=resumen_cacheado,
            )

    camino = await resolver_camino_de_pelo(cliente, sesion, pelo_n_id)
    if camino.estado != ESTADO_OK:
        raise TrackingNoDisponible(camino.motivo, camino.estado)

    ahora = datetime.now(timezone.utc)
    nombre = nombre_archivo_tracking(camino.servicio_at62, camino.pelo_n_id or pelo_n_id)
    contenido = renderizar_tracking_txt(camino, generado_en=ahora)
    pelos_camino = pelos_del_camino(camino) | {pelo_n_id}
    resumen = resumen_del_camino(camino)

    await tracking_cache.guardar(
        sesion,
        pelo_n_id=pelo_n_id,
        servicio_id=servicio_id,
        nombre_archivo=nombre,
        contenido=contenido,
        duracion_ms=camino.duracion_ms,
        pelos_camino=sorted(pelos_camino),
        extremos=resumen.a_json(),
        ahora=ahora,
    )
    await sesion.commit()

    logger.info(
        "action=cromo_tracking origen=cromo servicio_id=%s pelo_n_id=%s nodos=%s duracion_ms=%s",
        servicio_id,
        pelo_n_id,
        camino.estadisticas.nodos,
        camino.duracion_ms,
    )
    return TrackingGenerado(
        pelo_n_id=pelo_n_id,
        nombre_archivo=nombre,
        contenido=contenido,
        desde_cache=False,
        generado_at=ahora,
        duracion_ms=camino.duracion_ms,
        pelos_camino=pelos_camino,
        extremos=resumen,
    )


@dataclass(slots=True)
class TrackingsPorCamino:
    """`omitidos` es `{semilla descartada: pelo cuyo camino ya la recorría}`, para el log.

    `no_cubiertos` son las semillas que no quedaron en ningún camino generado: las que fallaron y,
    si se tocó un tope, las que no se llegaron a pedir. `completo` dice si el recorrido terminó sin
    tocar `max_llamadas` ni `max_fallidos`; `tope_llamadas` dice si el que se tocó fue el de
    llamadas (para no culpar al tope cuando el corte fue por semillas fallidas). `llamadas` cuenta
    las que fueron a Cromo (lo servido del caché no cuenta).
    """

    trackings: list[TrackingGenerado] = field(default_factory=list)
    omitidos: dict[int, int] = field(default_factory=dict)
    errores: list[str] = field(default_factory=list)
    no_cubiertos: list[int] = field(default_factory=list)
    completo: bool = True
    tope_llamadas: bool = False
    llamadas: int = 0


async def trackings_por_camino(
    cliente: CromoClient,
    sesion: AsyncSession,
    *,
    servicio_id: int,
    pelos_n_id: Iterable[int],
    max_fallidos: Optional[int] = None,
    max_llamadas: Optional[int] = None,
) -> TrackingsPorCamino:
    """Un tracking por camino distinto, no uno por semilla, hasta cubrir **todas** las semillas.

    Las semillas por defecto son las posiciones de ODF del Servicio, y un hilo tiene posición en
    cada ODF que atraviesa —extremos e intermedias, propias o de cables de terceros—. Caso real,
    Servicio 42351: dos hilos, posiciones en TASA, TECO y Facebook. El operador espera 2 `.txt`
    con el camino completo, no uno por ODF.

    Se recorren en orden; una semilla que ya aparece en el camino de una anterior se descarta
    **sin** pedirla a Cromo. Un pelo que falla no cancela los demás. `CromoClientError` no se
    atrapa: Cromo caído se lleva la corrida entera y lo reporta el llamador.

    Ya no se corta en los caminos esperados (2026-10-16): Cromo corta `/path` en una ODF Nodo sin
    patch, así que un servicio segmentado tiene más caminos que la moda de pelos por cable, y
    cortar perdía tramos reales (Servicio 102452: 27 caminos sobre 217 pelos). Qué camino es tramo
    y cuál residual lo decide después `clasificar_caminos`. Los frenos son `max_llamadas` (tope de
    llamadas a Cromo) y `max_fallidos` (semillas fallidas toleradas); tocar cualquiera de los dos
    con semillas todavía sin cubrir deja el resultado `completo=False`.
    """
    resultado = TrackingsPorCamino()
    cubiertos: dict[int, int] = {}
    semillas = list(dict.fromkeys(pelos_n_id))
    fallidos: set[int] = set()
    for pelo_n_id in semillas:
        if pelo_n_id in cubiertos:
            resultado.omitidos[pelo_n_id] = cubiertos[pelo_n_id]
            continue
        if max_fallidos is not None and len(fallidos) >= max_fallidos:
            resultado.completo = False
            break
        if max_llamadas is not None and resultado.llamadas >= max_llamadas:
            resultado.completo = False
            resultado.tope_llamadas = True
            break
        try:
            tracking = await obtener_tracking(
                cliente, sesion, servicio_id=servicio_id, pelo_n_id=pelo_n_id
            )
        except TrackingNoDisponible as exc:
            resultado.llamadas += 1
            resultado.errores.append(f"Pelo {pelo_n_id}: {exc.motivo}")
            fallidos.add(pelo_n_id)
            continue
        if not tracking.desde_cache:
            resultado.llamadas += 1
        resultado.trackings.append(tracking)
        for pelo in tracking.pelos_camino | {pelo_n_id}:
            cubiertos.setdefault(pelo, pelo_n_id)

    resultado.no_cubiertos = [p for p in semillas if p not in cubiertos]

    if resultado.omitidos:
        logger.info(
            "action=cromo_tracking evento=caminos_repetidos servicio_id=%s omitidos=%s",
            servicio_id,
            len(resultado.omitidos),
        )
    if not resultado.completo:
        logger.warning(
            "action=cromo_tracking evento=tope_alcanzado servicio_id=%s llamadas=%s fallidos=%s "
            "no_cubiertos=%s",
            servicio_id,
            resultado.llamadas,
            len(fallidos),
            len(resultado.no_cubiertos),
        )
    return resultado


# ── Clasificación TRAMO / RESIDUAL ────────────────────────────────────────────────────────────
#
# Umbrales medidos el 2026-10-16 contra Cromo real sobre los Servicios 102452, 42351, 93154 y
# 94673 (los 77 caminos medidos están en tests/test_cromo_tracking_clasificacion.py):
#
# - Un "par" es otro camino que recorre (casi) los mismos cables. Los dos hilos de 42351 no
#   recorren exactamente los mismos (155 y 165 cables, Jaccard 0,86), así que la igualdad exacta
#   lo perdía; el mejor Jaccard entre caminos que NO son par fue 0,33. Corte: 0,8.
# - Proporción mínima de pelos respecto del camino candidato más largo. Tramos reales: 24/47 =
#   0,51 (102452) como mínimo; residuales con par y extremo en ODF: 8/99 = 0,08 (93154) y 3/47 =
#   0,06 (102452) como máximo. Corte: 0,25.
_JACCARD_PAR_MINIMO = 0.8
_PROPORCION_PELOS_MINIMA = 0.25
CLASES_ODF_EXTREMO = frozenset({69, 86})  # 69 = ODF, 86 = ODF Nodo


def _jaccard(a: frozenset[int], b: frozenset[int]) -> float:
    # Dos caminos sin cables no son evidencia de par: un pelo suelto sin cable resuelto.
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _son_par(a: frozenset[int], b: frozenset[int]) -> bool:
    """Dos caminos son par (hilos del mismo recorrido) si recorren (casi) los mismos cables."""
    return _jaccard(a, b) >= _JACCARD_PAR_MINIMO


def contar_segmentos(tramos: Sequence[TrackingGenerado]) -> int:
    """Cuántos segmentos físicos cubren los tramos: grupos de tramos que son par entre sí. Pura.

    Los dos hilos de un mismo recorrido (42351: 2 trackings) son UN segmento; un servicio cortado
    por una ODF Nodo sin patch (102452: 3 pares, 6 trackings) son 3. El par es el mismo de
    `clasificar_caminos` (Jaccard de cables >= 0,8), con cierre transitivo.
    """
    cables = [frozenset(_resumen(t).cables) for t in tramos]
    grupo = list(range(len(tramos)))

    def _raiz(i: int) -> int:
        while grupo[i] != i:
            grupo[i] = grupo[grupo[i]]
            i = grupo[i]
        return i

    for i in range(len(tramos)):
        for j in range(i + 1, len(tramos)):
            if _son_par(cables[i], cables[j]):
                grupo[_raiz(i)] = _raiz(j)
    return len({_raiz(i) for i in range(len(tramos))})


def _resumen(tracking: TrackingGenerado) -> ResumenCamino:
    return tracking.extremos or ResumenCamino()


def _termina_en_odf(resumen: ResumenCamino) -> bool:
    """Al menos un extremo en un conector de ODF (69) u ODF Nodo (86).

    Sin clase conocida (payload sin `class` en el `gfather`) alcanza con que el conector tenga
    ODF: se prefiere no perder un tramo a descartarlo por un dato faltante.
    """
    return any(
        e.es_conector_odf and (e.odf_clase is None or e.odf_clase in CLASES_ODF_EXTREMO)
        for e in resumen.extremos
    )


def _odfs_de_extremos(resumen: ResumenCamino) -> set[int]:
    """Ids de las ODF donde termina el camino (conectores de ODF en sus extremos)."""
    return {e.odf_id for e in resumen.extremos if e.es_conector_odf and e.odf_id is not None}


def clasificar_caminos(
    caminos: Sequence[TrackingGenerado],
    odfs_confirmadas: frozenset[int] = frozenset(),
) -> list[str]:
    """Rol de cada camino (`TRAMO` o `RESIDUAL`), en el mismo orden. Función pura.

    1. Una ODF confirmada del Servicio rescata al camino que TERMINA en ella (un extremo en un
       conector de esa ODF) y no es ruido chico (pasa la proporción del punto 3): es `TRAMO`
       aunque no tenga par. Pasar por la ODF en el medio no alcanza, y un camino de 2-3 pelos
       que termina en ella sigue siendo ruido. Medido en dev (2026-10-18, 102452): con la regla
       anterior ("toca una ODF confirmada") confirmar KORN y los racks de Dixon pasaba de 6 a 12
       trackings, todos caminos de 2-3 pelos.
    2. Candidatos: los caminos con al menos un extremo en un conector de ODF u ODF Nodo — así
       quedan protegidas las FO que salen de una ODF Nodo y no terminan en otra ODF (102452). Si
       ningún camino termina en ODF (94673, o un servicio cuyas ODFs son sólo intermedias),
       todos los caminos no confirmados son candidatos.
    3. Primero la proporción: pasan los candidatos con al menos el 25% de los pelos del más
       largo. Así el ruido chico (pares de 1-8 pelos) no decide nada.
    4. Después el par, sólo entre los que pasaron: si alguno tiene par (otro con los mismos
       cables, Jaccard >= 0,8), el servicio es bifilar y sólo son `TRAMO` los que tienen par. Si
       ninguno tiene par (servicio monofilar, PON), todos los que pasaron son `TRAMO`.
    5. El resto es `RESIDUAL`.

    Medido real (2026-10-16): da 6 tramos en 102452 (3 pares), 2 en 42351, 2 en 93154 y 2 en
    94673. La regla "extremo en ODF" sola daba 10, 3, 7 y 2: pares chicos de 1-8 pelos con
    extremo en ODF y caminos largos sin par (93154: 65 y 36 pelos) que no son los hilos del
    servicio.
    """
    resumenes = [_resumen(c) for c in caminos]
    roles = [ROL_RESIDUAL] * len(caminos)

    todos = list(range(len(caminos)))
    # Si ningún camino TERMINA en ODF (las ODFs intermedias no cuentan), todos son candidatos.
    candidatos = [i for i in todos if _termina_en_odf(resumenes[i])] or todos
    if not candidatos:
        return roles

    maximo = max(len(caminos[i].pelos_camino) for i in candidatos)
    largos_todos = [
        i for i in candidatos if len(caminos[i].pelos_camino) >= maximo * _PROPORCION_PELOS_MINIMA
    ]
    confirmados = {
        i
        for i in largos_todos
        if odfs_confirmadas and _odfs_de_extremos(resumenes[i]) & odfs_confirmadas
    }
    for i in confirmados:
        roles[i] = ROL_TRAMO

    largos = [i for i in largos_todos if i not in confirmados]
    if not largos:
        return roles
    cables = {i: frozenset(resumenes[i].cables) for i in largos}
    con_par = [
        i
        for i in largos
        if any(j != i and _son_par(cables[i], cables[j]) for j in largos)
    ]
    for i in con_par or largos:
        roles[i] = ROL_TRAMO
    return roles


def _es_extremo_odf(extremo: Optional[ExtremoCamino]) -> bool:
    # Mismo criterio que `_termina_en_odf`: sin clase conocida alcanza con que sea conector de ODF.
    return bool(
        extremo is not None
        and extremo.es_conector_odf
        and (extremo.odf_clase is None or extremo.odf_clase in CLASES_ODF_EXTREMO)
    )


def es_camino_completo(t: TrackingGenerado) -> bool:
    """El camino termina en un conector de ODF (69) u ODF Nodo (86) en sus DOS extremos. Pura.

    Es lo que separa un recorrido real que sale sólo de posiciones (93150: el camino viejo va de
    O-1252871-1:1 a O-1252734-1:11, medido en dev el 2026-10-21) de un camino que corta en un pelo
    (7469850: de un pelo suelto a la ODF de Ramos Mejía, 19 pelos).
    """
    resumen = _resumen(t)
    return _es_extremo_odf(resumen.inicio) and _es_extremo_odf(resumen.fin)


def origen_del_camino(
    t: TrackingGenerado, *, etiquetados: frozenset[int], declarados: frozenset[int]
) -> str:
    """`DECLARADO`, `ETIQUETADO` o `POSICION`, por intersección de pelos. Pura.

    Se mira qué pelos recorre el camino y no qué semilla lo resolvió: el camino nuevo del 93150
    también sale de una posición (O-1239922-1:1), y el resultado no puede depender de cuál de las
    dos semillas se pidió primero. Un camino que toca un pelo declarado es el declarado aunque
    también toque uno etiquetado.
    """
    pelos = t.pelos_camino | {t.pelo_n_id}
    if pelos & declarados:
        return ORIGEN_DECLARADO
    if pelos & etiquetados:
        return ORIGEN_ETIQUETADO
    return ORIGEN_POSICION


def clasificar_con_posiciones(
    caminos: Sequence[TrackingGenerado],
    *,
    etiquetados: frozenset[int],
    declarados: frozenset[int],
    odfs_confirmadas: frozenset[int] = frozenset(),
    de_otro_activo: frozenset[int] = frozenset(),
) -> list[str]:
    """Rol de cada camino (`VIGENTE`, `TRAMO`, `ADICIONAL` o `RESIDUAL`), en el mismo orden. Pura.

    1. `clasificar_caminos` corre SÓLO sobre los caminos de origen `ETIQUETADO`: si entraran los
       de posiciones o el declarado moverían el máximo del 25 % y los pares, y un tramo de hoy podía
       pasar a RESIDUAL. Por lo mismo la ODF confirmada sólo rescata entre los etiquetados.
    2. `DECLARADO` es `VIGENTE`.
    3. `ETIQUETADO` lleva el rol de `clasificar_caminos`; si algún camino es `DECLARADO` (la
       declaración se aplicó), sus `TRAMO` pasan a `ADICIONAL`: siguen siendo un recorrido real,
       pero el servicio va por el vigente.
    4. `POSICION` es `ADICIONAL` si es un camino completo (ODF en los dos extremos) y `RESIDUAL`
       si no, o si recorre algún pelo de `de_otro_activo` (pelos que matchean a otro servicio
       Activo y no a este, `pelos_de_otro_servicio_activo`): el filtro de las posiciones sólo mira
       el pelo semilla, y el camino puede ser el de otro Activo. No aplica al `DECLARADO` (decisión
       explícita del admin) ni al `ETIQUETADO`.

    Con `declarados` vacío y todas las semillas etiquetadas da exactamente lo mismo que
    `clasificar_caminos` (regresión sobre los 77 caminos medidos).
    """
    origenes = [
        origen_del_camino(c, etiquetados=etiquetados, declarados=declarados) for c in caminos
    ]
    indices_etiquetados = [i for i, o in enumerate(origenes) if o == ORIGEN_ETIQUETADO]
    roles_etiquetados = dict(
        zip(
            indices_etiquetados,
            clasificar_caminos(
                [caminos[i] for i in indices_etiquetados], odfs_confirmadas=odfs_confirmadas
            ),
        )
    )
    hay_vigente = ORIGEN_DECLARADO in origenes

    roles: list[str] = []
    for i, (camino, origen) in enumerate(zip(caminos, origenes)):
        if origen == ORIGEN_DECLARADO:
            roles.append(ROL_VIGENTE)
        elif origen == ORIGEN_ETIQUETADO:
            rol = roles_etiquetados[i]
            roles.append(ROL_ADICIONAL if hay_vigente and rol == ROL_TRAMO else rol)
        elif _pelos_de_tracking(camino) & de_otro_activo:
            roles.append(ROL_RESIDUAL)
        else:
            roles.append(ROL_ADICIONAL if es_camino_completo(camino) else ROL_RESIDUAL)
    return roles


def ordenar_tramos(tramos: Iterable[TrackingGenerado]) -> list[TrackingGenerado]:
    """Orden estable de los tramos: más pelos primero, y a igual cantidad, menor `pelo_n_id`."""
    return sorted(tramos, key=lambda t: (-len(t.pelos_camino), t.pelo_n_id))


@dataclass(slots=True, frozen=True)
class InfoAdicional:
    """Por qué posición sale un camino adicional y qué etiqueta llevan sus pelos, para el aviso.

    `posiciones` son pares `(patchera, conector)` (`etiqueta_posiciones` los junta en
    `"O-1252871-1:1,2"`); `etiquetas`, el `servicio_numero` de los pelos de esas posiciones
    (`"44649"` en el 93150). `origen` es el de `origen_del_camino`.
    """

    pelo_n_id: int
    origen: str
    posiciones: tuple[tuple[str, str], ...] = ()
    etiquetas: tuple[str, ...] = ()


@dataclass(slots=True)
class EstadoPosicion:
    """La posición vigente declarada del Servicio en esta corrida.

    `declaradas` son las vigentes después de los retiros de esta corrida; `aplicada` dice si sus
    caminos se usaron como VIGENTE (si no, la corrida usó el cálculo automático); `etiqueta` es
    `"O-1252871-1:1,2"` de las declaradas; `avisos`, lo que el operador tiene que saber (retiros,
    camino no resuelto o incompleto, pelo dañado sin alternativa).
    """

    declaradas: list[PosicionDeclarada] = field(default_factory=list)
    aplicada: bool = False
    etiqueta: str = ""
    avisos: list[AvisoPosicion] = field(default_factory=list)


@dataclass(slots=True)
class TrackingsDelServicio:
    """Los caminos de un Servicio separados en tramos, adicionales y residuales.

    `tramos` ya vienen ordenados (`ordenar_tramos`) y con su nombre de archivo de tramo: son los
    VIGENTE si se aplicó una posición declarada, o los TRAMO si no. `adicionales` son recorridos
    reales del Servicio que no son por donde va (`{n} CROMO A{k} pelo X.txt`), alineados con
    `info_adicionales`; `caminos_resueltos` = tramos ∪ adicionales (lo que sube `track N full`;
    nunca descarta un tramo, aunque termine en un pelo). `residuales` conservan el nombre de siempre.
    `esperados_declarados` es la cantidad de tramos que declaró el operador
    (`servicios.trackings_esperados`, `None` si no declaró); `odf_confirmadas` son las ODF
    confirmadas vigentes del Servicio. `completo` = no se tocó el tope de llamadas ni el de fallidos
    con semillas etiquetadas pendientes; `tope_llamadas` = se tocó el de llamadas. `no_cubiertos` son
    las semillas etiquetadas que no quedaron en ningún camino (fallaron o no se llegaron a pedir):
    con `completo=True` también puede haberlas, y ahí puede faltar un tramo entero. Las fallas de
    los pelos declarados y de las posiciones van aparte (`errores_posiciones`,
    `no_cubiertos_posiciones`): no hacen al resultado incompleto. `segmentos` son los grupos de
    tramos que comparten cables (`contar_segmentos`). `auditoria` es el resumen de la auditoría de
    huérfanos que corre al final (`None` si no corrió o falló).
    """

    tramos: list[TrackingGenerado]
    residuales: list[TrackingGenerado]
    errores: list[str]
    completo: bool
    esperados_declarados: Optional[int] = None
    odf_confirmadas: list[dict[str, Any]] = field(default_factory=list)
    auditoria: Optional[Any] = None
    no_cubiertos: list[int] = field(default_factory=list)
    tope_llamadas: bool = False
    segmentos: int = 0
    # Por qué no se auditó (`"INCOMPLETO"`: tope tocado, semillas fallidas o sin cubrir); `None` si
    # se auditó o si no se pidió auditar.
    auditoria_omitida: Optional[str] = None
    adicionales: list[TrackingGenerado] = field(default_factory=list)
    info_adicionales: list[InfoAdicional] = field(default_factory=list)
    caminos_resueltos: list[TrackingGenerado] = field(default_factory=list)
    posicion: EstadoPosicion = field(default_factory=EstadoPosicion)
    errores_posiciones: list[str] = field(default_factory=list)
    no_cubiertos_posiciones: list[int] = field(default_factory=list)


_SQL_NUMERO_SERVICIO = text("SELECT servicio_id FROM app.servicios WHERE id = :servicio_id")


async def numero_del_servicio(sesion: AsyncSession, servicio_id: int) -> Optional[str]:
    """El número vigente del Servicio en LAS-FOCAS, para nombrar los `.txt` de tramo.

    No se usa el at.62 del pelo: medido en dev (2026-10-17) el 42351 salía "42352 CROMO" y un hilo
    del 93154 "83254 CROMO". El parser de trackings legacy toma el servicio del NOMBRE del archivo,
    así que un at.62 mal cargado en Cromo asignaría el tracking a otro Servicio.
    """
    valor = (await sesion.execute(_SQL_NUMERO_SERVICIO, {"servicio_id": servicio_id})).scalar_one_or_none()
    return str(valor).strip() if valor is not None else None


# Qué posiciones entran como semillas en `trackings_del_servicio`. Web y Slack usan "todas"; la
# corrida global de auditoría, "declaradas": de los 50 servicios que recorre sólo 7 sumaban semillas
# de posiciones (10 pelos, 46-140 s más por corrida) que no aportan nada a la auditoría.
POSICIONES_TODAS = "todas"
POSICIONES_DECLARADAS = "declaradas"
POSICIONES_NINGUNA = "ninguna"
_MODOS_POSICIONES = (POSICIONES_TODAS, POSICIONES_DECLARADAS, POSICIONES_NINGUNA)


async def posiciones_del_servicio(
    sesion: AsyncSession, servicio_id: int, modo: str
) -> tuple[list[PosicionPosible], list[PosicionDeclarada]]:
    """`(posibles, declaradas vigentes)` según el modo. Único punto de lectura de posiciones.

    "declaradas" no consulta las posibles; "ninguna" no lee nada. `ValueError` con otro modo.
    """
    if modo not in _MODOS_POSICIONES:
        raise ValueError(f"Modo de posiciones inválido {modo!r}: debe ser uno de {', '.join(_MODOS_POSICIONES)}.")
    if modo == POSICIONES_NINGUNA:
        return [], []
    declaradas = await listar_declaradas(sesion, servicio_id)
    posibles = await posiciones_posibles(sesion, servicio_id) if modo == POSICIONES_TODAS else []
    return posibles, declaradas


async def _por_camino_en_fases(
    cliente: CromoClient,
    sesion: AsyncSession,
    fases: Sequence[tuple[Optional[int], Sequence[int]]],
) -> list[TrackingsPorCamino]:
    """`trackings_por_camino` fase por fase, compartiendo los topes y lo ya recorrido.

    Cada fase es `(servicio_id del caché, pelos)`. Un pelo que ya recorrió un camino de una fase
    anterior no se vuelve a pedir. Uno que falló en una fase anterior tampoco (sería otra llamada
    de 4,6-14 s a Cromo con el mismo resultado), pero sigue contando en cada fase que lo pide: si
    ningún camino de esa fase lo recorre, va a sus `errores` (con el motivo original) y a sus
    `no_cubiertos`. Así una semilla etiquetada que también estaba declarada y falló como declarada
    deja la fase de etiquetadas incompleta, en vez de darse por vista. Uno que no se llegó a pedir
    por un tope vuelve a entrar en la fase siguiente (que, con el tope agotado, lo deja sin
    cubrir). Los topes de llamadas y de fallidas son los de una sola corrida: cada fase recibe lo
    que dejaron las anteriores. Separar las fases es lo que permite contar aparte las fallas de las
    semillas declaradas y de las posiciones, y cachear las posiciones sin servicio. Con una sola
    fase es exactamente `trackings_por_camino`.
    """
    max_llamadas = tracking_max_llamadas()
    llamadas = 0
    fallidas = 0
    cubiertos: set[int] = set()
    fallidos: dict[int, str] = {}  # pelo → error de la fase en que falló
    resultados: list[TrackingsPorCamino] = []
    for servicio_cache, pelos in fases:
        pedidos = [p for p in dict.fromkeys(pelos) if p not in cubiertos]
        ya_fallidos = [p for p in pedidos if p in fallidos]
        pendientes = [p for p in pedidos if p not in fallidos]
        if pendientes:
            resultado = await trackings_por_camino(
                cliente,
                sesion,
                servicio_id=servicio_cache,
                pelos_n_id=pendientes,
                max_fallidos=_MAX_FALLIDOS_TOLERADOS - fallidas,
                max_llamadas=max_llamadas - llamadas,
            )
        else:
            resultado = TrackingsPorCamino()
        llamadas += resultado.llamadas
        fallidas += len(resultado.errores)
        for tracking in resultado.trackings:
            cubiertos.update(tracking.pelos_camino | {tracking.pelo_n_id})
        for error in resultado.errores:
            pelo = _pelo_del_error(error)
            if pelo is not None and pelo not in cubiertos:
                fallidos.setdefault(pelo, error)
        for pelo in ya_fallidos:
            if pelo not in cubiertos:
                resultado.errores.append(fallidos[pelo])
                resultado.no_cubiertos.append(pelo)
        resultados.append(resultado)
    return resultados


def _pelo_del_error(error: str) -> Optional[int]:
    """El pelo de un error de `trackings_por_camino` (`"Pelo 7028862: motivo"`), o `None`."""
    cabeza, _, _ = error.partition(":")
    numero = cabeza.removeprefix("Pelo ").strip()
    return int(numero) if numero.lstrip("-").isdigit() else None


def _pelos_de_tracking(t: TrackingGenerado) -> frozenset[int]:
    return t.pelos_camino | {t.pelo_n_id}


def _es_posicion_del_extremo(p: PosicionPosible, e: ExtremoCamino) -> bool:
    if e.id_cromo == p.conector_n_id:
        return True
    # Por nombre sólo dentro de la misma ODF: hay patcheras con el mismo nombre en ODF distintas
    # (O-1249273-1 en 6644107 y 9193140).
    return bool(
        e.patchera_nombre
        and e.patchera_nombre == p.bandeja_nombre
        and e.conector_numero == p.numero_conector
        and (e.odf_id is None or e.odf_id == p.odf_n_id)
    )


def describir_adicionales(
    adicionales: Sequence[TrackingGenerado],
    tramos: Sequence[TrackingGenerado],
    posibles: Sequence[PosicionPosible],
    origenes: Sequence[str],
) -> list[InfoAdicional]:
    """Por qué posición sale cada adicional y con qué etiqueta, alineado con `adicionales`. Pura.

    Se miran los extremos del camino que son conector de ODF, salvo los que están en una ODF donde
    termina algún tramo (ahí el adicional no se distingue del tramo; si no queda ninguno, se usan
    todos). Las posiciones son las posibles de esos conectores; si ninguno es posición posible,
    el propio conector del extremo. Las etiquetas son las `etiqueta_pelo` de esas posiciones.
    """
    odfs_de_tramos: set[int] = set()
    for t in tramos:
        odfs_de_tramos |= _odfs_de_extremos(_resumen(t))
    infos: list[InfoAdicional] = []
    for camino, origen in zip(adicionales, origenes):
        extremos = [e for e in _resumen(camino).extremos if e.es_conector_odf]
        propios = [e for e in extremos if e.odf_id not in odfs_de_tramos] or extremos
        coinciden = [p for e in propios for p in posibles if _es_posicion_del_extremo(p, e)]
        if coinciden:
            pares = [(p.bandeja_nombre, p.numero_conector) for p in coinciden]
        else:
            pares = [(e.patchera_nombre, e.conector_numero) for e in propios]
        infos.append(
            InfoAdicional(
                pelo_n_id=camino.pelo_n_id,
                origen=origen,
                posiciones=tuple(dict.fromkeys((a, b) for a, b in pares if a and b)),
                etiquetas=tuple(dict.fromkeys(p.etiqueta_pelo for p in coinciden if p.etiqueta_pelo)),
            )
        )
    return infos


def _aviso_de_camino(d: PosicionDeclarada, codigo: str, **detalle: Any) -> AvisoPosicion:
    return AvisoPosicion(
        conector_n_id=d.conector_n_id,
        posicion=d.posicion,
        codigo=codigo,
        retirada=False,
        declaracion_id=d.id,
        pelo_declarado=d.pelo_declarado,
        detalle=detalle,
    )


async def _validar_caminos_declarados(
    sesion: AsyncSession,
    declaradas: Sequence[PosicionDeclarada],
    caminos: Sequence[TrackingGenerado],
    errores: Sequence[str],
) -> list[AvisoPosicion]:
    """Un aviso por declarada cuyo camino no sirve como VIGENTE en esta corrida.

    `CAMINO_NO_RESUELTO` (Cromo no lo resolvió o no se llegó a pedir) y `CAMINO_INCOMPLETO` (no
    termina en ODF en los dos extremos) nunca retiran. `PELO_DANADO` y `CABLE_SIN_USO` retiran
    sólo si hay otro camino completo sano (`decidir_retiro`); como alternativa no cuentan los
    caminos de las otras declaradas (el otro hilo del mismo par no es "otro camino").
    """
    pelos_declarados = {d.pelo_declarado for d in declaradas}
    alternativos = [c for c in caminos if not _pelos_de_tracking(c) & pelos_declarados]
    avisos: list[AvisoPosicion] = []
    for d in declaradas:
        camino = next((c for c in caminos if d.pelo_declarado in _pelos_de_tracking(c)), None)
        if camino is None:
            motivo = next((e for e in errores if e.startswith(f"Pelo {d.pelo_declarado}:")), None)
            avisos.append(
                _aviso_de_camino(d, AVISO_CAMINO_NO_RESUELTO, motivo=motivo or "no se llegó a pedir")
            )
        elif not es_camino_completo(camino):
            avisos.append(_aviso_de_camino(d, AVISO_CAMINO_INCOMPLETO, pelo=camino.pelo_n_id))
        else:
            aviso = await validar_camino(sesion, d, camino)
            if aviso is not None:
                avisos.append(
                    await decidir_retiro(
                        sesion,
                        aviso,
                        declarado=camino,
                        caminos=alternativos,
                        es_completo=es_camino_completo,
                    )
                )
    return avisos


def _impide_aplicar(aviso: AvisoPosicion) -> bool:
    # Un pelo dañado sin alternativa sana se avisa pero se usa: no hay un camino mejor.
    return aviso.retirada or aviso.codigo in (AVISO_CAMINO_NO_RESUELTO, AVISO_CAMINO_INCOMPLETO)


async def _aplicar_retiros_sin_romper(
    sesion: AsyncSession, servicio_id: int, avisos: Sequence[AvisoPosicion]
) -> None:
    """Retira las declaradas marcadas, cada una en su transacción. Nunca levanta: el tracking ya
    está resuelto y un retiro que falla se vuelve a intentar en la próxima corrida."""
    if not any(a.retirada for a in avisos):
        return
    try:
        retiradas = await aplicar_retiros(sesion, avisos)
    except Exception:  # noqa: BLE001 - el retiro es accesorio al tracking
        logger.exception(
            "action=cromo_posicion_vigente evento=retiro_fallido servicio_id=%s", servicio_id
        )
        await sesion.rollback()
        return
    logger.info(
        "action=cromo_posicion_vigente evento=retiro servicio_id=%s retiradas=%s motivos=%s",
        servicio_id,
        retiradas,
        [a.codigo for a in avisos if a.retirada],
    )


def _etiqueta_de_declaradas(declaradas: Sequence[PosicionDeclarada]) -> str:
    return etiqueta_posiciones(
        (d.bandeja_nombre, d.numero_conector)
        for d in declaradas
        if d.bandeja_nombre and d.numero_conector
    )


async def trackings_del_servicio(
    cliente: CromoClient,
    sesion: AsyncSession,
    servicio_id: int,
    *,
    odfs_confirmadas: Optional[frozenset[int]] = None,
    auditar: bool = True,
    corrida_id: Optional[int] = None,
    fuente_evidencia: str = "WEB",
    posiciones: str = POSICIONES_TODAS,
) -> TrackingsDelServicio:
    """Un camino por semilla no cubierta, clasificado en vigentes/tramos, adicionales y residuales.
    Lo usan Slack, web y la corrida global.

    Semillas, en este orden: los pelos de las posiciones declaradas vigentes, las etiquetadas con
    el Servicio (`semillas_para_tracking`, posiciones de ODF primero) y los pelos de las posiciones
    posibles (`posiciones_posibles`; sólo con `posiciones="todas"`). Las posiciones no declaradas
    se cachean sin servicio. Tope de llamadas: `CROMO_TRACKING_MAX_LLAMADAS` (default 80), uno solo
    para las tres fases; las posiciones van al final, así que nunca le quitan llamadas a las
    etiquetadas.

    Posición vigente (`servicio_posicion_vigente`): antes de resolver, `validar_en_db` marca para
    retiro las declaradas que el inventario ya no sostiene (conector inexistente, sin pelo, pelo
    cambiado); después, `_validar_caminos_declarados` revisa sus caminos. Si alguna declarada
    tiene un aviso que impide usarla, la corrida entera usa el cálculo automático; los retiros se
    aplican al final, cada uno en su transacción. Roles: `clasificar_con_posiciones`.

    Lo declarado por el operador (ODF confirmadas y trackings esperados) se lee de la DB. Si
    `odfs_confirmadas` se pasa explícito, pisa a las de la DB (tests); los esperados siempre salen
    de la DB.

    Al final audita los huérfanos con este mismo resultado, sin volver a Cromo
    (`auditoria_huerfanos.auditar_sin_romper`: savepoint propio, nunca levanta), con vigentes/tramos
    y adicionales como tramos y sólo las semillas etiquetadas. Es el único punto de enganche:
    Slack, el portal y la corrida global (`corrida_id`) pasan por acá. Sólo si las semillas
    etiquetadas resolvieron todo (`completo`, sin fallidas ni sin cubrir): si no, no se escribe ni
    se borra nada y `auditoria_omitida = "INCOMPLETO"`. Las fallas de las declaradas y de las
    posiciones no cuentan.
    """
    declaradas = await declaraciones_del_servicio(sesion, servicio_id)
    confirmadas = declaradas.odf_ids if odfs_confirmadas is None else odfs_confirmadas
    semillas = await semillas_para_tracking(sesion, servicio_id)
    posibles, declaradas_pos = await posiciones_del_servicio(sesion, servicio_id, posiciones)

    avisos = validar_en_db(declaradas_pos)
    invalidas = {a.declaracion_id for a in avisos}
    validas = [d for d in declaradas_pos if d.id not in invalidas]
    etiquetados = [s.pelo_n_id for s in semillas]
    pelos_declarados = list(dict.fromkeys(d.pelo_declarado for d in validas))
    pelos_posiciones = pelos_de_posiciones(posibles)

    if not semillas and not pelos_posiciones and not pelos_declarados:
        await _aplicar_retiros_sin_romper(sesion, servicio_id, avisos)
        return TrackingsDelServicio(
            tramos=[],
            residuales=[],
            errores=[],
            completo=True,
            esperados_declarados=declaradas.trackings_esperados,
            odf_confirmadas=declaradas.confirmadas,
            posicion=EstadoPosicion(declaradas=validas, etiqueta=_etiqueta_de_declaradas(validas), avisos=avisos),
        )

    por_declarados, por_camino, por_posiciones = await _por_camino_en_fases(
        cliente,
        sesion,
        [
            (servicio_id, pelos_declarados),
            (servicio_id, etiquetados),
            (None, pelos_posiciones),
        ],
    )
    caminos = [*por_declarados.trackings, *por_camino.trackings, *por_posiciones.trackings]

    if validas:
        avisos = [
            *avisos,
            *await _validar_caminos_declarados(sesion, validas, caminos, por_declarados.errores),
        ]
    aplicada = bool(validas) and not any(_impide_aplicar(a) for a in avisos)
    retiradas = {a.declaracion_id for a in avisos if a.retirada}
    vigentes_tras_retiro = [d for d in declaradas_pos if d.id not in retiradas]

    declarados = frozenset(pelos_declarados) if aplicada else frozenset()
    etiquetados_set = frozenset(etiquetados)
    # Una sola consulta por corrida, y sólo si hay caminos de origen POSICION: sus pelos de otro
    # servicio Activo los bajan a RESIDUAL (el filtro de las posiciones sólo mira el pelo semilla).
    pelos_de_posicion = frozenset().union(
        *(
            _pelos_de_tracking(c)
            for c in caminos
            if origen_del_camino(c, etiquetados=etiquetados_set, declarados=declarados)
            == ORIGEN_POSICION
        )
    )
    de_otro_activo = (
        await pelos_de_otro_servicio_activo(sesion, servicio_id, pelos_de_posicion)
        if pelos_de_posicion
        else frozenset()
    )
    roles = clasificar_con_posiciones(
        caminos,
        etiquetados=etiquetados_set,
        declarados=declarados,
        odfs_confirmadas=frozenset(confirmadas),
        de_otro_activo=de_otro_activo,
    )
    tramos: list[TrackingGenerado] = []
    adicionales: list[TrackingGenerado] = []
    residuales: list[TrackingGenerado] = []
    for tracking, rol in zip(caminos, roles):
        destino = (
            tramos
            if rol in (ROL_VIGENTE, ROL_TRAMO)
            else adicionales if rol == ROL_ADICIONAL else residuales
        )
        destino.append(replace(tracking, rol=rol))

    numero_servicio = await numero_del_servicio(sesion, servicio_id)
    tramos = [
        replace(
            tracking,
            nombre_archivo=nombre_archivo_tramo(
                numero_servicio or _resumen(tracking).servicio_at62, numero, tracking.pelo_n_id
            ),
        )
        for numero, tracking in enumerate(ordenar_tramos(tramos), start=1)
    ]
    # Los adicionales se nombran SIEMPRE con el número del Servicio, nunca con el at.62: el de los
    # pelos viejos del 93150 es `4649` y el parser legacy lo asignaría a otro servicio.
    adicionales = [
        replace(
            tracking,
            nombre_archivo=nombre_archivo_adicional(numero_servicio, numero, tracking.pelo_n_id),
        )
        for numero, tracking in enumerate(ordenar_tramos(adicionales), start=1)
    ]
    info_adicionales = describir_adicionales(
        adicionales,
        tramos,
        posibles,
        [origen_del_camino(t, etiquetados=etiquetados_set, declarados=declarados) for t in adicionales],
    )

    auditoria = None
    auditoria_omitida: Optional[str] = None
    resuelto_entero = (
        por_camino.completo and not por_camino.no_cubiertos and not por_camino.errores
    )
    if auditar and not resuelto_entero:
        # Con un tope tocado o con semillas que fallaron (aunque sean menos que el tope de
        # fallidas) hay pelos sin camino resuelto: los de un tramo cuya semilla falló podrían
        # quedar como huérfanos (y normalizables). No se escribe ni se borra nada.
        auditoria_omitida = "INCOMPLETO"
        logger.warning(
            "action=cromo_auditoria_huerfanos evento=omitida motivo=incompleto servicio_id=%s "
            "corrida_id=%s completo=%s no_cubiertos=%s errores=%s",
            servicio_id,
            corrida_id,
            por_camino.completo,
            len(por_camino.no_cubiertos),
            len(por_camino.errores),
        )
    elif auditar:
        # Import diferido: `auditoria_huerfanos` importa los tipos de este módulo.
        from core.services.cromo.auditoria_huerfanos import auditar_sin_romper

        # Los adicionales son recorridos reales del Servicio: sus pelos no son huérfanos. Las
        # semillas son sólo las etiquetadas (las de posiciones no tienen la etiqueta del Servicio).
        auditoria = await auditar_sin_romper(
            sesion,
            servicio_id,
            tramos=[*tramos, *adicionales],
            residuales=residuales,
            semillas=etiquetados_set,
            odfs_confirmadas=frozenset(confirmadas),
            corrida_id=corrida_id,
        )
    # Evidencia para el árbitro: los caminos ya resueltos no cuestan otra llamada a Cromo. Nunca
    # levanta (`registrar_y_encolar` traga sus errores).
    from core.services.cromo.arbitro.evidencia import entradas_de_trackings, registrar_y_encolar

    await registrar_y_encolar(
        sesion,
        servicio_id,
        entradas_de_trackings([*tramos, *adicionales, *residuales]),
        completo=resuelto_entero,
        fuente=fuente_evidencia,
    )
    await _aplicar_retiros_sin_romper(sesion, servicio_id, avisos)
    logger.info(
        "action=cromo_tracking evento=clasificacion servicio_id=%s tramos=%s residuales=%s "
        "completo=%s adicionales=%s posicion_aplicada=%s avisos_posicion=%s",
        servicio_id,
        [t.pelo_n_id for t in tramos],
        len(residuales),
        por_camino.completo,
        [t.pelo_n_id for t in adicionales],
        aplicada,
        [a.codigo for a in avisos],
    )
    return TrackingsDelServicio(
        tramos=tramos,
        residuales=residuales,
        errores=por_camino.errores,
        completo=por_camino.completo,
        esperados_declarados=declaradas.trackings_esperados,
        odf_confirmadas=declaradas.confirmadas,
        auditoria=auditoria,
        auditoria_omitida=auditoria_omitida,
        no_cubiertos=por_camino.no_cubiertos,
        tope_llamadas=por_camino.tope_llamadas,
        segmentos=contar_segmentos(tramos),
        adicionales=adicionales,
        info_adicionales=info_adicionales,
        caminos_resueltos=[*tramos, *adicionales],
        posicion=EstadoPosicion(
            declaradas=vigentes_tras_retiro,
            aplicada=aplicada,
            etiqueta=_etiqueta_de_declaradas(vigentes_tras_retiro),
            avisos=avisos,
        ),
        # Sin repetir: un pelo declarado que falló vuelve a contar en la fase de posiciones si
        # ningún camino lo recorrió (`_por_camino_en_fases`).
        errores_posiciones=list(dict.fromkeys([*por_declarados.errores, *por_posiciones.errores])),
        no_cubiertos_posiciones=list(
            dict.fromkeys([*por_declarados.no_cubiertos, *por_posiciones.no_cubiertos])
        ),
    )


# Semillas fallidas toleradas antes de rendirse. Cada una es una llamada de 4,6-14 s a Cromo que no
# aporta camino. Medido real 2026-10-16: 0 fallidas en 102452, 42351, 93154 y 94673 (77 caminos).
_MAX_FALLIDOS_TOLERADOS = 10


def nombre_distinguible(nombre: str, pelo_n_id: int, *, distinguir: bool) -> str:
    """Nombre de archivo que identifica al pelo cuando el Servicio tiene más de uno.

    `nombre_archivo_tracking` deriva el nombre del número de servicio (at.62), así que los N pelos
    de un mismo Servicio devuelven **el mismo** nombre. Bajándolos como archivos sueltos, el
    navegador los guardaría como "93154 CROMO.txt", "93154 CROMO (1).txt"… y se pierde cuál es
    cuál.

    Con `distinguir=False` (el Servicio tiene un solo pelo, el caso PON) el nombre queda idéntico
    al de hoy, así que nada de lo que consume ese `.txt` aguas abajo cambia. Con varios pelos se
    intercala el `n_id`, que es lo que efectivamente los distingue y es el mismo identificador que
    muestra el selector en pantalla.
    """
    if not distinguir or str(pelo_n_id) in nombre:
        # Cuando el at.62 no da un número de servicio plausible, `nombre_archivo_tracking` ya cae a
        # `tracking_cromo_pelo_<n_id>.txt`: volver a intercalar el n_id daría el redundante
        # "tracking_cromo_pelo_6899054 pelo 6899054.txt". Encontrado verificando contra Cromo real.
        return nombre
    raiz, punto, extension = nombre.rpartition(".")
    if not punto:
        return f"{nombre} pelo {pelo_n_id}"
    return f"{raiz} pelo {pelo_n_id}.{extension}"
