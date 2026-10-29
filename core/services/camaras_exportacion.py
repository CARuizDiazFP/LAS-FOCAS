# Nombre de archivo: camaras_exportacion.py
# Ubicación de archivo: core/services/camaras_exportacion.py
# Descripción: Exportación de Cámaras: armado de filas y serialización a CSV y XLSX

"""Exportación de Cámaras movida desde `web/app/routers/camaras.py`.

`filas_exportacion` arma las filas (mismas claves y orden de columnas que siempre), `a_csv` las
serializa con BOM UTF-8 y `a_xlsx` con pandas/openpyxl (devuelve None si no están disponibles).
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from sqlalchemy.orm import Session, selectinload

from db.models.infra import Camara, CamaraEstado, Empalme, IncidenteBaneo, RutaServicio, Servicio

HOJA_XLSX = "Cámaras"
AVISO_SIN_XLSX = "XLSX no disponible, exportando como CSV"


def nombre_archivo_exportacion(ext: str) -> str:
    """Nombre del archivo descargable: `camaras_<UTC %Y%m%d_%H%M%S>.<ext>`."""
    return f"camaras_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.{ext}"


def _filtrar_por_estado(query, filter_status: str | None):
    """Aplica el filtro de estado; un valor desconocido o ALL no filtra."""
    if filter_status and filter_status.upper() != "ALL":
        estado_upper = filter_status.upper()
        if estado_upper in [e.value for e in CamaraEstado]:
            return query.filter(Camara.estado == CamaraEstado(estado_upper))
    return query


def _camara_ids_de_servicio(servicio: Servicio) -> set[int]:
    ids: set[int] = set()
    for ruta in servicio.rutas_activas:
        for empalme in ruta.empalmes:
            if empalme.camara:
                ids.add(empalme.camara.id)
    return ids


def _filtrar_por_servicio(session: Session, query, servicio_id: str | None):
    """Restringe a las cámaras del servicio; un servicio sin cámaras deja la query vacía."""
    if not servicio_id:
        return query
    # Rutas -> empalmes -> cámara por lote; el resultado es un set de ids, el orden no importa.
    servicio = (
        session.query(Servicio)
        .filter(Servicio.servicio_id == servicio_id)
        .options(
            selectinload(Servicio.rutas)
            .selectinload(RutaServicio.empalmes)
            .selectinload(Empalme.camara)
        )
        .first()
    )
    if not servicio:
        return query
    camara_ids = _camara_ids_de_servicio(servicio)
    if camara_ids:
        return query.filter(Camara.id.in_(camara_ids))
    return query.filter(Camara.id == -1)


def _tickets_por_servicio(session: Session) -> dict:
    tickets: dict = {}
    for baneo in session.query(IncidenteBaneo).filter(IncidenteBaneo.activo == True).all():  # noqa: E712
        tickets[baneo.servicio_protegido_id] = baneo.ticket_asociado or f"INC-{baneo.id}"
    return tickets


def _servicios_de_camara(camara: Camara) -> list[str]:
    """Servicios de las rutas de los empalmes propios, en el orden de los empalmes y sin repetir."""
    servicios: list[str] = []
    for empalme in camara.empalmes:
        for ruta in empalme.rutas:
            srv = ruta.servicio
            if srv.servicio_id and srv.servicio_id not in servicios:
                servicios.append(srv.servicio_id)
    return servicios


def _ticket_de_baneo(camara: Camara, servicios: list[str], tickets: dict) -> str:
    if camara.estado == CamaraEstado.BANEADA:
        for svc_id in servicios:
            if svc_id in tickets:
                return tickets[svc_id]
    return ""


def _fila(camara: Camara, tickets: dict) -> dict[str, object]:
    servicios = _servicios_de_camara(camara)
    return {
        "ID": camara.id,
        "Nombre": camara.nombre or "",
        "Fontine_ID": camara.fontine_id or "",
        "Dirección": camara.direccion or "",
        "Estado": camara.estado.value if camara.estado else "LIBRE",
        "Servicios_Cat6": ", ".join(servicios),
        "Ticket_Baneo": _ticket_de_baneo(camara, servicios, tickets),
        "Latitud": camara.latitud or "",
        "Longitud": camara.longitud or "",
        "Origen_Datos": camara.origen_datos.value if camara.origen_datos else "MANUAL",
    }


def filas_exportacion(
    session: Session, *, filter_status: str | None, servicio_id: str | None
) -> list[dict[str, object]]:
    """Filas de la exportación, ordenadas por nombre, con filtros opcionales de estado y servicio."""
    # Empalmes, sus rutas y el servicio de cada ruta por lote (`selectinload`), no una query lazy por
    # cámara y por empalme.
    query = session.query(Camara).options(
        selectinload(Camara.empalmes).selectinload(Empalme.rutas).selectinload(RutaServicio.servicio)
    )
    query = _filtrar_por_estado(query, filter_status)
    query = _filtrar_por_servicio(session, query, servicio_id)
    camaras = query.order_by(Camara.nombre).all()
    tickets = _tickets_por_servicio(session)
    return [_fila(camara, tickets) for camara in camaras]


def a_csv(filas: list[dict]) -> bytes:
    """CSV en UTF-8 con BOM; sin filas escribe `Sin datos` con salto de línea real."""
    salida = io.StringIO()
    if filas:
        escritor = csv.DictWriter(salida, fieldnames=filas[0].keys())
        escritor.writeheader()
        escritor.writerows(filas)
    else:
        salida.write("Sin datos\n")
    return salida.getvalue().encode("utf-8-sig")


def a_xlsx(filas: list[dict]) -> bytes | None:
    """XLSX de una hoja `Cámaras`; None si pandas/openpyxl no están disponibles."""
    try:
        import pandas as pd

        df = pd.DataFrame(filas)
        salida = io.BytesIO()
        with pd.ExcelWriter(salida, engine="openpyxl") as escritor:
            df.to_excel(escritor, sheet_name=HOJA_XLSX, index=False)
        salida.seek(0)
        return salida.getvalue()
    except ImportError:
        return None
