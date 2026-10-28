# Nombre de archivo: baneo_aviso.py
# Ubicación de archivo: core/services/baneo_aviso.py
# Descripción: Aviso de baneo por email (adjuntos XLS/TXT, envío SMTP y estado de config) compartido por el panel y la API

"""Aviso de baneo por email movido desde `web/app/routers/camaras.py` y `api/app/routes/infra.py`.

`adjuntos_aviso_baneo` arma el XLS (una fila por cámara e incidente) y un TXT de tracking por
incidente; `enviar_aviso_baneo` los junta y manda el correo; `estado_config_email` informa si el SMTP
está configurado. Todo es bloqueante (DB y SMTP): la API lo ejecuta entero en `asyncio.to_thread`.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from core.services.email_service import EmailAttachment, get_email_service
from core.services.protection_service import ProtectionService
from db.models.infra import IncidenteBaneo, Servicio

logger = logging.getLogger(__name__)

# D8: unión de las columnas que armaban el panel (Fontine_ID, Ticket) y el .eml de la API (Servicios, Lat/Long).
COLUMNAS_XLS_BANEO = [
    "ID", "Nombre", "Fontine_ID", "Dirección", "Estado", "Ticket", "Servicios", "Latitud", "Longitud",
]
HOJA_XLS_BANEO = "Baneos_Activos"
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

MENSAJE_SIN_SMTP = "Servicio de email no configurado"
ERROR_SIN_SMTP = "SMTP no está configurado en el servidor"
MENSAJE_SIN_INCIDENTES = "No se encontraron incidentes con los IDs especificados"
ERROR_SIN_INCIDENTES = "incidente_ids vacíos o inválidos"


@dataclass
class EmailNotifyResultado:
    """Resultado del aviso; las claves coinciden con el cuerpo JSON de `notify/email`."""

    success: bool
    message: str
    error: str | None = None
    recipients_count: int = 0


def _servicios_de_camara(camara: Any) -> str:
    """IDs de los servicios que pasan por la cámara (vía empalmes), sin repetir y separados por coma."""
    ids: list[str] = []
    for empalme in getattr(camara, "empalmes", None) or []:
        for servicio in getattr(empalme, "servicios", None) or []:
            sid = getattr(servicio, "servicio_id", None)
            if sid and sid not in ids:
                ids.append(sid)
    return ", ".join(ids)


def _filas_xls(session: Session, incidentes: list[Any]) -> list[dict[str, Any]]:
    """Una fila por cámara afectada de cada incidente, con las columnas de `COLUMNAS_XLS_BANEO`."""
    protection = ProtectionService(session)
    filas: list[dict[str, Any]] = []
    for incidente in incidentes:
        ticket = incidente.ticket_asociado or f"INC-{incidente.id}"
        camaras = protection.get_camaras_for_servicio(
            incidente.servicio_protegido_id, incidente.ruta_protegida_id
        )
        for camara in camaras:
            filas.append({
                "ID": camara.id,
                "Nombre": camara.nombre or "",
                "Fontine_ID": camara.fontine_id or "",
                "Dirección": camara.direccion or "",
                "Estado": camara.estado.value if camara.estado else "-",
                "Ticket": ticket,
                "Servicios": _servicios_de_camara(camara),
                "Latitud": getattr(camara, "latitud", None),
                "Longitud": getattr(camara, "longitud", None),
            })
    return filas


def _adjunto_xls(session: Session, incidentes: list[Any]) -> EmailAttachment | None:
    """XLS `baneos_activos.xlsx` con todas las cámaras; `None` si no hay filas o falta pandas."""
    try:
        import pandas as pd
    except ImportError:
        logger.warning("action=notify_email warning=pandas_not_available skipping_xls=true")
        return None
    filas = _filas_xls(session, incidentes)
    if not filas:
        return None
    salida = io.BytesIO()
    with pd.ExcelWriter(salida, engine="openpyxl") as escritor:
        pd.DataFrame(filas, columns=COLUMNAS_XLS_BANEO).to_excel(
            escritor, sheet_name=HOJA_XLS_BANEO, index=False
        )
    return EmailAttachment(filename="baneos_activos.xlsx", content=salida.getvalue(), mime_type=MIME_XLSX)


def _adjunto_txt(session: Session, incidente: Any) -> EmailAttachment | None:
    """TXT original de tracking del servicio protegido: la ruta protegida si tiene contenido, si no la primera que tenga (D7)."""
    servicio = (
        session.query(Servicio).filter(Servicio.servicio_id == incidente.servicio_protegido_id).first()
    )
    rutas = [r for r in (getattr(servicio, "rutas", None) or []) if r.raw_file_content]
    if not rutas:
        return None
    ruta = next((r for r in rutas if r.id == incidente.ruta_protegida_id), rutas[0])
    return EmailAttachment(
        filename=ruta.nombre_archivo_origen or f"tracking_{servicio.servicio_id}.txt",
        content=ruta.raw_file_content.encode("utf-8"),
        mime_type="text/plain; charset=utf-8",
    )


def adjuntos_aviso_baneo(
    session: Session,
    incidente_ids: list[int],
    *,
    include_xls: bool,
    include_txt: bool,
) -> list[EmailAttachment] | None:
    """Adjuntos del aviso; `None` si ningún id corresponde a un incidente.

    El XLS (si se pide) junta las cámaras de todos los incidentes; el TXT va uno por incidente.
    Se arma todo dentro de la sesión recibida (las cámaras cargan relaciones perezosas).
    """
    incidentes = (
        session.query(IncidenteBaneo).filter(IncidenteBaneo.id.in_(incidente_ids)).all()
        if incidente_ids
        else []
    )
    if not incidentes:
        return None

    adjuntos: list[EmailAttachment] = []
    if include_xls:
        xls = _adjunto_xls(session, incidentes)
        if xls:
            adjuntos.append(xls)
    if include_txt:
        for incidente in incidentes:
            txt = _adjunto_txt(session, incidente)
            if txt:
                adjuntos.append(txt)
    return adjuntos


def estado_config_email() -> dict[str, Any]:
    """Estado de configuración del SMTP; el remitente sólo se expone si está configurado."""
    servicio = get_email_service()
    configurado = servicio.is_configured()
    return {
        "configured": configurado,
        "from_email": servicio.settings.from_email if configurado else None,
        "from_name": servicio.settings.from_name if configurado else None,
    }


def enviar_aviso_baneo(
    session: Session,
    *,
    to: list[str],
    cc: list[str] | None,
    subject: str,
    body: str,
    incidente_ids: list[int],
    include_xls: bool,
    include_txt: bool,
) -> EmailNotifyResultado:
    """Arma los adjuntos y envía el aviso (D6: SMTP sin configurar o sin incidentes → `success=False`)."""
    servicio = get_email_service()
    if not servicio.is_configured():
        return EmailNotifyResultado(False, MENSAJE_SIN_SMTP, ERROR_SIN_SMTP)

    adjuntos = adjuntos_aviso_baneo(
        session, incidente_ids, include_xls=include_xls, include_txt=include_txt
    )
    if adjuntos is None:
        return EmailNotifyResultado(False, MENSAJE_SIN_INCIDENTES, ERROR_SIN_INCIDENTES)

    resultado = servicio.send_email(
        to=to, cc=cc, subject=subject, body=body, attachments=adjuntos or None
    )
    return EmailNotifyResultado(
        success=resultado.success,
        message=resultado.message,
        error=resultado.error,
        recipients_count=len(to) + len(cc or []),
    )
