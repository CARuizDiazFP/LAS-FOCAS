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
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from core.services.cromo import tracking_cache
from core.services.cromo.camino_optico_service import ESTADO_OK, resolver_camino_de_pelo
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
        if cacheado is not None:
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
            )

    camino = await resolver_camino_de_pelo(cliente, sesion, pelo_n_id)
    if camino.estado != ESTADO_OK:
        raise TrackingNoDisponible(camino.motivo, camino.estado)

    ahora = datetime.now(timezone.utc)
    nombre = nombre_archivo_tracking(camino.servicio_at62, camino.pelo_n_id or pelo_n_id)
    contenido = renderizar_tracking_txt(camino, generado_en=ahora)

    await tracking_cache.guardar(
        sesion,
        pelo_n_id=pelo_n_id,
        servicio_id=servicio_id,
        nombre_archivo=nombre,
        contenido=contenido,
        duracion_ms=camino.duracion_ms,
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
    )


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
