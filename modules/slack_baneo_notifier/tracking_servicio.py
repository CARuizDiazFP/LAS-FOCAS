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
tramo (`{at62} CROMO T{n} pelo {n_id}.txt`), uno por `files_upload_v2`. Los residuales NO se
mencionan en el hilo (van a la auditoría de la web). El resumen es una línea por aviso y sólo
cuando aplica: segmentación (más de un segmento físico), cantidad esperada distinta de la
generada, semillas que no resolvieron (con sus errores) y, aparte, tope de consultas a Cromo sólo
si de verdad se tocó.

Posición vigente y `track N full` (2026-10-21): si el operador declaró la posición vigente del
Servicio (Detalle de Servicio), sus caminos son los VIGENTE y se suben en lugar de los tramos. Los
caminos ADICIONALES (recorridos reales que no son por donde va el Servicio, p. ej. el camino viejo
del 93150 por O-1252871-1:1,2) se mencionan en el resumen pero no se suben; `track N full` sube un
`.txt` por camino resuelto (vigentes/tramos ∪ adicionales, nunca residuales). `track odf
<patchera>:<conectores>` sube el tracking de posiciones sueltas de una patchera, sin auditoría ni
evidencia (`generar_tracking_posiciones`).
"""

from __future__ import annotations

import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

logger = logging.getLogger(__name__)

# `track`/`tracking` + un número, y nada más. `\b` al final del verbo para que "trackear 67395" no
# matchee. El ancla `$` es deliberada: un mensaje con texto de más no es este comando, y tragarlo
# haría que el bot conteste a menciones que no le hablaban a él.
_RE_TRACK = re.compile(r"(?i)^track(?:ing)?\s+(\d+)$")

# "track 93150 full": misma forma y mismo ancla que `_RE_TRACK`, con el modo al final. Regex aparte
# (y no un grupo opcional en `_RE_TRACK`) para que el comando de siempre y sus tests no cambien.
_RE_TRACK_FULL = re.compile(r"(?i)^track(?:ing)?\s+(\d+)\s+full$")

# Slack no renderiza el mrkdwn antes de mandarnos el evento: *67395* llega con los asteriscos
# literales. Es el mismo bug real que rompió "Info cable" el 2026-08-25 — acá se previene de entrada.
_RE_FORMATO_SLACK = re.compile(r"[*_`~]")


def extraer_comando_track(texto: str) -> Optional[str]:
    """Extrae el identificador de "track 67395". Devuelve `None` si el texto no es este comando
    (no es un error: puede ser una mención de cualquier otro comando, o ninguno)."""
    normalizado = _RE_FORMATO_SLACK.sub("", re.sub(r"\s+", " ", texto).strip())
    match = _RE_TRACK.match(normalizado)
    return match.group(1) if match else None


def extraer_comando_track_full(texto: str) -> Optional[str]:
    """Extrae el identificador de "track 93150 full" (misma normalización que `extraer_comando_track`).
    `None` si no es este comando; "track 93150" no lo es."""
    normalizado = _RE_FORMATO_SLACK.sub("", re.sub(r"\s+", " ", texto).strip())
    match = _RE_TRACK_FULL.match(normalizado)
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
    # Cantidad de trackings esperados que declaró el operador en LAS-FOCAS
    # (`servicios.trackings_esperados`, no es un dato de Cromo); `None` si no declaró.
    esperados_declarados: Optional[int] = None
    completo: bool = True
    # Semillas que no quedaron en ningún camino (fallaron o no se llegaron a pedir).
    no_cubiertos: int = 0
    # Se cortó por el tope de consultas a Cromo (`CROMO_TRACKING_MAX_LLAMADAS`).
    tope_llamadas: bool = False
    # Segmentos físicos: grupos de tramos que comparten cables. Dos hilos del mismo recorrido son
    # uno solo (`tracking_service.contar_segmentos`).
    segmentos: int = 1
    # Caminos adicionales (no se suben salvo en `full`) y por qué posiciones salen: "O-1252871-1:1,2"
    # y la etiqueta de sus pelos ("44649"), para el aviso.
    adicionales: int = 0
    posiciones_adicionales: str = ""
    etiquetas_adicionales: str = ""
    # Etiqueta de la posición vigente declarada, sólo si se aplicó en esta corrida.
    posicion_declarada: str = ""
    # Retiros y avisos de la posición vigente (`servicio_posicion_vigente.textos_avisos`).
    avisos_posicion: list[str] = field(default_factory=list)
    # Vigentes/tramos + adicionales: contra esto se comparan los esperados. `None` = comportamiento
    # de antes (contra los archivos subidos).
    caminos_resueltos: Optional[int] = None
    # Vigentes/tramos: es lo que cuenta la segmentación (los archivos de `full` son más). `None` =
    # los archivos.
    tramos: Optional[int] = None
    full: bool = False
    numero_servicio: str = ""


ESTADO_OK = "ok"
ESTADO_ERROR = "error"


def mensaje_resumen(resultado: ResultadoTrack) -> Optional[str]:
    """Aviso que acompaña a los archivos en el hilo, o `None` si no hay nada que avisar.

    Sólo las líneas que aplican, en este orden: avisos de la posición vigente (retiros, camino no
    usable), segmentación (más de un segmento físico; un par de hilos del mismo recorrido no lo es;
    cuenta tramos, no archivos), cantidad esperada distinta de la de caminos resueltos (o de la
    generada, si no se informaron), caminos adicionales, semillas que no resolvieron con sus
    errores —aunque el recorrido haya terminado: puede faltar un tramo entero— y el tope de
    consultas a Cromo sólo si se tocó. Los residuales nunca se mencionan.
    """
    if resultado.estado != ESTADO_OK:
        return None
    partes: list[str] = [f":warning: {texto}" for texto in resultado.avisos_posicion]
    generados = resultado.tramos if resultado.tramos is not None else len(resultado.archivos)
    if resultado.segmentos > 1:
        partes.append(
            f"Servicio segmentado en {resultado.segmentos} tramos ({generados} trackings)."
        )
    declarados = resultado.esperados_declarados
    if declarados is not None:
        if resultado.caminos_resueltos is None:
            if declarados != generados:
                partes.append(f"Se esperaban {declarados} trackings y se generaron {generados}.")
        elif declarados != resultado.caminos_resueltos:
            partes.append(
                f"Se esperaban {declarados} trackings y Cromo documenta "
                f"{resultado.caminos_resueltos} camino(s) óptico(s)."
            )
    if resultado.adicionales:
        partes.append(_linea_adicionales(resultado))
    sin_resolver = max(resultado.no_cubiertos, len(resultado.errores))
    if sin_resolver or not resultado.completo:
        partes.append(
            f":warning: Tracking incompleto: {sin_resolver} semilla(s) no resolvieron."
        )
        if resultado.errores:
            partes.append("\n".join(f"• {e}" for e in resultado.errores))
    if resultado.tope_llamadas:
        partes.append("Se alcanzó el tope de consultas a Cromo.")
    return "\n".join(partes) if partes else None


def _linea_adicionales(resultado: ResultadoTrack) -> str:
    por = f" por {resultado.posiciones_adicionales}" if resultado.posiciones_adicionales else ""
    hay = f"Hay {resultado.adicionales} camino(s) óptico(s) adicional(es){por}"
    if not resultado.posicion_declarada:
        etiqueta = (
            f" (pelos con etiqueta {resultado.etiquetas_adicionales})"
            if resultado.etiquetas_adicionales
            else ""
        )
        return f"{hay}{etiqueta}. Declarar la posición vigente en el Detalle de Servicio."
    linea = f"Posición vigente declarada: {resultado.posicion_declarada}. {hay}."
    if not resultado.full:
        linea += f" No se suben: pedí `track {resultado.numero_servicio} full` para incluirlos."
    return linea


def _archivo(tracking: Any) -> TrackingArchivo:
    return TrackingArchivo(
        nombre=tracking.nombre_archivo,
        contenido=tracking.contenido,
        desde_cache=tracking.desde_cache,
        duracion_ms=tracking.duracion_ms,
    )


def resultado_de_trackings(
    del_servicio: Any, *, full: bool, numero_servicio: Optional[str]
) -> ResultadoTrack:
    """`ResultadoTrack` a partir de `trackings_del_servicio`. Pura.

    En modo normal se suben los vigentes/tramos (ya con su nombre `{n} CROMO T{k} pelo X.txt`) y
    los adicionales sólo se mencionan; en `full`, un `.txt` por camino resuelto (`caminos_resueltos`
    = vigentes/tramos ∪ adicionales, con los nombres T{k} y A{k} que puso el core). Los residuales
    nunca se suben ni se mencionan.
    """
    from core.services.cromo.servicio_posicion_vigente import etiqueta_posiciones, textos_avisos

    avisos = textos_avisos(del_servicio.posicion.avisos)
    errores = del_servicio.errores
    origen = del_servicio.caminos_resueltos if full else del_servicio.tramos
    archivos = [_archivo(tracking) for tracking in origen]
    if not archivos:
        mensaje = "No se pudo generar ningún tracking para este Servicio."
        return ResultadoTrack(
            estado=ESTADO_ERROR,
            mensaje="\n".join([mensaje, *(f":warning: {a}" for a in avisos)]),
            errores=errores,
        )
    infos = del_servicio.info_adicionales
    etiquetas = dict.fromkeys(e for info in infos for e in info.etiquetas)
    return ResultadoTrack(
        estado=ESTADO_OK,
        archivos=archivos,
        errores=errores,
        esperados_declarados=del_servicio.esperados_declarados,
        completo=del_servicio.completo,
        no_cubiertos=len(del_servicio.no_cubiertos),
        tope_llamadas=del_servicio.tope_llamadas,
        segmentos=del_servicio.segmentos,
        adicionales=len(del_servicio.adicionales),
        posiciones_adicionales=etiqueta_posiciones(p for info in infos for p in info.posiciones),
        etiquetas_adicionales=", ".join(etiquetas),
        posicion_declarada=del_servicio.posicion.etiqueta if del_servicio.posicion.aplicada else "",
        avisos_posicion=avisos,
        caminos_resueltos=len(del_servicio.caminos_resueltos),
        tramos=len(del_servicio.tramos),
        full=full,
        numero_servicio=numero_servicio or "",
    )


@asynccontextmanager
async def _sesion_async() -> AsyncIterator[Any]:
    """Sesión async sobre un engine propio con `NullPool`, descartado al salir.

    No se usa el pool singleton de `db.session`: ese pool queda atado al event loop del primer
    checkout, y acá corremos en un loop nuevo por invocación. Reusarlo es exactamente el `Future
    attached to a different loop` con el que este repo ya tropezó.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from db.session import async_engine

    engine = create_async_engine(
        async_engine.url.render_as_string(hide_password=False), poolclass=NullPool
    )
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as sesion:
            yield sesion
    finally:
        await engine.dispose()


async def _generar_async(servicio_pk: int, *, full: bool = False) -> ResultadoTrack:
    from core.services.cromo import camino_optico_service, servicio_posicion_vigente
    from core.services.cromo import client as cromo_client
    from core.services.cromo import tracking_service
    from core.services.cromo.config import get_cromo_config

    async with _sesion_async() as sesion:
        # El universo real, sin el tope de `listar_pelos_semilla`: es lo que decide si hay camino
        # posible. Un Servicio sin pelos etiquetados puede tener posiciones (conectores que dicen
        # su número, o una declarada): esos sí tienen camino.
        total_pelos, _con_odf = await camino_optico_service.contar_semillas(sesion, servicio_pk)
        if total_pelos == 0 and not await servicio_posicion_vigente.tiene_posiciones(
            sesion, servicio_pk
        ):
            return ResultadoTrack(
                estado=camino_optico_service.ESTADO_SIN_SEMILLA,
                mensaje=(
                    "El Servicio no tiene ningún pelo en Cromo, así que no hay camino que "
                    "resolver."
                ),
            )

        try:
            async with cromo_client.CromoClient(config=get_cromo_config()) as cliente:
                del_servicio = await tracking_service.trackings_del_servicio(
                    cliente, sesion, servicio_pk, fuente_evidencia="SLACK"
                )
        except cromo_client.CromoClientError as exc:
            # Cromo caído se lleva puesta la corrida entera, no un pelo: se reporta como tal.
            return ResultadoTrack(
                estado=ESTADO_ERROR,
                mensaje=f"Cromo no respondió: {exc}",
            )

        numero = await tracking_service.numero_del_servicio(sesion, servicio_pk)
        return resultado_de_trackings(del_servicio, full=full, numero_servicio=numero)


def _correr_en_thread(nombre: str, fabrica: Any) -> Any:
    """Corre la corrutina que arma `fabrica()` en un thread propio con su propio event loop."""
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix=nombre) as ejecutor:
        return ejecutor.submit(lambda: asyncio.run(fabrica())).result()


def generar_trackings(servicio_pk: int, *, full: bool = False) -> ResultadoTrack:
    """Genera los `.txt` del Servicio. Bloqueante: en frío cuesta entre 4,6 s y 14 s **por pelo**
    contra Cromo (con hasta 4 pelos, ~1 minuto); sobre el caché de 24 h es inmediato. La demora en
    frío está contemplada y aceptada (usuario, 2026-09-28).

    Corre el camino async en un thread propio con su propio event loop: `asyncio.run` revienta si
    el thread que llama ya tiene un loop corriendo, y los callbacks de Slack Bolt no garantizan
    cuál de los dos casos es. Un thread por invocación es barato — esto es un comando de chat, no
    un loop batch.

    `full=True` sube también los caminos adicionales (`track N full`).
    """
    return _correr_en_thread("slack-track", lambda: _generar_async(servicio_pk, full=full))


# ── "track odf <patchera>:<conectores>" ─────────────────────────────────────────────────────

# Tope de conectores por comando: una patchera real llega a 144 conectores y cada pelo en frío
# cuesta 4,6-14 s contra Cromo (`1-144` serían 11-34 minutos).
MAX_CONECTORES_TRACK_ODF = 8

# `.+?` perezoso y una lista sin ":" ⇒ corta en el ÚLTIMO ":" (hay un nombre real con ":" adentro,
# "ODF : ODF-CALLE 14 LIMA(PRACTICA) - LIMA CALLE 14", y 5 con coma, "ODF Ruta 6 km 3,5 - 1000").
_RE_TRACK_ODF = re.compile(
    r"(?i)^track(?:ing)?\s+odf\s+(?P<patchera>.+?)\s*:\s*(?P<conectores>[\d\s,\-]+)$"
)
# Sólo `*` y `` ` ``: `_RE_FORMATO_SLACK` también borra `_` y `~`, y 13 patcheras reales usan `_`.
_RE_FORMATO_TRACK_ODF = re.compile(r"[*`]")
_RE_RANGO = re.compile(r"^(\d+)\s*-\s*(\d+)$")

_USO_TRACK_ODF = (
    f"Uso: `track odf O-1252871-1:1`, `:1,2` o `:1-2` (hasta {MAX_CONECTORES_TRACK_ODF} conectores)."
)


@dataclass(slots=True, frozen=True)
class ComandoTrackOdf:
    """`conectores` en el orden pedido y sin repetidos. Con `error`, la lista no era válida (y
    `conectores` queda vacío): el comando es este, pero hay que explicarle el uso al operador."""

    patchera: str
    conectores: tuple[int, ...]
    error: Optional[str] = None


def _expandir_conectores(lista: str) -> tuple[tuple[int, ...], Optional[str]]:
    numeros: list[int] = []
    for token in (t.strip() for t in lista.split(",")):
        rango = _RE_RANGO.match(token)
        if rango:
            desde, hasta = int(rango.group(1)), int(rango.group(2))
        elif token.isdigit():
            desde = hasta = int(token)
        else:
            return (), f"La lista de conectores `{lista.strip()}` no es válida."
        if desde < 1 or hasta < desde:
            return (), f"El conector o rango `{token}` no es válido."
        # Se corta antes de expandir: "1-999999999" no arma una lista gigante.
        if hasta - desde + 1 > MAX_CONECTORES_TRACK_ODF:
            return (), f"Son demasiados conectores: el máximo es {MAX_CONECTORES_TRACK_ODF}."
        numeros.extend(n for n in range(desde, hasta + 1) if n not in numeros)
        if len(numeros) > MAX_CONECTORES_TRACK_ODF:
            return (), f"Son demasiados conectores: el máximo es {MAX_CONECTORES_TRACK_ODF}."
    return tuple(numeros), None


def extraer_comando_track_odf(texto: str) -> Optional[ComandoTrackOdf]:
    """Extrae patchera y conectores de "track odf O-1252871-1:1,2" (`:1`, `:1,2`, `:1-2`,
    `:1,3-4`). `None` si el texto no es este comando; una lista inválida o de más de
    `MAX_CONECTORES_TRACK_ODF` conectores devuelve el comando con `error`.

    La patchera se devuelve cruda (sin mayúsculas ni el cambio `0-`/`O-`): eso lo resuelve
    `odf_conectores.bandejas_por_nombre`.
    """
    normalizado = _RE_FORMATO_TRACK_ODF.sub("", re.sub(r"\s+", " ", texto).strip())
    match = _RE_TRACK_ODF.match(normalizado)
    if not match:
        return None
    patchera = match.group("patchera").strip()
    if not patchera:
        return None
    conectores, error = _expandir_conectores(match.group("conectores"))
    return ComandoTrackOdf(patchera=patchera, conectores=conectores, error=error)


def texto_uso_track_odf(error: str) -> str:
    return f":warning: {error} {_USO_TRACK_ODF}"


ESTADO_PATCHERA_NO_ENCONTRADA = "PATCHERA_NO_ENCONTRADA"
ESTADO_PATCHERA_AMBIGUA = "PATCHERA_AMBIGUA"

POSICION_OK = "ok"
POSICION_INEXISTENTE = "inexistente"
POSICION_SIN_PELO = "sin_pelo"
POSICION_SIN_CAMINO = "sin_camino"

_MAX_CANDIDATAS_LISTADAS = 10


@dataclass(slots=True)
class PosicionTrack:
    """Lo que salió de un conector pedido. `archivo` y `descripcion` (el comentario del `.txt` en
    el hilo) sólo con `estado="ok"`; `motivo`, por qué Cromo no resolvió el camino."""

    conector: int
    estado: str
    descripcion: str = ""
    archivo: Optional[TrackingArchivo] = None
    motivo: Optional[str] = None
    pelo_n_id: Optional[int] = None
    patch_conector_n_id: Optional[int] = None


@dataclass(slots=True)
class ResultadoTrackOdf:
    """`estado`: "ok", patchera no encontrada o ambigua (`candidatas`), o error de Cromo (`mensaje`,
    con las `posiciones` que se llegaron a resolver antes de la caída)."""

    estado: str
    patchera: str
    bandeja: Optional[Any] = None
    candidatas: list[Any] = field(default_factory=list)
    posiciones: list[PosicionTrack] = field(default_factory=list)
    mensaje: str = ""


def _es_activo(estado: Optional[str]) -> bool:
    return (estado or "").strip().lower() == "activo"


def _con_estado(numero: str, estado: Optional[str]) -> str:
    return f"{numero} ({estado})" if estado else numero


def descripcion_posicion(bandeja: Any, conector: Any) -> str:
    """Comentario del `.txt` de una posición. Pura. Ejemplo real (93150):

    "`O-1252871-1:1` · ODF San Martin 137 P5 D · pelo 7028862 (F-PC-CC #1) · conector: 93150 BANCO
    DE LA PROVINCIA DE BUENOS AIRES (Activo) · etiqueta del pelo: 44649 (Baja)"

    El histórico del conector se muestra sólo si no coincide ni con el servicio del conector ni
    con la etiqueta del pelo; la etiqueta, sólo si es distinta del servicio del conector.
    """
    partes = [
        f"`{bandeja.bandeja_nombre}:{conector.numero_conector}`",
        bandeja.odf_nombre or f"ODF {bandeja.odf_n_id}",
    ]
    detalle_pelo = [
        f"{conector.cable_nombre} #{conector.numero_pelo}" if conector.cable_nombre and conector.numero_pelo
        else conector.cable_nombre or ""
    ]
    if conector.pelo_n_id is None and conector.patch_conector_n_id is not None:
        detalle_pelo.append(f"por patch al conector {conector.patch_conector_n_id}")
    detalle = ", ".join(d for d in detalle_pelo if d)
    partes.append(f"pelo {conector.pelo_efectivo}" + (f" ({detalle})" if detalle else ""))

    identidad = conector.servicio_numero or conector.servicio_resuelto
    if conector.servicio_numero:
        cliente = conector.nombre_cliente or conector.cliente or "sin cliente"
        partes.append(
            f"conector: {conector.servicio_numero} {cliente} ({conector.estado_servicio or 'sin estado'})"
        )
    elif conector.servicio_resuelto:
        partes.append(f"conector: {conector.servicio_resuelto} (no está en LAS-FOCAS)")
    else:
        partes.append("conector: sin servicio en Cromo")

    etiqueta = conector.etiqueta_numero or conector.etiqueta_pelo
    conocidos = {identidad, conector.servicio_resuelto, etiqueta, conector.etiqueta_pelo} - {None}
    if conector.historico_numero and conector.historico_numero not in conocidos:
        partes.append(f"histórico: {_con_estado(conector.historico_numero, conector.historico_estado)}")
    if etiqueta and etiqueta not in {identidad, conector.servicio_resuelto}:
        partes.append(f"etiqueta del pelo: {_con_estado(etiqueta, conector.etiqueta_estado)}")
    return " · ".join(partes)


def texto_candidatas(patchera: str, candidatas: list[Any]) -> str:
    """Respuesta a una patchera que está en varias bandejas: se listan (hasta 10) y no se elige."""
    lineas = [
        f":warning: La patchera `{patchera}` está en {len(candidatas)} bandejas distintas; no elijo una:"
    ]
    lineas += [
        f"• {b.odf_nombre or 'ODF sin nombre'} (ODF {b.odf_n_id}) · patchera {b.bandeja_nombre} "
        f"(bandeja {b.bandeja_n_id})"
        for b in candidatas[:_MAX_CANDIDATAS_LISTADAS]
    ]
    if len(candidatas) > _MAX_CANDIDATAS_LISTADAS:
        lineas.append(f"… y {len(candidatas) - _MAX_CANDIDATAS_LISTADAS} más.")
    return "\n".join(lineas)


def texto_posicion_sin_archivo(patchera: str, posicion: PosicionTrack) -> Optional[str]:
    """Aviso de un conector que no dio `.txt`, o `None` si dio."""
    donde = f"`{patchera}:{posicion.conector}`"
    if posicion.estado == POSICION_INEXISTENTE:
        return f":mag: {donde} no existe en esa patchera."
    if posicion.estado == POSICION_SIN_PELO:
        patch = (
            f" (tiene patch al conector {posicion.patch_conector_n_id})"
            if posicion.patch_conector_n_id is not None
            else ""
        )
        return (
            f":information_source: {donde} no tiene pelo conectado en Cromo, así que no hay "
            f"tracking{patch}."
        )
    if posicion.estado == POSICION_SIN_CAMINO:
        return (
            f":warning: {donde} — Cromo no resolvió el camino del pelo {posicion.pelo_n_id}: "
            f"{posicion.motivo or 'sin detalle'}."
        )
    return None


async def resolver_posiciones(
    sesion: Any, abrir_cliente: Any, patchera: str, conectores: tuple[int, ...]
) -> ResultadoTrackOdf:
    """Busca la patchera, sus conectores pedidos y el tracking de cada pelo.

    `abrir_cliente()` devuelve el context manager async del cliente de Cromo; se abre una sola vez
    y sólo si algún conector tiene pelo. El pelo es el del conector o, si no tiene, el del conector
    al que tiene patch (un salto). La caché se atribuye al Servicio del conector sólo si está
    Activo; si no, `servicio_id=None` (el upsert conserva la atribución que ya tuviera la fila).
    No escribe auditoría ni evidencia del árbitro: una posición suelta no es el Servicio entero.
    """
    from core.services.cromo import client as cromo_client
    from core.services.cromo import odf_conectores, tracking_service
    from core.services.cromo.camino_optico_txt import nombre_archivo_posicion

    bandejas = await odf_conectores.bandejas_por_nombre(sesion, patchera)
    if not bandejas:
        return ResultadoTrackOdf(estado=ESTADO_PATCHERA_NO_ENCONTRADA, patchera=patchera)
    if len(bandejas) > 1:
        return ResultadoTrackOdf(
            estado=ESTADO_PATCHERA_AMBIGUA, patchera=patchera, candidatas=list(bandejas)
        )
    (bandeja,) = bandejas
    por_numero = {
        c.numero_conector: c
        for c in await odf_conectores.conectores_de_bandeja(
            sesion, bandeja.bandeja_n_id, [str(n) for n in conectores], odf_n_id=bandeja.odf_n_id
        )
    }
    resultado = ResultadoTrackOdf(estado=ESTADO_OK, patchera=patchera, bandeja=bandeja)
    pendientes: list[tuple[int, Any]] = []
    for numero in conectores:
        conector = por_numero.get(str(numero))
        if conector is None:
            resultado.posiciones.append(PosicionTrack(numero, POSICION_INEXISTENTE))
        elif conector.pelo_efectivo is None:
            resultado.posiciones.append(
                PosicionTrack(
                    numero, POSICION_SIN_PELO, patch_conector_n_id=conector.patch_conector_n_id
                )
            )
        else:
            resultado.posiciones.append(PosicionTrack(numero, POSICION_OK))
            pendientes.append((len(resultado.posiciones) - 1, conector))
    if not pendientes:
        return resultado

    async with abrir_cliente() as cliente:
        for indice, conector in pendientes:
            pelo = conector.pelo_efectivo
            posicion = resultado.posiciones[indice]
            posicion.pelo_n_id = pelo
            try:
                tracking = await tracking_service.obtener_tracking(
                    cliente,
                    sesion,
                    servicio_id=conector.servicio_pk if _es_activo(conector.estado_servicio) else None,
                    pelo_n_id=pelo,
                )
            except tracking_service.TrackingNoDisponible as exc:
                posicion.estado, posicion.motivo = POSICION_SIN_CAMINO, exc.motivo or str(exc)
                continue
            except cromo_client.CromoClientError as exc:
                # Cromo caído: lo ya resuelto se entrega, el resto no se llegó a pedir.
                resultado.posiciones = resultado.posiciones[:indice] + [
                    p for p in resultado.posiciones[indice + 1 :] if p.estado != POSICION_OK
                ]
                resultado.estado, resultado.mensaje = ESTADO_ERROR, f"Cromo no respondió: {exc}"
                return resultado
            posicion.descripcion = descripcion_posicion(bandeja, conector)
            posicion.archivo = TrackingArchivo(
                nombre=nombre_archivo_posicion(
                    conector.servicio_numero, bandeja.bandeja_nombre, conector.numero_conector, pelo
                ),
                contenido=tracking.contenido,
                desde_cache=tracking.desde_cache,
                duracion_ms=tracking.duracion_ms,
            )
    return resultado


async def _posiciones_async(patchera: str, conectores: tuple[int, ...]) -> ResultadoTrackOdf:
    from core.services.cromo import client as cromo_client
    from core.services.cromo.config import get_cromo_config

    async with _sesion_async() as sesion:
        return await resolver_posiciones(
            sesion,
            lambda: cromo_client.CromoClient(config=get_cromo_config()),
            patchera,
            conectores,
        )


def generar_tracking_posiciones(patchera: str, conectores: tuple[int, ...]) -> ResultadoTrackOdf:
    """Los `.txt` de las posiciones pedidas de una patchera. Bloqueante, como `generar_trackings`
    (mismo thread propio con su event loop y engine `NullPool`)."""
    return _correr_en_thread(
        "slack-track-odf", lambda: _posiciones_async(patchera, tuple(conectores))
    )
