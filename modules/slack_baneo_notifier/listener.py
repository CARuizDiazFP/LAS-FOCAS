# Nombre de archivo: listener.py
# Ubicación de archivo: modules/slack_baneo_notifier/listener.py
# Descripción: Listener de ingresos técnicos + comandos de Cables via Slack Bolt (Socket Mode)

"""Escucha en tiempo real los formularios de ingreso a cámaras enviados por técnicos
en un canal de Slack.  Cuando llega un mensaje, extrae el nombre de cámara del campo
"Cámara:", normaliza el texto, consulta la DB y responde en el **hilo original**
con uno de los tres estados posibles.

Desde 2026-08-13 también escucha menciones directas (`app_mention`) para los comandos de Cables/
Servicios de Cromo especificados en `docs/slack_app_cables.md` — misma Slack App/tokens que el
listener de ingresos, sólo un evento distinto de Slack. Implementados los 3 comandos: "Info cable
<nombre>", "Verificar cable <nombre> B<N>" e "Info cable <nombre> B<N>" (ver `cable_info.py`).

Requiere:
  - SLACK_BOT_TOKEN  (xoxb-...)  — ya existente en .env
  - SLACK_APP_TOKEN  (xapp-...)  — nuevo, para Socket Mode
  - Scope adicional para app_mention: `app_mentions:read` en la Slack App (verificar en Slack, no
    asumible desde el código)

Se integra en worker.py como un daemon thread independiente.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Any, Optional

from core.services.camara_estado_service import obtener_ultimo_motivo_baneo_manual
from core.services.cromo.camara_botella_busqueda import buscar_camara_o_botella_cromo
from core.services.cromo.detalle import pelos_de_tubo_sync
from core.services.cromo.empalme_resolucion import resolver_botella_por_fusion_sync
from core.services.cromo.verificador import servicios_por_tubo_sync
from db.models.cromo import CromoCable
from db.session import SessionLocal
from modules.slack_baneo_notifier.cable_info import (
    buscar_cable_por_nombre,
    construir_respuesta_ambiguo,
    construir_respuesta_buffer_no_encontrado,
    construir_respuesta_info_buffer,
    construir_respuesta_info_cable,
    construir_respuesta_no_encontrado,
    construir_respuesta_verificar_buffer,
    contar_buffers_cable,
    extraer_comando_cable_buffer,
    extraer_comando_info_cable,
    resolver_tubo_por_numero,
)
from modules.slack_baneo_notifier.camara_search import AmbiguousSearchError, detectar_multi_bot, extraer_nombre_camara, limpiar_ruido_operativo

logger = logging.getLogger("slack_baneo_worker.listener")

# Slack antepone el mention token (ej. "<@U01ABCXYZ> ") al texto de un evento app_mention — se
# recorta antes de intentar matchear cualquier comando.
_RE_MENTION_PREFIX = re.compile(r"^\s*<@[^>]+>\s*")

_NOMBRE_SERVICIO_LISTENER = "slack_ingreso_listener"
_CANAL_ID_DEFAULT = ""  # Se completa desde config_servicios en DB

# Regex para detectar nombres que corresponden a Nodos (no son cámaras).
# Se aplica sobre el nombre extraído —no el texto completo— para evitar falsos
# positivos con el label del Workflow "*Nombre: Nodo/Camara/botella*".
_RE_NODO = re.compile(r"\bnodos?\b", re.IGNORECASE)

# Detecta una respuesta de seguimiento con el ID de empalme más cercano, en el hilo de un caso
# `IngresoSinMatch` pendiente (ver el aviso agregado en `_construir_respuesta_camara` cuando no hay
# match). Dígitos puros, opcionalmente precedidos de "empalme" o "#". Mínimo 3 dígitos a propósito:
# evita falsos positivos con respuestas cortas tipo "sí"/"ok"/números de piso — un `fusion_n_id`
# real de Cromo tiene muchos más dígitos (ver ejemplos en `core/services/cromo/empalmes.py`).
_RE_SEGUIMIENTO_EMPALME = re.compile(r"^\s*(?:empalme\s*)?#?(\d{3,})\s*$", re.IGNORECASE)


class IngresoListener:
    """Escucha mensajes de ingreso técnico en un canal Slack y responde en hilo."""

    def __init__(self, bot_token: str, app_token: str) -> None:
        self._bot_token = bot_token
        self._app_token = app_token
        self._handler: Any = None
        self._thread: threading.Thread | None = None
        self._running = False

    # ── Configuración desde DB ───────────────────────────────────────────

    def _get_config(self, session: Any) -> tuple[str, bool, list[str], bool]:
        """Lee canal_id, activo, workflow_ids y solo_workflows desde config_servicios.

        Crea la fila con defaults si no existe todavía (primer arranque).
        Devuelve (canal_id, activo, workflow_ids_list, solo_workflows).
        """
        try:
            from db.models.servicios import ConfigServicios

            row = (
                session.query(
                    ConfigServicios.slack_channels,
                    ConfigServicios.activo,
                    ConfigServicios.workflow_ids,
                    ConfigServicios.solo_workflows,
                )
                .filter(ConfigServicios.nombre_servicio == _NOMBRE_SERVICIO_LISTENER)
                .one_or_none()
            )
            if row is None:
                # Primera vez: crear fila con defaults (inactivo hasta configuración manual)
                config = ConfigServicios(
                    nombre_servicio=_NOMBRE_SERVICIO_LISTENER,
                    intervalo_horas=0,
                    slack_channels="",
                    activo=False,
                    workflow_ids=None,
                    solo_workflows=False,
                )
                session.add(config)
                session.commit()
                logger.info("Fila '%s' creada en config_servicios (inactivo por defecto)", _NOMBRE_SERVICIO_LISTENER)
                return "", False, [], False

            canal_id = (row[0] or "").strip()
            activo = bool(row[1])
            raw_ids = row[2] or ""
            workflow_ids = [w.strip() for w in raw_ids.split(",") if w.strip()]
            solo_workflows = bool(row[3])
            return canal_id, activo, workflow_ids, solo_workflows

        except Exception as exc:
            logger.warning("No se pudo leer config del listener: %s", exc)
            return "", False, [], False

    # ── Handler principal ────────────────────────────────────────────────

    def _construir_respuesta_camara(
        self,
        nombre_buscado: str,
        session: Any,
        *,
        channel: str = "",
        thread_ts: str | None = None,
    ) -> str:
        """Busca una cámara por nombre y construye el texto de respuesta.

        Aplica el filtro de ruido operativo antes de buscar y antes de registrar,
        descartando sufijos como '- CUADRILLA DE HIDROCONS' o '/ Móvil 4'.

        Desde la Tarea 2 del refactor de ingreso (2026-08-23), la búsqueda usa
        ``buscar_camara_o_botella_cromo()`` (no ``buscar_camara()`` directo): además de
        ``app.camaras``, cubre botellas que sólo existen en el inventario de Cromo (ver
        `core/services/cromo/camara_botella_busqueda.py`). Puede lanzar ``AmbiguousSearchError``,
        que no se captura acá — la maneja el caller (`_handle_message`).

        Si no encuentra nada en ninguna fuente, NUNCA bloquea el ingreso ni crea una `Camara` nueva
        (2026-08-11 — Cromo es la fuente de verdad del inventario; un caso sin match es un problema
        de escritura/regex, no una cámara faltante de alta). Registra el caso en `IngresoSinMatch`
        (junto con `thread_ts`, para poder detectar más tarde una respuesta de seguimiento con el ID
        de empalme más cercano — ver `_procesar_seguimiento_empalme`) para revisión manual posterior
        y mejora del regex, y responde dejando explícito que el técnico puede continuar igual —
        nunca lee como un rechazo. Si encuentra una cámara (propia o resuelta desde una
        `CromoBotella`), evalúa el estado de acceso vía `_evaluar_estado_acceso_camara`.
        """
        nombre_buscado = limpiar_ruido_operativo(nombre_buscado)
        resultado = buscar_camara_o_botella_cromo(nombre_buscado, session)
        camara = resultado.camara
        nombre_norm = resultado.nombre_norm
        logger.info(
            "Resultado búsqueda — cámara: %s (normalizado: '%s', fuente: %s)",
            camara,
            nombre_norm,
            resultado.fuente,
        )

        if camara is None:
            from db.models.infra import IngresoSinMatch

            caso = IngresoSinMatch(
                texto_original=nombre_buscado,
                origen="slack",
                contexto=channel or None,
                thread_ts=thread_ts,
            )
            session.add(caso)
            session.commit()
            logger.info(
                "Cámara '%s' sin match — registrado IngresoSinMatch id=%s para revisión manual",
                nombre_buscado,
                caso.id,
            )
            return (
                "⚠️ No pude confirmar automáticamente la cámara *{}* contra el inventario — "
                "quedó registrada para revisión manual (puede ser un error de tipeo o una "
                "diferencia de formato). *Podés continuar con el ingreso con normalidad.* "
                "Si conocés el ID de empalme más cercano, respondé en este mismo hilo sólo "
                "con el número."
            ).format(nombre_buscado)

        return self._evaluar_estado_acceso_camara(camara, session)

    def _evaluar_estado_acceso_camara(self, camara: Any, session: Any) -> str:
        """Evalúa el estado de acceso de una `Camara` ya resuelta y arma el texto de respuesta.

        Factorizado de `_construir_respuesta_camara` (Tarea 2, 2026-08-23) para poder reusar la
        misma jerarquía de bloqueo desde `_procesar_seguimiento_empalme`, que resuelve la cámara
        por otro camino (fusión de empalme → botella dueña → `camara_id`) pero debe aplicar
        exactamente el mismo criterio de acceso. Jerarquía:

        1. Incidente de red activo (``IncidenteBaneo.activo``) → 🚨 ATENCIÓN.
        2. Estado ``BANEADA`` sin incidente activo (baneo manual desde el panel)
           → :no_entry: con el motivo extraído de ``camaras_estado_auditoria``.
        3. Cualquier otro estado → ✅ podés proceder.
        """
        incidentes = _obtener_incidentes_activos_camara(camara, session)
        if incidentes:
            inc = incidentes[0]
            logger.info("Cámara '%s' BANEADA — incidente #%s", camara.nombre, inc.id)
            return (
                f"🚨 *ATENCIÓN* — La cámara *{camara.nombre}* tiene el incidente "
                f"*#{inc.id}* activo (Baneo de Protección).\n"
                f"Ticket: {inc.ticket_asociado or 'sin ticket'} | "
                f"Servicio protegido: {inc.servicio_protegido_id}\n"
                "_No acceder a esta cámara hasta nuevo aviso._"
            )

        from db.models.infra import CamaraEstado

        if camara.estado == CamaraEstado.BANEADA:
            motivo = obtener_ultimo_motivo_baneo_manual(session, camara.id)
            motivo_texto = motivo or "sin motivo registrado"
            logger.info(
                "Cámara '%s' BANEADA manualmente — sin incidente activo, motivo: '%s'",
                camara.nombre,
                motivo_texto,
            )
            return (
                f":no_entry: La cámara *{camara.nombre}* fue baneada manualmente. "
                f"Motivo: _{motivo_texto}_.\n"
                "_No podés proceder con el ingreso._"
            )

        logger.info("Cámara '%s' OK — sin incidentes activos", camara.nombre)
        return (
            f"✅ Cámara *{camara.nombre}* registrada en el sistema. "
            f"Sin incidentes activos.\n_puede continuar con el proceso de aprobación._"
        )

    def _procesar_seguimiento_empalme(
        self,
        texto: str,
        thread_ts_evento: str,
        session: Any,
        client: Any,
        channel: str,
    ) -> bool:
        """Detecta y procesa una respuesta de seguimiento con un ID de empalme, en el hilo de un
        caso `IngresoSinMatch` pendiente (invitado por `_construir_respuesta_camara` cuando no
        matcheó ninguna cámara).

        Devuelve `True` cuando el mensaje fue tratado como intento de seguimiento (el caller debe
        cortar ahí, no seguir al flujo normal) y `False` cuando no aplica: el texto no matchea el
        patrón numérico, o matchea pero no hay un caso `IngresoSinMatch` pendiente para este hilo
        (puede ser cualquier otro mensaje numérico del canal sin relación — no se trata como un
        intento de empalme fallido).
        """
        match = _RE_SEGUIMIENTO_EMPALME.match(texto)
        if not match:
            return False

        from db.models.infra import IngresoSinMatch

        caso = (
            session.query(IngresoSinMatch)
            .filter(
                IngresoSinMatch.thread_ts == thread_ts_evento,
                IngresoSinMatch.resuelto_via_empalme == False,  # noqa: E712
            )
            .order_by(IngresoSinMatch.id.desc())
            .first()
        )
        if caso is None:
            return False

        fusion_n_id = int(match.group(1))
        logger.info(
            "Seguimiento de empalme detectado en hilo %s: fusion_n_id=%s (caso IngresoSinMatch id=%s)",
            thread_ts_evento,
            fusion_n_id,
            caso.id,
        )

        botella = resolver_botella_por_fusion_sync(session, fusion_n_id)
        camara = None
        if botella is not None and botella.camara_id is not None:
            from db.models.infra import Camara

            camara = session.query(Camara).filter(Camara.id == botella.camara_id).one_or_none()

        if camara is not None:
            respuesta = self._evaluar_estado_acceso_camara(camara, session)
        else:
            logger.info(
                "Empalme #%s no resolvió una botella con cámara asociada (caso id=%s)",
                fusion_n_id,
                caso.id,
            )
            respuesta = (
                f"⚠️ No pude ubicar una botella asociada al ID de empalme *{fusion_n_id}*. "
                "*Podés continuar con el ingreso con normalidad.*"
            )

        caso.resuelto_via_empalme = True
        session.commit()

        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts_evento,
            text=respuesta,
            mrkdwn=True,
        )
        return True

    def _handle_message(self, event: dict[str, Any], client: Any) -> None:
        """Procesa un mensaje entrante y responde en el mismo hilo."""
        # Ignorar ediciones para no procesar dos veces el mismo ingreso
        if event.get("subtype") == "message_changed":
            return
        # Los Workflows de Slack envían subtype=bot_message con bot_id propio.
        # IgnoringSelfEvents ya bloquea nuestros propios eventos; aquí procesamos
        # mensajes de cualquier bot externo (incluidos Workflows).

        texto = event.get("text", "")
        event_thread_ts = event.get("thread_ts")
        event_ts = event.get("ts")
        thread_ts = event_thread_ts or event_ts
        channel = event.get("channel", "")

        session = SessionLocal()
        try:
            canal_id, activo, workflow_ids, solo_workflows = self._get_config(session)

            if not activo:
                logger.debug("Listener inactivo, ignorando mensaje en canal %s", channel)
                return

            if canal_id and channel != canal_id:
                logger.debug("Mensaje de canal %s ignorado (esperado: %s)", channel, canal_id)
                return

            # Filtro de Workflow ID: si está activo, solo procesar mensajes de Workflows configurados
            if solo_workflows:
                event_workflow_id = event.get("workflow_id") or ""
                if not event_workflow_id:
                    logger.debug("Mensaje sin workflow_id ignorado (filtro solo_workflows activo)")
                    return
                if workflow_ids and event_workflow_id not in workflow_ids:
                    logger.debug(
                        "workflow_id '%s' no está en la lista permitida — ignorado",
                        event_workflow_id,
                    )
                    return

            logger.info(
                "Mensaje de ingreso recibido — canal=%s ts=%s bot_id=%s",
                channel,
                event.get("ts"),
                event.get("bot_id", "—"),
            )

            # Respuesta de seguimiento con ID de empalme: sólo aplica si el evento es una
            # respuesta REAL dentro de un hilo (thread_ts presente y distinto del ts propio del
            # mensaje raíz) — evita interpretar el primer mensaje de un hilo nuevo como
            # seguimiento. Se evalúa ANTES de extraer_nombre_camara y, si aplica, corta acá.
            if event_thread_ts and event_thread_ts != event_ts:
                if self._procesar_seguimiento_empalme(texto, event_thread_ts, session, client, channel):
                    return

            nombre_raw = extraer_nombre_camara(texto)
            logger.info("Nombre extraído por regex: '%s'", nombre_raw)
            if not nombre_raw:
                logger.info("No se pudo extraer nombre de cámara del mensaje")
                return

            # Exclusión temprana: mensajes de Nodo no corresponden a cámaras.
            # La verificación se hace sobre el nombre extraído (no el texto bruto)
            # para evitar falsos positivos con el label "Nodo/Camara/botella" del Workflow.
            if _RE_NODO.search(nombre_raw):
                logger.info(
                    "Mensaje ignorado: Corresponde a un Nodo ('%s')",
                    nombre_raw,
                )
                return

            # Detectar si el técnico mencionó múltiples botellas en un mismo mensaje
            # (ej: "Botella 1 y 2") y separar en búsquedas independientes.
            nombres_a_buscar = detectar_multi_bot(nombre_raw)
            if nombres_a_buscar is not None:
                logger.info(
                    "Multi-bot detectado en '%s' → búsquedas independientes: %s",
                    nombre_raw,
                    nombres_a_buscar,
                )
            else:
                nombres_a_buscar = [nombre_raw]

            respuestas = [
                self._construir_respuesta_camara(nombre, session, channel=channel, thread_ts=thread_ts)
                for nombre in nombres_a_buscar
            ]

            # Para múltiples cámaras, separar con línea divisoria para mayor claridad
            separador = "\n\n─────────────────────\n\n" if len(respuestas) > 1 else ""
            respuesta = separador.join(respuestas)

            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=respuesta,
                mrkdwn=True,
            )

        except AmbiguousSearchError as exc:
            # Los candidatos ya vienen fusionados (Camara + CromoBotella) y acotados a 3 desde la
            # Tarea 1 (`AmbiguousSearchError.__init__`) — se listan como viñetas de texto plano.
            candidatos_texto = ""
            if exc.candidatos:
                vinetas = "\n".join(f"• {c}" for c in exc.candidatos)
                candidatos_texto = f"\nCandidatos:\n{vinetas}"

            if exc.cantidad == 0:
                aviso = (
                    f":warning: El nombre *'{exc.nombre_raw}'* es demasiado genérico "
                    "para identificar una cámara. Por favor, especificá la dirección "
                    "completa o el número exacto. Recuerdo para accesos a Nodos anteponer la Palabra 'Nodo' (ej: 'Nodo Pilar')."
                    f"{candidatos_texto}\n"
                    "*Podés continuar con el ingreso con normalidad.*"
                )
            else:
                aviso = (
                    f":warning: Tu solicitud *'{exc.nombre_raw}'* es ambigua y coincide "
                    f"con *{exc.cantidad}* cámaras en el sistema. Por favor, especificá "
                    "la dirección o el número exacto."
                    f"{candidatos_texto}\n"
                    "*Podés continuar con el ingreso con normalidad.*"
                )
            logger.info(
                "Búsqueda ambigua para '%s': cantidad=%d candidatos=%s",
                exc.nombre_raw,
                exc.cantidad,
                exc.candidatos,
            )
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=aviso,
                mrkdwn=True,
            )
        except Exception as exc:
            logger.error("Error procesando mensaje de ingreso: %s", exc, exc_info=True)
        finally:
            session.close()

    # ── Comandos de Cables (docs/slack_app_cables.md) ───────────────────────

    def _resolver_cable_o_responder(
        self, session: Any, nombre_cable: str, client: Any, channel: str, thread_ts: str
    ) -> Optional[CromoCable]:
        """Busca el cable por nombre; si no hay exactamente un match, ya responde el aviso
        correspondiente (no encontrado / ambiguo) y devuelve `None` para que el caller corte."""
        cables = buscar_cable_por_nombre(session, nombre_cable)
        if not cables:
            client.chat_postMessage(
                channel=channel, thread_ts=thread_ts, text=construir_respuesta_no_encontrado(nombre_cable), mrkdwn=True
            )
            return None
        if len(cables) > 1:
            client.chat_postMessage(
                channel=channel, thread_ts=thread_ts, text=construir_respuesta_ambiguo(nombre_cable, cables), mrkdwn=True
            )
            return None
        return cables[0]

    def _handle_app_mention(self, event: dict[str, Any], client: Any) -> None:
        """Procesa una mención directa al bot (`@bot <comando>`) — soporta "Info cable <nombre>",
        "Verificar cable <nombre> B<N>" e "Info cable <nombre> B<N>" (docs/slack_app_cables.md).
        Mismo canal/config que el listener de ingresos; no se pisan entre sí porque escuchan eventos
        distintos de Slack (`message` vs `app_mention`).

        El comando CON buffer se intenta primero: `extraer_comando_info_cable` es "goloso" (toma todo
        el resto de la línea como nombre de cable) y matchearía de más si un mensaje con sufijo
        "B<N>" llegara primero acá."""
        texto = _RE_MENTION_PREFIX.sub("", event.get("text", ""))
        thread_ts = event.get("thread_ts") or event.get("ts")
        channel = event.get("channel", "")

        comando_buffer = extraer_comando_cable_buffer(texto)
        if comando_buffer is not None:
            self._handle_cable_buffer(comando_buffer, client, channel, thread_ts)
            return

        nombre_cable = extraer_comando_info_cable(texto)
        if nombre_cable is None:
            logger.debug("Mención sin comando reconocido: '%s'", texto)
            return

        session = SessionLocal()
        try:
            cable = self._resolver_cable_o_responder(session, nombre_cable, client, channel, thread_ts)
            if cable is None:
                return
            respuesta = construir_respuesta_info_cable(cable, session)
            client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=respuesta, mrkdwn=True)
        except Exception as exc:
            logger.error("Error procesando 'Info cable %s': %s", nombre_cable, exc, exc_info=True)
        finally:
            session.close()

    def _handle_cable_buffer(
        self, comando: tuple[str, str, int], client: Any, channel: str, thread_ts: str
    ) -> None:
        """"Verificar cable <nombre> B<N>" / "Info cable <nombre> B<N>" — resuelve cable, resuelve
        buffer por número (1-indexado, ver `cable_info.py`), y arma la respuesta según el verbo."""
        verbo, nombre_cable, numero_buffer = comando
        session = SessionLocal()
        try:
            cable = self._resolver_cable_o_responder(session, nombre_cable, client, channel, thread_ts)
            if cable is None:
                return

            tubo = resolver_tubo_por_numero(session, cable.n_id, numero_buffer)
            if tubo is None:
                total = contar_buffers_cable(session, cable.n_id)
                respuesta = construir_respuesta_buffer_no_encontrado(nombre_cable, numero_buffer, total)
                client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=respuesta, mrkdwn=True)
                return

            if verbo == "verificar":
                resultado = servicios_por_tubo_sync(session, tubo.n_id)
                respuesta = construir_respuesta_verificar_buffer(cable, tubo, resultado)
            else:
                pelos = pelos_de_tubo_sync(session, tubo.n_id)
                respuesta = construir_respuesta_info_buffer(cable, tubo, pelos)

            client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=respuesta, mrkdwn=True)
        except Exception as exc:
            logger.error(
                "Error procesando '%s cable %s B%s': %s", verbo, nombre_cable, numero_buffer, exc, exc_info=True
            )
        finally:
            session.close()

    # ── Ciclo de vida ────────────────────────────────────────────────────

    def start(self) -> None:
        """Arranca el Socket Mode handler en el thread actual (bloqueante).

        Diseñado para ser llamado desde un daemon thread en worker.py.
        """
        try:
            from slack_bolt import App  # type: ignore[import]
            from slack_bolt.adapter.socket_mode import SocketModeHandler  # type: ignore[import]
        except ImportError:
            logger.error("slack_bolt no disponible — listener no iniciado. Instalá slack_bolt>=1.22")
            return

        app = App(token=self._bot_token)

        @app.event("message")
        def on_message(event: dict[str, Any], client: Any) -> None:
            self._handle_message(event, client)

        @app.event("app_mention")
        def on_app_mention(event: dict[str, Any], client: Any) -> None:
            self._handle_app_mention(event, client)

        self._handler = SocketModeHandler(app, self._app_token)
        self._running = True
        logger.info("IngresoListener iniciado en modo Socket (escuchando eventos message + app_mention)")
        try:
            self._handler.start()
        finally:
            self._running = False

    def stop(self) -> None:
        """Detiene el handler si está activo."""
        if self._handler is not None:
            try:
                self._handler.close()
                logger.info("IngresoListener detenido")
            except Exception as exc:
                logger.warning("Error deteniendo listener: %s", exc)
        self._running = False

    def is_running(self) -> bool:
        """Retorna True si el listener está activo."""
        return self._running


# ── Helpers ──────────────────────────────────────────────────────────────


def _obtener_incidentes_activos_camara(camara: Any, session: Any) -> list[Any]:
    """Retorna los incidentes de baneo activos cuando la cámara está en estado BANEADA.

    Las cámaras con estado LIBRE, DETECTADA o PENDIENTE_REVISION se tratan como
    aptas para ingreso: devuelven lista vacía.  Estado BANEADA con un
    ``IncidenteBaneo.activo`` asociado retorna ese incidente (nivel 1 de la
    jerarquía).  BANEADA sin incidente activo es manejado por la rama
    siguiente en ``_construir_respuesta_camara`` (baneo manual, nivel 2).
    """
    try:
        from db.models.infra import CamaraEstado, IncidenteBaneo

        estado = getattr(camara, "estado", None)
        if estado != CamaraEstado.BANEADA:
            return []

        return (
            session.query(IncidenteBaneo)
            .filter(IncidenteBaneo.activo == True)  # noqa: E712
            .order_by(IncidenteBaneo.fecha_inicio.desc())
            .limit(1)
            .all()
        )
    except Exception as exc:
        logger.warning("Error consultando incidentes para cámara %s: %s", getattr(camara, "id", "?"), exc)
        return []
