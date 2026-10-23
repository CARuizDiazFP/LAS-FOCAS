# Nombre de archivo: test_ingresos_anulados_real_db.py
# Ubicación de archivo: tests/test_ingresos_anulados_real_db.py
# Descripción: Un ingreso anulado (baja lógica) no cambia el resultado de ningún lector que decide estado, contra Postgres real

"""Cada lector que decide estado a partir de `app.ingresos` filtra `Ingreso.vigente()`. Un mock no
puede probar un filtro SQL (la cadena `query().filter().first()` devuelve lo mismo con o sin la
condición), así que estos tests corren contra el Postgres de dev, dentro de una transacción externa
que se revierte al final (`create_savepoint`): los `commit()` de los servicios sólo liberan
savepoints.

Patrón de cada test: un control con el ingreso vigente (que sí cambia el resultado, para que el test
no pase por vacío) y el mismo caso con el ingreso anulado (que no lo cambia)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.services import ingreso_correccion_service as ics
from core.services import ingreso_reproceso_service as irs
from core.services.camara_estado_service import get_camara_estado_contexto
from core.services.ingreso_service import registrar_egreso_historico, registrar_movimiento_ingreso
from core.services.protection_service import ProtectionService
from db.models.infra import Camara, CamaraEstado, Ingreso, IngresoSinMatch, IngresoTipo
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real

TECNICO = "TEST-ANULADOS"
HILO = "1799999998.000200"


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


def _camara_libre(s: Session) -> Camara:
    """Cámara raíz sin botellas hijas y sin ningún ingreso: su grupo es ella sola y no hay ruido."""
    camara_id = s.execute(
        text(
            """
            SELECT c.id FROM app.camaras c
            WHERE c.camara_padre_id IS NULL
              AND NOT EXISTS (SELECT 1 FROM app.camaras h WHERE h.camara_padre_id = c.id)
              AND NOT EXISTS (SELECT 1 FROM app.ingresos i WHERE i.camara_id = c.id)
            ORDER BY c.id
            LIMIT 1
            """
        )
    ).scalar()
    assert camara_id is not None, "dev necesita al menos una cámara raíz sin ingresos"
    return s.get(Camara, camara_id)


def _ingreso_abierto(s: Session, camara: Camara, *, anulado: bool, momento: datetime | None = None) -> Ingreso:
    ing = Ingreso(
        camara_id=camara.id,
        cromo_botella_id=None,
        tecnico_id=TECNICO,
        tipo=IngresoTipo.INGRESO,
        fecha_inicio=momento or datetime.now(timezone.utc) - timedelta(hours=1),
        fecha_fin=None,
        thread_ts=HILO,
        canal_id="CTEST",
    )
    if anulado:
        ing.anulado_at = datetime.now(timezone.utc)
        ing.anulado_por = "admin-test"
        ing.anulado_motivo = "nunca ocurrió (test)"
    s.add(ing)
    s.flush()
    return ing


# ── Estado derivado de la cámara ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("anulado, esperado", [(False, True), (True, False)])
def test_get_camara_estado_contexto_ignora_anulado(session, anulado, esperado):
    camara = _camara_libre(session)
    _ingreso_abierto(session, camara, anulado=anulado)
    contexto = get_camara_estado_contexto(session, camara.id)
    assert contexto.tiene_ingreso_activo is esperado


@pytest.mark.parametrize("anulado, esperado", [(False, CamaraEstado.OCUPADA), (True, CamaraEstado.LIBRE)])
def test_restauracion_de_baneo_ignora_anulado(session, anulado, esperado):
    camara = _camara_libre(session)
    _ingreso_abierto(session, camara, anulado=anulado)
    incidente = SimpleNamespace(fecha_inicio=None)  # sin historial aplicable: cae a LIBRE/OCUPADA
    assert ProtectionService(session)._determinar_estado_restauracion(camara, incidente) == esperado


# ── Egreso: nunca cierra un ingreso anulado ──────────────────────────────────────────────────────


@pytest.mark.parametrize("anulado", [False, True])
def test_egreso_en_vivo_no_cierra_anulado(session, anulado):
    camara = _camara_libre(session)
    abierto = _ingreso_abierto(session, camara, anulado=anulado)
    fila = registrar_movimiento_ingreso(
        session, camara=camara, botella=None, tipo_movimiento="Egreso", tecnico_nombre=TECNICO
    )
    if anulado:
        assert fila.id != abierto.id and fila.tipo == IngresoTipo.EGRESO  # egreso huérfano
        session.refresh(abierto)
        assert abierto.fecha_fin is None
    else:
        assert fila.id == abierto.id and fila.fecha_fin is not None


@pytest.mark.parametrize("anulado", [False, True])
def test_egreso_historico_no_cierra_anulado(session, anulado):
    camara = _camara_libre(session)
    abierto = _ingreso_abierto(session, camara, anulado=anulado)
    fila, cerro = registrar_egreso_historico(
        session,
        camara=camara,
        botella=None,
        tecnico_nombre=TECNICO,
        slack_user_id=None,
        momento=datetime.now(timezone.utc),
    )
    assert cerro is (not anulado)
    assert (fila.id == abierto.id) is (not anulado)


# ── Corrección de ingresos (Slack/web) ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("anulado, nivel", [(False, 1), (True, None)])
def test_resolver_contexto_hilo_nivel_1_ignora_anulado(session, anulado, nivel):
    camara = _camara_libre(session)
    _ingreso_abierto(session, camara, anulado=anulado)
    # Sin IngresoSinMatch y con client=None, si el nivel 1 no responde la cascada se agota.
    assert session.query(IngresoSinMatch).filter(IngresoSinMatch.thread_ts == HILO).first() is None
    ctx = ics.resolver_contexto_hilo(session, None, thread_ts=HILO, canal_id="CTEST")
    assert ctx.nivel == nivel
    assert (ctx.camara is not None and ctx.camara.id == camara.id) is (not anulado)


def test_ingresos_abiertos_excluye_anulado(session):
    camara = _camara_libre(session)
    vigente = _ingreso_abierto(session, camara, anulado=False)
    _ingreso_abierto(session, camara, anulado=True)
    assert [i.id for i in ics._ingresos_abiertos(session, camara)] == [vigente.id]


# ── Reproceso por lote ───────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("anulado", [False, True])
def test_reproceso_ya_registrado_ignora_anulado(session, anulado):
    camara = _camara_libre(session)
    ing = _ingreso_abierto(session, camara, anulado=anulado)
    caso = SimpleNamespace(thread_ts=HILO)
    existente = irs._ya_registrado(session, caso, camara.id, None, IngresoTipo.INGRESO)
    assert (existente is not None and existente.id == ing.id) is (not anulado)


# ── Hueco cerrado: DELETE de cámara pendiente borraba sus ingresos por la cascada del ORM ────────


@pytest.mark.parametrize("con_ingreso, anulado", [(False, False), (True, False), (True, True)])
def test_eliminar_camara_pendiente_bloquea_si_tiene_ingresos(session, monkeypatch, con_sesion, con_ingreso, anulado):
    from fastapi.testclient import TestClient

    from tests.test_web_ingest_camaras import _fake_session_local
    from web.app.main import app

    camara = Camara(nombre="TEST-PENDIENTE-ANULADOS", estado=CamaraEstado.PENDIENTE_REVISION)
    session.add(camara)
    session.flush()
    ingreso = _ingreso_abierto(session, camara, anulado=anulado) if con_ingreso else None
    session.commit()
    monkeypatch.setattr("db.session.SessionLocal", _fake_session_local(session))
    con_sesion("admin")

    res = TestClient(app).delete(f"/api/admin/infra/camaras/pendientes/{camara.id}")

    if con_ingreso:
        # Un anulado también bloquea: la fila se conserva como historial de la baja lógica.
        assert res.status_code == 409
        assert res.json() == {"error": "No se puede eliminar: la cámara tiene ingresos asociados."}
        assert session.get(Camara, camara.id) is not None
        assert session.get(Ingreso, ingreso.id) is not None
    else:
        assert res.status_code == 200
        assert session.get(Camara, camara.id) is None
