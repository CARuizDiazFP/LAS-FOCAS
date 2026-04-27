# Nombre de archivo: listener.py
# Ubicación de archivo: modules/slack_baneo_notifier/listener.py
# Descripción: Listener de ingresos técnicos via Slack Bolt (Socket Mode) — responde en hilo con estado de baneo

"""Escucha en tiempo real los formularios de ingreso a cámaras enviados por técnicos
en un canal de Slack.  Cuando llega un mensaje, extrae el nombre de cámara del campo
"Cámara:", normaliza el texto, consulta la DB y responde en el **hilo original**
con uno de los tres estados posibles.

Requiere:
  - SLACK_BOT_TOKEN  (xoxb-...)  — ya existente en .env
  - SLACK_APP_TOKEN  (xapp-...)  — nuevo, para Socket Mode

Se integra en worker.py como un daemon thread independiente.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from db.session import SessionLocal
from modules.slack_baneo_notifier.camara_search import buscar_camara, extraer_nombre_camara

logger = logging.getLogger("slack_baneo_worker.listener")

_NOMBRE_SERVICIO_LISTENER = "slack_ingreso_listener"
_CANAL_ID_DEFAULT = ""  # Se completa desde config_servicios en DB


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

    def _handle_message(self, event: dict[str, Any], client: Any) -> None:
        """Procesa un mensaje entrante y responde en el mismo hilo."""
        # Ignorar ediciones para no procesar dos veces el mismo ingreso
        if event.get("subtype") == "message_changed":
            return
        # Los Workflows de Slack envían subtype=bot_message con bot_id propio.
        # IgnoringSelfEvents ya bloquea nuestros propios eventos; aquí procesamos
        # mensajes de cualquier bot externo (incluidos Workflows).

        texto = event.get("text", "")
        thread_ts = event.get("thread_ts") or event.get("ts")
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

            nombre_raw = extraer_nombre_camara(texto)
            logger.info("Nombre extraído por regex: '%s'", nombre_raw)
            if not nombre_raw:
                logger.info("No se pudo extraer nombre de cámara del mensaje")
                return

            camara, nombre_norm = buscar_camara(nombre_raw, session)
            logger.info("Resultado búsqueda DB — cámara: %s (normalizado: '%s')", camara, nombre_norm)

            if camara is None:
                # Auto-registrar la cámara con estado PENDIENTE_REVISION para que
                # un administrador la revise y apruebe (o la marque como alias).
                from datetime import datetime, timezone
                from db.models.infra import Camara, CamaraEstado, CamaraOrigenDatos

                nueva_camara = Camara(
                    nombre=nombre_raw,
                    estado=CamaraEstado.PENDIENTE_REVISION,
                    origen_datos=CamaraOrigenDatos.MANUAL,
                    last_update=datetime.now(timezone.utc),
                )
                session.add(nueva_camara)
                session.commit()
                respuesta = (
                    "✅ Cámara no registrada previamente, se registra automáticamente "
                    "bajo revisión. Sin incidentes activos. Podés proceder."
                )
                logger.info(
                    "Cámara desconocida '%s' auto-registrada con estado PENDIENTE_REVISION (id=%s)",
                    nombre_raw,
                    nueva_camara.id,
                )
            else:
                incidentes = _obtener_incidentes_activos_camara(camara, session)
                if incidentes:
                    inc = incidentes[0]
                    respuesta = (
                        f"🚨 *ATENCIÓN* — La cámara *{camara.nombre}* tiene el incidente "
                        f"*#{inc.id}* activo (Baneo de Protección).\n"
                        f"Ticket: {inc.ticket_asociado or 'sin ticket'} | "
                        f"Servicio protegido: {inc.servicio_protegido_id}\n"
                        "_No acceder a esta cámara hasta nuevo aviso._"
                    )
                    logger.info("Cámara '%s' BANEADA — incidente #%s", camara.nombre, inc.id)
                else:
                    respuesta = (
                        f"✅ Cámara *{camara.nombre}* registrada en el sistema. "
                        f"Sin incidentes activos.\n_Podés proceder con el ingreso._"
                    )
                    logger.info("Cámara '%s' OK — sin incidentes activos", camara.nombre)

            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=respuesta,
                mrkdwn=True,
            )

        except Exception as exc:
            logger.error("Error procesando mensaje de ingreso: %s", exc, exc_info=True)
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

        self._handler = SocketModeHandler(app, self._app_token)
        self._running = True
        logger.info("IngresoListener iniciado en modo Socket (escuchando eventos message)")
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

    Las cámaras con estado LIBRE o DETECTADA (tracking inicial sin baneo real)
    se tratan como aptas para ingreso: devuelven lista vacía.
    Solo BANEADA implica restricción de acceso.
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
