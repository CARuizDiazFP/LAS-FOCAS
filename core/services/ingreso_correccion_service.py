# Nombre de archivo: ingreso_correccion_service.py
# Ubicación de archivo: core/services/ingreso_correccion_service.py
# Descripción: Servicio de corrección manual de Ingresos/Egresos ("Forzar ingreso"/"Forzar egreso") con resolución del hilo Slack en cascada y auditoría append-only

"""Resuelve y ejecuta los comandos de corrección `Forzar ingreso` / `Forzar egreso`
(`docs/superpowers/plans/2026-09-23-correccion-ingresos-servicios.md`, Task 5).

El parser de los comandos es puro y vive en `core/services/ingreso_correccion_comandos.py`
(Task 4): decide qué **forma** escribió el operador, nunca si esa forma es válida. Esa decisión —
que depende del formulario original del hilo — es de este módulo. El wiring con el listener de
Slack (detección del mensaje, posteo de la respuesta, flujo de "fecha pendiente") es de la Task 6;
acá no se postea nada ni se lee ningún evento: el caller pasa los datos del mensaje y recibe un
`ResultadoCorreccion` con el texto ya armado.

## Cascada de resolución del hilo (Step 1 del brief)

1. `Ingreso.thread_ts` — el movimiento real que el hilo ya generó. Da tipo, técnico, cámara y
   botella sin una sola llamada de red.
2. `IngresoSinMatch.thread_ts` — el caso que quedó pendiente en ese hilo. Da `texto_mensaje`
   (el evento completo), del que se re-extraen tipo, técnico y nombre de cámara.
3. `client.conversations_replies(channel, ts=thread_ts, limit=1)` — el mensaje raíz. Cubre los
   hilos históricos anteriores a las columnas de la Task 2. **Requiere el scope `channels:history`
   (o `groups:history`) en el panel de la Slack App** — no verificable desde código, mismo criterio
   que `app_mentions:read` (`listener.py`) y `users:read` (`core/services/slack_usuarios.py`). Si el scope
   falta, la llamada falla y la cascada **degrada con gracia**: no se propaga ninguna excepción, se
   loguea un warning y se termina pidiendo la forma con fecha explícita.

El **momento del hilo** no sale de ninguno de los tres niveles sino del propio `thread_ts`: en Slack
el `thread_ts` de una respuesta *es* el `ts` del mensaje raíz, y ese `ts` es el momento en que el
formulario se envió. `IngresoSinMatch.created_at` (cuándo el listener lo *procesó*) y
`Ingreso.fecha_inicio` quedan sólo como fallback para un `ts` que no se pueda convertir. Esto además
disuelve el caso "más de un caso en el hilo": un mensaje multi-botella genera varias filas, pero
todas comparten un único `ts` de mensaje raíz.

## Regla del momento implícito (Step 3, ruling vinculante del coordinador)

| Hilo | Comando | Momento |
|---|---|---|
| Ingreso | `Forzar ingreso <CAMARA>` | `ts` del hilo |
| Egreso | `Forzar egreso [<CAMARA>]` | `ts` del hilo |
| Ingreso | `Forzar egreso` | fecha/hora explícita, **siempre** |
| Egreso | `Forzar ingreso` | fecha/hora explícita, **siempre** |

El momento sale del hilo **sólo** cuando el tipo del formulario coincide con el tipo forzado. Forzar
un egreso en el hilo de un formulario de *Ingreso* con el `ts` de ese hilo registraría una visita de
duración cero — el mismo error que `ingreso_service.py` evita a propósito dejando `fecha_inicio=None`
en un egreso huérfano. El caso operativo que más importa es justamente ese: el ingreso quedó abierto
porque el formulario de egreso nunca llegó.

## Egreso sin fallback implícito (Step 4)

`registrar_movimiento_ingreso(tipo_movimiento="Egreso")` **crea una fila EGRESO huérfana** si no
encuentra un ingreso abierto. Correcto para el flujo en vivo, inaceptable acá: alguien puede repetir
el comando por error. Nunca se la llama a ciegas. Primero se resuelve el conjunto de ingresos
abiertos candidatos (`tipo=INGRESO`, `fecha_fin IS NULL`) y recién ahí se decide:

- **0 candidatos** → sólo la forma con cámara *y* fecha explícitas asienta deliberadamente (ahí sí
  se llama a `registrar_movimiento_ingreso`, sabiendo que va a crear la fila huérfana); las demás
  responden que no hay nada que cerrar.
- **1 candidato** → se cierra **esa** fila con `cerrar_ingreso_forzado` (nunca re-seleccionada por
  heurística).
- **2 o más** → se listan con `id`, técnico y `fecha_inicio`, y se exige `Forzar egreso #<id>`.

Validación dura: `momento_egreso > ingreso.fecha_inicio`, **estricto**.

## Auditoría (Step 5)

**Cada** invocación escribe una fila en `app.ingresos_correcciones`, incluidos todos los rechazos,
con su `resultado` y su `error_detalle` — un rechazo sin rastro es un agujero en el log. La tabla
tiene un trigger que bloquea `UPDATE`/`DELETE`: es append-only de verdad, nunca se corrige una fila
anterior. `Forzar ingreso` sobre un grupo hoy baneado registra un **INGRESO real**, nunca
`INTENTO_BLOQUEADO`: el operador está afirmando que el técnico entró, y el estado de baneo de *ahora*
no es evidencia sobre el pasado (ver `docs/decisiones.md`, entrada 2026-09-23). La respuesta sí avisa
si el grupo está baneado en este momento.

Sin allowlist: cualquiera del canal puede ejecutar estos comandos, y un operador puede cerrar el
ingreso abierto de otro técnico. La auditoría es el único control (decisión de producto ya tomada).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy.orm import Session

from core.services.camara_estado_service import get_camara_estado_contexto
from core.services.cromo.camara_botella_busqueda import buscar_camara_o_botella_cromo
from core.services.fo_monitor.alcance import resolver_alcance
from core.services.fo_monitor.motor import ESTADOS_ABIERTOS as FOMON_ESTADOS_ABIERTOS
from core.services.fo_monitor.motor import congelar_alcance
from core.services.ingreso_service import cerrar_ingreso_forzado, registrar_movimiento_ingreso
from db.models.cromo import CromoBotella
from db.models.fo_monitor import (
    FomonConsulta,
    FomonIntervencion,
    FomonIntervencionIngreso,
    FomonIntervencionServicio,
)
from db.models.infra import Camara, Ingreso, IngresoCorreccion, IngresoSinMatch, IngresoTipo
from core.services.camara_busqueda_nombre import AmbiguousSearchError
from core.text.mensaje_ingreso import (
    extraer_nombre_camara,
    extraer_slack_user_id_autorizacion,
    extraer_tipo_movimiento,
)
from core.text.normalizacion import limpiar_ruido_operativo
from core.services.ingreso_correccion_comandos import (
    ComandoForzarEgreso,
    ComandoForzarIngreso,
    IngresoAbiertoInfo,
    MomentoInvalidoError,
    construir_respuesta_camara_ambigua,
    construir_respuesta_camara_no_encontrada,
    construir_respuesta_egreso_anterior_al_ingreso,
    construir_respuesta_falta_fecha,
    construir_respuesta_hilo_sin_formulario,
    construir_respuesta_ingreso_anulado,
    construir_respuesta_ingreso_no_encontrado,
    construir_respuesta_ingreso_ya_cerrado,
    construir_respuesta_momento_invalido,
    construir_respuesta_ok_forzar_egreso_asentado,
    construir_respuesta_ok_forzar_egreso_cerrado,
    construir_respuesta_ok_forzar_ingreso,
    construir_respuesta_sin_ingreso_abierto,
    construir_respuesta_varios_ingresos_abiertos,
    extraer_comando_forzar_egreso,
    extraer_comando_forzar_ingreso,
)
from core.services.slack_usuarios import resolver_nombre_tecnico

logger = logging.getLogger("slack_baneo_worker.ingreso_correccion")

# ── Valores de `IngresoCorreccion.comando` (String(32)) ─────────────────────────────────────────

COMANDO_FORZAR_INGRESO = "FORZAR_INGRESO"
COMANDO_FORZAR_EGRESO = "FORZAR_EGRESO"
# Desde 2026-10-23: corrección desde el portal (admin), siempre `origen='web'`.
COMANDO_MOVER_INGRESO = "MOVER_INGRESO"
COMANDO_ANULAR_INGRESO = "ANULAR_INGRESO"

# ── Valores de `IngresoCorreccion.origen` (String(16), migración `20260928_01`) ─────────────────

ORIGEN_SLACK = "slack"
ORIGEN_WEB = "web"

# ── Valores de `IngresoCorreccion.fuente_momento` (String(16)) ──────────────────────────────────

FUENTE_MOMENTO_HILO = "hilo"
FUENTE_MOMENTO_EXPLICITO = "explicito"

# ── Valores de `IngresoCorreccion.resultado` (String(64)) ───────────────────────────────────────
# Constantes y no literales sueltos: son el vocabulario del log de auditoría y la Task 6 los
# consulta para el flujo de "fecha pendiente".

RESULTADO_OK_INGRESO = "OK_INGRESO"
RESULTADO_OK_EGRESO_CERRADO = "OK_EGRESO_CERRADO"
RESULTADO_OK_EGRESO_ASENTADO = "OK_EGRESO_ASENTADO"
RESULTADO_CAMARA_AMBIGUA = "CAMARA_AMBIGUA"
RESULTADO_CAMARA_NO_ENCONTRADA = "CAMARA_NO_ENCONTRADA"
RESULTADO_VARIOS_INGRESOS_ABIERTOS = "VARIOS_INGRESOS_ABIERTOS"
RESULTADO_SIN_INGRESO_ABIERTO = "SIN_INGRESO_ABIERTO"
RESULTADO_EGRESO_ANTERIOR_AL_INGRESO = "EGRESO_ANTERIOR_AL_INGRESO"
RESULTADO_INGRESO_YA_CERRADO = "INGRESO_YA_CERRADO"
# Desde 2026-10-23: `#<id>` (Slack o web) apunta a un ingreso anulado desde el portal.
RESULTADO_INGRESO_ANULADO = "INGRESO_ANULADO"
RESULTADO_INGRESO_NO_ENCONTRADO = "INGRESO_NO_ENCONTRADO"
RESULTADO_HILO_SIN_FORMULARIO = "HILO_SIN_FORMULARIO"
RESULTADO_MOMENTO_INVALIDO = "MOMENTO_INVALIDO"
RESULTADO_ERROR_INTERNO = "ERROR_INTERNO"
# Desde 2026-10-23: mover/anular un ingreso desde el portal (`mover_ingreso_web`/`anular_ingreso_web`).
# Un ingreso inexistente, uno anulado y una cámara destino inexistente reusan
# `INGRESO_NO_ENCONTRADO`, `INGRESO_ANULADO` y `CAMARA_NO_ENCONTRADA`.
RESULTADO_OK_INGRESO_MOVIDO = "OK_INGRESO_MOVIDO"
RESULTADO_OK_INGRESO_ANULADO = "OK_INGRESO_ANULADO"
RESULTADO_BOTELLA_INVALIDA = "BOTELLA_INVALIDA"
RESULTADO_MISMO_DESTINO = "MISMO_DESTINO"
RESULTADO_MOTIVO_INVALIDO = "MOTIVO_INVALIDO"
# El destino es una fila con `camara_padre_id` (Botella legado dentro de otra Cámara), no una Cámara raíz.
RESULTADO_DESTINO_NO_RAIZ = "DESTINO_NO_RAIZ"

# Pedido de fecha: NO es un rechazo terminal, es un **estado pendiente**. La Task 6 busca
# exactamente esta fila (`resultado='PENDIENTE_FECHA'`, mismo `thread_ts`, menos de 30 minutos) para
# reconocer la respuesta de seguimiento que trae sólo `DD-MM-AAAA HH:MM` y re-ejecutar el comando.
# Deliberadamente no existe un `RESULTADO_FALTA_FECHA` paralelo: dos nombres para el mismo evento
# dejarían el seguimiento consultando un valor que nadie escribe, y el flujo moriría en silencio.
RESULTADO_PENDIENTE_FECHA = "PENDIENTE_FECHA"

# ── Valores explícitos de `camara_texto_solicitado` (NOT NULL) ──────────────────────────────────
# Ruling 6 del coordinador: las formas "bare" y `#<id>` no nombran ninguna cámara, pero la columna
# es NOT NULL y la migración ya está aplicada y verificada. Se escribe un valor explícito y legible
# en vez de una cadena vacía, que en un log de auditoría es ambigua (¿no había texto, o el texto se
# perdió?).
CAMARA_TEXTO_DEL_HILO = "(del hilo)"
CAMARA_TEXTO_NO_PARSEADO = "(no parseado)"

_LARGO_CAMARA_TEXTO = 512
_LARGO_ACTOR_NOMBRE = 255

TipoFormulario = Literal["Ingreso", "Egreso"]

# Por qué mover/anular dejó una intervención de FO Monitor abierta como estaba.
# - OTROS_INGRESOS_VIGENTES: le quedan otros ingresos vigentes vinculados que no acompañan el cambio
#   ("Botella 1 y 2" del mismo hilo) — mover y anular.
# - CONSULTAS_YA_ENVIADAS: ya se le mandó a burritoIA al menos una consulta (ENVIADA, RESPONDIDA o
#   TIMEOUT) con el alcance de la cámara vieja; recalcularlo en silencio mezclaría mediciones de dos
#   cámaras — sólo mover.
OMISION_OTROS_INGRESOS_VIGENTES = "OTROS_INGRESOS_VIGENTES"
OMISION_CONSULTAS_YA_ENVIADAS = "CONSULTAS_YA_ENVIADAS"


@dataclass(slots=True, frozen=True)
class IntervencionFomonOmitida:
    intervencion_id: int
    motivo: str


@dataclass(slots=True)
class ResultadoCorreccion:
    """Lo que la Task 6 necesita para responder en el hilo y para decidir si abre el flujo de fecha
    pendiente. `auditoria` es la fila de `app.ingresos_correcciones` recién insertada (o `None` si
    la propia escritura de auditoría falló, que se loguea como error pero nunca rompe la respuesta)."""

    resultado: str
    respuesta: str
    comando: str
    ingreso: Ingreso | None = None
    auditoria: IngresoCorreccion | None = None
    # Sólo mover/anular desde el portal: ids de las intervenciones de FO Monitor abiertas vinculadas
    # al ingreso que se reubicaron/cancelaron, y las que se dejaron como estaban (con el motivo,
    # `OMISION_*`).
    intervenciones_fomon: list[int] = field(default_factory=list)
    intervenciones_fomon_omitidas: list[IntervencionFomonOmitida] = field(default_factory=list)


@dataclass(slots=True)
class ContextoHilo:
    """Formulario original del hilo, resuelto por la cascada de tres niveles.

    `nivel` es `None` cuando ningún nivel respondió (hilo histórico sin filas y sin scope de
    `conversations.replies`, o comando enviado fuera de un hilo). `camaras_del_hilo` sólo se puebla
    cuando el nivel 1 encontró filas `Ingreso` de **más de una `camara_id` distinta** para el mismo
    hilo (mensaje multi-botella): ahí sí la cámara del hilo es ambigua y las formas implícitas no
    pueden adivinar cuál. Dos o más filas de la MISMA cámara (p. ej. `Forzar ingreso` repetido por
    error, sin guard porque dos técnicos en la misma cámara es legítimo) no cuentan como ambigüedad
    de cámara — ahí `camara` ya viene resuelta y Step 4 decide con `VARIOS_INGRESOS_ABIERTOS`.
    """

    nivel: int | None = None
    tipo_movimiento: TipoFormulario | None = None
    momento: datetime | None = None
    camara: Camara | None = None
    botella: CromoBotella | None = None
    camaras_del_hilo: list[str] = field(default_factory=list)
    texto_camara: str | None = None
    tecnico_nombre: str | None = None
    caso_sin_match: IngresoSinMatch | None = None
    detalle: str = "sin hilo"


# ── Helpers de momento ──────────────────────────────────────────────────────────────────────────


def _momento_desde_ts(ts: str | None) -> datetime | None:
    """Convierte un `ts` de Slack (`"1690000000.000001"`, segundos epoch con microsegundos) a
    `datetime` UTC-aware. Devuelve `None` ante cualquier valor no convertible — un `ts` malformado
    nunca rompe el comando, sólo hace caer el momento al fallback del nivel correspondiente."""
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        logger.warning("ts de Slack no convertible a datetime: %r", ts)
        return None


def _como_utc(momento: datetime | None) -> datetime | None:
    """Normaliza a UTC-aware antes de comparar. Una fila vieja de `app.ingresos` podría venir naive
    (la columna es `DateTime(timezone=True)`, pero el dato histórico manda); comparar naive contra
    aware lanza `TypeError`. Mismo criterio que `core/utils/tz.fmt_local`: naive se asume UTC."""
    if momento is None:
        return None
    if momento.tzinfo is None:
        return momento.replace(tzinfo=timezone.utc)
    return momento


def _momento_de_fila(ingreso: Ingreso) -> datetime | None:
    """Momento que representa el movimiento de una fila `Ingreso`: `fecha_fin` para un EGRESO (el
    único horario que esa fila conoce), `fecha_inicio` para un INGRESO o un INTENTO_BLOQUEADO."""
    if ingreso.tipo == IngresoTipo.EGRESO:
        return ingreso.fecha_fin
    return ingreso.fecha_inicio


def _tipo_formulario_de_fila(ingreso: Ingreso) -> TipoFormulario:
    """Tipo del **formulario** que originó la fila. Un `INTENTO_BLOQUEADO` nació de un formulario de
    Ingreso (el intento se bloqueó por baneo, pero el formulario decía "Ingreso")."""
    return "Egreso" if ingreso.tipo == IngresoTipo.EGRESO else "Ingreso"


# ── Cascada de resolución del hilo ──────────────────────────────────────────────────────────────


def _mensaje_raiz_del_hilo(client: Any, canal_id: str | None, thread_ts: str | None) -> dict | None:
    """Nivel 3: el mensaje raíz del hilo vía `conversations.replies`.

    **Nunca lanza** — mismo contrato que `slack_usuarios.resolver_nombre_tecnico`. Degrada a
    `None` ante cualquiera de los tres modos de falla reales: excepción (scope `channels:history`
    faltante, timeout de red, canal inaccesible), respuesta con `ok=False`, o respuesta sin
    `messages`. El caller cae entonces al pedido de fecha explícita, que no necesita el hilo."""
    if client is None or not canal_id or not thread_ts:
        return None
    try:
        respuesta = client.conversations_replies(channel=canal_id, ts=thread_ts, limit=1)
        if respuesta is None:
            return None
        if respuesta.get("ok") is False:
            logger.warning(
                "conversations.replies devolvió ok=False para canal=%s thread_ts=%s (¿falta el "
                "scope channels:history/groups:history?)",
                canal_id,
                thread_ts,
            )
            return None
        mensajes = respuesta.get("messages") or []
        if not mensajes:
            return None
        return mensajes[0]
    except Exception as exc:
        logger.warning(
            "No se pudo leer el mensaje raíz del hilo %s en %s: %s", thread_ts, canal_id, exc
        )
        return None


def _contexto_desde_texto(
    texto: str, *, client: Any
) -> tuple[TipoFormulario | None, str | None, str | None]:
    """Re-extrae (tipo de movimiento, nombre de cámara, técnico resuelto) del texto completo de un
    formulario de Workflow — reusa las tres funciones que ya usa el flujo en vivo, no reimplementa
    ninguna."""
    tipo = extraer_tipo_movimiento(texto)
    nombre_crudo = extraer_nombre_camara(texto)
    texto_camara = limpiar_ruido_operativo(nombre_crudo) if nombre_crudo else None
    tecnico = resolver_nombre_tecnico(client, extraer_slack_user_id_autorizacion(texto))
    return tipo, (texto_camara or None), tecnico


def resolver_contexto_hilo(
    session: Session, client: Any, *, thread_ts: str | None, canal_id: str | None
) -> ContextoHilo:
    """Cascada de tres niveles (ver docstring del módulo). El nivel 2 se consulta **siempre**,
    incluso cuando gana el nivel 1: la fila `IngresoSinMatch` del hilo hay que marcarla como
    resuelta si la corrección termina registrando el movimiento, y un mensaje multi-botella puede
    tener a la vez una cámara que matcheó (nivel 1) y otra que no (nivel 2)."""
    if not thread_ts:
        return ContextoHilo(detalle="el comando no llegó dentro de un hilo")

    momento_ts = _momento_desde_ts(thread_ts)

    caso = (
        session.query(IngresoSinMatch)
        .filter(IngresoSinMatch.thread_ts == thread_ts)
        .order_by(IngresoSinMatch.id.desc())
        .first()
    )

    # ── Nivel 1: el `Ingreso` real del hilo, sin llamadas de red ──────────────────────────────
    # Sólo vigentes: un ingreso anulado desde el portal nunca ocurrió, así que no define la cámara
    # ni el tipo del hilo (si todos están anulados, la cascada sigue por los niveles 2 y 3).
    ingresos = (
        session.query(Ingreso)
        .filter(Ingreso.thread_ts == thread_ts, Ingreso.vigente())
        .order_by(Ingreso.id.asc())
        .all()
    )
    if ingresos:
        primero = ingresos[0]
        # Dedup por `camara_id`, no por nombre: dos cámaras/botellas distintas pueden compartir
        # nombre en este inventario, y "Forzar ingreso" repetido (sin guard — dos técnicos en la
        # misma cámara es un caso legítimo, decisión de producto deliberada) puede dejar dos filas
        # Ingreso de la MISMA cámara con el mismo thread_ts. Eso no es una cámara ambigua: es una
        # sola cámara con varios ingresos abiertos, exactamente el caso que Step 4 resuelve con
        # `VARIOS_INGRESOS_ABIERTOS` — nunca hay que tratarlo como `CAMARA_AMBIGUA`.
        camaras_ids = {i.camara_id for i in ingresos}
        unico = len(camaras_ids) == 1
        return ContextoHilo(
            nivel=1,
            tipo_movimiento=_tipo_formulario_de_fila(primero),
            momento=momento_ts if momento_ts is not None else _momento_de_fila(primero),
            camara=primero.camara if unico else None,
            botella=primero.cromo_botella if unico else None,
            camaras_del_hilo=(
                []
                if unico
                else list(dict.fromkeys(i.camara.nombre for i in ingresos if i.camara is not None))
            ),
            tecnico_nombre=primero.tecnico_id,
            caso_sin_match=caso,
            detalle=f"nivel 1: {len(ingresos)} fila(s) Ingreso con thread_ts={thread_ts}",
        )

    # ── Nivel 2: el caso `IngresoSinMatch` del hilo ────────────────────────────────────────────
    # `texto_mensaje` es el evento COMPLETO (no el nombre recortado de `texto_original`), así que
    # trae los campos "Ingreso o Egreso" y "Persona que solicito La Autorizacion". Es `None` en
    # filas anteriores a 2026-09-07: esas caen al nivel 3, que lee el mismo mensaje desde Slack.
    if caso is not None and caso.texto_mensaje:
        tipo, texto_camara, tecnico = _contexto_desde_texto(caso.texto_mensaje, client=client)
        return ContextoHilo(
            nivel=2,
            tipo_movimiento=tipo,
            momento=momento_ts if momento_ts is not None else caso.created_at,
            texto_camara=texto_camara,
            tecnico_nombre=tecnico,
            caso_sin_match=caso,
            detalle=f"nivel 2: IngresoSinMatch id={caso.id}",
        )

    # ── Nivel 3: el mensaje raíz del hilo vía conversations.replies ────────────────────────────
    mensaje = _mensaje_raiz_del_hilo(client, canal_id, thread_ts)
    if mensaje is None:
        return ContextoHilo(
            caso_sin_match=caso,
            detalle=(
                "cascada agotada: sin Ingreso ni IngresoSinMatch para el hilo y "
                "conversations.replies no respondió"
            ),
        )

    texto = mensaje.get("text") or ""
    tipo, texto_camara, tecnico = _contexto_desde_texto(texto, client=client)
    momento_raiz = _momento_desde_ts(mensaje.get("ts"))
    return ContextoHilo(
        nivel=3,
        tipo_movimiento=tipo,
        momento=momento_raiz if momento_raiz is not None else momento_ts,
        texto_camara=texto_camara,
        tecnico_nombre=tecnico,
        caso_sin_match=caso,
        detalle="nivel 3: mensaje raíz vía conversations.replies",
    )


# ── Auditoría ───────────────────────────────────────────────────────────────────────────────────


def _truncar(valor: str | None, largo: int) -> str | None:
    if valor is None:
        return None
    return valor[:largo]


@dataclass(slots=True)
class _Invocacion:
    """Todo lo que identifica la invocación y se repite en cada fila de auditoría — se arma una vez
    al principio para que ningún camino de rechazo pueda olvidarse un campo."""

    comando: str
    comando_crudo: str
    actor_slack_user_id: str | None
    actor_nombre: str | None
    canal_id: str | None
    thread_ts: str | None
    mensaje_ts: str | None
    # "slack" | "web" (migración `20260928_01`). Un CHECK de Postgres exige las tres columnas de
    # Slack de arriba para "slack" y `actor_web_usuario` para "web".
    origen: str = ORIGEN_SLACK
    actor_web_usuario: str | None = None


def _finalizar(
    session: Session,
    inv: _Invocacion,
    *,
    resultado: str,
    respuesta: str,
    camara_texto_solicitado: str,
    motivo: str | None = None,
    camara: Camara | None = None,
    botella: CromoBotella | None = None,
    momento_solicitado: datetime | None = None,
    momento_efectivo: datetime | None = None,
    fuente_momento: str | None = None,
    ingreso: Ingreso | None = None,
    error_detalle: str | None = None,
    camara_id_anterior: int | None = None,
    cromo_botella_id_anterior: int | None = None,
    atomico: bool = False,
) -> ResultadoCorreccion:
    """Escribe la fila de auditoría y arma el `ResultadoCorreccion`. **Todo** camino de retorno de
    `procesar_comando_correccion` pasa por acá — incluidos los rechazos: un rechazo sin rastro es un
    agujero en el log.

    Si la escritura de auditoría falla, se loguea como error y se hace `rollback()` (la sesión es
    compartida con el resto del handler de Slack: sin el rollback, cualquier operación posterior
    relanza `PendingRollbackError`), pero la respuesta al operador se devuelve igual — el movimiento
    ya se registró y no tiene sentido ocultárselo.

    `atomico=True` (mover/anular desde el portal): el caller deja su cambio **sin confirmar** y este
    `commit()` es el único — cambio y auditoría entran juntos o no entra ninguno. Si falla, se hace
    `rollback()` (que también deshace el cambio) y la excepción se propaga: el endpoint la convierte
    en `error_interno`. Un cambio sin su fila de auditoría no puede quedar persistido."""
    fila = IngresoCorreccion(
        comando=inv.comando,
        origen=inv.origen,
        actor_web_usuario=inv.actor_web_usuario,
        actor_slack_user_id=inv.actor_slack_user_id,
        actor_nombre=_truncar(inv.actor_nombre, _LARGO_ACTOR_NOMBRE),
        canal_id=inv.canal_id,
        thread_ts=inv.thread_ts,
        mensaje_ts=inv.mensaje_ts,
        comando_crudo=inv.comando_crudo,
        motivo=motivo,
        camara_texto_solicitado=_truncar(camara_texto_solicitado, _LARGO_CAMARA_TEXTO) or CAMARA_TEXTO_NO_PARSEADO,
        camara_id_resuelta=camara.id if camara is not None else None,
        cromo_botella_id_resuelta=botella.n_id if botella is not None else None,
        momento_solicitado=momento_solicitado,
        momento_efectivo=momento_efectivo,
        fuente_momento=fuente_momento,
        ingreso_id=ingreso.id if ingreso is not None else None,
        resultado=resultado,
        error_detalle=error_detalle,
        camara_id_anterior=camara_id_anterior,
        cromo_botella_id_anterior=cromo_botella_id_anterior,
    )
    try:
        session.add(fila)
        session.commit()
    except Exception as exc:
        try:
            session.rollback()
        except Exception:
            pass
        logger.error(
            "No se pudo escribir la fila de auditoría (resultado=%s, comando_crudo=%r): %s",
            resultado,
            inv.comando_crudo,
            exc,
            exc_info=True,
        )
        if atomico:
            raise
        return ResultadoCorreccion(
            resultado=resultado, respuesta=respuesta, comando=inv.comando, ingreso=ingreso
        )

    logger.info(
        "Corrección %s resultado=%s actor=%s hilo=%s ingreso_id=%s",
        inv.comando,
        resultado,
        inv.actor_slack_user_id or inv.actor_web_usuario,
        inv.thread_ts,
        ingreso.id if ingreso is not None else None,
    )
    return ResultadoCorreccion(
        resultado=resultado,
        respuesta=respuesta,
        comando=inv.comando,
        ingreso=ingreso,
        auditoria=fila,
    )


def _marcar_caso_resuelto(session: Session, caso: IngresoSinMatch | None, ingreso: Ingreso | None) -> None:
    """Cierra el caso `IngresoSinMatch` del hilo cuando la corrección terminó registrando el
    movimiento real, para que no quede colgado esperando una revalidación que ya no hace falta.
    Mismo par de campos que usa `_procesar_revalidacion_ingreso` (`listener.py`): `ingreso_id` para
    trazabilidad y `resuelto_via_revalidacion` para no reprocesarlo.

    Nunca lanza: si la escritura falla, la corrección ya está hecha y auditada — perder la marca es
    mucho menos grave que romper la respuesta."""
    if caso is None or ingreso is None or caso.resuelto_via_revalidacion:
        return
    try:
        caso.ingreso_id = ingreso.id
        caso.resuelto_via_revalidacion = True
        session.commit()
    except Exception as exc:
        try:
            session.rollback()
        except Exception:
            pass
        logger.warning("No se pudo marcar IngresoSinMatch como resuelto: %s", exc)


# ── Avisos que se suman a la respuesta OK ───────────────────────────────────────────────────────


def _aviso_baneo_actual(session: Session, camara: Camara) -> str:
    """Aviso (no bloqueo) de que el grupo de la cámara está baneado **ahora**. Decisión deliberada:
    `Forzar ingreso` sobre un grupo hoy baneado registra un INGRESO real, porque el operador está
    afirmando que el técnico entró y el estado de *ahora* no es evidencia sobre el pasado.

    Fail-open ante cualquier error, igual que `_evaluar_estado_acceso_camara` (`listener.py`): un
    hiccup de DB en un chequeo puramente informativo no puede romper una corrección ya escrita."""
    try:
        contexto = get_camara_estado_contexto(session, camara.id)
    except Exception as exc:
        logger.warning("No se pudo evaluar el baneo actual de camara_id=%s: %s", camara.id, exc)
        return ""
    if contexto is not None and contexto.tiene_baneo_activo:
        return (
            "\n:no_entry: Ojo: el grupo de esta cámara está *baneado en este momento*. El ingreso "
            "se registró igual porque estás afirmando que el técnico ya entró — el baneo de ahora "
            "no dice nada sobre el pasado."
        )
    return ""


def _aviso_tecnico_no_identificado(tecnico_nombre: str | None) -> str:
    """El valor operativo (cámara OCUPADA/LIBRE) no depende de la identidad del técnico, así que un
    técnico irresoluble nunca bloquea: se registra `tecnico_id=NULL` y se dice en la respuesta. La
    fila de auditoría siempre tiene al actor que ejecutó el comando."""
    if tecnico_nombre:
        return ""
    return (
        "\n_No pude identificar al técnico del formulario — el movimiento quedó registrado sin "
        "técnico asociado._"
    )


# ── Resolución de la cámara ─────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class _CamaraResuelta:
    camara: Camara | None = None
    botella: CromoBotella | None = None
    # Rechazo ya armado (resultado + respuesta) cuando la cámara no se pudo resolver.
    resultado: str | None = None
    respuesta: str | None = None
    error_detalle: str | None = None


def _buscar_camara(texto: str, session: Session) -> _CamaraResuelta:
    """Búsqueda canónica (la misma que usa el flujo en vivo), traduciendo sus dos modos de falla a
    rechazos con respuesta propia: ambigua (`AmbiguousSearchError`) y sin match (`camara=None`,
    que esa función devuelve sin lanzar)."""
    try:
        resultado = buscar_camara_o_botella_cromo(texto, session)
    except AmbiguousSearchError as exc:
        return _CamaraResuelta(
            resultado=RESULTADO_CAMARA_AMBIGUA,
            respuesta=construir_respuesta_camara_ambigua(texto, exc.candidatos),
            error_detalle=f"{exc.cantidad} candidatos para '{exc.nombre_raw}'",
        )
    if resultado.camara is None:
        return _CamaraResuelta(
            resultado=RESULTADO_CAMARA_NO_ENCONTRADA,
            respuesta=construir_respuesta_camara_no_encontrada(texto),
            error_detalle=f"sin match en Camara ni CromoBotella para '{texto}'",
        )
    return _CamaraResuelta(camara=resultado.camara, botella=resultado.botella)


def _camara_del_hilo(ctx: ContextoHilo, session: Session) -> _CamaraResuelta:
    """Cámara para las formas que no la nombran (`Forzar egreso` bare). El nivel 1 la da resuelta;
    los niveles 2 y 3 dan el texto del formulario y hay que buscarla igual que el flujo en vivo."""
    if ctx.camara is not None:
        return _CamaraResuelta(camara=ctx.camara, botella=ctx.botella)
    if ctx.camaras_del_hilo:
        # Mensaje multi-botella: el hilo tiene varias cámaras y ninguna es "la" del hilo. No se
        # adivina — se listan y se pide la forma con cámara explícita.
        return _CamaraResuelta(
            resultado=RESULTADO_CAMARA_AMBIGUA,
            respuesta=construir_respuesta_camara_ambigua(
                CAMARA_TEXTO_DEL_HILO, ctx.camaras_del_hilo
            ),
            error_detalle=f"{len(ctx.camaras_del_hilo)} cámaras en el mismo hilo",
        )
    if ctx.texto_camara:
        return _buscar_camara(ctx.texto_camara, session)
    return _CamaraResuelta(
        resultado=RESULTADO_HILO_SIN_FORMULARIO,
        respuesta=construir_respuesta_hilo_sin_formulario(),
        error_detalle=ctx.detalle,
    )


# ── Resolución del momento (Step 3) ─────────────────────────────────────────────────────────────


@dataclass(slots=True)
class _MomentoResuelto:
    momento: datetime | None = None
    fuente: str | None = None
    resultado: str | None = None
    respuesta: str | None = None
    error_detalle: str | None = None


def _resolver_momento(
    *,
    momento_solicitado: datetime | None,
    tipo_forzado: TipoFormulario,
    ctx: ContextoHilo,
    camara_texto_respuesta: str,
) -> _MomentoResuelto:
    """Implementa la tabla de la regla del momento implícito (ver docstring del módulo)."""
    if momento_solicitado is not None:
        return _MomentoResuelto(momento=momento_solicitado, fuente=FUENTE_MOMENTO_EXPLICITO)

    if ctx.tipo_movimiento is None:
        # No se pudo identificar ningún formulario en el hilo (o no hay hilo): sin tipo no hay forma
        # de saber si el `ts` del hilo representa el mismo movimiento que se está forzando.
        return _MomentoResuelto(
            resultado=RESULTADO_HILO_SIN_FORMULARIO,
            respuesta=construir_respuesta_hilo_sin_formulario(),
            error_detalle=ctx.detalle,
        )

    if ctx.tipo_movimiento != tipo_forzado:
        # Filas 3 y 4 de la tabla: el tipo del hilo no coincide con el forzado. Usar el `ts` del
        # hilo registraría una visita de duración cero.
        #
        # Se audita como `PENDIENTE_FECHA` y no como un rechazo: la Task 6 consume esta fila como
        # el estado que habilita, durante los 30 minutos siguientes y en este mismo hilo, una
        # respuesta de seguimiento con sólo `DD-MM-AAAA HH:MM` (que re-ejecuta el comando vía
        # `momento_explicito`, escribiendo una fila nueva — la tabla es append-only). Renombrar esto
        # a un valor de rechazo rompería ese guard sin que ningún test de este módulo lo note.
        return _MomentoResuelto(
            resultado=RESULTADO_PENDIENTE_FECHA,
            respuesta=construir_respuesta_falta_fecha(
                camara_texto_respuesta, "ingreso" if tipo_forzado == "Ingreso" else "egreso"
            ),
            error_detalle=(
                f"el hilo es un formulario de {ctx.tipo_movimiento} y se está forzando un "
                f"{tipo_forzado}: la fecha explícita es obligatoria"
            ),
        )

    if ctx.momento is None:
        return _MomentoResuelto(
            resultado=RESULTADO_HILO_SIN_FORMULARIO,
            respuesta=construir_respuesta_hilo_sin_formulario(),
            error_detalle=f"tipo del hilo coincide pero no hay momento utilizable ({ctx.detalle})",
        )

    # Filas 1 y 2: el tipo coincide, el momento sale del `ts` del hilo.
    return _MomentoResuelto(momento=ctx.momento, fuente=FUENTE_MOMENTO_HILO)


# ── Ingresos abiertos candidatos (Step 4) ───────────────────────────────────────────────────────


def _ingresos_abiertos(session: Session, camara: Camara) -> list[Ingreso]:
    """Ingresos abiertos de la cámara: `tipo=INGRESO` (un `INTENTO_BLOQUEADO` también tiene
    `fecha_fin IS NULL` y nunca fue un ingreso real), `fecha_fin IS NULL` y vigentes (no anulados).

    El alcance es la cámara entera, sin filtrar por `cromo_botella_id`: `Ingreso.camara_id` siempre
    apunta a la cámara raíz (tanto el flujo en vivo como la búsqueda de Cromo resuelven a la raíz),
    y ese grupo es exactamente la unidad que `camara_estado_service` considera OCUPADA — que es el
    problema que estos comandos existen para corregir. Un ingreso abierto en una botella del grupo
    aparece acá aunque el operador haya nombrado la cámara padre; si hay más de uno, no se adivina:
    se listan y se exige `#<id>`."""
    return (
        session.query(Ingreso)
        .filter(
            Ingreso.camara_id == camara.id,
            Ingreso.tipo == IngresoTipo.INGRESO,
            Ingreso.fecha_fin.is_(None),
            Ingreso.vigente(),
        )
        .order_by(Ingreso.fecha_inicio.desc())
        .all()
    )


# ── Entry point ─────────────────────────────────────────────────────────────────────────────────


def procesar_comando_correccion(
    session: Session,
    *,
    texto: str,
    actor_slack_user_id: str,
    canal_id: str,
    mensaje_ts: str,
    thread_ts: str | None = None,
    client: Any = None,
    momento_explicito: datetime | None = None,
    ahora: datetime | None = None,
) -> ResultadoCorreccion | None:
    """Procesa un mensaje que puede ser un comando de corrección.

    Devuelve `None` — sin escribir nada, ni en `app.ingresos` ni en la auditoría — cuando el texto
    no es ninguno de los dos comandos: es el caso normal de cualquier otro mensaje del canal, no un
    error. Si **sí** es un comando, devuelve siempre un `ResultadoCorreccion` y **siempre** deja una
    fila de auditoría, haya terminado en un movimiento o en un rechazo.

    Args:
        texto: el texto completo del mensaje de Slack, tal como llegó.
        actor_slack_user_id: quién ejecutó el comando (no el técnico del formulario). Sin allowlist:
            no se valida identidad, la auditoría es el único control.
        canal_id / mensaje_ts / thread_ts: coordenadas del mensaje. `thread_ts` es el `ts` del
            mensaje raíz del hilo y, por lo tanto, el momento en que se envió el formulario.
        client: el `slack_sdk.WebClient` que Bolt inyecta en el handler. Opcional: sin él, el nivel 3
            de la cascada y la resolución de nombres quedan sin efecto, pero nada falla.
        momento_explicito: fecha/hora ya parseada que el operador mandó como respuesta de
            seguimiento al pedido del bot (flujo de "fecha pendiente" de la Task 6). Se usa **sólo**
            cuando el comando no trae la suya — en el flujo diseñado nunca conviven, porque un
            comando que ya traía fecha nunca queda pendiente.
        ahora: momento de referencia para las validaciones de rango del parser (fecha futura / más
            de 90 días atrás). Inyectable para tests deterministas.
    """
    comando_crudo = texto or ""
    comando: str | None = None
    cmd_ingreso: ComandoForzarIngreso | None = None
    cmd_egreso: ComandoForzarEgreso | None = None
    error_momento: MomentoInvalidoError | None = None

    try:
        cmd_ingreso = extraer_comando_forzar_ingreso(comando_crudo, ahora=ahora)
        if cmd_ingreso is not None:
            comando = COMANDO_FORZAR_INGRESO
    except MomentoInvalidoError as exc:
        comando, error_momento = COMANDO_FORZAR_INGRESO, exc

    if comando is None:
        try:
            cmd_egreso = extraer_comando_forzar_egreso(comando_crudo, ahora=ahora)
            if cmd_egreso is not None:
                comando = COMANDO_FORZAR_EGRESO
        except MomentoInvalidoError as exc:
            comando, error_momento = COMANDO_FORZAR_EGRESO, exc

    if comando is None:
        return None

    inv = _Invocacion(
        comando=comando,
        comando_crudo=comando_crudo,
        actor_slack_user_id=actor_slack_user_id or "",
        actor_nombre=resolver_nombre_tecnico(client, actor_slack_user_id),
        canal_id=canal_id or "",
        thread_ts=thread_ts,
        mensaje_ts=mensaje_ts or "",
    )

    if error_momento is not None:
        # El sufijo tenía forma de fecha pero el valor no sirve (formato, futura, >90 días). El
        # nombre de cámara nunca llegó a parsearse — el comando entero queda igual en
        # `comando_crudo`, así que la columna NOT NULL lleva un marcador explícito (Ruling 6).
        return _finalizar(
            session,
            inv,
            resultado=RESULTADO_MOMENTO_INVALIDO,
            respuesta=construir_respuesta_momento_invalido(error_momento),
            camara_texto_solicitado=CAMARA_TEXTO_NO_PARSEADO,
            error_detalle=str(error_momento),
        )

    try:
        if cmd_ingreso is not None:
            return _procesar_forzar_ingreso(
                session,
                inv,
                cmd=cmd_ingreso,
                client=client,
                momento_explicito=momento_explicito,
            )
        assert cmd_egreso is not None  # garantizado por la lógica de parseo de arriba
        return _procesar_forzar_egreso(
            session, inv, cmd=cmd_egreso, client=client, momento_explicito=momento_explicito
        )
    except Exception as exc:
        # Defensa en profundidad: cualquier fallo inesperado (DB caída, lazy-load roto) deja igual
        # su rastro en la auditoría, con la sesión ya saneada para que `_finalizar` pueda escribir.
        try:
            session.rollback()
        except Exception:
            pass
        logger.error("Error procesando %s (%r): %s", comando, comando_crudo, exc, exc_info=True)
        return _finalizar(
            session,
            inv,
            resultado=RESULTADO_ERROR_INTERNO,
            respuesta=(
                ":warning: No pude completar la corrección por un error interno — quedó registrada "
                "en la auditoría. Reintentá en un momento."
            ),
            camara_texto_solicitado=CAMARA_TEXTO_NO_PARSEADO,
            error_detalle=f"{type(exc).__name__}: {exc}",
        )


def _procesar_forzar_ingreso(
    session: Session,
    inv: _Invocacion,
    *,
    cmd: ComandoForzarIngreso,
    client: Any,
    momento_explicito: datetime | None,
) -> ResultadoCorreccion:
    """`Forzar ingreso <CAMARA> [DD-MM-AAAA HH:MM]` — siempre crea una fila nueva (nunca reabre ni
    reutiliza una existente, igual que el flujo en vivo)."""
    camara_texto = cmd.camara_texto
    momento_solicitado = cmd.momento if cmd.momento is not None else momento_explicito

    ctx = resolver_contexto_hilo(session, client, thread_ts=inv.thread_ts, canal_id=inv.canal_id)

    resuelta = _buscar_camara(camara_texto, session)
    if resuelta.resultado is not None:
        return _finalizar(
            session,
            inv,
            resultado=resuelta.resultado,
            respuesta=resuelta.respuesta or "",
            camara_texto_solicitado=camara_texto,
            motivo=cmd.motivo,
            momento_solicitado=momento_solicitado,
            error_detalle=resuelta.error_detalle,
        )

    camara = resuelta.camara
    assert camara is not None

    momento = _resolver_momento(
        momento_solicitado=momento_solicitado,
        tipo_forzado="Ingreso",
        ctx=ctx,
        camara_texto_respuesta=camara.nombre,
    )
    if momento.resultado is not None:
        return _finalizar(
            session,
            inv,
            resultado=momento.resultado,
            respuesta=momento.respuesta or "",
            camara_texto_solicitado=camara_texto,
            motivo=cmd.motivo,
            camara=camara,
            botella=resuelta.botella,
            momento_solicitado=momento_solicitado,
            error_detalle=momento.error_detalle,
        )

    momento_efectivo = momento.momento
    assert momento_efectivo is not None

    # Valores capturados ANTES de los commits: `expire_on_commit` (default de `SessionLocal`) expira
    # los objetos y la respuesta ya calculada no debe depender de un re-fetch.
    camara_nombre = camara.nombre
    tecnico_nombre = ctx.tecnico_nombre
    aviso_baneo = _aviso_baneo_actual(session, camara)

    ingreso = registrar_movimiento_ingreso(
        session,
        camara=camara,
        botella=resuelta.botella,
        tipo_movimiento="Ingreso",
        tecnico_nombre=tecnico_nombre,
        momento=momento_efectivo,
        thread_ts=inv.thread_ts,
        canal_id=inv.canal_id or None,
    )
    _marcar_caso_resuelto(session, ctx.caso_sin_match, ingreso)

    respuesta = (
        construir_respuesta_ok_forzar_ingreso(
            camara_nombre, momento_efectivo, inv.actor_nombre or inv.actor_slack_user_id
        )
        + _aviso_tecnico_no_identificado(tecnico_nombre)
        + aviso_baneo
    )
    return _finalizar(
        session,
        inv,
        resultado=RESULTADO_OK_INGRESO,
        respuesta=respuesta,
        camara_texto_solicitado=camara_texto,
        motivo=cmd.motivo,
        camara=camara,
        botella=resuelta.botella,
        momento_solicitado=momento_solicitado,
        momento_efectivo=momento_efectivo,
        fuente_momento=momento.fuente,
        ingreso=ingreso,
    )


def _procesar_forzar_egreso(
    session: Session,
    inv: _Invocacion,
    *,
    cmd: ComandoForzarEgreso,
    client: Any,
    momento_explicito: datetime | None,
) -> ResultadoCorreccion:
    """Las cuatro formas de `Forzar egreso`: bare, `<CAMARA>` sin fecha, `<CAMARA> DD-MM-AAAA HH:MM`
    y `#<id>`. Ninguna llama a `registrar_movimiento_ingreso` sin haber resuelto antes el conjunto
    de ingresos abiertos candidatos (ver docstring del módulo)."""
    momento_solicitado = cmd.momento if cmd.momento is not None else momento_explicito
    ctx = resolver_contexto_hilo(session, client, thread_ts=inv.thread_ts, canal_id=inv.canal_id)

    # ── Qué cámara, qué candidatos y qué texto va a la auditoría, según la forma ───────────────
    if cmd.ingreso_id is not None:
        camara_texto_solicitado = f"#{cmd.ingreso_id}"  # Ruling 6: nunca cadena vacía
        objetivo = session.query(Ingreso).filter(Ingreso.id == cmd.ingreso_id).first()
        if objetivo is None or objetivo.tipo != IngresoTipo.INGRESO:
            return _finalizar(
                session,
                inv,
                resultado=RESULTADO_INGRESO_NO_ENCONTRADO,
                respuesta=construir_respuesta_ingreso_no_encontrado(cmd.ingreso_id),
                camara_texto_solicitado=camara_texto_solicitado,
                motivo=cmd.motivo,
                momento_solicitado=momento_solicitado,
                error_detalle=(
                    f"Ingreso id={cmd.ingreso_id} inexistente"
                    if objetivo is None
                    else f"Ingreso id={cmd.ingreso_id} es de tipo {objetivo.tipo}"
                ),
            )
        if objetivo.anulado_at is not None:
            return _finalizar(
                session,
                inv,
                resultado=RESULTADO_INGRESO_ANULADO,
                respuesta=construir_respuesta_ingreso_anulado(objetivo.id),
                camara_texto_solicitado=camara_texto_solicitado,
                motivo=cmd.motivo,
                camara=objetivo.camara,
                momento_solicitado=momento_solicitado,
                ingreso=objetivo,
                error_detalle=f"anulado el {objetivo.anulado_at} por {objetivo.anulado_por}",
            )
        if objetivo.fecha_fin is not None:
            return _finalizar(
                session,
                inv,
                resultado=RESULTADO_INGRESO_YA_CERRADO,
                respuesta=construir_respuesta_ingreso_ya_cerrado(objetivo.id, objetivo.fecha_fin),
                camara_texto_solicitado=camara_texto_solicitado,
                motivo=cmd.motivo,
                camara=objetivo.camara,
                momento_solicitado=momento_solicitado,
                ingreso=objetivo,
                error_detalle=f"ya cerrado el {objetivo.fecha_fin}",
            )
        camara = objetivo.camara
        botella = objetivo.cromo_botella
        candidatos = [objetivo]
        if camara is None:
            return _finalizar(
                session,
                inv,
                resultado=RESULTADO_INGRESO_NO_ENCONTRADO,
                respuesta=construir_respuesta_ingreso_no_encontrado(cmd.ingreso_id),
                camara_texto_solicitado=camara_texto_solicitado,
                motivo=cmd.motivo,
                momento_solicitado=momento_solicitado,
                error_detalle=f"Ingreso id={cmd.ingreso_id} sin cámara asociada",
            )
    else:
        if cmd.camara_texto:
            camara_texto_solicitado = cmd.camara_texto
            resuelta = _buscar_camara(cmd.camara_texto, session)
        else:
            camara_texto_solicitado = CAMARA_TEXTO_DEL_HILO  # Ruling 6: forma bare
            resuelta = _camara_del_hilo(ctx, session)
        if resuelta.resultado is not None:
            return _finalizar(
                session,
                inv,
                resultado=resuelta.resultado,
                respuesta=resuelta.respuesta or "",
                camara_texto_solicitado=camara_texto_solicitado,
                motivo=cmd.motivo,
                momento_solicitado=momento_solicitado,
                error_detalle=resuelta.error_detalle,
            )
        camara = resuelta.camara
        assert camara is not None
        botella = resuelta.botella
        candidatos = _ingresos_abiertos(session, camara)

    camara_nombre = camara.nombre

    # ── Momento (Step 3) ───────────────────────────────────────────────────────────────────────
    momento = _resolver_momento(
        momento_solicitado=momento_solicitado,
        tipo_forzado="Egreso",
        ctx=ctx,
        camara_texto_respuesta=camara_nombre,
    )
    if momento.resultado is not None:
        return _finalizar(
            session,
            inv,
            resultado=momento.resultado,
            respuesta=momento.respuesta or "",
            camara_texto_solicitado=camara_texto_solicitado,
            motivo=cmd.motivo,
            camara=camara,
            botella=botella,
            momento_solicitado=momento_solicitado,
            error_detalle=momento.error_detalle,
        )
    momento_efectivo = momento.momento
    assert momento_efectivo is not None

    # ── Cero candidatos: sólo la forma deliberada (cámara + fecha explícitas) asienta ──────────
    if not candidatos:
        deliberada = cmd.camara_texto is not None and momento.fuente == FUENTE_MOMENTO_EXPLICITO
        if not deliberada:
            return _finalizar(
                session,
                inv,
                resultado=RESULTADO_SIN_INGRESO_ABIERTO,
                respuesta=construir_respuesta_sin_ingreso_abierto(camara_nombre),
                camara_texto_solicitado=camara_texto_solicitado,
                motivo=cmd.motivo,
                camara=camara,
                botella=botella,
                momento_solicitado=momento_solicitado,
                momento_efectivo=momento_efectivo,
                fuente_momento=momento.fuente,
                error_detalle="sin ingresos abiertos y la forma usada no puede asentar de cero",
            )
        # Acá sí se llama a `registrar_movimiento_ingreso` con "Egreso": ya sabemos que no hay
        # ningún ingreso abierto en la cámara, así que va a crear la fila huérfana
        # (`fecha_inicio=None`) — que es exactamente lo que el operador pidió al dar cámara y fecha.
        ingreso = registrar_movimiento_ingreso(
            session,
            camara=camara,
            botella=botella,
            tipo_movimiento="Egreso",
            tecnico_nombre=ctx.tecnico_nombre,
            momento=momento_efectivo,
            thread_ts=inv.thread_ts,
            canal_id=inv.canal_id or None,
        )
        _marcar_caso_resuelto(session, ctx.caso_sin_match, ingreso)
        return _finalizar(
            session,
            inv,
            resultado=RESULTADO_OK_EGRESO_ASENTADO,
            respuesta=construir_respuesta_ok_forzar_egreso_asentado(
                camara_nombre, momento_efectivo, inv.actor_nombre or inv.actor_slack_user_id
            ),
            camara_texto_solicitado=camara_texto_solicitado,
            motivo=cmd.motivo,
            camara=camara,
            botella=botella,
            momento_solicitado=momento_solicitado,
            momento_efectivo=momento_efectivo,
            fuente_momento=momento.fuente,
            ingreso=ingreso,
        )

    # ── Dos o más candidatos: se listan, nunca se adivina ──────────────────────────────────────
    if len(candidatos) > 1:
        infos = [
            IngresoAbiertoInfo(id=c.id, tecnico=c.tecnico_id, fecha_inicio=c.fecha_inicio)
            for c in candidatos
        ]
        return _finalizar(
            session,
            inv,
            resultado=RESULTADO_VARIOS_INGRESOS_ABIERTOS,
            respuesta=construir_respuesta_varios_ingresos_abiertos(camara_nombre, infos),
            camara_texto_solicitado=camara_texto_solicitado,
            motivo=cmd.motivo,
            camara=camara,
            botella=botella,
            momento_solicitado=momento_solicitado,
            momento_efectivo=momento_efectivo,
            fuente_momento=momento.fuente,
            error_detalle=f"{len(candidatos)} ingresos abiertos: {[c.id for c in candidatos]}",
        )

    # ── Un solo candidato: se cierra ESA fila ──────────────────────────────────────────────────
    objetivo = candidatos[0]
    fecha_inicio = _como_utc(objetivo.fecha_inicio)
    if fecha_inicio is not None and _como_utc(momento_efectivo) <= fecha_inicio:
        return _finalizar(
            session,
            inv,
            resultado=RESULTADO_EGRESO_ANTERIOR_AL_INGRESO,
            respuesta=construir_respuesta_egreso_anterior_al_ingreso(momento_efectivo, fecha_inicio),
            camara_texto_solicitado=camara_texto_solicitado,
            motivo=cmd.motivo,
            camara=camara,
            botella=botella,
            momento_solicitado=momento_solicitado,
            momento_efectivo=momento_efectivo,
            fuente_momento=momento.fuente,
            ingreso=objetivo,
            error_detalle=f"fecha_inicio real del ingreso #{objetivo.id}: {fecha_inicio}",
        )

    tecnico_original = objetivo.tecnico_id
    ingreso = cerrar_ingreso_forzado(session, ingreso=objetivo, momento=momento_efectivo)
    _marcar_caso_resuelto(session, ctx.caso_sin_match, ingreso)
    return _finalizar(
        session,
        inv,
        resultado=RESULTADO_OK_EGRESO_CERRADO,
        respuesta=construir_respuesta_ok_forzar_egreso_cerrado(
            camara_nombre,
            momento_efectivo,
            inv.actor_nombre or inv.actor_slack_user_id,
            tecnico_original=tecnico_original,
        ),
        camara_texto_solicitado=camara_texto_solicitado,
        motivo=cmd.motivo,
        camara=camara,
        botella=botella,
        momento_solicitado=momento_solicitado,
        momento_efectivo=momento_efectivo,
        fuente_momento=momento.fuente,
        ingreso=ingreso,
    )


# ── Egreso desde el panel web (botón "Registrar egreso", vista Ingresos del Servicio) ──────────


def registrar_egreso_web(
    session: Session,
    *,
    ingreso_id: int,
    momento: datetime,
    motivo: str,
    usuario_web: str,
    ahora: datetime | None = None,
) -> ResultadoCorreccion:
    """Cierra desde el panel web un `Ingreso` que quedó "en curso" porque el formulario de Egreso
    nunca llegó por Slack. Es la forma `Forzar egreso #<id> DD-MM-AAAA HH:MM` sin Slack: el operador
    elige la fila exacta en la tabla, así que no hay cámara que resolver ni candidatos que desempatar.

    Mismas reglas que ese camino (`_procesar_forzar_egreso`): sólo filas `tipo=INGRESO` abiertas,
    `momento > fecha_inicio` **estricto**, cierre con `cerrar_ingreso_forzado` (nunca
    `registrar_movimiento_ingreso`, que podría crear un EGRESO huérfano) y una fila de auditoría en
    `app.ingresos_correcciones` por cada invocación, incluidos los rechazos — con `origen='web'` y
    `actor_web_usuario` en lugar de los datos de Slack. Además rechaza un `momento` futuro: el
    operador está afirmando cuándo salió el técnico, no agendando una salida.

    `momento` debe venir con zona horaria (el endpoint lo exige); `ahora` es inyectable para tests.
    """
    ahora = ahora if ahora is not None else datetime.now(timezone.utc)
    momento_utc = _como_utc(momento)
    assert momento_utc is not None
    inv = _Invocacion(
        comando=COMANDO_FORZAR_EGRESO,
        comando_crudo=f"[web] Registrar egreso #{ingreso_id} {momento_utc.isoformat()}",
        actor_slack_user_id=None,
        actor_nombre=_truncar(usuario_web, _LARGO_ACTOR_NOMBRE),
        canal_id=None,
        thread_ts=None,
        mensaje_ts=None,
        origen=ORIGEN_WEB,
        actor_web_usuario=_truncar(usuario_web, 64),
    )
    comunes = {
        "camara_texto_solicitado": f"#{ingreso_id}",
        "motivo": motivo,
        "momento_solicitado": momento_utc,
    }

    objetivo = session.query(Ingreso).filter(Ingreso.id == ingreso_id).first()
    if objetivo is None or objetivo.tipo != IngresoTipo.INGRESO:
        return _finalizar(
            session,
            inv,
            resultado=RESULTADO_INGRESO_NO_ENCONTRADO,
            respuesta=f"No existe un ingreso #{ingreso_id} que se pueda cerrar.",
            error_detalle=(
                f"Ingreso id={ingreso_id} inexistente"
                if objetivo is None
                else f"Ingreso id={ingreso_id} es de tipo {objetivo.tipo}"
            ),
            **comunes,
        )
    camara = objetivo.camara
    botella = objetivo.cromo_botella
    if objetivo.anulado_at is not None:
        return _finalizar(
            session,
            inv,
            resultado=RESULTADO_INGRESO_ANULADO,
            respuesta=f"El ingreso #{objetivo.id} está anulado; no se puede cerrar.",
            camara=camara,
            botella=botella,
            ingreso=objetivo,
            error_detalle=f"anulado el {objetivo.anulado_at} por {objetivo.anulado_por}",
            **comunes,
        )
    if objetivo.fecha_fin is not None:
        return _finalizar(
            session,
            inv,
            resultado=RESULTADO_INGRESO_YA_CERRADO,
            respuesta=f"El ingreso #{objetivo.id} ya tiene egreso registrado.",
            camara=camara,
            botella=botella,
            ingreso=objetivo,
            error_detalle=f"ya cerrado el {objetivo.fecha_fin}",
            **comunes,
        )
    if momento_utc > _como_utc(ahora):
        return _finalizar(
            session,
            inv,
            resultado=RESULTADO_MOMENTO_INVALIDO,
            respuesta="La fecha de egreso no puede ser futura.",
            camara=camara,
            botella=botella,
            ingreso=objetivo,
            error_detalle=f"momento futuro (ahora={_como_utc(ahora)})",
            **comunes,
        )
    fecha_inicio = _como_utc(objetivo.fecha_inicio)
    if fecha_inicio is not None and momento_utc <= fecha_inicio:
        return _finalizar(
            session,
            inv,
            resultado=RESULTADO_EGRESO_ANTERIOR_AL_INGRESO,
            respuesta="La fecha de egreso tiene que ser posterior a la de ingreso.",
            camara=camara,
            botella=botella,
            ingreso=objetivo,
            error_detalle=f"fecha_inicio real del ingreso #{objetivo.id}: {fecha_inicio}",
            **comunes,
        )

    ingreso = cerrar_ingreso_forzado(session, ingreso=objetivo, momento=momento_utc)
    return _finalizar(
        session,
        inv,
        resultado=RESULTADO_OK_EGRESO_CERRADO,
        respuesta=f"Egreso registrado para el ingreso #{ingreso.id}.",
        camara=camara,
        botella=botella,
        momento_efectivo=momento_utc,
        fuente_momento=FUENTE_MOMENTO_EXPLICITO,
        ingreso=ingreso,
        **comunes,
    )


# ── Mover / anular un ingreso desde el portal (admin) ──────────────────────────────────────────
#
# Plan `docs/superpowers/plans/2026-10-23-correccion-ingresos-portal.md`, decisiones 3 a 5. Mismo
# contrato que `registrar_egreso_web` (el operador elige la fila exacta; **una** fila de auditoría
# `origen='web'` por invocación, incluidos los rechazos), con una diferencia: el cambio y su auditoría
# se confirman en un **único** `commit()` (`_finalizar(atomico=True)`); si falla, no queda ninguno. Ninguna de las dos toca `Camara.estado` persistido (el estado
# derivado se corrige solo por el filtro `Ingreso.vigente()`) ni reabre el `IngresoSinMatch` que
# hubiera resuelto el ingreso: si el ingreso nunca ocurrió, no hay caso que reabrir.

MOTIVO_MIN = 3
MOTIVO_MAX = 500
_LARGO_ANULADO_POR = 128
_LARGO_ACTOR_WEB = 64


def _motivo_valido(motivo: str | None) -> str | None:
    """`motivo` sin espacios de borde si mide entre `MOTIVO_MIN` y `MOTIVO_MAX`; si no, `None`."""
    limpio = (motivo or "").strip()
    return limpio if MOTIVO_MIN <= len(limpio) <= MOTIVO_MAX else None


def _invocacion_web(comando: str, comando_crudo: str, usuario: str) -> _Invocacion:
    return _Invocacion(
        comando=comando,
        comando_crudo=comando_crudo,
        actor_slack_user_id=None,
        actor_nombre=_truncar(usuario, _LARGO_ACTOR_NOMBRE),
        canal_id=None,
        thread_ts=None,
        mensaje_ts=None,
        origen=ORIGEN_WEB,
        actor_web_usuario=_truncar(usuario, _LARGO_ACTOR_WEB),
    )


def _intervenciones_abiertas_vinculadas(session: Session, ingreso_id: int) -> list[FomonIntervencion]:
    """Intervenciones de FO Monitor vinculadas al ingreso que todavía no terminaron. "Abierta" es
    `motor.ESTADOS_ABIERTOS` (el mismo criterio con el que el motor agrupa y atribuye); `CERRADA` y
    `CANCELADA` son finales y no se tocan."""
    return (
        session.query(FomonIntervencion)
        .join(FomonIntervencionIngreso, FomonIntervencionIngreso.intervencion_id == FomonIntervencion.id)
        .filter(
            FomonIntervencionIngreso.ingreso_id == ingreso_id,
            FomonIntervencion.estado.in_(FOMON_ESTADOS_ABIERTOS),
        )
        .all()
    )


def _otros_vinculados_vigentes(session: Session, intervencion_id: int, ingreso_id: int) -> list[Ingreso]:
    """Los demás ingresos vigentes de la intervención ("Botella 1 y 2" en el mismo hilo agrupa
    varias filas en una sola intervención — `motor.detectar_ingresos`)."""
    return (
        session.query(Ingreso)
        .join(FomonIntervencionIngreso, FomonIntervencionIngreso.ingreso_id == Ingreso.id)
        .filter(
            FomonIntervencionIngreso.intervencion_id == intervencion_id,
            Ingreso.id != ingreso_id,
            Ingreso.vigente(),
        )
        .all()
    )


# Una consulta en estos estados ya salió hacia burritoIA (TIMEOUT = se envió y no contestó a tiempo).
# ERROR no cuenta: `enviar_consultas` lo pone cuando la publicación falló.
_ESTADOS_CONSULTA_ENVIADA = ("ENVIADA", "RESPONDIDA", "TIMEOUT")


def _consultas_ya_enviadas(session: Session, intervencion_id: int) -> bool:
    return (
        session.query(FomonConsulta.id)
        .filter(
            FomonConsulta.intervencion_id == intervencion_id,
            FomonConsulta.estado.in_(_ESTADOS_CONSULTA_ENVIADA),
        )
        .first()
        is not None
    )


def _cancelar_consultas_pendientes(session: Session, intervencion_id: int, motivo: str) -> None:
    """Las consultas `PENDIENTE` todavía no salieron: se cancelan para que `enviar_consultas` no las
    mande — mismo patrón que `motor._cancelar_pre_vencidas`."""
    pendientes = (
        session.query(FomonConsulta)
        .filter(FomonConsulta.intervencion_id == intervencion_id, FomonConsulta.estado == "PENDIENTE")
        .all()
    )
    for consulta in pendientes:
        consulta.estado = "CANCELADA"
        consulta.error = motivo


def _otras_abiertas_en_camara(session: Session, camara_id: int, intervencion_id: int) -> list[FomonIntervencion]:
    return (
        session.query(FomonIntervencion)
        .filter(
            FomonIntervencion.camara_id == camara_id,
            FomonIntervencion.id != intervencion_id,
            FomonIntervencion.estado.in_(FOMON_ESTADOS_ABIERTOS),
        )
        .all()
    )


def _cancelar_intervencion_fomon(session: Session, interv: FomonIntervencion, ahora: datetime) -> None:
    """Pasa la intervención a `CANCELADA` (estado final que el motor nunca vuelve a levantar: ningún
    paso del `tick` filtra por él) con `cerrada_at`, como `CERRADA`, y cancela sus consultas
    `PENDIENTE`. Las `ENVIADA` siguen su curso: su respuesta se guarda como cualquier otra, pero
    `avanzar_intervenciones` ya no la procesa."""
    interv.estado = "CANCELADA"
    interv.cerrada_at = ahora
    interv.proximo_evento_en = None
    _cancelar_consultas_pendientes(session, interv.id, "ingreso_anulado")


# Estado "en curso" → "pendiente" de la misma fase: `planificar_consultas` sólo crea consultas para
# `PRE_PENDIENTE`/`POST_PENDIENTE`. Sin esta vuelta atrás, una `PRE_EN_CURSO` con sus consultas
# canceladas pasaría en el próximo tick a `EN_CURSO` sin línea base.
_VOLVER_A_PENDIENTE = {"PRE_EN_CURSO": "PRE_PENDIENTE", "POST_EN_CURSO": "POST_PENDIENTE"}
# Estados en los que la PRE todavía se va a medir con el alcance nuevo.
_ESTADOS_PRE = ("PRE_PENDIENTE", "PRE_EN_CURSO")


def _reubicar_intervencion_fomon(
    session: Session,
    interv: FomonIntervencion,
    *,
    camara_id: int,
    botella_n_id: int | None,
    ahora: datetime,
) -> None:
    """Lleva una intervención abierta (sin consultas ya enviadas) a la cámara destino recalculando su
    alcance con la misma función que la etapa PRE (`fo_monitor.alcance.resolver_alcance`, sólo
    consultas a la DB, sin red) y reemplazando la lista congelada de cables/servicios.

    - Las consultas `PENDIENTE` (armadas con el alcance viejo) se cancelan; las nuevas las crea
      `motor.planificar_consultas` en el próximo tick, porque la intervención vuelve a
      `PRE_PENDIENTE`/`POST_PENDIENTE` (los demás estados abiertos no tienen consultas en vuelo y
      el motor planifica la fase siguiente con el alcance nuevo).
    - Siempre se limpia `aviso_ts`/`aviso_canal`, para que nada más salga en el hilo de la cámara
      vieja (ese aviso queda en Slack: no se edita desde acá). En `PRE_PENDIENTE`, el próximo tick
      publica un aviso raíz nuevo con la cámara correcta (`planificar_consultas`). Después de la PRE
      (`EN_CURSO`, `SIN_EGRESO`, `POST_*`) el motor sólo publica la raíz en fase PRE y `_avisar` no
      hace nada sin `aviso_ts`: esa intervención ya no avisa por Slack; sus resultados siguen en el
      panel de FO Monitor.
    - Después de la PRE, si el alcance nuevo tiene servicios, `sin_linea_base=True`: nunca se midió
      la PRE de esos servicios (sin consultas enviadas), igual que el motor cuando la PRE no da
      mediciones válidas.
    - La botella objetivo sale de `resolver_alcance`: la elegida si es vigente del destino; si no se
      eligió ninguna, la Botella 1 (`botella_1_inferida` según corresponda), igual que al crearla.
    - `atribucion_compartida` se marca como en `crear_intervencion` si el destino ya tiene otra
      intervención abierta."""
    _cancelar_consultas_pendientes(session, interv.id, "alcance_recalculado")
    session.query(FomonIntervencionServicio).filter(
        FomonIntervencionServicio.intervencion_id == interv.id
    ).delete(synchronize_session=False)
    alcance = resolver_alcance(session, camara_id, botella_n_id)
    interv.camara_id = camara_id
    interv.botella_objetivo_n_id = alcance.botella_objetivo_n_id
    interv.botella_1_inferida = alcance.botella_1_inferida
    congelar_alcance(session, interv, alcance)
    if interv.estado not in _ESTADOS_PRE and alcance.servicios_unicos():
        interv.sin_linea_base = True
    interv.aviso_ts = None
    interv.aviso_canal = None
    nuevo_estado = _VOLVER_A_PENDIENTE.get(interv.estado)
    if nuevo_estado is not None:
        interv.estado = nuevo_estado
        interv.proximo_evento_en = ahora
    otras = _otras_abiertas_en_camara(session, camara_id, interv.id)
    interv.atribucion_compartida = bool(otras)
    for otra in otras:
        otra.atribucion_compartida = True


def mover_ingreso_web(
    session: Session,
    *,
    ingreso_id: int,
    camara_destino_id: int,
    cromo_botella_destino_n_id: int | None,
    motivo: str,
    usuario: str,
    ahora: datetime | None = None,
) -> ResultadoCorreccion:
    """Mueve un `Ingreso` (cualquier `tipo`) a otra Cámara: el movimiento existió, pero quedó
    registrado en la cámara equivocada (Fontaine ID mal tipeado, reescritura en el hilo, "Forzar
    ingreso" con la cámara errónea).

    - `cromo_botella_id` pasa a `NULL` salvo que se elija una `CromoBotella` **vigente** cuya
      `camara_id` sea el destino.
    - No se mueve un ingreso anulado ni a la misma cámara con la misma botella.
    - Un ingreso abierto se mueve abierto: `fecha_inicio`/`fecha_fin` no cambian.
    - FO Monitor: cada intervención abierta vinculada se reubica en el destino con el alcance
      recalculado (`_reubicar_intervencion_fomon`), salvo que tenga otros ingresos vigentes que
      sigan en otra cámara (`OTROS_INGRESOS_VIGENTES`; mover también esos la reubica) o que ya
      haya consultado a burritoIA con el alcance viejo (`CONSULTAS_YA_ENVIADAS`): ésas quedan como
      están y vuelven en `intervenciones_fomon_omitidas`.

    La auditoría guarda el destino en `camara_id_resuelta`/`cromo_botella_id_resuelta` y el origen
    en `camara_id_anterior`/`cromo_botella_id_anterior`. `ahora` es inyectable para tests."""
    ahora_utc = _como_utc(ahora if ahora is not None else datetime.now(timezone.utc))
    assert ahora_utc is not None
    sufijo_botella = f" botella {cromo_botella_destino_n_id}" if cromo_botella_destino_n_id is not None else ""
    inv = _invocacion_web(
        COMANDO_MOVER_INGRESO,
        f"[web] Mover ingreso #{ingreso_id} a cámara {camara_destino_id}{sufijo_botella}",
        usuario,
    )
    comunes: dict[str, Any] = {
        "camara_texto_solicitado": f"camara_id={camara_destino_id}{sufijo_botella}",
        "motivo": motivo,
    }

    objetivo = session.query(Ingreso).filter(Ingreso.id == ingreso_id).first()
    if objetivo is None:
        return _finalizar(
            session,
            inv,
            resultado=RESULTADO_INGRESO_NO_ENCONTRADO,
            respuesta=f"No existe el ingreso #{ingreso_id}.",
            error_detalle=f"Ingreso id={ingreso_id} inexistente",
            **comunes,
        )
    anterior = {
        "camara_id_anterior": objetivo.camara_id,
        "cromo_botella_id_anterior": objetivo.cromo_botella_id,
    }
    if objetivo.anulado_at is not None:
        return _finalizar(
            session,
            inv,
            resultado=RESULTADO_INGRESO_ANULADO,
            respuesta=f"El ingreso #{objetivo.id} está anulado; no se puede mover.",
            ingreso=objetivo,
            error_detalle=f"anulado el {objetivo.anulado_at} por {objetivo.anulado_por}",
            **anterior,
            **comunes,
        )
    motivo_limpio = _motivo_valido(motivo)
    if motivo_limpio is None:
        return _finalizar(
            session,
            inv,
            resultado=RESULTADO_MOTIVO_INVALIDO,
            respuesta=f"El motivo tiene que tener entre {MOTIVO_MIN} y {MOTIVO_MAX} caracteres.",
            ingreso=objetivo,
            error_detalle=f"motivo de {len((motivo or '').strip())} caracteres",
            **anterior,
            **comunes,
        )
    comunes["motivo"] = motivo_limpio

    destino = session.get(Camara, camara_destino_id)
    if destino is None:
        return _finalizar(
            session,
            inv,
            resultado=RESULTADO_CAMARA_NO_ENCONTRADA,
            respuesta=f"No existe la cámara destino #{camara_destino_id}.",
            ingreso=objetivo,
            error_detalle=f"Camara id={camara_destino_id} inexistente",
            **anterior,
            **comunes,
        )
    if destino.camara_padre_id is not None:
        return _finalizar(
            session,
            inv,
            resultado=RESULTADO_DESTINO_NO_RAIZ,
            respuesta=(
                f"La cámara destino #{destino.id} es una botella dentro de la cámara "
                f"#{destino.camara_padre_id}; elegí la cámara raíz."
            ),
            camara=destino,
            ingreso=objetivo,
            error_detalle=f"Camara id={destino.id} tiene camara_padre_id={destino.camara_padre_id}",
            **anterior,
            **comunes,
        )

    botella: CromoBotella | None = None
    if cromo_botella_destino_n_id is not None:
        botella = session.get(CromoBotella, cromo_botella_destino_n_id)
        problema = None
        if botella is None:
            problema = f"CromoBotella n_id={cromo_botella_destino_n_id} inexistente"
        elif not botella.vigente:
            problema = f"CromoBotella n_id={botella.n_id} no vigente"
        elif botella.camara_id != destino.id:
            problema = f"CromoBotella n_id={botella.n_id} pertenece a camara_id={botella.camara_id}"
        if problema is not None:
            return _finalizar(
                session,
                inv,
                resultado=RESULTADO_BOTELLA_INVALIDA,
                respuesta="La botella elegida no es una botella vigente de la cámara destino.",
                camara=destino,
                ingreso=objetivo,
                error_detalle=problema,
                **anterior,
                **comunes,
            )
    nuevo_botella_n_id = botella.n_id if botella is not None else None

    if objetivo.camara_id == destino.id and objetivo.cromo_botella_id == nuevo_botella_n_id:
        return _finalizar(
            session,
            inv,
            resultado=RESULTADO_MISMO_DESTINO,
            respuesta=f"El ingreso #{objetivo.id} ya está en esa cámara con esa botella.",
            camara=destino,
            botella=botella,
            ingreso=objetivo,
            error_detalle="destino igual al origen",
            **anterior,
            **comunes,
        )

    # Sólo las columnas: la relación `camara` no se reasigna para no pasar por la colección
    # `Camara.ingresos` (cascade `delete-orphan`); `commit()` expira y recarga ambas.
    objetivo.camara_id = destino.id
    objetivo.cromo_botella_id = nuevo_botella_n_id

    actualizadas: list[int] = []
    omitidas: list[IntervencionFomonOmitida] = []
    for interv in _intervenciones_abiertas_vinculadas(session, objetivo.id):
        otros = _otros_vinculados_vigentes(session, interv.id, objetivo.id)
        if any(o.camara_id != destino.id for o in otros):
            omitidas.append(IntervencionFomonOmitida(interv.id, OMISION_OTROS_INGRESOS_VIGENTES))
            continue
        if _consultas_ya_enviadas(session, interv.id):
            omitidas.append(IntervencionFomonOmitida(interv.id, OMISION_CONSULTAS_YA_ENVIADAS))
            continue
        _reubicar_intervencion_fomon(
            session, interv, camara_id=destino.id, botella_n_id=nuevo_botella_n_id, ahora=ahora_utc
        )
        actualizadas.append(interv.id)

    # Un único commit: el cambio (ingreso + FO Monitor) y su auditoría, juntos.
    resultado = _finalizar(
        session,
        inv,
        resultado=RESULTADO_OK_INGRESO_MOVIDO,
        respuesta=f"Ingreso #{objetivo.id} movido a la cámara {destino.nombre}.",
        camara=destino,
        botella=botella,
        ingreso=objetivo,
        atomico=True,
        **anterior,
        **comunes,
    )
    if actualizadas or omitidas:
        logger.info(
            "Mover ingreso #%s: intervenciones FO Monitor actualizadas=%s omitidas=%s",
            objetivo.id,
            actualizadas,
            omitidas,
        )
    resultado.intervenciones_fomon = actualizadas
    resultado.intervenciones_fomon_omitidas = omitidas
    return resultado


def anular_ingreso_web(
    session: Session,
    *,
    ingreso_id: int,
    motivo: str,
    usuario: str,
    ahora: datetime | None = None,
) -> ResultadoCorreccion:
    """Baja lógica de un `Ingreso` (cualquier `tipo`) que nunca ocurrió: setea `anulado_at` (UTC),
    `anulado_por` y `anulado_motivo`; la fila se conserva y todo lector que decide estado la
    excluye vía `Ingreso.vigente()`. Un ingreso ya anulado no se vuelve a anular.

    FO Monitor: cada intervención abierta vinculada pasa a `CANCELADA` (ver
    `_cancelar_intervencion_fomon`), salvo que le queden otros ingresos vigentes — esos sí
    ocurrieron y se siguen verificando (`OTROS_INGRESOS_VIGENTES` en `intervenciones_fomon_omitidas`).

    `ahora` es inyectable para tests."""
    ahora_utc = _como_utc(ahora if ahora is not None else datetime.now(timezone.utc))
    assert ahora_utc is not None
    inv = _invocacion_web(COMANDO_ANULAR_INGRESO, f"[web] Anular ingreso #{ingreso_id}", usuario)
    comunes: dict[str, Any] = {"camara_texto_solicitado": f"#{ingreso_id}", "motivo": motivo}

    objetivo = session.query(Ingreso).filter(Ingreso.id == ingreso_id).first()
    if objetivo is None:
        return _finalizar(
            session,
            inv,
            resultado=RESULTADO_INGRESO_NO_ENCONTRADO,
            respuesta=f"No existe el ingreso #{ingreso_id}.",
            error_detalle=f"Ingreso id={ingreso_id} inexistente",
            **comunes,
        )
    camara = objetivo.camara
    botella = objetivo.cromo_botella
    if objetivo.anulado_at is not None:
        return _finalizar(
            session,
            inv,
            resultado=RESULTADO_INGRESO_ANULADO,
            respuesta=f"El ingreso #{objetivo.id} ya está anulado.",
            camara=camara,
            botella=botella,
            ingreso=objetivo,
            error_detalle=f"anulado el {objetivo.anulado_at} por {objetivo.anulado_por}",
            **comunes,
        )
    motivo_limpio = _motivo_valido(motivo)
    if motivo_limpio is None:
        return _finalizar(
            session,
            inv,
            resultado=RESULTADO_MOTIVO_INVALIDO,
            respuesta=f"El motivo tiene que tener entre {MOTIVO_MIN} y {MOTIVO_MAX} caracteres.",
            camara=camara,
            botella=botella,
            ingreso=objetivo,
            error_detalle=f"motivo de {len((motivo or '').strip())} caracteres",
            **comunes,
        )
    comunes["motivo"] = motivo_limpio

    objetivo.anulado_at = ahora_utc
    objetivo.anulado_por = _truncar(usuario, _LARGO_ANULADO_POR)
    objetivo.anulado_motivo = motivo_limpio

    canceladas: list[int] = []
    omitidas: list[IntervencionFomonOmitida] = []
    for interv in _intervenciones_abiertas_vinculadas(session, objetivo.id):
        if _otros_vinculados_vigentes(session, interv.id, objetivo.id):
            omitidas.append(IntervencionFomonOmitida(interv.id, OMISION_OTROS_INGRESOS_VIGENTES))
            continue
        _cancelar_intervencion_fomon(session, interv, ahora_utc)
        canceladas.append(interv.id)

    # Un único commit: la baja lógica (+ FO Monitor) y su auditoría, juntas.
    resultado = _finalizar(
        session,
        inv,
        resultado=RESULTADO_OK_INGRESO_ANULADO,
        respuesta=f"Ingreso #{objetivo.id} anulado.",
        camara=camara,
        botella=botella,
        momento_efectivo=ahora_utc,
        ingreso=objetivo,
        atomico=True,
        **comunes,
    )
    if canceladas or omitidas:
        logger.info(
            "Anular ingreso #%s: intervenciones FO Monitor canceladas=%s omitidas=%s",
            objetivo.id,
            canceladas,
            omitidas,
        )
    resultado.intervenciones_fomon = canceladas
    resultado.intervenciones_fomon_omitidas = omitidas
    return resultado


__all__ = [
    "CAMARA_TEXTO_DEL_HILO",
    "CAMARA_TEXTO_NO_PARSEADO",
    "COMANDO_ANULAR_INGRESO",
    "COMANDO_FORZAR_EGRESO",
    "COMANDO_FORZAR_INGRESO",
    "COMANDO_MOVER_INGRESO",
    "ContextoHilo",
    "FUENTE_MOMENTO_EXPLICITO",
    "FUENTE_MOMENTO_HILO",
    "IntervencionFomonOmitida",
    "MOTIVO_MAX",
    "MOTIVO_MIN",
    "OMISION_CONSULTAS_YA_ENVIADAS",
    "OMISION_OTROS_INGRESOS_VIGENTES",
    "ORIGEN_SLACK",
    "ORIGEN_WEB",
    "RESULTADO_BOTELLA_INVALIDA",
    "RESULTADO_CAMARA_AMBIGUA",
    "RESULTADO_CAMARA_NO_ENCONTRADA",
    "RESULTADO_DESTINO_NO_RAIZ",
    "RESULTADO_EGRESO_ANTERIOR_AL_INGRESO",
    "RESULTADO_ERROR_INTERNO",
    "RESULTADO_HILO_SIN_FORMULARIO",
    "RESULTADO_INGRESO_ANULADO",
    "RESULTADO_INGRESO_NO_ENCONTRADO",
    "RESULTADO_INGRESO_YA_CERRADO",
    "RESULTADO_MISMO_DESTINO",
    "RESULTADO_MOMENTO_INVALIDO",
    "RESULTADO_MOTIVO_INVALIDO",
    "RESULTADO_OK_EGRESO_ASENTADO",
    "RESULTADO_OK_EGRESO_CERRADO",
    "RESULTADO_OK_INGRESO",
    "RESULTADO_OK_INGRESO_ANULADO",
    "RESULTADO_OK_INGRESO_MOVIDO",
    "RESULTADO_PENDIENTE_FECHA",
    "RESULTADO_SIN_INGRESO_ABIERTO",
    "RESULTADO_VARIOS_INGRESOS_ABIERTOS",
    "ResultadoCorreccion",
    "anular_ingreso_web",
    "mover_ingreso_web",
    "procesar_comando_correccion",
    "registrar_egreso_web",
    "resolver_contexto_hilo",
]
