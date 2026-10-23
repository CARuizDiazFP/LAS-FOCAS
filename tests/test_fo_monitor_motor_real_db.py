# Nombre de archivo: test_fo_monitor_motor_real_db.py
# Ubicación de archivo: tests/test_fo_monitor_motor_real_db.py
# Descripción: Flujo completo del motor FO Monitor contra Postgres real con Slack falso y reloj controlado

"""Cada test corre en una transacción externa que se revierte al final (`create_savepoint`): los
`commit()` del motor y de `registrar_movimiento_ingreso` sólo liberan savepoints. Es la única forma
de limpiar, porque `fomon_resultados` es append-only (trigger) y no admite DELETE."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.services.fo_monitor import motor
from core.services.ingreso_service import cerrar_ingreso_forzado, registrar_movimiento_ingreso
from db.models.fo_monitor import FomonConfig, FomonConsulta, FomonIntervencion, FomonResultado
from db.models.infra import Camara, Ingreso
from db.models.servicios import ConfigServicios
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real

BURRITO = "U0A2HE3K950"
_RE_IDS = re.compile(r"verificar servicios? ([0-9, ]+)")


class FakeSlack:
    def __init__(self) -> None:
        self.publicados: list[dict] = []
        self.hilos: dict[str, list[dict]] = {}
        self._n = 1_800_000_000.0

    def publicar(self, canal, texto, thread_ts=None):
        self._n += 1
        ts = f"{self._n:.6f}"
        self.publicados.append({"canal": canal, "texto": texto, "thread_ts": thread_ts, "ts": ts})
        return ts

    def respuestas(self, canal, ts):
        return list(self.hilos.get(ts, []))

    def permalink(self, canal, ts):
        return f"https://slack.test/{canal}/{ts}"

    def buscar_token(self, canal, token, desde_epoch):
        for p in self.publicados:
            if re.search(re.escape(token) + r"(?!\d)", p["texto"]):
                return p["ts"]
        return None

    # --- helpers de test ---
    def consultas_sin_responder(self):
        return [p for p in self.publicados if "FOMON-Q" in p["texto"] and p["ts"] not in self.hilos]

    def responder_todas(self, ahora: datetime, estados: dict[str, str] | None = None, sin_bloque: bool = False):
        estados = estados or {}
        for p in self.consultas_sin_responder():
            ids = [i.strip() for i in _RE_IDS.search(p["texto"]).group(1).split(",") if i.strip()]
            if sin_bloque:
                cuerpo = "PROV no trae datos técnicos.\n_(ref: #ab12)_"
            else:
                lineas = "\n".join(f"FOMON|{i}|{estados.get(i, 'UP')}|-|test" for i in ids)
                cuerpo = f"diagnóstico...\n```\n{lineas}\n```\n_(ref: #ab12)_"
            self.hilos[p["ts"]] = [{"user": BURRITO, "text": cuerpo, "ts": f"{ahora.timestamp() - 30:.6f}"}]

    def avisos(self):
        return [p for p in self.publicados if "FOMON-Q" not in p["texto"]]


class Reloj:
    def __init__(self) -> None:
        self.t = datetime.now(timezone.utc)

    def __call__(self) -> datetime:
        return self.t

    def avanzar(self, **kw) -> datetime:
        self.t += timedelta(**kw)
        return self.t


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


def _camara_con_servicios(s: Session) -> Camara:
    camara_id = s.execute(
        text(
            """
            SELECT b.camara_id
            FROM app.cromo_botellas b
            JOIN app.cromo_cables c ON c.vigente AND c.clase = 51
                 AND (c.extremo_a_n_id = b.n_id OR c.extremo_b_n_id = b.n_id)
            JOIN app.cromo_pelos p ON p.cable_n_id = c.n_id AND p.vigente
            JOIN app.cromo_servicio_match m ON m.pelo_n_id = p.n_id
            JOIN app.servicios sv ON sv.id = m.servicio_id AND sv.es_verificable AND lower(sv.estado_servicio) = 'activo'
            WHERE b.vigente AND b.camara_id IS NOT NULL
            GROUP BY b.camara_id
            HAVING count(DISTINCT sv.id) BETWEEN 2 AND 15
            ORDER BY b.camara_id
            LIMIT 1
            """
        )
    ).scalar()
    assert camara_id is not None, "dev necesita al menos una cámara con 2-15 servicios verificables"
    return s.get(Camara, camara_id)


def _activar(s: Session, *, tope: int = 400, lote: int = 10) -> None:
    cfg = s.get(FomonConfig, 1)
    cfg.ventana_desde = None
    cfg.ventana_hasta = None
    cfg.tope_mensajes_diario = tope
    cfg.max_ids_por_mensaje = lote
    cs = s.query(ConfigServicios).filter(ConfigServicios.nombre_servicio == "fo_monitor").one()
    cs.activo = True
    cs.slack_channels = "CTEST"
    s.commit()


CANAL_PRUEBA = "C08UB8ML3LP"  # #baneo-de-camaras-prueba: único canal de ingresos habilitado por defecto
CANAL_PROD = "C015UKWP2MS"


def _ingreso(s: Session, camara: Camara, tipo: str = "Ingreso", momento: datetime | None = None,
             canal: str = CANAL_PRUEBA):
    return registrar_movimiento_ingreso(
        s, camara=camara, botella=None, tipo_movimiento=tipo, tecnico_nombre="TEST-FOMON",
        momento=momento, thread_ts="1799999999.000100", canal_id=canal,
    )


def _interv(s: Session) -> FomonIntervencion:
    return s.query(FomonIntervencion).order_by(FomonIntervencion.id.desc()).first()


def test_flujo_completo_con_caida_nueva_reverificada(session):
    slack, reloj = FakeSlack(), Reloj()
    _activar(session)
    camara = _camara_con_servicios(session)
    _ingreso(session, camara, momento=reloj())

    motor.tick(session, slack, reloj)
    interv = _interv(session)
    assert interv.estado == "PRE_EN_CURSO"
    assert interv.camara_id == camara.id
    assert slack.avisos()[0]["thread_ts"] is None and "FO Monitor" in slack.avisos()[0]["texto"]
    assert slack.consultas_sin_responder(), "se envió al menos una consulta PRE"

    slack.responder_todas(reloj.avanzar(seconds=40))
    motor.tick(session, slack, reloj)
    session.refresh(interv)
    assert interv.estado == "EN_CURSO"
    assert not interv.sin_linea_base

    # Egreso: el POST devuelve DOWN para el primer servicio → reverificación a los 4 min → AMARILLO.
    _ingreso(session, camara, tipo="Egreso", momento=reloj.avanzar(minutes=30))
    motor.tick(session, slack, reloj)
    session.refresh(interv)
    assert interv.estado == "POST_EN_CURSO"
    primer_id = _RE_IDS.search(slack.consultas_sin_responder()[0]["texto"]).group(1).split(",")[0].strip()
    slack.responder_todas(reloj.avanzar(seconds=40), {primer_id: "DOWN"})
    motor.tick(session, slack, reloj)
    reverif = session.query(FomonConsulta).filter_by(intervencion_id=interv.id, fase="REVERIF").all()
    assert len(reverif) == 1 and reverif[0].ids_solicitados == [primer_id]

    reloj.avanzar(minutes=5)
    motor.tick(session, slack, reloj)  # envía la reverificación
    slack.responder_todas(reloj.avanzar(seconds=40), {primer_id: "DOWN"})
    motor.tick(session, slack, reloj)
    session.refresh(interv)
    assert interv.estado == "CERRADA"
    texto_post = slack.avisos()[-1]["texto"]
    assert "POST completo" in texto_post and "Caídas nuevas" in texto_post and primer_id in texto_post


def test_piloto_inactivo_avanza_marca_sin_crear_intervencion(session):
    slack, reloj = FakeSlack(), Reloj()
    session.query(ConfigServicios).filter(ConfigServicios.nombre_servicio == "fo_monitor").update({"activo": False})
    session.commit()
    camara = _camara_con_servicios(session)
    antes = session.query(FomonIntervencion).count()
    ingreso = _ingreso(session, camara, momento=reloj())
    motor.tick(session, slack, reloj)
    assert session.query(FomonIntervencion).count() == antes
    assert session.get(FomonConfig, 1).ultimo_ingreso_id_procesado >= ingreso.id
    assert slack.publicados == []


def test_ingreso_del_canal_productivo_queda_en_stand_by(session):
    slack, reloj = FakeSlack(), Reloj()
    _activar(session)
    camara = _camara_con_servicios(session)
    antes = session.query(FomonIntervencion).count()
    ingreso = _ingreso(session, camara, momento=reloj(), canal=CANAL_PROD)
    motor.tick(session, slack, reloj)
    assert session.query(FomonIntervencion).count() == antes
    assert session.get(FomonConfig, 1).ultimo_ingreso_id_procesado >= ingreso.id

    session.get(FomonConfig, 1).canales_ingreso = f"{CANAL_PRUEBA},{CANAL_PROD}"
    session.commit()
    _ingreso(session, camara, momento=reloj(), canal=CANAL_PROD)
    motor.tick(session, slack, reloj)
    assert session.query(FomonIntervencion).count() == antes + 1


def test_ingreso_tardio_sin_linea_base_y_viejo_ignorado(session):
    slack, reloj = FakeSlack(), Reloj()
    _activar(session)
    camara = _camara_con_servicios(session)
    _ingreso(session, camara, momento=reloj() - timedelta(hours=9))
    motor.tick(session, slack, reloj)
    assert session.query(FomonIntervencion).filter_by(camara_id=camara.id, estado="PRE_EN_CURSO").count() == 0

    _ingreso(session, camara, momento=reloj() - timedelta(minutes=45))
    motor.tick(session, slack, reloj)
    assert _interv(session).sin_linea_base


def test_respuesta_sin_bloque_reintenta_de_a_uno_y_timeout(session):
    slack, reloj = FakeSlack(), Reloj()
    _activar(session)
    camara = _camara_con_servicios(session)
    _ingreso(session, camara, momento=reloj())
    motor.tick(session, slack, reloj)
    interv = _interv(session)
    enviadas = session.query(FomonConsulta).filter_by(intervencion_id=interv.id, estado="ENVIADA").all()
    n_ids = sum(len(c.ids_solicitados) for c in enviadas)

    slack.responder_todas(reloj.avanzar(seconds=60), sin_bloque=True)
    motor.tick(session, slack, reloj)
    reintentos = session.query(FomonConsulta).filter_by(intervencion_id=interv.id, intento=2).all()
    assert len(reintentos) == n_ids and all(len(c.ids_solicitados) == 1 for c in reintentos)
    desconocidos = session.query(FomonResultado).filter_by(intervencion_id=interv.id, estado="DESCONOCIDO").count()
    assert desconocidos == n_ids

    # Los reintentos salen tras el backoff y, sin respuesta, vencen por timeout.
    reloj.avanzar(seconds=61)
    motor.tick(session, slack, reloj)
    reloj.avanzar(seconds=400)
    motor.tick(session, slack, reloj)
    assert session.query(FomonConsulta).filter_by(intervencion_id=interv.id, estado="TIMEOUT").count() >= 1


def test_tope_diario_limita_envios(session):
    slack, reloj = FakeSlack(), Reloj()
    camara = _camara_con_servicios(session)
    usados = motor.mensajes_enviados_hoy(session, reloj())
    _activar(session, tope=usados + 1, lote=1)
    _ingreso(session, camara, momento=reloj())
    motor.tick(session, slack, reloj)
    assert len(slack.consultas_sin_responder()) == 1


def test_reconciliacion_de_envio_sin_ts(session):
    slack, reloj = FakeSlack(), Reloj()
    _activar(session)
    camara = _camara_con_servicios(session)
    _ingreso(session, camara, momento=reloj())
    motor.tick(session, slack, reloj)
    consulta = session.query(FomonConsulta).filter_by(estado="ENVIADA").order_by(FomonConsulta.id.desc()).first()
    ts_real = consulta.slack_ts
    consulta.slack_ts = None  # simula que el worker murió entre publicar y guardar
    session.commit()
    reloj.avanzar(seconds=90)
    motor.tick(session, slack, reloj)
    session.refresh(consulta)
    assert consulta.slack_ts == ts_real


def test_verificacion_manual_por_camara_cierra_tras_pre(session):
    slack, reloj = FakeSlack(), Reloj()
    _activar(session)
    camara = _camara_con_servicios(session)
    interv = motor.crear_intervencion_manual(session, usuario="admin-test", ahora=reloj(), camara_id=camara.id)
    session.commit()
    motor.tick(session, slack, reloj)
    slack.responder_todas(reloj.avanzar(seconds=40))
    motor.tick(session, slack, reloj)
    session.refresh(interv)
    assert interv.estado == "CERRADA"
    assert "PRE completo" in slack.avisos()[-1]["texto"]


# --------------------------------------------------------------------------------------------------
# Ingresos anulados desde el portal (baja lógica, 2026-10-23): nunca ocurrieron
# --------------------------------------------------------------------------------------------------


def _anular(s: Session, ingreso: Ingreso) -> None:
    ingreso.anulado_at = datetime.now(timezone.utc)
    ingreso.anulado_por = "admin-test"
    ingreso.anulado_motivo = "nunca ocurrió (test)"
    s.commit()


def _intervencion_en_curso(s: Session, slack: FakeSlack, reloj: Reloj, camara: Camara, n: int = 1):
    ingresos = [_ingreso(s, camara, momento=reloj()) for _ in range(n)]  # mismo hilo: una intervención
    motor.tick(s, slack, reloj)
    interv = _interv(s)
    slack.responder_todas(reloj.avanzar(seconds=40))
    motor.tick(s, slack, reloj)
    s.refresh(interv)
    assert interv.estado == "EN_CURSO"
    return interv, ingresos


@pytest.mark.parametrize("anulado", [False, True])
def test_ingreso_anulado_no_crea_intervencion(session, anulado):
    slack, reloj = FakeSlack(), Reloj()
    _activar(session)
    camara = _camara_con_servicios(session)
    antes = session.query(FomonIntervencion).count()
    ingreso = _ingreso(session, camara, momento=reloj())
    if anulado:
        _anular(session, ingreso)
    motor.tick(session, slack, reloj)
    assert session.query(FomonIntervencion).count() == antes + (0 if anulado else 1)
    assert session.get(FomonConfig, 1).ultimo_ingreso_id_procesado >= ingreso.id  # la marca cuenta todos


@pytest.mark.parametrize("anulado", [False, True])
def test_vinculado_anulado_no_bloquea_el_paso_a_post(session, anulado):
    slack, reloj = FakeSlack(), Reloj()
    _activar(session)
    camara = _camara_con_servicios(session)
    interv, (primero, segundo) = _intervencion_en_curso(session, slack, reloj, camara, n=2)
    cerrar_ingreso_forzado(session, ingreso=primero, momento=reloj.avanzar(minutes=30))
    if anulado:
        _anular(session, segundo)
    motor.tick(session, slack, reloj)
    session.refresh(interv)
    if anulado:
        assert interv.estado.startswith("POST_") and interv.fecha_egreso == primero.fecha_fin
        assert not interv.egreso_inferido
    else:
        assert interv.estado == "EN_CURSO"  # el segundo vinculado sigue adentro


@pytest.mark.parametrize("anulado", [False, True])
def test_egreso_huerfano_anulado_no_infiere_egreso(session, anulado):
    slack, reloj = FakeSlack(), Reloj()
    _activar(session)
    camara = _camara_con_servicios(session)
    interv, _ = _intervencion_en_curso(session, slack, reloj, camara)
    huerfano = registrar_movimiento_ingreso(
        session, camara=camara, botella=None, tipo_movimiento="Egreso", tecnico_nombre="TEST-FOMON-OTRO",
        momento=reloj.avanzar(minutes=30), thread_ts="1799999999.000200", canal_id=CANAL_PRUEBA,
    )
    assert huerfano.fecha_inicio is None  # EGRESO huérfano: el técnico no tenía ingreso abierto
    if anulado:
        _anular(session, huerfano)
    motor.tick(session, slack, reloj)
    session.refresh(interv)
    if anulado:
        assert interv.estado == "EN_CURSO" and interv.fecha_egreso is None
    else:
        assert interv.estado.startswith("POST_") and interv.egreso_inferido
