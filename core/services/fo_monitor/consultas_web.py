# Nombre de archivo: consultas_web.py
# Ubicación de archivo: core/services/fo_monitor/consultas_web.py
# Descripción: Lecturas y mutaciones de FO Monitor para la API web (intervenciones, GeoJSON del mapa, reconocimientos, config)

"""Funciones síncronas (Session) que usa `web/fo_monitor_routes.py`. Devuelven estructuras JSON-
serializables; la ruta sólo valida auth/CSRF y traduce errores. Testeables contra Postgres real.

Color resumen de una intervención: el "peor" de sus cables según urgencia operativa —
AMARILLO (caída nueva) > ROJO > NARANJA > GRIS > VERDE.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session

from core.services.fo_monitor.estado import EstadoCable, Medicion, estado_intervencion
from db.models.cromo import CromoBotella
from db.models.fo_monitor import (
    FomonConfig,
    FomonConfigAuditoria,
    FomonConsulta,
    FomonIntervencion,
    FomonIntervencionServicio,
    FomonReconocimiento,
)
from db.models.infra import Camara
from db.models.servicios import ConfigServicios

URGENCIA = {"AMARILLO": 0, "ROJO": 1, "NARANJA": 2, "GRIS": 3, "VERDE": 4}
ESTADOS_ACTIVOS = ("PRE_PENDIENTE", "PRE_EN_CURSO", "EN_CURSO", "POST_PENDIENTE", "POST_EN_CURSO", "SIN_EGRESO")
LIMITE_MAXIMO = 200


class NoEncontrado(LookupError):
    pass


def _iso(valor: Optional[datetime]) -> Optional[str]:
    return valor.isoformat() if valor else None


def _peor(cables: list[EstadoCable]) -> Optional[str]:
    """Los cables sin servicios verificables (GRIS "sin_verificables") no tiñen el resumen: casi toda
    cámara tiene alguno (bajadas, cables proyectados) y taparían el verde real del resto."""
    con_datos = [c for c in cables if c.semaforo.motivo != "sin_verificables"] or cables
    return min((c.semaforo.color for c in con_datos), key=lambda c: URGENCIA[c], default=None)


def _medicion(m: Optional[Medicion]) -> Optional[dict]:
    if m is None:
        return None
    return {"estado": m.estado, "medido_at": _iso(m.medido_at), "extremo": m.extremo, "motivo": m.motivo}


def _cable_json(c: EstadoCable) -> dict:
    s = c.semaforo
    return {
        "cable_n_id": c.cable_n_id, "nombre": c.nombre, "clase": c.clase, "botella_n_id": c.botella_n_id,
        "es_objetivo": c.es_objetivo, "color": s.color, "motivo": s.motivo, "fase": s.fase,
        "evaluables": s.evaluables, "conocidos": s.conocidos, "up": s.up, "down": s.down,
        "cobertura": s.cobertura, "caidas_nuevas": s.caidas_nuevas, "recuperaciones": s.recuperaciones,
        "servicios": [
            {
                "servicio_pk": x.servicio_pk, "servicio_id": x.servicio_id_externo, "tipo": x.tipo_servicio,
                "categoria": x.categoria, "cliente": x.cliente, "reconocido": x.reconocido,
                "pre": _medicion(x.pre), "post": _medicion(x.post),
            }
            for x in c.servicios
        ],
    }


def _resumen_intervencion(session: Session, i: FomonIntervencion, cables: list[EstadoCable]) -> dict:
    camara = session.get(Camara, i.camara_id) if i.camara_id else None
    botella = session.get(CromoBotella, i.botella_objetivo_n_id) if i.botella_objetivo_n_id else None
    return {
        "id": i.id, "origen": i.origen, "estado": i.estado,
        "camara_id": i.camara_id, "camara": camara.nombre if camara else None,
        "botella_objetivo_n_id": i.botella_objetivo_n_id, "botella_objetivo": botella.nombre if botella else None,
        "botella_1_inferida": i.botella_1_inferida, "cable_n_id_manual": i.cable_n_id_manual,
        "tecnico": i.tecnico, "iniciada_por": i.iniciada_por,
        "fecha_ingreso": _iso(i.fecha_ingreso), "fecha_egreso": _iso(i.fecha_egreso),
        "creada_at": _iso(i.creada_at), "cerrada_at": _iso(i.cerrada_at),
        "sin_linea_base": i.sin_linea_base, "post_tardio": i.post_tardio, "egreso_inferido": i.egreso_inferido,
        "atribucion_compartida": i.atribucion_compartida,
        "color": _peor(cables), "cables": len(cables),
        "servicios": len({x.servicio_pk for c in cables for x in c.servicios}),
        "caidas_nuevas": len({pk for c in cables for pk in c.semaforo.caidas_nuevas}),
    }


def listar_intervenciones(
    session: Session, *, estado: Optional[str] = None, desde: Optional[datetime] = None,
    hasta: Optional[datetime] = None, tecnico: Optional[str] = None, cable: Optional[str] = None,
    limit: int = 50, offset: int = 0,
) -> dict:
    limit = max(1, min(limit, LIMITE_MAXIMO))
    offset = max(0, offset)
    q = session.query(FomonIntervencion)
    if estado == "ACTIVAS":
        q = q.filter(FomonIntervencion.estado.in_(ESTADOS_ACTIVOS))
    elif estado:
        q = q.filter(FomonIntervencion.estado == estado)
    if desde:
        q = q.filter(FomonIntervencion.creada_at >= desde)
    if hasta:
        q = q.filter(FomonIntervencion.creada_at < hasta)
    if tecnico:
        q = q.filter(or_(FomonIntervencion.tecnico.ilike(f"%{tecnico}%"), FomonIntervencion.iniciada_por.ilike(f"%{tecnico}%")))
    if cable:
        sub = session.query(FomonIntervencionServicio.intervencion_id).filter(
            FomonIntervencionServicio.cable_nombre.ilike(f"%{cable}%")
            if not cable.isdigit() else FomonIntervencionServicio.cable_n_id == int(cable)
        )
        q = q.filter(FomonIntervencion.id.in_(sub))
    total = q.count()
    filas = q.order_by(FomonIntervencion.id.desc()).offset(offset).limit(limit).all()
    return {
        "total": total, "limit": limit, "offset": offset,
        "items": [_resumen_intervencion(session, i, estado_intervencion(session, i)) for i in filas],
    }


def detalle_intervencion(session: Session, intervencion_id: int) -> dict:
    i = session.get(FomonIntervencion, intervencion_id)
    if i is None:
        raise NoEncontrado(f"intervención {intervencion_id}")
    cables = estado_intervencion(session, i)
    consultas = (
        session.query(FomonConsulta).filter(FomonConsulta.intervencion_id == i.id).order_by(FomonConsulta.id).all()
    )
    reconocimientos = (
        session.query(FomonReconocimiento).filter(FomonReconocimiento.intervencion_id == i.id)
        .order_by(FomonReconocimiento.id).all()
    )
    return {
        **_resumen_intervencion(session, i, cables),
        "cables_detalle": [_cable_json(c) for c in cables],
        "consultas": [
            {
                "id": c.id, "fase": c.fase, "intento": c.intento, "estado": c.estado,
                "ids": list(c.ids_solicitados), "permalink": c.permalink, "ref": c.ref_burrito,
                "completa": c.completa, "enviada_at": _iso(c.enviada_at), "respondida_at": _iso(c.respondida_at),
                "error": c.error,
            }
            for c in consultas
        ],
        "reconocimientos": [
            {"id": r.id, "servicio_pk": r.servicio_pk, "usuario": r.usuario, "motivo": r.motivo,
             "created_at": _iso(r.created_at)}
            for r in reconocimientos
        ],
    }


# --------------------------------------------------------------------------------------------------
# Mapa
# --------------------------------------------------------------------------------------------------


def _parse_bbox(bbox: Optional[str]) -> Optional[tuple[float, float, float, float]]:
    if not bbox:
        return None
    try:
        min_lon, min_lat, max_lon, max_lat = (float(v) for v in bbox.split(","))
    except ValueError as exc:
        raise ValueError("bbox debe ser min_lon,min_lat,max_lon,max_lat") from exc
    if min_lon > max_lon or min_lat > max_lat:
        raise ValueError("bbox invertido")
    return min_lon, min_lat, max_lon, max_lat


def _coords(session: Session, cable_ids: list[int]) -> dict[int, list]:
    if not cable_ids:
        return {}
    filas = session.execute(
        text("SELECT cable_n_id, coords FROM app.fomon_cable_geo WHERE cable_n_id = ANY(:ids ::bigint[])"),
        {"ids": cable_ids},
    ).all()
    return {int(f.cable_n_id): f.coords for f in filas}


def geojson_intervenciones(session: Session, *, horas: int = 24, ahora: Optional[datetime] = None) -> dict:
    """Cables de intervenciones activas o cerradas en las últimas `horas`. Si un cable aparece en
    varias, gana la intervención más reciente."""
    ahora = ahora or datetime.now(timezone.utc)
    desde = ahora - timedelta(hours=max(1, min(horas, 24 * 30)))
    intervenciones = (
        session.query(FomonIntervencion)
        .filter(or_(FomonIntervencion.estado.in_(ESTADOS_ACTIVOS), FomonIntervencion.creada_at >= desde))
        .order_by(FomonIntervencion.id.desc())
        .limit(LIMITE_MAXIMO)
        .all()
    )
    por_cable: dict[int, tuple[FomonIntervencion, EstadoCable]] = {}
    for i in intervenciones:
        for c in estado_intervencion(session, i):
            por_cable.setdefault(c.cable_n_id, (i, c))
    coords = _coords(session, list(por_cable))
    features = []
    for cable_n_id, (i, c) in por_cable.items():
        if cable_n_id not in coords:
            continue
        s = c.semaforo
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords[cable_n_id]},
            "properties": {
                "cable_n_id": cable_n_id, "nombre": c.nombre, "color": s.color, "intervencion_id": i.id,
                "estado_intervencion": i.estado, "es_objetivo": c.es_objetivo, "up": s.up,
                "evaluables": s.evaluables, "caidas_nuevas": len(s.caidas_nuevas),
            },
        })
    return {"type": "FeatureCollection", "features": features}


def huella_red(session: Session) -> str:
    fila = session.execute(text("SELECT count(*), max(actualizado_at) FROM app.fomon_cable_geo")).one()
    return f"{fila[0]}-{fila[1].timestamp() if fila[1] else 0:.0f}"


def geojson_red(session: Session) -> str:
    """Red completa (todos los cables con geometría), ya serializada: el endpoint la cachea por huella."""
    filas = session.execute(
        text(
            """
            SELECT g.cable_n_id, g.coords::text AS coords, c.nombre, c.clase
            FROM app.fomon_cable_geo g JOIN app.cromo_cables c ON c.n_id = g.cable_n_id
            """
        )
    ).all()
    partes = [
        '{"type":"Feature","geometry":{"type":"LineString","coordinates":%s},"properties":{"id":%d,"n":%s,"c":%d}}'
        % (f.coords, f.cable_n_id, json.dumps(f.nombre or ""), f.clase or 0)
        for f in filas
    ]
    return '{"type":"FeatureCollection","features":[' + ",".join(partes) + "]}"


TIPOS_BUSQUEDA = ("servicio", "cable", "camara")
LIMITE_BUSQUEDA = 300

_SQL_BUSCAR_SERVICIO = text(
    """
    WITH s AS (
        SELECT id FROM app.servicios
        WHERE servicio_id = CAST(:q AS varchar) OR numero_primer_servicio = CAST(:q AS varchar)
           OR CAST(:q AS varchar) = ANY(alias_ids)
    )
    SELECT DISTINCT c.n_id, c.nombre, c.clase
    FROM app.cromo_servicio_match m
    JOIN app.cromo_pelos p ON p.n_id = m.pelo_n_id AND p.vigente
    JOIN app.cromo_cables c ON c.n_id = p.cable_n_id AND c.vigente
    WHERE m.servicio_id IN (SELECT id FROM s)
    LIMIT :limite
    """
)
_SQL_BUSCAR_CABLE = text(
    """
    SELECT c.n_id, c.nombre, c.clase
    FROM app.cromo_cables c
    WHERE c.vigente AND (c.nombre ILIKE :patron OR c.n_id = :nid)
    ORDER BY (c.nombre ILIKE :exacto) DESC, c.nombre
    LIMIT :limite
    """
)
_SQL_BUSCAR_CAMARA = text(
    """
    WITH cam AS (
        SELECT id FROM app.camaras WHERE nombre ILIKE :patron OR id = :nid ORDER BY nombre LIMIT 5
    ), bot AS (
        SELECT b.n_id FROM app.cromo_botellas b WHERE b.vigente AND b.camara_id IN (SELECT id FROM cam)
    )
    SELECT DISTINCT c.n_id, c.nombre, c.clase
    FROM app.cromo_cables c
    WHERE c.vigente AND (c.extremo_a_n_id IN (SELECT n_id FROM bot) OR c.extremo_b_n_id IN (SELECT n_id FROM bot))
    LIMIT :limite
    """
)


def buscar_en_mapa(session: Session, *, tipo: str, q: str) -> dict:
    """Cables (con geometría) que coinciden con un servicio, un nombre de cable o una cámara: es la
    forma de cargar el mapa sin bajar la red completa (~8 MB). Devuelve GeoJSON + metadatos."""
    tipo = (tipo or "").lower()
    q = (q or "").strip()
    if tipo not in TIPOS_BUSQUEDA:
        raise ValueError(f"tipo debe ser uno de {', '.join(TIPOS_BUSQUEDA)}")
    if len(q) < 2:
        raise ValueError("ingresá al menos 2 caracteres")
    nid = int(q) if q.isdigit() else -1
    params = {"limite": LIMITE_BUSQUEDA + 1, "patron": f"%{q}%", "exacto": q, "nid": nid, "q": q}
    sql = {"servicio": _SQL_BUSCAR_SERVICIO, "cable": _SQL_BUSCAR_CABLE, "camara": _SQL_BUSCAR_CAMARA}[tipo]
    filas = session.execute(sql, params).all()
    truncado = len(filas) > LIMITE_BUSQUEDA
    filas = filas[:LIMITE_BUSQUEDA]
    coords = _coords(session, [int(f.n_id) for f in filas])
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords[int(f.n_id)]},
            "properties": {"cable_n_id": int(f.n_id), "nombre": f.nombre, "clase": f.clase},
        }
        for f in filas
        if int(f.n_id) in coords
    ]
    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {"tipo": tipo, "q": q, "encontrados": len(filas), "con_geometria": len(features), "truncado": truncado},
    }


def geojson_botellas(session: Session, *, bbox: Optional[str], limit: int = 5000) -> dict:
    caja = _parse_bbox(bbox)
    q = session.query(CromoBotella.n_id, CromoBotella.nombre, CromoBotella.latitud, CromoBotella.longitud,
                      CromoBotella.camara_id).filter(CromoBotella.vigente.is_(True), CromoBotella.latitud.isnot(None))
    if caja:
        min_lon, min_lat, max_lon, max_lat = caja
        q = q.filter(CromoBotella.longitud.between(min_lon, max_lon), CromoBotella.latitud.between(min_lat, max_lat))
    filas = q.limit(max(1, min(limit, 20000))).all()
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [f.longitud, f.latitud]},
             "properties": {"n_id": f.n_id, "nombre": f.nombre, "camara_id": f.camara_id}}
            for f in filas
        ],
    }


def historial_cable(session: Session, cable_n_id: int, *, limit: int = 50) -> dict:
    ids = [
        r[0]
        for r in session.query(FomonIntervencionServicio.intervencion_id)
        .filter(FomonIntervencionServicio.cable_n_id == cable_n_id)
        .distinct()
        .order_by(FomonIntervencionServicio.intervencion_id.desc())
        .limit(max(1, min(limit, LIMITE_MAXIMO)))
        .all()
    ]
    items = []
    for i in session.query(FomonIntervencion).filter(FomonIntervencion.id.in_(ids)).order_by(FomonIntervencion.id.desc()):
        cable = next((c for c in estado_intervencion(session, i) if c.cable_n_id == cable_n_id), None)
        if cable is not None:
            items.append({"intervencion_id": i.id, "estado": i.estado, "creada_at": _iso(i.creada_at),
                          "fecha_egreso": _iso(i.fecha_egreso), "color": cable.semaforo.color,
                          "up": cable.semaforo.up, "evaluables": cable.semaforo.evaluables})
    return {"cable_n_id": cable_n_id, "items": items}


# --------------------------------------------------------------------------------------------------
# Mutaciones (admin)
# --------------------------------------------------------------------------------------------------


def reconocer(session: Session, intervencion_id: int, *, usuario: str, motivo: str,
              servicio_pk: Optional[int] = None) -> dict:
    if session.get(FomonIntervencion, intervencion_id) is None:
        raise NoEncontrado(f"intervención {intervencion_id}")
    motivo = (motivo or "").strip()
    if len(motivo) < 3:
        raise ValueError("el motivo debe tener al menos 3 caracteres")
    r = FomonReconocimiento(intervencion_id=intervencion_id, servicio_pk=servicio_pk, usuario=usuario, motivo=motivo[:500])
    session.add(r)
    session.commit()
    return {"id": r.id}


CAMPOS_CONFIG = ("ventana_desde", "ventana_hasta", "tope_mensajes_diario", "max_ids_por_mensaje",
                 "timeout_base_s", "timeout_por_servicio_s", "concurrencia", "prompt_version", "canales_ingreso")


def leer_config(session: Session) -> dict:
    fila = session.get(FomonConfig, 1)
    cs = session.query(ConfigServicios).filter(ConfigServicios.nombre_servicio == "fo_monitor").first()
    hoy = datetime.now(timezone.utc)
    from core.services.fo_monitor.motor import mensajes_enviados_hoy

    return {
        "activo": bool(cs and cs.activo),
        "canal": (cs.slack_channels if cs else None),
        **{k: (_iso(getattr(fila, k)) if isinstance(getattr(fila, k), datetime) else getattr(fila, k))
           for k in CAMPOS_CONFIG},
        "mensajes_hoy": mensajes_enviados_hoy(session, hoy),
        "actualizado_por": fila.actualizado_por,
        "actualizado_at": _iso(fila.actualizado_at),
    }


def actualizar_config(session: Session, cambios: dict[str, Any], *, usuario: str) -> dict:
    fila = session.get(FomonConfig, 1)
    cs = session.query(ConfigServicios).filter(ConfigServicios.nombre_servicio == "fo_monitor").one()
    aplicados: dict[str, Any] = {}
    if "activo" in cambios and cambios["activo"] is not None:
        cs.activo = bool(cambios["activo"])
        aplicados["activo"] = cs.activo
    for campo in CAMPOS_CONFIG:
        if campo in cambios:
            setattr(fila, campo, cambios[campo])
            valor = cambios[campo]
            aplicados[campo] = valor.isoformat() if isinstance(valor, datetime) else valor
    if not aplicados:
        return leer_config(session)
    fila.actualizado_por = usuario
    fila.actualizado_at = func.now()
    session.add(FomonConfigAuditoria(usuario=usuario, cambios=aplicados))
    session.commit()
    return leer_config(session)
