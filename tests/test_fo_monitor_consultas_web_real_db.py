# Nombre de archivo: test_fo_monitor_consultas_web_real_db.py
# Ubicación de archivo: tests/test_fo_monitor_consultas_web_real_db.py
# Descripción: Consultas web de FO Monitor contra Postgres real (listado, detalle, GeoJSON, historial, reconocer, config)

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from core.services.fo_monitor import consultas_web, motor
from db.models.fo_monitor import FomonConfigAuditoria, FomonConsulta, FomonIntervencionServicio, FomonResultado
from tests.soporte_postgres_real import requiere_postgres_real
from tests.test_fo_monitor_motor_real_db import _camara_con_servicios

pytestmark = requiere_postgres_real


@pytest.fixture
def session():
    from db.session import engine

    conn = engine.connect()
    trans = conn.begin()
    s = Session(bind=conn, join_transaction_mode="create_savepoint", autoflush=False)
    try:
        yield s
    finally:
        s.close()
        trans.rollback()
        conn.close()


def _intervencion_con_pre(s: Session, estado_servicio: str = "UP"):
    ahora = datetime.now(timezone.utc)
    camara = _camara_con_servicios(s)
    interv = motor.crear_intervencion_manual(s, usuario="admin-test", ahora=ahora, camara_id=camara.id)
    filas = s.query(FomonIntervencionServicio).filter_by(intervencion_id=interv.id).filter(
        FomonIntervencionServicio.servicio_pk.isnot(None)).all()
    pks = sorted({f.servicio_pk for f in filas})
    externos = {f.servicio_pk: f.servicio_id_externo for f in filas}
    consulta = FomonConsulta(intervencion_id=interv.id, fase="PRE", estado="RESPONDIDA", servicios_pk=pks,
                             ids_solicitados=[externos[p] for p in pks], enviada_at=ahora, respondida_at=ahora)
    s.add(consulta)
    s.flush()
    for pk in pks:
        s.add(FomonResultado(consulta_id=consulta.id, intervencion_id=interv.id, fase="PRE", servicio_pk=pk,
                             servicio_id_externo=externos[pk], estado=estado_servicio, parseado=True, medido_at=ahora))
    interv.estado = "CERRADA"
    s.commit()
    return interv, filas


def test_listado_detalle_y_filtro_por_cable(session):
    interv, filas = _intervencion_con_pre(session)
    listado = consultas_web.listar_intervenciones(session, estado="CERRADA", limit=500)
    assert listado["limit"] == consultas_web.LIMITE_MAXIMO
    item = next(i for i in listado["items"] if i["id"] == interv.id)
    assert item["color"] == "VERDE" and item["servicios"] == len({f.servicio_pk for f in filas})

    por_cable = consultas_web.listar_intervenciones(session, cable=str(filas[0].cable_n_id))
    assert interv.id in [i["id"] for i in por_cable["items"]]

    detalle = consultas_web.detalle_intervencion(session, interv.id)
    assert detalle["consultas"][0]["fase"] == "PRE"
    servicios = [x for c in detalle["cables_detalle"] for x in c["servicios"]]
    assert servicios and all(x["pre"]["estado"] == "UP" for x in servicios)
    with pytest.raises(consultas_web.NoEncontrado):
        consultas_web.detalle_intervencion(session, -1)


def test_geojson_intervenciones_y_red(session):
    interv, filas = _intervencion_con_pre(session, "DOWN")
    fc = consultas_web.geojson_intervenciones(session, horas=1)
    props = [f["properties"] for f in fc["features"] if f["properties"]["intervencion_id"] == interv.id]
    con_geo = {f.cable_n_id for f in session.query(FomonIntervencionServicio).filter_by(intervencion_id=interv.id)}
    assert props, "fomon_cable_geo debe estar cargada en dev (scripts/fo_monitor_generar_geo.py)"
    assert {p["cable_n_id"] for p in props} <= con_geo
    assert all(p["color"] == "ROJO" for p in props if p["evaluables"])

    red = json.loads(consultas_web.geojson_red(session))
    assert len(red["features"]) > 30000
    assert red["features"][0]["geometry"]["type"] == "LineString"


def test_historial_reconocer_y_config_auditada(session):
    interv, filas = _intervencion_con_pre(session)
    hist = consultas_web.historial_cable(session, filas[0].cable_n_id)
    assert hist["items"][0]["intervencion_id"] == interv.id

    with pytest.raises(ValueError):
        consultas_web.reconocer(session, interv.id, usuario="admin", motivo=" ")
    assert consultas_web.reconocer(session, interv.id, usuario="admin", motivo="evento Telecom")["id"]

    antes = session.query(FomonConfigAuditoria).count()
    cfg = consultas_web.actualizar_config(session, {"activo": True, "tope_mensajes_diario": 123}, usuario="admin")
    assert cfg["activo"] is True and cfg["tope_mensajes_diario"] == 123
    assert session.query(FomonConfigAuditoria).count() == antes + 1


def test_buscar_en_mapa_por_servicio_cable_y_camara(session):
    from sqlalchemy import text as _t

    fila = session.execute(_t(
        """
        SELECT s.servicio_id, c.nombre, b.camara_id
        FROM app.cromo_servicio_match m
        JOIN app.servicios s ON s.id = m.servicio_id
        JOIN app.cromo_pelos p ON p.n_id = m.pelo_n_id AND p.vigente
        JOIN app.cromo_cables c ON c.n_id = p.cable_n_id AND c.vigente
        JOIN app.fomon_cable_geo g ON g.cable_n_id = c.n_id
        JOIN app.cromo_botellas b ON b.n_id = c.extremo_a_n_id AND b.camara_id IS NOT NULL
        LIMIT 1
        """
    )).one()

    por_servicio = consultas_web.buscar_en_mapa(session, tipo="servicio", q=fila.servicio_id)
    assert fila.nombre in {f["properties"]["nombre"] for f in por_servicio["features"]}

    por_cable = consultas_web.buscar_en_mapa(session, tipo="cable", q=fila.nombre)
    assert por_cable["features"][0]["properties"]["nombre"] == fila.nombre  # coincidencia exacta primero

    por_camara = consultas_web.buscar_en_mapa(session, tipo="camara", q=str(fila.camara_id))
    assert fila.nombre in {f["properties"]["nombre"] for f in por_camara["features"]}

    with pytest.raises(ValueError):
        consultas_web.buscar_en_mapa(session, tipo="pelo", q="123")
    with pytest.raises(ValueError):
        consultas_web.buscar_en_mapa(session, tipo="cable", q="F")
