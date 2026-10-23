# Nombre de archivo: test_ingresos_mover_anular_real_db.py
# Ubicación de archivo: tests/test_ingresos_mover_anular_real_db.py
# Descripción: mover_ingreso_web/anular_ingreso_web contra Postgres real (auditoría, FO Monitor, Camara.estado), con rollback

"""Lo que un mock no puede probar: que las columnas nuevas de la auditoría persisten (y el CHECK de
`origen='web'` acepta la fila), que el `CHECK ck_ingresos_anulado_coherente` acepta la baja lógica, que
el filtro de intervenciones abiertas excluye las finales, que "otros vinculados vigentes" lee bien la
tabla de vínculo, y que nada toca `Camara.estado` ni el `IngresoSinMatch` resuelto.

Corre dentro de una transacción externa que se revierte al final (`create_savepoint`): los `commit()`
del servicio sólo liberan savepoints y nada queda escrito en dev."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.services import ingreso_correccion_service as ics
from core.services.camara_estado_service import get_camara_estado_contexto
from db.models.cromo import CromoBotella
from db.models.fo_monitor import FomonConsulta, FomonIntervencion, FomonIntervencionIngreso
from db.models.infra import Camara, Ingreso, IngresoCorreccion, IngresoSinMatch, IngresoTipo
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real

TECNICO = "TEST-MOVER-ANULAR"
USUARIO = "test-mover-anular"
HILO = "1799999998.000300"
AHORA = datetime.now(timezone.utc)


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


def _camara_origen(s: Session, excluir: int) -> Camara:
    """Cámara raíz sin ingresos ni botellas hijas, distinta del destino."""
    camara_id = s.execute(
        text(
            """
            SELECT c.id FROM app.camaras c
            WHERE c.camara_padre_id IS NULL AND c.id <> :excluir
              AND NOT EXISTS (SELECT 1 FROM app.camaras h WHERE h.camara_padre_id = c.id)
              AND NOT EXISTS (SELECT 1 FROM app.ingresos i WHERE i.camara_id = c.id)
            ORDER BY c.id
            LIMIT 1
            """
        ),
        {"excluir": excluir},
    ).scalar()
    assert camara_id is not None, "dev necesita al menos una cámara raíz sin ingresos"
    return s.get(Camara, camara_id)


def _botella_vigente_con_camara(s: Session) -> CromoBotella:
    n_id = s.execute(
        text(
            """
            SELECT b.n_id FROM app.cromo_botellas b
            WHERE b.vigente AND b.camara_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM app.ingresos i WHERE i.camara_id = b.camara_id)
            ORDER BY b.n_id
            LIMIT 1
            """
        )
    ).scalar()
    assert n_id is not None, "dev necesita una CromoBotella vigente con cámara padre"
    return s.get(CromoBotella, n_id)


def _ingreso(s: Session, camara: Camara, *, botella_n_id: int | None = None) -> Ingreso:
    ing = Ingreso(
        camara_id=camara.id,
        cromo_botella_id=botella_n_id,
        tecnico_id=TECNICO,
        tipo=IngresoTipo.INGRESO,
        fecha_inicio=AHORA - timedelta(hours=1),
        fecha_fin=None,
        thread_ts=HILO,
        canal_id="CTEST",
    )
    s.add(ing)
    s.flush()
    return ing


def _intervencion(s: Session, camara: Camara, ingresos: list[Ingreso], *, estado: str) -> FomonIntervencion:
    interv = FomonIntervencion(
        origen="INGRESO", camara_id=camara.id, botella_objetivo_n_id=None, botella_1_inferida=True,
        tecnico=TECNICO, estado=estado, fecha_ingreso=AHORA - timedelta(hours=1), proximo_evento_en=AHORA,
        cerrada_at=AHORA if estado == "CERRADA" else None,
    )
    s.add(interv)
    s.flush()
    for ing in ingresos:
        s.add(FomonIntervencionIngreso(intervencion_id=interv.id, ingreso_id=ing.id))
    s.flush()
    return interv


def _auditoria(s: Session, ingreso_id: int, comando: str) -> list[IngresoCorreccion]:
    return (
        s.query(IngresoCorreccion)
        .filter(IngresoCorreccion.ingreso_id == ingreso_id, IngresoCorreccion.comando == comando)
        .order_by(IngresoCorreccion.id)
        .all()
    )


@pytest.mark.parametrize(("estado", "se_actualiza"), [("EN_CURSO", True), ("SIN_EGRESO", True), ("CERRADA", False)])
def test_mover_persiste_cambio_auditoria_y_fo_monitor(session, estado, se_actualiza):
    botella = _botella_vigente_con_camara(session)
    destino = session.get(Camara, botella.camara_id)
    origen = _camara_origen(session, excluir=destino.id)
    estados_antes = (origen.estado, destino.estado)
    ing = _ingreso(session, origen)
    interv = _intervencion(session, origen, [ing], estado=estado)
    session.commit()

    resultado = ics.mover_ingreso_web(
        session, ingreso_id=ing.id, camara_destino_id=destino.id, cromo_botella_destino_n_id=botella.n_id,
        motivo="Fontaine mal tipeado", usuario=USUARIO,
    )

    assert resultado.resultado == ics.RESULTADO_OK_INGRESO_MOVIDO
    session.expire_all()
    ing = session.get(Ingreso, ing.id)
    assert (ing.camara_id, ing.cromo_botella_id, ing.fecha_fin) == (destino.id, botella.n_id, None)
    (fila,) = _auditoria(session, ing.id, ics.COMANDO_MOVER_INGRESO)
    assert fila.origen == "web" and fila.actor_web_usuario == USUARIO
    assert (fila.camara_id_resuelta, fila.cromo_botella_id_resuelta) == (destino.id, botella.n_id)
    assert (fila.camara_id_anterior, fila.cromo_botella_id_anterior) == (origen.id, None)
    interv = session.get(FomonIntervencion, interv.id)
    if se_actualiza:
        assert (interv.camara_id, interv.botella_objetivo_n_id) == (destino.id, botella.n_id)
        assert resultado.intervenciones_fomon == [interv.id]
    else:
        assert (interv.camara_id, interv.botella_objetivo_n_id) == (origen.id, None)
        assert resultado.intervenciones_fomon == []
    assert interv.estado == estado
    assert (session.get(Camara, origen.id).estado, session.get(Camara, destino.id).estado) == estados_antes
    # El estado derivado sigue al ingreso: ahora está activo en el destino y no en el origen.
    assert get_camara_estado_contexto(session, destino.id).tiene_ingreso_activo is True
    assert get_camara_estado_contexto(session, origen.id).tiene_ingreso_activo is False


def test_mover_rechazo_persiste_una_fila_y_no_cambia_nada(session):
    botella = _botella_vigente_con_camara(session)
    destino = session.get(Camara, botella.camara_id)
    origen = _camara_origen(session, excluir=destino.id)
    ing = _ingreso(session, origen)
    session.commit()

    # La botella es vigente pero de OTRA cámara que el destino pedido (el origen).
    resultado = ics.mover_ingreso_web(
        session, ingreso_id=ing.id, camara_destino_id=origen.id, cromo_botella_destino_n_id=botella.n_id,
        motivo="prueba", usuario=USUARIO,
    )

    assert resultado.resultado == ics.RESULTADO_BOTELLA_INVALIDA
    session.expire_all()
    assert session.get(Ingreso, ing.id).camara_id == origen.id
    (fila,) = _auditoria(session, ing.id, ics.COMANDO_MOVER_INGRESO)
    assert fila.resultado == ics.RESULTADO_BOTELLA_INVALIDA and fila.camara_id_anterior == origen.id


def test_anular_persiste_baja_logica_cancela_fo_monitor_y_no_reabre_el_caso(session):
    botella = _botella_vigente_con_camara(session)
    camara = _camara_origen(session, excluir=botella.camara_id)
    estado_antes = camara.estado
    ing = _ingreso(session, camara)
    caso = IngresoSinMatch(
        texto_original="cámara mal escrita", origen="slack", thread_ts=HILO,
        resuelto_via_revalidacion=True, ingreso_id=ing.id,
    )
    session.add(caso)
    interv = _intervencion(session, camara, [ing], estado="PRE_EN_CURSO")
    pendiente = FomonConsulta(intervencion_id=interv.id, fase="PRE", estado="PENDIENTE", servicios_pk=[1], ids_solicitados=["X1"])
    enviada = FomonConsulta(intervencion_id=interv.id, fase="PRE", estado="ENVIADA", servicios_pk=[2], ids_solicitados=["X2"])
    session.add_all([pendiente, enviada])
    session.commit()
    assert get_camara_estado_contexto(session, camara.id).tiene_ingreso_activo is True  # control

    resultado = ics.anular_ingreso_web(session, ingreso_id=ing.id, motivo="nunca ocurrió", usuario=USUARIO)

    assert resultado.resultado == ics.RESULTADO_OK_INGRESO_ANULADO
    session.expire_all()
    ing = session.get(Ingreso, ing.id)
    assert ing.anulado_at is not None and ing.anulado_at.tzinfo is not None
    assert (ing.anulado_por, ing.anulado_motivo) == (USUARIO, "nunca ocurrió")
    assert ing.fecha_fin is None
    interv = session.get(FomonIntervencion, interv.id)
    assert interv.estado == "CANCELADA" and interv.cerrada_at is not None and interv.proximo_evento_en is None
    assert session.get(FomonConsulta, pendiente.id).estado == "CANCELADA"
    assert session.get(FomonConsulta, enviada.id).estado == "ENVIADA"
    caso = session.get(IngresoSinMatch, caso.id)
    assert (caso.resuelto_via_revalidacion, caso.ingreso_id) == (True, ing.id)
    assert session.get(Camara, camara.id).estado == estado_antes
    assert get_camara_estado_contexto(session, camara.id).tiene_ingreso_activo is False
    (fila,) = _auditoria(session, ing.id, ics.COMANDO_ANULAR_INGRESO)
    assert fila.origen == "web" and fila.resultado == ics.RESULTADO_OK_INGRESO_ANULADO

    # Segundo intento: rechazo auditado, la anulación original intacta.
    anulado_at = ing.anulado_at
    otra = ics.anular_ingreso_web(session, ingreso_id=ing.id, motivo="otra vez", usuario="otro-admin")
    assert otra.resultado == ics.RESULTADO_INGRESO_ANULADO
    session.expire_all()
    assert session.get(Ingreso, ing.id).anulado_at == anulado_at
    assert [f.resultado for f in _auditoria(session, ing.id, ics.COMANDO_ANULAR_INGRESO)] == [
        ics.RESULTADO_OK_INGRESO_ANULADO,
        ics.RESULTADO_INGRESO_ANULADO,
    ]


def test_anular_intervencion_con_dos_ingresos_se_cancela_recien_con_el_ultimo(session):
    """"Botella 1 y 2": anular una fila deja la intervención verificando la otra; anular la segunda
    la cancela."""
    botella = _botella_vigente_con_camara(session)
    camara = _camara_origen(session, excluir=botella.camara_id)
    primero, segundo = _ingreso(session, camara), _ingreso(session, camara)
    interv = _intervencion(session, camara, [primero, segundo], estado="EN_CURSO")
    session.commit()

    r1 = ics.anular_ingreso_web(session, ingreso_id=primero.id, motivo="duplicado", usuario=USUARIO)
    session.expire_all()
    assert r1.intervenciones_fomon_omitidas == [interv.id]
    assert session.get(FomonIntervencion, interv.id).estado == "EN_CURSO"

    r2 = ics.anular_ingreso_web(session, ingreso_id=segundo.id, motivo="duplicado", usuario=USUARIO)
    session.expire_all()
    assert r2.intervenciones_fomon == [interv.id]
    assert session.get(FomonIntervencion, interv.id).estado == "CANCELADA"
