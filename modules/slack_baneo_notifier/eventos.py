# Nombre de archivo: eventos.py
# Ubicación de archivo: modules/slack_baneo_notifier/eventos.py
# Descripción: Notificaciones de eventos puntuales de baneo/desbaneo a Slack, disparadas desde los endpoints de Infra

"""Envío inmediato de avisos a Slack cuando se crea o levanta un baneo desde Infra.

A diferencia del reporte periódico (worker.py), estas notificaciones son
texto corto que describen el *evento* concreto ocurrido.  Se leen los
canales y el estado del servicio desde ``app.config_servicios``.
Se diseñó sin dependencias de APScheduler para poder ser importado desde el
contenedor de la API (sin el worker en ejecución).
"""

from __future__ import annotations

import logging
from typing import Any

from core.utils.tz import ahora_fmt

from sqlalchemy.orm import Session

logger = logging.getLogger("slack_baneo_worker.eventos")

_NOMBRE_SERVICIO = "slack_baneo_notifier"


def _leer_canales_y_estado(session: Session) -> tuple[list[str], bool]:
    """Lee canales y flag *activo* de app.config_servicios.

    Returns:
        (canales, activo) — canales puede ser lista vacía si no hay config.
    """
    try:
        from db.models.servicios import ConfigServicios
        row = (
            session.query(ConfigServicios.slack_channels, ConfigServicios.activo)
            .filter(ConfigServicios.nombre_servicio == _NOMBRE_SERVICIO)
            .one_or_none()
        )
        if row is None:
            return [], False
        canales = [c.strip() for c in (row[0] or "").split(",") if c.strip()]
        return canales, bool(row[1])
    except Exception as exc:
        logger.warning("No se pudo leer canales de config_servicios: %s", exc)
        return [], False


def notificar_evento_baneo(
    session: Session,
    tipo: str,
    datos: dict[str, Any],
    bot_token: str,
) -> None:
    """Envía un aviso puntual a los canales Slack configurados.

    Se llama **tras** el commit de la operación;  los errores de Slack se
    registran en el log pero no propagan excepción (no debe interrumpir la
    respuesta a Infra).

    Args:
        session:   Sesión SQLAlchemy *ya commiteada* (solo lectura de config).
        tipo:      ``"create"`` o ``"lift"``.
        datos:     Campos del BanResult / LiftResult (``to_dict()``).
        bot_token: Token del bot de Slack (de ``get_settings().slack.bot_token``).
    """
    if not bot_token:
        logger.debug("SLACK_BOT_TOKEN no configurado, omitiendo notificación de evento")
        return

    canales, activo = _leer_canales_y_estado(session)
    if not activo:
        logger.debug("Servicio slack_baneo_notifier inactivo, omitiendo notificación de evento")
        return
    if not canales:
        logger.debug("Sin canales configurados, omitiendo notificación de evento")
        return

    texto = _armar_mensaje(tipo, datos)
    _enviar(canales, bot_token, texto)

    # Reenviar reporte actualizado de cámaras baneadas tras cada evento
    try:
        from modules.slack_baneo_notifier.notifier import enviar_reporte_baneos
        error = enviar_reporte_baneos(canales, bot_token, session)
        if error:
            logger.warning("Error enviando reporte actualizado tras evento '%s': %s", tipo, error)
        else:
            logger.info("Reporte actualizado de cámaras baneadas enviado tras evento '%s'", tipo)
    except Exception as exc:
        logger.error("Error inesperado al enviar reporte tras evento '%s': %s", tipo, exc)


def _armar_mensaje(tipo: str, datos: dict[str, Any]) -> str:
    """Construye el texto del mensaje según el tipo de evento."""
    ahora = ahora_fmt()

    if tipo == "create":
        incidente_id = datos.get("incidente_id", "?")
        camaras = datos.get("camaras_baneadas", 0)
        servicio_afectado = datos.get("servicio_afectado_id", "?")
        servicio_protegido = datos.get("servicio_protegido_id", "?")
        ticket = datos.get("ticket_asociado") or "sin ticket"
        usuario = datos.get("usuario_ejecutor") or "sistema"
        motivo = datos.get("motivo") or "no especificado"
        return (
            f"🚨 *Nuevo Baneo Activo*\n"
            f"• Incidente: *#{incidente_id}*\n"
            f"• Servicio afectado: `{servicio_afectado}`  →  Servicio protegido: `{servicio_protegido}`\n"
            f"• Ticket: {ticket}\n"
            f"• Cámaras baneadas: *{camaras}*\n"
            f"• Ejecutado por: {usuario}\n"
            f"• Motivo: {motivo}\n"
            f"• Fecha: {ahora}"
        )
    elif tipo == "lift":
        incidente_id = datos.get("incidente_id", "?")
        camaras_rest = datos.get("camaras_restauradas", 0)
        camaras_mant = datos.get("camaras_mantenidas_baneadas", 0)
        usuario = datos.get("usuario_ejecutor") or "sistema"
        motivo = datos.get("motivo_cierre") or "no especificado"
        return (
            f"✅ *Baneo Levantado*\n"
            f"• Incidente: *#{incidente_id}*\n"
            f"• Cámaras restauradas: *{camaras_rest}*"
            + (f"  |  Siguen baneadas (otro incidente): {camaras_mant}" if camaras_mant else "")
            + f"\n"
            f"• Ejecutado por: {usuario}\n"
            f"• Motivo: {motivo}\n"
            f"• Fecha: {ahora}"
        )
    else:
        return f"ℹ️ *Evento de baneo — tipo {tipo}*\n{ahora}"


def _enviar(canales: list[str], bot_token: str, texto: str) -> None:
    """Envía texto a cada canal; registra errores en log, no propaga."""
    try:
        from slack_sdk import WebClient
        from slack_sdk.errors import SlackApiError
    except ImportError:
        logger.error("slack_sdk no disponible en este entorno; no se pudo enviar aviso de evento")
        return

    client = WebClient(token=bot_token)
    for canal in canales:
        try:
            client.chat_postMessage(channel=canal, text=texto, mrkdwn=True)
            logger.info("Aviso de evento enviado a %s", canal)
        except SlackApiError as exc:
            logger.error("Error enviando aviso de evento a %s: %s", canal, exc.response.get("error", exc))
        except Exception as exc:
            logger.error("Error inesperado enviando aviso de evento a %s: %s", canal, exc)
