# Nombre de archivo: tracking_servicio.py
# Ubicación de archivo: modules/slack_baneo_notifier/tracking_servicio.py
# Descripción: Comando de Slack "@bot track <id>" — parser, resolución del Servicio por sus tres identidades y generación de los .txt de tracking desde Cromo

"""Soporte del comando `@bot track <id de servicio>`.

Vive en su propio módulo y no en `cable_info.py` (donde están los otros `extraer_comando_*`) porque
no tiene nada que ver con cables: resuelve un Servicio y le genera los trackings. `listener.py` ya
pasa las 1.400 líneas, así que la orquestación también viene acá en vez de engordarlo más.

El `.txt` **no es uno por Servicio, es uno por camino distinto**: las semillas son las posiciones
de ODF del Servicio y después el resto de sus pelos, y las que recorren el mismo camino se colapsan
en un solo archivo (`trackings_por_camino`). El 42351 da 2: sus dos hilos, cada uno con el camino
completo, incluidos los cables de terceros. Se suben todos al hilo (decisiones del usuario,
2026-09-28 y 2026-09-29).

Tracking por tramos (2026-10-16): se pide un camino por cada semilla no cubierta y cada uno se
clasifica como TRAMO o RESIDUAL (`tracking_service.clasificar_caminos`). Se sube un `.txt` por
tramo (`{at62} CROMO T{n} pelo {n_id}.txt`); los residuales sólo se avisan. El resumen definitivo
del hilo es de la Tarea 3.
"""

from __future__ import annotations

import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# `track`/`tracking` + un número, y nada más. `\b` al final del verbo para que "trackear 67395" no
# matchee. El ancla `$` es deliberada: un mensaje con texto de más no es este comando, y tragarlo
# haría que el bot conteste a menciones que no le hablaban a él.
_RE_TRACK = re.compile(r"(?i)^track(?:ing)?\s+(\d+)$")

# Slack no renderiza el mrkdwn antes de mandarnos el evento: *67395* llega con los asteriscos
# literales. Es el mismo bug real que rompió "Info cable" el 2026-08-25 — acá se previene de entrada.
_RE_FORMATO_SLACK = re.compile(r"[*_`~]")


def extraer_comando_track(texto: str) -> Optional[str]:
    """Extrae el identificador de "track 67395". Devuelve `None` si el texto no es este comando
    (no es un error: puede ser una mención de cualquier otro comando, o ninguno)."""
    normalizado = _RE_FORMATO_SLACK.sub("", re.sub(r"\s+", " ", texto).strip())
    match = _RE_TRACK.match(normalizado)
    return match.group(1) if match else None


def resolver_servicio(session: Any, numero: str) -> Optional[Any]:
    """Resuelve un Servicio por CUALQUIERA de sus tres identidades: `servicio_id` (el vigente),
    `numero_primer_servicio` (el de primera línea) o `alias_ids` (los históricos).

    Mismo criterio que `infra_service._find_servicio_by_identificador` y que
    `cromo/ingesta.py::_SQL_BUSCAR_SERVICIO`, que es el canónico del repo. Deliberadamente NO es el
    de `_find_servicio_por_identificador_web`, que mira `numero_linea` en vez de `alias_ids`.

    Medido en dev (2026-09-28): de las 5.435 filas de `app.servicios_historial_id`, **cero** tienen
    un `numero_id` que estas tres identidades no cubran ya — por eso no hace falta joinear el
    histórico para resolver un ID viejo.
    """
    from db.models.infra import Servicio
    from sqlalchemy import or_

    return (
        session.query(Servicio)
        .filter(
            or_(
                Servicio.servicio_id == numero,
                Servicio.numero_primer_servicio == numero,
                Servicio.alias_ids.contains([numero]),
            )
        )
        .first()
    )


@dataclass(slots=True)
class TrackingArchivo:
    nombre: str
    contenido: str
    desde_cache: bool
    duracion_ms: Optional[int]


@dataclass(slots=True)
class ResultadoTrack:
    """`estado` es "ok" cuando hay al menos un archivo; si no, el motivo por el que no lo hay.

    `errores` puede venir poblado junto con archivos: un Servicio de 4 posiciones de ODF donde una
    sola falla igual entrega las otras tres, en vez de perderlas por un pelo roto.
    """

    estado: str
    archivos: list[TrackingArchivo] = field(default_factory=list)
    mensaje: str = ""
    errores: list[str] = field(default_factory=list)
    esperados: int = 0
    completo: bool = True
    # Una línea por camino residual, ya formateada para el hilo ("pelo 6799772 · 3 pelos").
    residuales: list[str] = field(default_factory=list)


ESTADO_OK = "ok"
ESTADO_ERROR = "error"


# Un Servicio largo puede tener decenas de residuales; el hilo no es el lugar para listarlos todos.
_MAX_HUERFANOS_LISTADOS = 15


def _describir_pelo(semilla: Any) -> str:
    """"pelo 6799772 · F-VIN-TEC · 21 AM": lo que el operador necesita para ubicarlo en Cromo."""
    partes = [f"pelo {semilla.pelo_n_id}"]
    if semilla.cable_nombre:
        partes.append(semilla.cable_nombre)
    numero = " ".join(x for x in (semilla.numero_pelo, semilla.color) if x)
    if numero:
        partes.append(numero)
    return " · ".join(partes)


def mensaje_resumen(resultado: ResultadoTrack) -> Optional[str]:
    """Aviso que acompaña a los archivos en el hilo, o `None` si no hay nada que avisar.

    - Incompleto: se tocó el tope de llamadas a Cromo (o de pelos fallidos) con semillas sin
      cubrir; se dice cuántos tramos se generaron y por qué fallaron los que fallaron.
    - Hay residuales: caminos que no son tramos del Servicio; se listan y no se sube su `.txt`.
    """
    if resultado.estado != ESTADO_OK:
        return None
    partes: list[str] = []
    generados = len(resultado.archivos)
    if not resultado.completo:
        partes.append(
            f":warning: El tracking quedó incompleto (se alcanzó el tope de llamadas a Cromo); "
            f"se generaron {generados} tramo(s)."
        )
        if resultado.errores:
            partes.append("\n".join(f"• {e}" for e in resultado.errores))
    if resultado.residuales:
        partes.append(
            f":link: {len(resultado.residuales)} camino(s) residual(es): pelos con la etiqueta del "
            "Servicio cuyo camino no es un tramo del Servicio. No se generó tracking para ellos:"
        )
        partes.append(
            "\n".join(f"• {h}" for h in resultado.residuales[:_MAX_HUERFANOS_LISTADOS])
        )
        if len(resultado.residuales) > _MAX_HUERFANOS_LISTADOS:
            partes.append(f"… y {len(resultado.residuales) - _MAX_HUERFANOS_LISTADOS} más.")
    return "\n".join(partes) if partes else None


def _describir_residual(tracking: Any) -> str:
    """"pelo 6799772 · 3 pelos": la semilla del camino residual y su largo."""
    return f"pelo {tracking.pelo_n_id} · {len(tracking.pelos_camino)} pelos"


async def _generar_async(servicio_pk: int) -> ResultadoTrack:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from core.services.cromo.camino_optico_service import ESTADO_SIN_SEMILLA, contar_semillas
    from core.services.cromo.client import CromoClient, CromoClientError
    from core.services.cromo.config import get_cromo_config
    from core.services.cromo.tracking_service import trackings_del_servicio
    from db.session import async_engine

    # Engine propio con `NullPool` en vez del pool singleton de `db.session`: ese pool queda atado
    # al event loop del primer checkout, y acá corremos en un loop nuevo por invocación. Reusarlo
    # es exactamente el `Future attached to a different loop` con el que este repo ya tropezó.
    engine = create_async_engine(
        async_engine.url.render_as_string(hide_password=False), poolclass=NullPool
    )
    Session = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with Session() as sesion:
            # El universo real, sin el tope de `listar_pelos_semilla`: es lo que decide si hay
            # camino posible.
            total_pelos, _con_odf = await contar_semillas(sesion, servicio_pk)
            if total_pelos == 0:
                return ResultadoTrack(
                    estado=ESTADO_SIN_SEMILLA,
                    mensaje=(
                        "El Servicio no tiene ningún pelo en Cromo, así que no hay camino que "
                        "resolver."
                    ),
                )

            try:
                async with CromoClient(config=get_cromo_config()) as cliente:
                    del_servicio = await trackings_del_servicio(cliente, sesion, servicio_pk)
            except CromoClientError as exc:
                # Cromo caído se lleva puesta la corrida entera, no un pelo: se reporta como tal.
                return ResultadoTrack(
                    estado=ESTADO_ERROR,
                    mensaje=f"Cromo no respondió: {exc}",
                )

            errores = del_servicio.errores
            # Un `.txt` por tramo, ya con su nombre de tramo (`{at62} CROMO T{n} pelo {n_id}.txt`),
            # que no se pisan entre sí. Los residuales no se suben: sólo se avisan.
            archivos = [
                TrackingArchivo(
                    nombre=tracking.nombre_archivo,
                    contenido=tracking.contenido,
                    desde_cache=tracking.desde_cache,
                    duracion_ms=tracking.duracion_ms,
                )
                for tracking in del_servicio.tramos
            ]
            residuales = [_describir_residual(t) for t in del_servicio.residuales]

            if not archivos:
                return ResultadoTrack(
                    estado=ESTADO_ERROR,
                    mensaje="No se pudo generar ningún tracking para este Servicio.",
                    errores=errores,
                )
            return ResultadoTrack(
                estado=ESTADO_OK,
                archivos=archivos,
                errores=errores,
                esperados=del_servicio.esperados_declarados or len(archivos),
                completo=del_servicio.completo,
                residuales=residuales,
            )
    finally:
        await engine.dispose()


def generar_trackings(servicio_pk: int) -> ResultadoTrack:
    """Genera los `.txt` del Servicio. Bloqueante: en frío cuesta entre 4,6 s y 14 s **por pelo**
    contra Cromo (con hasta 4 pelos, ~1 minuto); sobre el caché de 24 h es inmediato. La demora en
    frío está contemplada y aceptada (usuario, 2026-09-28).

    Corre el camino async en un thread propio con su propio event loop: `asyncio.run` revienta si
    el thread que llama ya tiene un loop corriendo, y los callbacks de Slack Bolt no garantizan
    cuál de los dos casos es. Un thread por invocación es barato — esto es un comando de chat, no
    un loop batch.
    """
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="slack-track") as ejecutor:
        return ejecutor.submit(lambda: asyncio.run(_generar_async(servicio_pk))).result()
