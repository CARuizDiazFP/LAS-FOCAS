# Nombre de archivo: correccion_ingreso.py
# Ubicación de archivo: modules/slack_baneo_notifier/correccion_ingreso.py
# Descripción: Parser y constructores de respuesta de los comandos "Forzar ingreso"/"Forzar egreso" (funciones puras, sin DB ni Slack)

"""Comandos de corrección manual de un `Ingreso` mal registrado (docs/superpowers/plans/
2026-09-23-correccion-ingresos-servicios.md, Task 4):

    Forzar ingreso <CAMARA>
    Forzar ingreso <CAMARA> DD-MM-AAAA HH:MM
    Forzar egreso
    Forzar egreso <CAMARA> DD-MM-AAAA HH:MM
    Forzar egreso #<ingreso_id>

Este módulo es deliberadamente puro: parsea texto y arma strings de respuesta, sin tocar DB ni
Slack. La resolución real (buscar la cámara, resolver el hilo, decidir qué `Ingreso` cerrar) vive en
`core/services/ingreso_correccion_service.py` (Task 5) y el wiring del listener en
`modules/slack_baneo_notifier/listener.py` (Task 6) — ambos consumen las funciones de acá.

Dos casos especiales de la gramática de "Forzar egreso" que NO están en la lista de arriba pero se
derivan de ella:

- Texto vacío tras "Forzar egreso" (nada más) → forma "bare": ambos `camara_texto` e `ingreso_id`
  quedan en `None` — la Task 5 resuelve la cámara y el momento enteramente desde el hilo.
- Texto tras "Forzar egreso" que NO matchea ni "<CAMARA> DD-MM-AAAA HH:MM" ni "#<id>" (ej. sólo
  "Forzar egreso Cra Mitre 302", sin fecha) → `camara_texto` queda seteado, `momento` e `ingreso_id`
  en `None`. Este parser no conoce el tipo de formulario del hilo (Ingreso o Egreso) — devuelve esa
  combinación de forma neutral, sin prescribir una respuesta única. La decisión es de la Task 5,
  según la tabla "Regla del momento implícito" del plan: si el hilo es de tipo Egreso, el momento
  puede resolverse implícito desde su `ts` (misma regla que "Forzar ingreso <CAMARA>"); si no hay
  ningún hilo así, no hay ningún momento disponible y corresponde pedirlo explícito con
  `construir_respuesta_falta_fecha`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from core.utils.tz import TZ_ARG, fmt_local
from modules.slack_baneo_notifier.cable_info import quitar_formato_slack
from modules.slack_baneo_notifier.camara_search import limpiar_ruido_operativo

# "Forzar ingreso <CAMARA> DD-MM-AAAA HH:MM" — mismo patrón no-goloso que `_RE_CABLE_BUFFER`
# (`cable_info.py:52`) y por la misma razón: sin el `.+?` (en vez de `.+`), el nombre de cámara se
# comería la fecha entera. El datetime va anclado con `\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}` inmediatamente
# después del nombre; el grupo final opcional es el `motivo` libre que puede sobrar (decisión de
# producto: no hay `motivo:` obligatorio ni palabra clave — cualquier texto que sobre después de la
# hora se captura como motivo, nunca se exige ni se rechaza por su ausencia).
_RE_FORZAR_INGRESO_CON_FECHA = re.compile(
    r"(?i)^forzar\s+ingreso\s+(.+?)\s+(\d{2}-\d{2}-\d{4})\s+(\d{2}:\d{2})(?:\s+(.+))?$"
)
# "Forzar ingreso <CAMARA>" sin fecha — el momento queda implícito (lo resuelve la Task 5 desde el
# `ts` del hilo). Acá sí es correcto que el nombre sea "goloso" (`.+`): no hay ningún sufijo del que
# protegerlo.
_RE_FORZAR_INGRESO_SIN_FECHA = re.compile(r"(?i)^forzar\s+ingreso\s+(.+)$")

# "Forzar egreso #<ingreso_id>" — el operador ya sabe cuál de varios ingresos abiertos cerrar (ver
# `construir_respuesta_varios_ingresos_abiertos`, que le ofrece justamente este comando).
_RE_FORZAR_EGRESO_POR_ID = re.compile(r"(?i)^forzar\s+egreso\s+#(\d+)(?:\s+(.+))?$")
# "Forzar egreso <CAMARA> DD-MM-AAAA HH:MM" — mismo patrón/razón que `_RE_FORZAR_INGRESO_CON_FECHA`.
_RE_FORZAR_EGRESO_CON_FECHA = re.compile(
    r"(?i)^forzar\s+egreso\s+(.+?)\s+(\d{2}-\d{2}-\d{4})\s+(\d{2}:\d{2})(?:\s+(.+))?$"
)
# Catch-all de "Forzar egreso" — se intenta DESPUÉS de los dos anteriores (más específicos). Cubre
# tanto la forma "bare" (nada más, grupo 1 vacío) como el caso "cámara sin fecha" (grupo 1 con texto
# que no matcheó ni el patrón `#<id>` ni el patrón con fecha) — ver docstring del módulo.
_RE_FORZAR_EGRESO_BARE = re.compile(r"(?i)^forzar\s+egreso(?:\s+(.+))?$")

# Respuesta de seguimiento cuando el operador contesta en el hilo sólo con la fecha/hora pendiente
# (Task 6: "Fecha pendiente" — el bot ya pidió la fecha con `construir_respuesta_falta_fecha` y
# espera esta forma corta como respuesta, no el comando completo de nuevo).
_RE_MOMENTO_SOLO = re.compile(r"(?i)^(\d{2}-\d{2}-\d{4})\s+(\d{2}:\d{2})$")

# Ver `Step 3` del brief: rechazar fecha futura (no puede haber pasado todavía) y fecha de más de 90
# días atrás (protección contra el error de tipeo de año más común con `DD-MM-AAAA`: un `2024` tipeado
# en vez de `2026` da una fecha absurdamente vieja en vez de un desvío chico y difícil de notar).
_DIAS_MAXIMOS_HACIA_ATRAS = 90

RazonMomentoInvalido = Literal["formato", "futuro", "fuera_de_rango"]


class MomentoInvalidoError(Exception):
    """Se lanza cuando el sufijo `DD-MM-AAAA HH:MM` matchea la forma sintáctica del regex pero el
    valor no es un momento válido para forzar un movimiento — mismo patrón que
    `camara_search.AmbiguousSearchError` (una condición esperada del dominio, no un bug).

    Atributos:
        razon: ``"formato"`` (fecha/hora no calendáricamente válida, ej. día 32 o "25:00"),
            ``"futuro"`` (posterior al momento de referencia) o ``"fuera_de_rango"`` (más de
            `_DIAS_MAXIMOS_HACIA_ATRAS` días antes del momento de referencia).
        texto_crudo: el "DD-MM-AAAA HH:MM" tal como lo escribió el operador, para mostrarlo en la
            respuesta de error.
    """

    def __init__(self, razon: RazonMomentoInvalido, texto_crudo: str) -> None:
        self.razon = razon
        self.texto_crudo = texto_crudo
        super().__init__(f"Momento inválido ({razon}): '{texto_crudo}'")


@dataclass(slots=True)
class ComandoForzarIngreso:
    """Resultado de parsear "Forzar ingreso <CAMARA>" (`momento=None`, implícito del `ts` del hilo —
    lo resuelve la Task 5) o "Forzar ingreso <CAMARA> DD-MM-AAAA HH:MM" (`momento` ya parseado y
    convertido a UTC)."""

    camara_texto: str
    momento: datetime | None
    motivo: str | None


@dataclass(slots=True)
class ComandoForzarEgreso:
    """Resultado de parsear una de las formas de "Forzar egreso" — ver docstring del módulo para el
    detalle de qué combinación de campos corresponde a cada forma:

    - bare: ``camara_texto=None``, ``ingreso_id=None``, ``momento=None``.
    - cámara sin momento resuelto (ver docstring del módulo — la Task 5 decide qué responder según
      el tipo de hilo): ``camara_texto`` seteado, el resto en `None`.
    - cámara + fecha: ``camara_texto`` y ``momento`` seteados, ``ingreso_id=None``.
    - ``#<id>``: ``ingreso_id`` seteado, ``camara_texto=None``, ``momento=None``.
    """

    camara_texto: str | None
    ingreso_id: int | None
    momento: datetime | None
    motivo: str | None


@dataclass(slots=True)
class IngresoAbiertoInfo:
    """Datos mínimos de un `Ingreso` abierto candidato a cerrar, para
    `construir_respuesta_varios_ingresos_abiertos` — un dataclass propio (no el modelo ORM `Ingreso`)
    para que este resultado no dependa de una sesión de SQLAlchemy: la Task 5 lo arma a partir de
    filas `Ingreso` ya resueltas y desconectadas de la sesión."""

    id: int
    tecnico: str | None
    fecha_inicio: datetime | None


def _normalizar_texto(texto: str) -> str:
    return quitar_formato_slack(re.sub(r"\s+", " ", texto).strip())


def parsear_momento_ar(fecha_str: str, hora_str: str, *, ahora: datetime | None = None) -> datetime:
    """Parsea "DD-MM-AAAA" + "HH:MM" en hora de Buenos Aires (`TZ_ARG`) y devuelve el datetime
    convertido a UTC — `registrar_movimiento_ingreso` (`core/services/ingreso_service.py`) persiste
    `datetime.now(timezone.utc)`, así que todo lo que se compare o se guarde tiene que estar en la
    misma zona.

    Se usa `.replace(tzinfo=TZ_ARG)` sobre el datetime naive, nunca `.astimezone()` sobre un datetime
    naive (que asumiría la zona horaria del proceso que corre esto, no GMT-3 explícito) — el worker
    corre con `TZ=America/Argentina/Buenos_Aires`, pero esta función tiene que dar el mismo resultado
    sin importar en qué zona corran los tests.

    `ahora` (opcional, UTC-aware): momento de referencia para las validaciones de rango — permite que
    los tests de "fecha futura"/"fecha fuera de los 90 días" sean deterministas sin depender del reloj
    real ni de la zona horaria del proceso. Por defecto usa `datetime.now(timezone.utc)`.

    Lanza `MomentoInvalidoError`:
    - ``razon="formato"``: `fecha_str`/`hora_str` no son una fecha/hora calendáricamente válida (ej.
      día 32, mes 13, hora 25) — `datetime.strptime` ya rechaza estos valores.
    - ``razon="futuro"``: el momento es posterior al de referencia.
    - ``razon="fuera_de_rango"``: el momento es más de `_DIAS_MAXIMOS_HACIA_ATRAS` días anterior al
      de referencia.
    """
    texto_crudo = f"{fecha_str} {hora_str}"
    try:
        momento_naive = datetime.strptime(texto_crudo, "%d-%m-%Y %H:%M")
    except ValueError as exc:
        raise MomentoInvalidoError("formato", texto_crudo) from exc

    momento_ar = momento_naive.replace(tzinfo=TZ_ARG)
    momento_utc = momento_ar.astimezone(timezone.utc)
    referencia = ahora if ahora is not None else datetime.now(timezone.utc)

    if momento_utc > referencia:
        raise MomentoInvalidoError("futuro", texto_crudo)
    if referencia - momento_utc > timedelta(days=_DIAS_MAXIMOS_HACIA_ATRAS):
        raise MomentoInvalidoError("fuera_de_rango", texto_crudo)

    return momento_utc


def extraer_comando_forzar_ingreso(
    texto: str, *, ahora: datetime | None = None
) -> ComandoForzarIngreso | None:
    """Extrae "Forzar ingreso <CAMARA>" o "Forzar ingreso <CAMARA> DD-MM-AAAA HH:MM". Devuelve `None`
    si el texto no matchea (no es un error — puede ser cualquier otro mensaje del canal).

    Puede propagar `MomentoInvalidoError` cuando el texto SÍ trae un sufijo con forma de fecha/hora
    pero el valor no es válido — el caller (Task 5/6) la captura para responder con
    `construir_respuesta_momento_invalido`."""
    texto_normalizado = _normalizar_texto(texto)

    match = _RE_FORZAR_INGRESO_CON_FECHA.match(texto_normalizado)
    if match:
        camara_cruda, fecha_str, hora_str, motivo = match.groups()
        camara_texto = limpiar_ruido_operativo(camara_cruda.strip())
        if not camara_texto:
            return None
        momento = parsear_momento_ar(fecha_str, hora_str, ahora=ahora)
        return ComandoForzarIngreso(
            camara_texto=camara_texto, momento=momento, motivo=(motivo.strip() if motivo else None)
        )

    match = _RE_FORZAR_INGRESO_SIN_FECHA.match(texto_normalizado)
    if match:
        camara_texto = limpiar_ruido_operativo(match.group(1).strip())
        if not camara_texto:
            return None
        return ComandoForzarIngreso(camara_texto=camara_texto, momento=None, motivo=None)

    return None


def extraer_comando_forzar_egreso(
    texto: str, *, ahora: datetime | None = None
) -> ComandoForzarEgreso | None:
    """Extrae una de las formas de "Forzar egreso" (bare, cámara sin fecha, cámara + fecha, o
    `#<id>`) — ver docstring del módulo. Devuelve `None` si el texto no matchea en absoluto (no es un
    error — puede ser cualquier otro mensaje del canal).

    Puede propagar `MomentoInvalidoError` (ver `extraer_comando_forzar_ingreso`)."""
    texto_normalizado = _normalizar_texto(texto)

    match = _RE_FORZAR_EGRESO_POR_ID.match(texto_normalizado)
    if match:
        ingreso_id_str, motivo = match.groups()
        return ComandoForzarEgreso(
            camara_texto=None,
            ingreso_id=int(ingreso_id_str),
            momento=None,
            motivo=(motivo.strip() if motivo else None),
        )

    match = _RE_FORZAR_EGRESO_CON_FECHA.match(texto_normalizado)
    if match:
        camara_cruda, fecha_str, hora_str, motivo = match.groups()
        camara_texto = limpiar_ruido_operativo(camara_cruda.strip())
        if not camara_texto:
            return None
        momento = parsear_momento_ar(fecha_str, hora_str, ahora=ahora)
        return ComandoForzarEgreso(
            camara_texto=camara_texto,
            ingreso_id=None,
            momento=momento,
            motivo=(motivo.strip() if motivo else None),
        )

    match = _RE_FORZAR_EGRESO_BARE.match(texto_normalizado)
    if match:
        resto = (match.group(1) or "").strip()
        if not resto:
            return ComandoForzarEgreso(camara_texto=None, ingreso_id=None, momento=None, motivo=None)
        # Hay texto pero no matcheó ni "#<id>" ni "<CAMARA> DD-MM-AAAA HH:MM": no hay ningún momento
        # que este parser pueda resolver por sí mismo (no conoce el tipo de hilo). Se devuelve de
        # forma neutral — la Task 5 decide si el hilo resuelve el momento implícito o si corresponde
        # `construir_respuesta_falta_fecha` (ver docstring del módulo).
        camara_texto = limpiar_ruido_operativo(resto)
        return ComandoForzarEgreso(
            camara_texto=(camara_texto or None), ingreso_id=None, momento=None, motivo=None
        )

    return None


def extraer_momento_solo(texto: str, *, ahora: datetime | None = None) -> datetime | None:
    """Extrae el momento (parseado y convertido a UTC) de una respuesta de seguimiento que sólo trae
    "DD-MM-AAAA HH:MM" (Task 6: el operador contesta en el hilo la fecha que el bot pidió con
    `construir_respuesta_falta_fecha`, en vez de reenviar el comando completo). Devuelve `None` si el
    texto no matchea (no es un error). Puede propagar `MomentoInvalidoError`."""
    texto_normalizado = _normalizar_texto(texto)
    match = _RE_MOMENTO_SOLO.match(texto_normalizado)
    if not match:
        return None
    fecha_str, hora_str = match.groups()
    return parsear_momento_ar(fecha_str, hora_str, ahora=ahora)


# ── Constructores de respuesta (todos devuelven `str`) ──────────────────────────────────────────


def construir_respuesta_ok_forzar_ingreso(camara_nombre: str, momento_utc: datetime, actor_nombre: str) -> str:
    return (
        f"✅ Ingreso forzado registrado en *{camara_nombre}* — {fmt_local(momento_utc)}. "
        f"Ejecutado por *{actor_nombre}*."
    )


def construir_respuesta_ok_forzar_egreso_cerrado(
    camara_nombre: str,
    momento_utc: datetime,
    actor_nombre: str,
    tecnico_original: str | None = None,
) -> str:
    """"Forzar egreso" que cerró un `Ingreso` abierto existente — `tecnico_original` es el técnico de
    esa fila (puede ser `None` si nunca se pudo resolver, ver docstring de
    `_tecnico_id_filtro` en `ingreso_service.py`)."""
    tecnico_txt = f" (ingreso de *{tecnico_original}*)" if tecnico_original else ""
    return (
        f"✅ Egreso forzado registrado en *{camara_nombre}*{tecnico_txt} — cierra el ingreso abierto, "
        f"{fmt_local(momento_utc)}. Ejecutado por *{actor_nombre}*."
    )


def construir_respuesta_ok_forzar_egreso_asentado(camara_nombre: str, momento_utc: datetime, actor_nombre: str) -> str:
    """"Forzar egreso <CAMARA> DD-MM-AAAA HH:MM" cuando no había ningún `Ingreso` abierto para
    cerrar — la Task 5 lo asienta igual porque el operador lo pidió con cámara y fecha explícitas
    (nunca con las formas implícitas, que sólo pueden cerrar, no asentar de cero)."""
    return (
        f"✅ Egreso asentado en *{camara_nombre}* — {fmt_local(momento_utc)}. No había ningún ingreso "
        f"abierto para cerrar; se registró igual porque lo pediste explícitamente. "
        f"Ejecutado por *{actor_nombre}*."
    )


def construir_respuesta_falta_fecha(camara_texto: str, comando: Literal["ingreso", "egreso"]) -> str:
    """Pide la fecha/hora explícita porque no hay ningún momento implícito disponible. Sirve para
    los dos comandos, no sólo "Forzar egreso": la tabla "Regla del momento implícito" (Task 5) exige
    fecha explícita tanto para "Forzar egreso <CAMARA>" en un hilo que no es de tipo Egreso como para
    "Forzar ingreso <CAMARA>" en un hilo de tipo Egreso — mismo mensaje, sólo cambia el verbo."""
    return (
        f":warning: Para forzar un {comando} en *{camara_texto}* hace falta la fecha y hora — "
        f"reenviá el comando completo (*Forzar {comando} {camara_texto} DD-MM-AAAA HH:MM*) o "
        f"respondé en este mismo hilo sólo con *DD-MM-AAAA HH:MM*."
    )


def construir_respuesta_camara_ambigua(camara_texto: str, candidatos: list[str]) -> str:
    lista = "\n".join(f"• {c}" for c in candidatos)
    return (
        f":warning: Encontré *{len(candidatos)}* cámaras que podrían ser *{camara_texto}* — "
        f"especificá cuál:\n{lista}"
    )


def construir_respuesta_camara_no_encontrada(camara_texto: str) -> str:
    """La búsqueda no devolvió ninguna cámara ni botella para el texto pedido (distinto de
    `construir_respuesta_camara_ambigua`, que es "demasiadas"). Agregada en la Task 5: es un camino
    real y alcanzable (`buscar_camara_o_botella_cromo` devuelve `camara=None` sin lanzar) que no
    tenía respuesta propia."""
    return (
        f":warning: No encontré ninguna cámara ni botella que matchee *{camara_texto}* en el "
        f"inventario — revisá el nombre y reenviá el comando."
    )


def construir_respuesta_ingreso_no_encontrado(ingreso_id: int) -> str:
    """"Forzar egreso #<id>" con un id que no existe, o que no corresponde a una fila de tipo
    `INGRESO` (puede ser un `EGRESO` huérfano o un `INTENTO_BLOQUEADO`, que nunca fue un ingreso
    real y por lo tanto no se cierra)."""
    return (
        f":warning: No encontré ningún ingreso *#{ingreso_id}* que se pueda cerrar — verificá el "
        f"número en la lista que te pasé."
    )


def construir_respuesta_sin_ingreso_abierto(camara_nombre: str) -> str:
    """No hay ningún `Ingreso` abierto para cerrar en la cámara resuelta. Sólo la forma con cámara y
    fecha explícitas puede asentar un egreso de cero (ver `construir_respuesta_ok_forzar_egreso_asentado`);
    las formas implícitas responden esto en vez de crear una fila EGRESO huérfana."""
    return (
        f":warning: No hay ningún ingreso abierto en *{camara_nombre}* para cerrar. Si aun así "
        f"querés asentar el egreso, usá la forma completa: *Forzar egreso {camara_nombre} "
        f"DD-MM-AAAA HH:MM*."
    )


def construir_respuesta_varios_ingresos_abiertos(camara_nombre: str, ingresos: list[IngresoAbiertoInfo]) -> str:
    lineas = []
    for ing in ingresos:
        tecnico_txt = ing.tecnico or "técnico no identificado"
        fecha_txt = fmt_local(ing.fecha_inicio) if ing.fecha_inicio else "sin fecha registrada"
        lineas.append(f"• *#{ing.id}* — {tecnico_txt} — ingresó {fecha_txt}")
    detalle = "\n".join(lineas)
    return (
        f":warning: Hay *{len(ingresos)}* ingresos abiertos en *{camara_nombre}* — elegí cuál cerrar "
        f"con *Forzar egreso #<id>*:\n{detalle}"
    )


def construir_respuesta_egreso_anterior_al_ingreso(momento_egreso_utc: datetime, fecha_inicio_utc: datetime) -> str:
    return (
        f":warning: El egreso ({fmt_local(momento_egreso_utc)}) no puede ser anterior o igual al "
        f"ingreso que cerraría ({fmt_local(fecha_inicio_utc)}) — corregí la fecha."
    )


def construir_respuesta_ingreso_ya_cerrado(ingreso_id: int, fecha_fin_utc: datetime) -> str:
    return (
        f":warning: El ingreso *#{ingreso_id}* ya tiene un egreso registrado "
        f"({fmt_local(fecha_fin_utc)}) — no hay nada para cerrar."
    )


def construir_respuesta_hilo_sin_formulario() -> str:
    return (
        ":warning: No pude identificar ningún formulario de Ingreso/Egreso en este hilo — usá la "
        "forma completa con cámara y fecha explícitas, ej. *Forzar egreso <cámara> DD-MM-AAAA HH:MM*."
    )


def construir_respuesta_momento_invalido(error: MomentoInvalidoError) -> str:
    if error.razon == "futuro":
        return (
            f":warning: La fecha *{error.texto_crudo}* es futura — no se puede forzar un movimiento "
            f"que todavía no pasó."
        )
    if error.razon == "fuera_de_rango":
        return (
            f":warning: La fecha *{error.texto_crudo}* es de hace más de {_DIAS_MAXIMOS_HACIA_ATRAS} "
            f"días — revisá si hay un error de tipeo en el año."
        )
    return (
        f":warning: No pude interpretar la fecha/hora *{error.texto_crudo}* — usá el formato "
        f"DD-MM-AAAA HH:MM (ej. 22-09-2026 10:00)."
    )


__all__ = [
    "ComandoForzarEgreso",
    "ComandoForzarIngreso",
    "IngresoAbiertoInfo",
    "MomentoInvalidoError",
    "construir_respuesta_camara_ambigua",
    "construir_respuesta_camara_no_encontrada",
    "construir_respuesta_egreso_anterior_al_ingreso",
    "construir_respuesta_falta_fecha",
    "construir_respuesta_hilo_sin_formulario",
    "construir_respuesta_ingreso_no_encontrado",
    "construir_respuesta_ingreso_ya_cerrado",
    "construir_respuesta_momento_invalido",
    "construir_respuesta_ok_forzar_egreso_asentado",
    "construir_respuesta_ok_forzar_egreso_cerrado",
    "construir_respuesta_ok_forzar_ingreso",
    "construir_respuesta_sin_ingreso_abierto",
    "construir_respuesta_varios_ingresos_abiertos",
    "extraer_comando_forzar_egreso",
    "extraer_comando_forzar_ingreso",
    "extraer_momento_solo",
    "parsear_momento_ar",
]
