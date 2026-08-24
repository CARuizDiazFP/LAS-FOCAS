# Nombre de archivo: notifier.py
# Ubicación de archivo: modules/slack_baneo_notifier/notifier.py
# Descripción: Lógica de generación de Excel y envío de reportes de baneos a Slack

from __future__ import annotations

import io
import logging
from datetime import datetime, timezone

import pandas as pd

from core.services.baneos_grupos_service import listar_grupos_baneados
from core.utils.tz import TZ_ARG, ahora_local, fmt_local
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from sqlalchemy.orm import Session

from db.models.infra import Camara

logger = logging.getLogger("slack_baneo_worker.notifier")


def generar_excel_baneadas(session: Session) -> tuple[int, io.BytesIO | None, str]:
    """Consulta grupos de Cámaras baneadas (agrupados por Cámara padre — ver
    `core/services/baneos_grupos_service.py::listar_grupos_baneados`) y genera un Excel en memoria,
    una fila por grupo (no por Botella individual — evita filas redundantes del mismo incidente
    físico).

    Returns:
        Tupla (cantidad_de_grupos, buffer_excel_o_None, nombre_archivo).
        Si no hay grupos baneados, buffer es None.
    """
    resultado = listar_grupos_baneados(session, limit=None, incluir_contexto=False)
    grupos = resultado.grupos

    cantidad = len(grupos)
    ahora = ahora_local()
    nombre_archivo = f"camaras_baneadas_{ahora:%Y%m%d_%H%M}.xlsx"

    if cantidad == 0:
        return cantidad, None, nombre_archivo

    # `GrupoBaneado` no trae latitud/longitud/last_update (el panel interactivo no las necesita) —
    # se completan acá con una query propia y liviana, sólo para las filas del Excel.
    ids = [g.camara_id for g in grupos]
    extra = {c.id: c for c in session.query(Camara).filter(Camara.id.in_(ids)).all()}

    rows = [
        {
            "ID": g.camara_id,
            "Fontine ID": (extra[g.camara_id].fontine_id or "") if g.camara_id in extra else "",
            "Cámara": g.nombre,
            "Dirección": g.direccion or "",
            "Botellas baneadas": g.botellas_count,
            "Botellas": " · ".join(b.nombre for b in g.botellas) if g.botellas else "",
            "Latitud": extra[g.camara_id].latitud if g.camara_id in extra else None,
            "Longitud": extra[g.camara_id].longitud if g.camara_id in extra else None,
            "Último Update": (
                fmt_local(extra[g.camara_id].last_update, "%d/%m/%Y %H:%M")
                if g.camara_id in extra and extra[g.camara_id].last_update
                else ""
            ),
        }
        for g in grupos
    ]

    df = pd.DataFrame(rows)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Cámaras Baneadas", index=False)
    output.seek(0)

    return cantidad, output, nombre_archivo


def enviar_reporte_baneos(
    canales: list[str],
    bot_token: str,
    session: Session,
) -> str | None:
    """Envía reporte de cámaras baneadas a los canales de Slack indicados.

    Returns:
        None si fue exitoso, o string con descripción del error.
    """
    if not bot_token:
        msg = "SLACK_BOT_TOKEN no configurado, omitiendo envío"
        logger.warning(msg)
        return msg

    client = WebClient(token=bot_token)
    cantidad, excel_buf, nombre_archivo = generar_excel_baneadas(session)

    ahora = ahora_local()
    fecha_str = ahora.strftime("%d/%m/%Y %H:%M") + " (GMT-3)"

    if cantidad == 0:
        texto = (
            f"📊 *Reporte de Cámaras Baneadas*\n"
            f"• Total: 0 cámaras baneadas\n"
            f"• Fecha: {fecha_str}\n\n"
            f"_No hay cámaras baneadas actualmente._"
        )
    else:
        texto = (
            f"📊 *Reporte de Cámaras Baneadas*\n"
            f"• Total: *{cantidad}* cámara{'s' if cantidad != 1 else ''}\n"
            f"• Fecha: {fecha_str}"
        )

    errores: list[str] = []

    for canal in canales:
        canal = canal.strip()
        if not canal:
            continue
        try:
            if cantidad == 0 or excel_buf is None:
                client.chat_postMessage(channel=canal, text=texto, mrkdwn=True)
            else:
                excel_buf.seek(0)
                client.files_upload_v2(
                    channel=canal,
                    file=excel_buf,
                    filename=nombre_archivo,
                    title=f"Cámaras Baneadas — {fecha_str}",
                    initial_comment=texto,
                )
            logger.info("Reporte enviado a %s (%d cámaras)", canal, cantidad)
        except SlackApiError as exc:
            error_msg = f"Error enviando a {canal}: {exc.response['error']}"
            logger.error(error_msg)
            errores.append(error_msg)
        except Exception as exc:
            error_msg = f"Error inesperado enviando a {canal}: {exc}"
            logger.error(error_msg, exc_info=True)
            errores.append(error_msg)

    if errores:
        return "; ".join(errores)
    return None
