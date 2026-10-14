# Nombre de archivo: tracking_service.py
# Ubicación de archivo: core/services/cromo/tracking_service.py
# Descripción: Generación del tracking .txt de un pelo de un Servicio, con caché de 24 h — un
# archivo por pelo, que es lo que permite bajar los 1, 2 o más trackings que tiene un Servicio

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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from core.services.cromo import tracking_cache
from core.services.cromo.camino_optico_service import (
    ESTADO_OK,
    CaminoOptico,
    PeloSemilla,
    caminos_esperados,
    resolver_camino_de_pelo,
    semillas_para_tracking,
)
from core.services.cromo.camino_optico_txt import (
    nombre_archivo_tracking,
    renderizar_tracking_txt,
)
from core.services.cromo.client import CromoClient

logger = logging.getLogger(__name__)

class TrackingNoDisponible(RuntimeError):
    """El camino del pelo no resolvió, así que no hay `.txt` que generar."""

    def __init__(self, motivo: Optional[str], estado: str) -> None:
        super().__init__(motivo or f"El camino no resolvió (estado {estado}).")
        self.motivo = motivo
        self.estado = estado


class DemasiadosPelos(ValueError):
    """Se pidieron más pelos que la cota de una sola descarga."""


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


_CLASE_PELO = 130


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
    servicio_id: int,
    pelo_n_id: int,
    forzar: bool = False,
) -> TrackingGenerado:
    """Tracking `.txt` de un pelo: del caché si está fresco, o generado y cacheado.

    `forzar=True` saltea la lectura del caché pero igual reescribe la entrada — es la vía para
    regenerar a mano un tracking que quedó viejo antes de vencer.

    Hace `commit` de la entrada de caché apenas la escribe, para que una descarga de varios pelos
    no pierda lo ya resuelto si un pelo posterior falla.
    """
    if not forzar:
        cacheado = await tracking_cache.leer(sesion, pelo_n_id)
        # Una entrada sin `pelos_camino` es anterior a esa columna: sin la lista no se pueden
        # descartar caminos repetidos, así que se regenera (una sola vez, queda guardada).
        if cacheado is not None and cacheado.pelos_camino is not None:
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
            )

    camino = await resolver_camino_de_pelo(cliente, sesion, pelo_n_id)
    if camino.estado != ESTADO_OK:
        raise TrackingNoDisponible(camino.motivo, camino.estado)

    ahora = datetime.now(timezone.utc)
    nombre = nombre_archivo_tracking(camino.servicio_at62, camino.pelo_n_id or pelo_n_id)
    contenido = renderizar_tracking_txt(camino, generado_en=ahora)
    pelos_camino = pelos_del_camino(camino) | {pelo_n_id}

    await tracking_cache.guardar(
        sesion,
        pelo_n_id=pelo_n_id,
        servicio_id=servicio_id,
        nombre_archivo=nombre,
        contenido=contenido,
        duracion_ms=camino.duracion_ms,
        pelos_camino=sorted(pelos_camino),
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
    )


@dataclass(slots=True)
class TrackingsPorCamino:
    """`omitidos` es `{semilla descartada: pelo cuyo camino ya la recorría}`, para el log.

    `no_cubiertos` son las semillas que no quedaron en ningún camino generado (las que fallaron y,
    con `esperados`, las que no hizo falta pedir). `completo` dice si se llegó a los caminos
    esperados: sólo entonces las no cubiertas son huérfanas de verdad y no caminos que faltaron.
    """

    trackings: list[TrackingGenerado] = field(default_factory=list)
    omitidos: dict[int, int] = field(default_factory=dict)
    errores: list[str] = field(default_factory=list)
    no_cubiertos: list[int] = field(default_factory=list)
    completo: bool = True


async def trackings_por_camino(
    cliente: CromoClient,
    sesion: AsyncSession,
    *,
    servicio_id: int,
    pelos_n_id: Iterable[int],
    esperados: Optional[int] = None,
    max_fallidos: Optional[int] = None,
) -> TrackingsPorCamino:
    """Un tracking por camino distinto, no uno por semilla.

    Las semillas por defecto son las posiciones de ODF del Servicio, y un hilo tiene posición en
    cada ODF que atraviesa —extremos e intermedias, propias o de cables de terceros—. Caso real,
    Servicio 42351: dos hilos, posiciones en TASA, TECO y Facebook. El operador espera 2 `.txt`
    con el camino completo, no uno por ODF.

    Se recorren en orden; una semilla que ya aparece en el camino de una anterior se descarta
    **sin** pedirla a Cromo. Un pelo que falla no cancela los demás. `CromoClientError` no se
    atrapa: Cromo caído se lleva la corrida entera y lo reporta el llamador.

    `esperados` corta al llegar a esa cantidad de caminos: un pelo huérfano (etiqueta vieja de un
    pelo movido) no genera un tracking de más, y no se le pide a Cromo (Servicio 94673,
    2026-10-05). `max_fallidos` acota cuántas semillas fallidas se toleran antes de rendirse, para
    que un Servicio con cientos de pelos sin camino no dispare cientos de llamadas.
    """
    resultado = TrackingsPorCamino()
    cubiertos: dict[int, int] = {}
    semillas = list(dict.fromkeys(pelos_n_id))
    fallidos: set[int] = set()
    for pelo_n_id in semillas:
        if esperados is not None and len(resultado.trackings) >= esperados:
            break
        if max_fallidos is not None and len(fallidos) >= max_fallidos:
            break
        if pelo_n_id in cubiertos:
            resultado.omitidos[pelo_n_id] = cubiertos[pelo_n_id]
            continue
        try:
            tracking = await obtener_tracking(
                cliente, sesion, servicio_id=servicio_id, pelo_n_id=pelo_n_id
            )
        except TrackingNoDisponible as exc:
            resultado.errores.append(f"Pelo {pelo_n_id}: {exc.motivo}")
            fallidos.add(pelo_n_id)
            continue
        resultado.trackings.append(tracking)
        for pelo in tracking.pelos_camino | {pelo_n_id}:
            cubiertos.setdefault(pelo, pelo_n_id)

    resultado.no_cubiertos = [p for p in semillas if p not in cubiertos]
    if esperados is not None:
        resultado.completo = len(resultado.trackings) >= esperados

    if resultado.omitidos:
        logger.info(
            "action=cromo_tracking evento=caminos_repetidos servicio_id=%s omitidos=%s",
            servicio_id,
            len(resultado.omitidos),
        )
    return resultado


@dataclass(slots=True)
class TrackingsDelServicio:
    """Los trackings de un Servicio, con lo que hace falta para explicarle el resultado al operador.

    `huerfanos` sólo se llena cuando se generaron todos los caminos esperados: recién ahí un pelo
    fuera de todo camino es un huérfano y no un camino que no se pudo resolver.
    """

    trackings: list[TrackingGenerado]
    esperados: int
    huerfanos: list[PeloSemilla]
    errores: list[str]
    completo: bool


async def trackings_del_servicio(
    cliente: CromoClient, sesion: AsyncSession, servicio_id: int
) -> TrackingsDelServicio:
    """Un `.txt` por camino del Servicio, cortando en los caminos esperados. Lo usan Slack y web.

    Semillas: todas, con las posiciones de ODF primero (`semillas_para_tracking`). Esperados: la
    moda de pelos por cable u ODF (`caminos_esperados`); si no hay ningún grupo, uno.
    """
    semillas = await semillas_para_tracking(sesion, servicio_id)
    if not semillas:
        return TrackingsDelServicio([], 0, [], [], True)
    esperados = await caminos_esperados(sesion, servicio_id) or 1
    por_camino = await trackings_por_camino(
        cliente,
        sesion,
        servicio_id=servicio_id,
        pelos_n_id=[s.pelo_n_id for s in semillas],
        esperados=esperados,
        max_fallidos=max(_MIN_FALLIDOS_TOLERADOS, esperados),
    )
    por_id = {s.pelo_n_id: s for s in semillas}
    huerfanos = (
        [por_id[p] for p in por_camino.no_cubiertos if p in por_id] if por_camino.completo else []
    )
    if huerfanos:
        logger.info(
            "action=cromo_tracking evento=pelos_huerfanos servicio_id=%s huerfanos=%s",
            servicio_id,
            [s.pelo_n_id for s in huerfanos],
        )
    return TrackingsDelServicio(
        trackings=por_camino.trackings,
        esperados=esperados,
        huerfanos=huerfanos,
        errores=por_camino.errores,
        completo=por_camino.completo,
    )


# Semillas fallidas toleradas antes de rendirse, como mínimo. Cada una es una llamada de 4,6-14 s a
# Cromo que no aporta camino.
_MIN_FALLIDOS_TOLERADOS = 3


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
