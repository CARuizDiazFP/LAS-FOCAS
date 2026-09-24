# Nombre de archivo: refresco_prov.py
# Ubicación de archivo: modules/slack_baneo_notifier/refresco_prov.py
# Descripción: Refresco asíncrono contra PROV de los servicios vencidos de un comando "Servicios <cable>"/"Servicios <cable> B<N>" de Slack, encolado desde el listener sin bloquear Socket Mode

"""Task 9 del plan "Corrección de ingresos/servicios" (2026-09-23).

La Task 8 ya marca con 🕒 los servicios vencidos que devuelve un comando `Servicios <cable>`/
`Servicios <cable> B<N>` (`core/services/prov/frescura.py`), pero no refresca nada — el propio
docstring de `_linea_frescura_prov` (`cable_info.py`) lo dice explícito: "el refresco real todavía
no existe (Task 9)". Este módulo es ese refresco: dado el subconjunto de `ServicioUnico` vencidos de
un comando puntual, dispara hasta 25 llamadas a `ProvClient.obtener_contexto_servicio` (Semaphore(3),
sin reintentos — `max_reintentos=0`, mismo criterio "interactivo" que
`api/app/routes/servicios.py::_PROV_REFRESCAR_MAX_REINTENTOS=1` pero más conservador porque acá hay
hasta 25 llamadas por comando, no 1) y postea un segundo mensaje de Slack en el mismo hilo con el
resultado.

Puente de threads (worker.py): el listener de Slack corre en un daemon thread síncrono (Slack Bolt),
mientras que este módulo es 100% asyncio y necesita el loop vivo de `_main_loop`. El listener
encola la corrutina `refrescar_servicios_vencidos` con `asyncio.run_coroutine_threadsafe(loop=...)` —
ver `IngresoListener._disparar_refresco_prov` — y nunca espera el resultado (`.result()` bloquearía
el thread del listener, exactamente lo que esta tarea existe para evitar).

Alcance del refresco: sólo los servicios YA vencidos de ESTE comando puntual (el conjunto que
`servicios_vencidos_sync` marcó para el cable/buffer consultado), nunca una barrida global de
`app.servicios` — ese es el trabajo del backfill masivo (`scripts/servicios_backfill_prov.py`), que
corre con su propio presupuesto de reintentos y sin deadline interactivo.

Orden de prioridad dentro del tope de 25 (Step 2 del brief, "ordenados por antigüedad"): por
`ultimo_intento` ascendente, nulls primero (nunca intentado antes → máxima prioridad), NO por
`ultima_sincronizacion_ok`. Es a propósito y es la pieza que hace cumplir la ruling vinculante del
coordinador: si ordenáramos por `ultima_sincronizacion_ok`, un servicio que PROV nunca puede
resolver (que se queda con esa columna en `NULL` para siempre, ver "Escritura de fallo" más abajo)
volvería a ganar el primer lugar en TODOS los comandos futuros — exactamente el escenario que la
ruling pide evitar ("desplazando a servicios que sí se podrían refrescar"). Ordenar por
`ultimo_intento` en cambio hace que, apenas se registra el intento fallido, ese servicio pase al
FINAL de la cola de prioridad — le da lugar a los demás vencidos antes de reintentarlo.
`_EPOCA_NUNCA_SINCRONIZADO` sigue existiendo como valor mínimo interno para ordenar el grupo "nunca
intentado" de `priorizar_por_antiguedad` — no tiene ninguna relación con lo que se escribe en
`ultima_sincronizacion_ok` (ver el punto siguiente).

Escritura de fallo (ruling vinculante, no contemplada por la Task 7): `_persistir_intento_fallido`
es un segundo embudo de escritura de `ServicioSyncProv`, además del camino de éxito de
`ingerir_contexto_prov` — persiste `ultimo_intento`/`ultimo_error` sin haber conseguido nunca un
contexto exitoso de PROV. `ultima_sincronizacion_ok` es `NULL` (nullable desde la migración
`20260923_03`, revirtiendo el `NOT NULL` original de `20260923_02`) en ese caso: `NULL` ya es el
encoding canónico de "nunca sincronizado" que espera la consulta de frescura
(`core/services/prov/frescura.py`: `IS NULL OR ... < corte`), así que no hace falta ningún
centinela para mantener al servicio "vencido" — un fallo repetido de PROV nunca produce un valor
real en esa columna. El `ON CONFLICT DO UPDATE` nunca toca `ultima_sincronizacion_ok` si ya existe
una fila con un valor real de un éxito anterior — sólo `ultimo_intento`/`ultimo_error` se actualizan
en el camino de fallo, igual que anticipa el docstring de `ServicioSyncProv` ("dejan la puerta
abierta a que un futuro camino de *fallo* actualice sólo `ultimo_intento`/`ultimo_error` de una
fila ya existente sin tocar la fecha de la última sincronización que sí funcionó").

(Nota histórica, revisión de calidad de la Task 9: la primera versión de este módulo usaba un
centinela `1970-01-01 UTC` en `ultima_sincronizacion_ok` para satisfacer el `NOT NULL` original —
se descartó porque `NULL` ya era el encoding que la consulta de frescura esperaba, y el centinela
sólo agregaba un segundo encoding del mismo estado que sostener para siempre. La migración
`20260923_03` hizo la columna nullable y este módulo escribe `NULL` directamente.)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.services.cromo.verificador import ServicioUnico
from core.services.prov.client import (
    ProvClientError,
    ProvServicioNoEncontradoError,
    get_prov_client,
)
from core.services.prov.ingesta import ingerir_contexto_prov
from db.models.infra import Servicio, ServicioSyncProv
from db.session import AsyncSessionLocal

logger = logging.getLogger("slack_baneo_worker.refresco_prov")

# Límites que fija el brief de la Task 9 — todos overridable por parámetro en
# `refrescar_servicios_vencidos` para que los tests puedan ejercitar el tope/deadline sin
# esperar 120s reales ni fabricar 25 servicios de verdad.
CONCURRENCIA_MAXIMA = 3
DEADLINE_SEGUNDOS = 120.0
TOPE_SERVICIOS_POR_COMANDO = 25
MAX_REINTENTOS_INTERACTIVO = 0  # ver docstring del módulo: más conservador que el 1 del endpoint

# Ya NO se escribe en `ultima_sincronizacion_ok` (esa columna usa `None`/NULL desde la migración
# `20260923_03` — ver docstring del módulo, "Escritura de fallo"). Sigue existiendo únicamente como
# valor mínimo interno para el desempate de `priorizar_por_antiguedad._clave` ("nunca intentado" ->
# máxima prioridad); cualquier datetime lo bastante viejo serviría, se reusa éste por comodidad.
_EPOCA_NUNCA_SINCRONIZADO = datetime(1970, 1, 1, tzinfo=timezone.utc)

# Cables con un refresco en curso — candado de proceso (Step 2: "para que dos personas no
# refresquen el mismo cable a la vez"). Nunca se toca fuera de una corrutina que corre en el loop
# del worker (ver docstring del módulo), y el check-and-set de más abajo no tiene ningún `await` en
# el medio, así que dos invocaciones concurrentes para el mismo cable no pueden pisarse — asyncio
# sólo cede el control en un punto de `await` explícito.
_cables_en_refresco: set[int] = set()

_SQL_ULTIMO_INTENTO_BATCH = text(
    "SELECT servicio_id, ultimo_intento FROM app.servicios_sync_prov WHERE servicio_id = ANY(:ids ::integer[])"
)


@dataclass(slots=True)
class ResultadoServicioRefrescado:
    """Resultado de intentar refrescar un `ServicioUnico` puntual — usado para armar el mensaje de
    seguimiento (`_construir_mensaje_seguimiento`)."""

    servicio_id: int
    servicio_id_externo: str
    ok: bool
    motivo_error: Optional[str] = None


def _con_tz(momento: Optional[datetime]) -> Optional[datetime]:
    if momento is None:
        return None
    if momento.tzinfo is None:
        return momento.replace(tzinfo=timezone.utc)
    return momento


async def priorizar_por_antiguedad(servicios: list[ServicioUnico]) -> list[ServicioUnico]:
    """Ordena `servicios` por `ultimo_intento` ascendente (nulls primero) — ver "Orden de
    prioridad" en el docstring del módulo. Sesión corta de sólo lectura, cerrada antes de que
    empiece cualquier llamada de red (mismo contrato que el resto del módulo)."""
    if not servicios:
        return []
    ids = [s.servicio_id for s in servicios]
    async with AsyncSessionLocal() as session:
        filas = (await session.execute(_SQL_ULTIMO_INTENTO_BATCH, {"ids": ids})).all()
    ultimo_intento_por_id = {fila[0]: _con_tz(fila[1]) for fila in filas}

    def _clave(servicio: ServicioUnico) -> tuple[int, datetime]:
        intento = ultimo_intento_por_id.get(servicio.servicio_id)
        if intento is None:
            return (0, _EPOCA_NUNCA_SINCRONIZADO)
        return (1, intento)

    return sorted(servicios, key=_clave)


async def _persistir_intento_fallido(servicio_id: int, nro_servicio_consultado: str, motivo: str) -> None:
    """Punto de escritura del camino de FALLO (la Task 7/`ingerir_contexto_prov` escribe el camino
    de éxito — ver docstring del módulo, "Escritura de fallo"). Nunca lanza: un fallo al persistir
    el fallo no debe tumbar el resto del lote ni impedir el mensaje de seguimiento.

    `ultima_sincronizacion_ok=None` en el INSERT (no un centinela): la columna es nullable desde la
    migración `20260923_03` y `NULL` ya es "nunca sincronizado" para la consulta de frescura. El
    `ON CONFLICT DO UPDATE` de abajo nunca incluye esta columna en el `SET`, así que un fallo
    posterior a un éxito real jamás le pisa la fecha que sí funcionó."""
    ahora = datetime.now(timezone.utc)
    tabla = ServicioSyncProv.__table__
    upsert = pg_insert(tabla).values(
        servicio_id=servicio_id,
        ultima_sincronizacion_ok=None,
        ultimo_intento=ahora,
        ultimo_error=motivo[:2000],
        nro_servicio_consultado=nro_servicio_consultado,
        created_at=ahora,
        updated_at=ahora,
    )
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(
                upsert.on_conflict_do_update(
                    index_elements=[tabla.c.servicio_id],
                    set_={
                        "ultimo_intento": upsert.excluded.ultimo_intento,
                        "ultimo_error": upsert.excluded.ultimo_error,
                        "nro_servicio_consultado": upsert.excluded.nro_servicio_consultado,
                        "updated_at": upsert.excluded.updated_at,
                    },
                )
            )
            await session.commit()
    except Exception as exc:  # defensivo — nunca debe tumbar el lote por un fallo de auditoría
        logger.error(
            "action=prov_refresco_slack evento=error_persistiendo_fallo servicio_id=%s error=%s",
            servicio_id,
            exc,
            exc_info=True,
        )


def _motivo_de_excepcion(exc: Exception) -> str:
    """Clasifica el motivo de un fallo puntual en las categorías que pide el brief ("no encontrado
    en PROV / 4xx / timeout"), para el mensaje de seguimiento nominal."""
    if isinstance(exc, ProvServicioNoEncontradoError):
        return "no encontrado en PROV"
    if isinstance(exc, ProvClientError):
        if exc.status_code is not None:
            return f"PROV respondió {exc.status_code}"
        return f"timeout o error de comunicación con PROV: {exc}"
    return f"error inesperado: {exc}"


async def refrescar_un_servicio(
    servicio: ServicioUnico, semaforo: asyncio.Semaphore, cliente: Any
) -> ResultadoServicioRefrescado:
    """Refresca un único `ServicioUnico` contra PROV. Nunca lanza — cualquier excepción (de PROV o
    de la escritura local) se traduce en un `ResultadoServicioRefrescado` con `ok=False`, así el
    caller (`refrescar_servicios_vencidos`) puede correr todo el lote con `asyncio.gather` sin que
    un fallo puntual cancele al resto (caso obligatorio del brief).

    Una sesión corta de DB por servicio, nunca sostenida a través de la llamada de red — mismo
    precedente que `refrescar_servicio_desde_prov` (`api/app/routes/servicios.py:686-697`): la
    sesión de escritura sólo se abre DESPUÉS de que la llamada a PROV ya volvió."""
    numero_prov = servicio.numero_primer_servicio or servicio.servicio_id_externo

    async with semaforo:
        try:
            contexto = await cliente.obtener_contexto_servicio(
                numero_prov, max_reintentos=MAX_REINTENTOS_INTERACTIVO
            )
        except Exception as exc:
            motivo = _motivo_de_excepcion(exc)
            logger.warning(
                "action=prov_refresco_slack evento=fallo_prov servicio_id=%s numero_prov=%s motivo=%s",
                servicio.servicio_id,
                numero_prov,
                motivo,
            )
            await _persistir_intento_fallido(servicio.servicio_id, numero_prov, motivo)
            return ResultadoServicioRefrescado(servicio.servicio_id, servicio.servicio_id_externo, False, motivo)

        try:
            async with AsyncSessionLocal() as session:
                fila = await session.execute(select(Servicio).where(Servicio.id == servicio.servicio_id))
                svc = fila.scalar_one_or_none()
                if svc is None:
                    # Se borró entre que se armó el lote y que le tocó su turno — la llamada a PROV
                    # fue exitosa igual, no tiene sentido reportarlo como fallo de PROV.
                    logger.warning(
                        "action=prov_refresco_slack evento=servicio_borrado_entre_medio servicio_id=%s",
                        servicio.servicio_id,
                    )
                    return ResultadoServicioRefrescado(servicio.servicio_id, servicio.servicio_id_externo, True, None)
                await ingerir_contexto_prov(session, svc, contexto)
                await session.commit()
        except Exception as exc:
            motivo = f"error guardando localmente: {exc}"
            logger.error(
                "action=prov_refresco_slack evento=error_guardado servicio_id=%s error=%s",
                servicio.servicio_id,
                exc,
                exc_info=True,
            )
            await _persistir_intento_fallido(servicio.servicio_id, numero_prov, motivo)
            return ResultadoServicioRefrescado(servicio.servicio_id, servicio.servicio_id_externo, False, motivo)

    return ResultadoServicioRefrescado(servicio.servicio_id, servicio.servicio_id_externo, True, None)


# Tope del motivo dentro del mensaje de Slack (Minor subido a obligatorio de la revisión de
# calidad): mucho más chico que el `[:2000]` que ya protege la columna `ultimo_error` en
# `_persistir_intento_fallido` porque acá hay hasta 25 motivos concatenados en un solo mensaje, no
# uno por fila de DB. Un `exc` de SQLAlchemy en el bucket "error guardando localmente: {exc}" trae
# sentencia + parámetros (1-3 KB fácil) — sin este tope, 25 de esos superan el límite de 40.000
# caracteres del campo `text` de Slack, `chat_postMessage` devuelve `msg_too_long` y el `except` de
# `refrescar_servicios_vencidos` se traga el follow-up entero (ver Important en el reporte de
# fix). De paso evita volcar SQL y valores de fila a un canal de Slack.
_TOPE_MOTIVO_EN_MENSAJE = 200


def _construir_mensaje_seguimiento(
    exitosos: list[ResultadoServicioRefrescado],
    fallidos: list[ResultadoServicioRefrescado],
    *,
    total_vencidos: int | None = None,
) -> str:
    """Segundo mensaje (Step 3): qué IDs cambiaron y la lista nominal de los que no se pudieron
    refrescar, con el motivo de cada uno — nunca sólo un conteo.

    `total_vencidos` (fix final, Important D): el primer mensaje (`_linea_frescura_prov`,
    `cable_info.py`) cuenta TODOS los vencidos del comando ("🕒 118 con validación PROV vencida —
    refrescando…"), pero este lote sólo intenta `TOPE_SERVICIOS_POR_COMANDO` (25) — sin este
    parámetro, los vencidos que quedan afuera del tope no figuraban ni como éxito ni como fallo en
    ningún mensaje, y el orden por `ultimo_intento` hacía que cada reintento agarrara otro
    subconjunto de 25 sin ninguna explicación visible. Con `total_vencidos` mayor que
    `len(exitosos) + len(fallidos)` (siempre `len(candidatos)`, el tope aplicado), se agrega una
    línea final explícita en vez de dejarlo implícito."""
    lineas = ["🔄 Refresco PROV completado"]
    if exitosos:
        ids = ", ".join(r.servicio_id_externo for r in exitosos)
        lineas.append(f"✅ {len(exitosos)} actualizado(s): {ids}")
    if fallidos:
        lineas.append(f"⚠️ {len(fallidos)} no se pudo(pudieron) refrescar:")
        lineas.extend(
            f"• {r.servicio_id_externo} — {(r.motivo_error or '')[:_TOPE_MOTIVO_EN_MENSAJE]}" for r in fallidos
        )
    if not exitosos and not fallidos:
        lineas.append("Nada para reportar.")
    intentados = len(exitosos) + len(fallidos)
    if total_vencidos is not None and total_vencidos > intentados:
        pendientes = total_vencidos - intentados
        lineas.append(f"⏳ Quedan {pendientes} pendiente(s) — volvé a pedir el comando.")
    return "\n".join(lineas)


async def refrescar_servicios_vencidos(
    *,
    cable_n_id: int,
    servicios: list[ServicioUnico],
    client: Any,
    channel: str,
    thread_ts: str,
    concurrencia: int = CONCURRENCIA_MAXIMA,
    deadline_segundos: float = DEADLINE_SEGUNDOS,
    tope: int = TOPE_SERVICIOS_POR_COMANDO,
) -> None:
    """Corrutina que el listener encola vía `asyncio.run_coroutine_threadsafe` (Step 1) — nunca se
    llama directamente desde el thread del listener. `servicios` ya viene filtrado a los vencidos
    de ESTE comando (lo decide el caller, `IngresoListener._disparar_refresco_prov`); acá sólo se
    aplican el tope, el orden de prioridad, la concurrencia y el deadline.

    `concurrencia`/`deadline_segundos`/`tope` son overridable sólo para tests (nunca se pasan en el
    camino real del listener) — los defaults son los límites que fija el brief.
    """
    if not servicios:
        return

    if cable_n_id in _cables_en_refresco:
        # Candado por cable (Step 2): otra invocación ya está refrescando este mismo cable — se
        # skipea el lote entero (ni PROV ni un segundo lote redundante), pero SÍ se le avisa a
        # este segundo hilo (Important 4 de la revisión de calidad): sin este mensaje, el segundo
        # técnico que dispara el comando se queda esperando indefinidamente un resultado que se
        # postea en el hilo del PRIMERO, exactamente el escenario para el que existe el candado.
        logger.info(
            "action=prov_refresco_slack evento=candado_activo cable_n_id=%s total=%d", cable_n_id, len(servicios)
        )
        try:
            await asyncio.to_thread(
                client.chat_postMessage,
                channel=channel,
                thread_ts=thread_ts,
                text="🔄 Ya hay un refresco PROV en curso para este cable — el resultado se postea en el hilo que lo disparó primero.",
                mrkdwn=True,
            )
        except Exception as exc:
            logger.error(
                "action=prov_refresco_slack evento=error_post_mensaje_candado cable_n_id=%s error=%s",
                cable_n_id,
                exc,
                exc_info=True,
            )
        return
    _cables_en_refresco.add(cable_n_id)

    inicio = time.monotonic()
    try:
        try:
            cliente = get_prov_client()
        except Exception as exc:
            # Defensivo: `IngresoListener._disparar_refresco_prov` ya valida esto ANTES de encolar
            # (Step 3 del brief) — llegar hasta acá con PROV mal configurado sería una carrera rara
            # (cambio de entorno entre el chequeo y la ejecución). No hay nada que refrescar.
            logger.error(
                "action=prov_refresco_slack evento=prov_no_configurado_en_corrutina cable_n_id=%s error=%s",
                cable_n_id,
                exc,
            )
            return

        ordenados = await priorizar_por_antiguedad(servicios)
        candidatos = ordenados[:tope]

        semaforo = asyncio.Semaphore(concurrencia)
        resultados: dict[int, ResultadoServicioRefrescado] = {}

        async def _tarea(servicio: ServicioUnico) -> None:
            resultados[servicio.servicio_id] = await refrescar_un_servicio(servicio, semaforo, cliente)

        tareas = [asyncio.create_task(_tarea(s)) for s in candidatos]
        try:
            await asyncio.wait_for(asyncio.gather(*tareas, return_exceptions=True), timeout=deadline_segundos)
        except asyncio.TimeoutError:
            logger.warning(
                "action=prov_refresco_slack evento=deadline_alcanzado cable_n_id=%s deadline_segundos=%.1f",
                cable_n_id,
                deadline_segundos,
            )
        finally:
            for tarea in tareas:
                if not tarea.done():
                    tarea.cancel()

        # Cualquier candidato sin resultado a esta altura es porque el deadline cortó el lote antes
        # de que le tocara su turno (nunca llegó a llamar a PROV) — se reporta igual en el mensaje
        # de seguimiento, nunca se descarta en silencio.
        for servicio in candidatos:
            if servicio.servicio_id not in resultados:
                resultados[servicio.servicio_id] = ResultadoServicioRefrescado(
                    servicio.servicio_id,
                    servicio.servicio_id_externo,
                    False,
                    "se agotó el tiempo del lote antes de poder intentarlo",
                )

        exitosos = [r for r in resultados.values() if r.ok]
        fallidos = [r for r in resultados.values() if not r.ok]
        duracion_ms = int((time.monotonic() - inicio) * 1000)

        logger.info(
            "action=prov_refresco_slack evento=lote_completado cable_n_id=%s total=%d refrescados=%d "
            "fallidos=%d duracion_ms=%d",
            cable_n_id,
            len(candidatos),
            len(exitosos),
            len(fallidos),
            duracion_ms,
        )

        texto = _construir_mensaje_seguimiento(exitosos, fallidos, total_vencidos=len(servicios))
        try:
            # `slack_sdk.WebClient.chat_postMessage` es una llamada HTTP síncrona — se corre en un
            # thread aparte para no bloquear el loop compartido del worker mientras espera la
            # respuesta de Slack (mismo motivo que el resto de este módulo evita sostener sesiones
            # de DB a través de una llamada de red).
            await asyncio.to_thread(
                client.chat_postMessage, channel=channel, thread_ts=thread_ts, text=texto, mrkdwn=True
            )
        except Exception as exc:
            logger.error(
                "action=prov_refresco_slack evento=error_post_mensaje cable_n_id=%s error=%s",
                cable_n_id,
                exc,
                exc_info=True,
            )
    except Exception as exc:
        # Red de seguridad de nivel superior (Important 1 de la revisión de calidad): sin este
        # `except`, una excepción de `priorizar_por_antiguedad` (Postgres caído, pool agotado) u
        # otro punto del lote escapa al `concurrent.futures.Future` que devuelve
        # `run_coroutine_threadsafe` en el listener — ese Future se descarta sin que nadie llame
        # `.result()`, así que ni loguea "exception was never retrieved" (eso sólo lo hace
        # `asyncio.Future`) ni deja rastro. El primer mensaje con el dato Cromo ya salió; sin este
        # `except` el segundo mensaje simplemente nunca llega y no queda ni una línea de log.
        logger.error(
            "action=prov_refresco_slack evento=error_no_manejado cable_n_id=%s total=%d error=%s",
            cable_n_id,
            len(servicios),
            exc,
            exc_info=True,
        )
        try:
            await asyncio.to_thread(
                client.chat_postMessage,
                channel=channel,
                thread_ts=thread_ts,
                text="⚠️ El refresco PROV de este cable se interrumpió por un error interno inesperado — reintentá el comando en unos minutos.",
                mrkdwn=True,
            )
        except Exception as exc_post:
            logger.error(
                "action=prov_refresco_slack evento=error_post_mensaje_error cable_n_id=%s error=%s",
                cable_n_id,
                exc_post,
                exc_info=True,
            )
    finally:
        _cables_en_refresco.discard(cable_n_id)


__all__ = [
    "CONCURRENCIA_MAXIMA",
    "DEADLINE_SEGUNDOS",
    "TOPE_SERVICIOS_POR_COMANDO",
    "MAX_REINTENTOS_INTERACTIVO",
    "ResultadoServicioRefrescado",
    "refrescar_servicios_vencidos",
    # Fix final (Important E, mecánico): promovidos de privados a públicos — el `from ... import`
    # de `web/app/main.py::_ejecutar_refresco_prov_lote` los importaba con el nombre privado desde
    # dentro del cuerpo de la función (un rename ahí revienta recién en runtime, ningún chequeo
    # estático lo agarra). No se movió nada de lugar ni se factorizó la duplicación con
    # `refrescar_servicios_vencidos` — eso queda como deuda declarada (ver `docs/decisiones.md`).
    "priorizar_por_antiguedad",
    "refrescar_un_servicio",
]
