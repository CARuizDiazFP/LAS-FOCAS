# Nombre de archivo: baneo_aviso.py
# Ubicación de archivo: core/services/baneo_aviso.py
# Descripción: Aviso de baneo por email (adjuntos XLS/TXT, envío SMTP y estado de config) compartido por el panel y la API

"""Aviso de baneo por email movido desde `web/app/routers/camaras.py` y `api/app/routes/infra.py`.

`adjuntos_aviso_baneo` arma el XLS (una fila por cámara e incidente) y un TXT de tracking por
incidente; `enviar_aviso_baneo` los junta y manda el correo; `estado_config_email` informa si el SMTP
está configurado. Todo es bloqueante (DB y SMTP): la API lo ejecuta entero en `asyncio.to_thread`.
"""

from __future__ import annotations

import html
import io
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate
from typing import Any

from sqlalchemy.orm import Session

from core.config import get_settings
from core.services.camaras_consulta import _collect_camara_rutas_info, _collect_camara_servicios_ids
from core.services.email_service import EmailAttachment, get_email_service, parte_mime_adjunto
from core.services.protection_service import ProtectionService
from core.utils.tz import TZ_ARG
from db.models.infra import IncidenteBaneo, Servicio

logger = logging.getLogger(__name__)

# D8 + Ruling 12: unión de las columnas del XLS viejo de notify/email (Incidente ID, Ticket, Servicio
# Afectado/Protegido, cámara, Estado, Fecha Inicio, Motivo) y de las dos del .eml (Fontine_ID, Dirección,
# Servicios, Latitud, Longitud). Una fila por cámara e incidente.
COLUMNAS_XLS_BANEO = [
    "Incidente ID", "Ticket", "Servicio Afectado", "Servicio Protegido", "ID", "Nombre", "Fontine_ID",
    "Dirección", "Estado", "Servicios", "Latitud", "Longitud", "Fecha Inicio", "Motivo",
]
HOJA_XLS_BANEO = "Baneos_Activos"
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

MENSAJE_SIN_SMTP = "Servicio de email no configurado"
ERROR_SIN_SMTP = "SMTP no está configurado en el servidor"
MENSAJE_SIN_INCIDENTES = "No se encontraron incidentes con los IDs especificados"
ERROR_SIN_INCIDENTES = "incidente_ids vacíos o inválidos"


# Plantilla HTML por defecto del aviso (movida tal cual desde el panel); `{{variable}}` se reemplaza al armar.
PLANTILLA_AVISO_BANEO = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .header { background: #2563eb; color: white; padding: 20px; border-radius: 8px 8px 0 0; }
        .content { padding: 20px; background: #f8fafc; border: 1px solid #e2e8f0; }
        .footer { padding: 15px; background: #f1f5f9; border-radius: 0 0 8px 8px; font-size: 12px; color: #64748b; }
        table { width: 100%; border-collapse: collapse; margin: 15px 0; }
        th, td { padding: 10px; text-align: left; border-bottom: 1px solid #e2e8f0; }
        th { background: #f1f5f9; font-weight: 600; }
        .badge { display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 12px; }
        .badge-warning { background: #fef3c7; color: #92400e; }
    </style>
</head>
<body>
    <div class="header">
        <h2>🔒 Notificación de Protocolo de Protección</h2>
    </div>
    <div class="content">
        <p>Se ha activado el Protocolo de Protección en la red de fibra óptica.</p>
        <table>
            <tr><th>Ticket</th><td>{{ticket}}</td></tr>
            <tr><th>Servicio Afectado</th><td>{{servicio_afectado}}</td></tr>
            <tr><th>Servicio Protegido</th><td>{{servicio_protegido}}</td></tr>
            <tr><th>Cámaras Baneadas</th><td>{{total_camaras}}</td></tr>
            <tr><th>Fecha</th><td>{{fecha}}</td></tr>
            <tr><th>Motivo</th><td>{{motivo}}</td></tr>
        </table>
        <p>Se adjunta el detalle de las cámaras afectadas.</p>
    </div>
    <div class="footer">
        <p>Este mensaje fue generado automáticamente por LAS-FOCAS - Metrotel</p>
    </div>
</body>
</html>
"""


@dataclass
class EmailNotifyResultado:
    """Resultado del aviso; las claves coinciden con el cuerpo JSON de `notify/email`."""

    success: bool
    message: str
    error: str | None = None
    recipients_count: int = 0


def _servicios_de_camara(camara: Any) -> str:
    """IDs de los servicios de la cámara (rutas con fallback legacy, D1), separados por coma."""
    return ", ".join(_collect_camara_servicios_ids(camara, _collect_camara_rutas_info(camara)))


def _filas_xls(session: Session, incidentes: list[Any]) -> list[dict[str, Any]]:
    """Una fila por cámara afectada de cada incidente, con las columnas de `COLUMNAS_XLS_BANEO`."""
    protection = ProtectionService(session)
    filas: list[dict[str, Any]] = []
    for incidente in incidentes:
        ticket = incidente.ticket_asociado or f"INC-{incidente.id}"
        inicio = getattr(incidente, "fecha_inicio", None)
        fecha_inicio = inicio.astimezone(TZ_ARG).strftime("%d/%m/%Y %H:%M") if inicio else ""
        camaras = protection.get_camaras_for_servicio(
            incidente.servicio_protegido_id, incidente.ruta_protegida_id
        )
        for camara in camaras:
            filas.append({
                "Incidente ID": incidente.id,
                "Ticket": ticket,
                "Servicio Afectado": getattr(incidente, "servicio_afectado_id", None) or "",
                "Servicio Protegido": incidente.servicio_protegido_id or "",
                "ID": camara.id,
                "Nombre": camara.nombre or "",
                "Fontine_ID": camara.fontine_id or "",
                "Dirección": camara.direccion or "",
                "Estado": camara.estado.value if camara.estado else "-",
                "Servicios": _servicios_de_camara(camara),
                "Latitud": getattr(camara, "latitud", None),
                "Longitud": getattr(camara, "longitud", None),
                "Fecha Inicio": fecha_inicio,
                "Motivo": getattr(incidente, "motivo", None) or "",
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


@dataclass
class EmlBaneo:
    """`.eml` armado del aviso, con el asunto y el cuerpo finales (ya reemplazadas las variables)."""

    contenido: bytes
    nombre_archivo: str
    subject: str
    html_body: str


def parsear_destinatarios(raw: str | None) -> list[str]:
    """Separa por coma, punto y coma o espacios y se queda sólo con los que tienen `@`."""
    return [r for r in re.split(r"[,;\s]+", (raw or "").strip()) if r and "@" in r]


def _variables_plantilla(incidente: Any, total_camaras: int) -> dict[str, str]:
    """Valores de `{{…}}` ya escapados para HTML (ticket, motivo, etc. vienen de datos cargados por usuarios)."""
    fecha = getattr(incidente, "fecha_inicio", None)
    valores = {
        "ticket": incidente.ticket_asociado or f"INC-{incidente.id}",
        "servicio_afectado": getattr(incidente, "servicio_afectado_id", None) or "-",
        "servicio_protegido": incidente.servicio_protegido_id or "-",
        "total_camaras": total_camaras,
        "fecha": fecha.astimezone(TZ_ARG).strftime("%d/%m/%Y %H:%M") if fecha else "-",
        "motivo": getattr(incidente, "motivo", None) or "Sin especificar",
    }
    return {clave: html.escape(str(valor)) for clave, valor in valores.items()}


def armar_eml_baneo(
    session: Session,
    incidente_id: int,
    *,
    destinatarios: list[str],
    subject: str | None,
    html_body: str | None,
    include_xls: bool = True,
    include_txt: bool = True,
) -> EmlBaneo | None:
    """Arma el `.eml` del aviso de baneo; `None` si el incidente no existe (D7, D8, D9, B6, B7).

    Cuerpo vacío → `PLANTILLA_AVISO_BANEO`. Asunto vacío → `AVISO DE BANEO - Ticket {ticket o id}`.
    Todo se arma dentro de la sesión recibida: los adjuntos cargan relaciones perezosas (B7).
    """
    incidente = session.query(IncidenteBaneo).filter(IncidenteBaneo.id == incidente_id).first()
    if incidente is None:
        return None

    camaras = ProtectionService(session).get_camaras_for_servicio(
        incidente.servicio_protegido_id, incidente.ruta_protegida_id
    )
    cuerpo = (html_body or "").strip() or PLANTILLA_AVISO_BANEO
    for clave, valor in _variables_plantilla(incidente, len(camaras)).items():
        cuerpo = cuerpo.replace(f"{{{{{clave}}}}}", valor)
    asunto = subject or f"AVISO DE BANEO - Ticket {incidente.ticket_asociado or incidente.id}"

    settings = get_settings().smtp
    msg = MIMEMultipart("mixed")
    msg["From"] = formataddr(
        (settings.from_name or "LAS-FOCAS", settings.from_email or "notificaciones@lasfocas.local")
    )
    if destinatarios:
        msg["To"] = ", ".join(destinatarios)
    msg["Subject"] = asunto
    msg["Date"] = formatdate(localtime=True)
    msg["X-Mailer"] = "LAS-FOCAS Notification System"
    msg["X-Unsent"] = "1"  # D9: Outlook lo abre como borrador editable
    msg.attach(MIMEText(cuerpo, "html", "utf-8"))
    for adjunto in adjuntos_aviso_baneo(
        session, [incidente_id], include_xls=include_xls, include_txt=include_txt
    ) or []:
        msg.attach(parte_mime_adjunto(adjunto))

    ticket_seguro = re.sub(r"[^A-Za-z0-9_\-]", "_", incidente.ticket_asociado or f"INC_{incidente.id}")
    marca = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return EmlBaneo(
        contenido=msg.as_bytes(),
        nombre_archivo=f"notificacion_{ticket_seguro}_{marca}.eml",
        subject=asunto,
        html_body=cuerpo,
    )


def detalle_incidente_baneo(session: Session, incidente_id: int) -> dict[str, Any] | None:
    """Detalle del incidente con la plantilla guardada del aviso (asunto y cuerpo) y el conteo de cámaras.

    `None` si el incidente no existe. Lo sirven `GET /api/infra/ban/{id}` de la API y del panel (P24).
    """
    service = ProtectionService(session)
    incidente = service.get_incidente_by_id(incidente_id)
    if incidente is None:
        return None
    camaras = service.get_camaras_for_servicio(incidente.servicio_protegido_id, incidente.ruta_protegida_id)
    return {
        "id": incidente.id,
        "ticket": incidente.ticket_asociado,
        "servicio_afectado": incidente.servicio_afectado_id,
        "servicio_protegido": incidente.servicio_protegido_id,
        "email_subject": incidente.email_subject,
        "email_body": incidente.email_body,
        "cantidad_camaras": len(camaras),
    }


def guardar_plantilla_aviso(
    session: Session, incidente_id: int, subject: str | None, html_body: str | None
) -> None:
    """Persiste en el incidente el asunto y el cuerpo editados (sólo la API; un `None` no toca esa columna)."""
    incidente = session.query(IncidenteBaneo).filter(IncidenteBaneo.id == incidente_id).first()
    if incidente is None:
        return
    if subject is not None:
        incidente.email_subject = subject
    if html_body is not None:
        incidente.email_body = html_body
    session.commit()
