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
from core.services.cromo.camino_optico_service import CLASES_CABLE
from core.services.fo_monitor import motor
from core.services.fo_monitor.alcance import resolver_alcance
from db.models.cromo import CromoBotella
from db.models.fo_monitor import (
    FomonConfig,
    FomonConsulta,
    FomonIntervencion,
    FomonIntervencionIngreso,
    FomonIntervencionServicio,
)
from db.models.infra import Camara, Ingreso, IngresoCorreccion, IngresoSinMatch, IngresoTipo
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real

TECNICO = "TEST-MOVER-ANULAR"
USUARIO = "test-mover-anular"
HILO = "1799999998.000300"
AHORA = datetime.now(timezone.utc)
CABLE_VIEJO = 999_999_999_901


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
    """Botella vigente con cámara padre sin ingresos y con al menos un cable verificable (clases de
    `CLASES_CABLE`), para que el alcance recalculado no sea vacío."""
    n_id = s.execute(
        text(
            """
            SELECT b.n_id FROM app.cromo_cables c
            JOIN app.cromo_botellas b ON b.n_id = c.extremo_a_n_id
            WHERE c.vigente AND c.clase = ANY(:clases ::smallint[])
              AND b.vigente AND b.camara_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM app.ingresos i WHERE i.camara_id = b.camara_id)
            ORDER BY c.n_id
            LIMIT 1
            """
        ),
        {"clases": sorted(CLASES_CABLE)},
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
        sin_linea_base=False, aviso_ts="1799999998.000399", aviso_canal="CTEST",
        tecnico=TECNICO, estado=estado, fecha_ingreso=AHORA - timedelta(hours=1), proximo_evento_en=AHORA,
        cerrada_at=AHORA if estado == "CERRADA" else None,
    )
    s.add(interv)
    s.flush()
    for ing in ingresos:
        s.add(FomonIntervencionIngreso(intervencion_id=interv.id, ingreso_id=ing.id))
    # Alcance "viejo" congelado: un cable inexistente, para distinguirlo del recalculado.
    s.add(FomonIntervencionServicio(intervencion_id=interv.id, cable_n_id=CABLE_VIEJO, cable_nombre="VIEJO",
                                    cable_clase=51, botella_n_id=None, es_objetivo=True))
    s.flush()
    return interv


def _cables_congelados(s: Session, intervencion_id: int) -> set[int]:
    return {
        f.cable_n_id
        for f in s.query(FomonIntervencionServicio).filter(FomonIntervencionServicio.intervencion_id == intervencion_id)
    }


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
    esperado = {c.n_id for c in resolver_alcance(session, destino.id, botella.n_id).cables}
    assert esperado, "la botella elegida tiene cables: el recálculo no puede pasar por vacío"

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
        assert _cables_congelados(session, interv.id) == esperado, "alcance recalculado para el destino"
        # Después de la PRE: la PRE del alcance nuevo nunca se midió y el hilo viejo no se usa más.
        assert interv.sin_linea_base is True and interv.aviso_ts is None
        assert resultado.intervenciones_fomon == [interv.id]
    else:
        assert (interv.camara_id, interv.botella_objetivo_n_id) == (origen.id, None)
        assert _cables_congelados(session, interv.id) == {CABLE_VIEJO}
        assert resultado.intervenciones_fomon == []
    assert interv.estado == estado
    assert (session.get(Camara, origen.id).estado, session.get(Camara, destino.id).estado) == estados_antes
    # El estado derivado sigue al ingreso: ahora está activo en el destino y no en el origen.
    assert get_camara_estado_contexto(session, destino.id).tiene_ingreso_activo is True
    assert get_camara_estado_contexto(session, origen.id).tiene_ingreso_activo is False


def test_mover_pre_en_curso_cancela_pendientes_y_el_motor_replanifica_con_el_alcance_nuevo(session):
    botella = _botella_vigente_con_camara(session)
    destino = session.get(Camara, botella.camara_id)
    origen = _camara_origen(session, excluir=destino.id)
    ing = _ingreso(session, origen)
    interv = _intervencion(session, origen, [ing], estado="PRE_EN_CURSO")
    interv.aviso_ts, interv.aviso_canal = "1799999998.000301", "CTEST"
    vieja = FomonConsulta(intervencion_id=interv.id, fase="PRE", estado="PENDIENTE", servicios_pk=[1], ids_solicitados=["VIEJO"])
    session.add(vieja)
    session.commit()

    resultado = ics.mover_ingreso_web(
        session, ingreso_id=ing.id, camara_destino_id=destino.id, cromo_botella_destino_n_id=None,
        motivo="cámara equivocada", usuario=USUARIO,
    )

    assert resultado.intervenciones_fomon == [interv.id]
    session.expire_all()
    interv = session.get(FomonIntervencion, interv.id)
    assert interv.estado == "PRE_PENDIENTE" and interv.aviso_ts is None
    assert session.get(FomonConsulta, vieja.id).estado == "CANCELADA"
    alcance = resolver_alcance(session, destino.id, None)
    assert interv.botella_objetivo_n_id == alcance.botella_objetivo_n_id

    # Próximo ciclo del motor (sin canal: no publica nada en Slack).
    cfg = motor.Config(fila=session.get(FomonConfig, 1) or FomonConfig(max_ids_por_mensaje=10, prompt_version="v4"),
                       activo=False, canal="", en_ventana=False)
    motor.planificar_consultas(session, cfg, slack=None, ahora=AHORA)
    session.flush()
    nuevas = (
        session.query(FomonConsulta)
        .filter(FomonConsulta.intervencion_id == interv.id, FomonConsulta.id != vieja.id)
        .all()
    )
    assert nuevas, "el alcance del destino tiene servicios: el motor tiene que crear consultas"
    assert session.get(FomonIntervencion, interv.id).estado == "PRE_EN_CURSO"
    assert {pk for c in nuevas for pk in c.servicios_pk} == {s.servicio_id for s in alcance.servicios_unicos()}
    assert all(c.fase == "PRE" and c.estado == "PENDIENTE" for c in nuevas)


@pytest.mark.parametrize("estado_consulta", ["ENVIADA", "RESPONDIDA", "TIMEOUT"])
def test_mover_omite_la_intervencion_que_ya_consulto_a_burrito(session, estado_consulta):
    botella = _botella_vigente_con_camara(session)
    destino = session.get(Camara, botella.camara_id)
    origen = _camara_origen(session, excluir=destino.id)
    ing = _ingreso(session, origen)
    interv = _intervencion(session, origen, [ing], estado="POST_EN_CURSO")
    enviada = FomonConsulta(intervencion_id=interv.id, fase="PRE", estado=estado_consulta, servicios_pk=[1], ids_solicitados=["X1"])
    pendiente = FomonConsulta(intervencion_id=interv.id, fase="POST", estado="PENDIENTE", servicios_pk=[1], ids_solicitados=["X1"])
    session.add_all([enviada, pendiente])
    session.commit()

    resultado = ics.mover_ingreso_web(
        session, ingreso_id=ing.id, camara_destino_id=destino.id, cromo_botella_destino_n_id=botella.n_id,
        motivo="cámara equivocada", usuario=USUARIO,
    )

    assert resultado.resultado == ics.RESULTADO_OK_INGRESO_MOVIDO
    assert resultado.intervenciones_fomon_omitidas == [
        ics.IntervencionFomonOmitida(interv.id, ics.OMISION_CONSULTAS_YA_ENVIADAS)
    ]
    session.expire_all()
    interv = session.get(FomonIntervencion, interv.id)
    assert (interv.camara_id, interv.estado) == (origen.id, "POST_EN_CURSO")
    assert _cables_congelados(session, interv.id) == {CABLE_VIEJO}
    assert session.get(FomonConsulta, pendiente.id).estado == "PENDIENTE"
    assert session.get(Ingreso, ing.id).camara_id == destino.id, "el ingreso se mueve igual"


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
    assert r1.intervenciones_fomon_omitidas == [
        ics.IntervencionFomonOmitida(interv.id, ics.OMISION_OTROS_INGRESOS_VIGENTES)
    ]
    assert session.get(FomonIntervencion, interv.id).estado == "EN_CURSO"

    r2 = ics.anular_ingreso_web(session, ingreso_id=segundo.id, motivo="duplicado", usuario=USUARIO)
    session.expire_all()
    assert r2.intervenciones_fomon == [interv.id]
    assert session.get(FomonIntervencion, interv.id).estado == "CANCELADA"


# ── Ronda de revisión ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("operacion", ["mover", "anular"])
def test_si_falla_la_auditoria_no_queda_el_cambio(session, monkeypatch, operacion):
    """Cambio y auditoría en un solo commit: forzando el fallo del INSERT de auditoría (CHECK de
    `origen`), la excepción se propaga y ni el ingreso ni FO Monitor quedan modificados."""
    botella = _botella_vigente_con_camara(session)
    destino = session.get(Camara, botella.camara_id)
    origen = _camara_origen(session, excluir=destino.id)
    ing = _ingreso(session, origen)
    interv = _intervencion(session, origen, [ing], estado="EN_CURSO")
    session.commit()
    monkeypatch.setattr(ics, "ORIGEN_WEB", "zz-invalido")

    with pytest.raises(Exception):
        if operacion == "mover":
            ics.mover_ingreso_web(session, ingreso_id=ing.id, camara_destino_id=destino.id,
                                  cromo_botella_destino_n_id=None, motivo="prueba", usuario=USUARIO)
        else:
            ics.anular_ingreso_web(session, ingreso_id=ing.id, motivo="prueba", usuario=USUARIO)

    session.expire_all()
    ing = session.get(Ingreso, ing.id)
    assert (ing.camara_id, ing.anulado_at) == (origen.id, None)
    interv = session.get(FomonIntervencion, interv.id)
    assert (interv.camara_id, interv.estado) == (origen.id, "EN_CURSO")
    assert _cables_congelados(session, interv.id) == {CABLE_VIEJO}
    comando = ics.COMANDO_MOVER_INGRESO if operacion == "mover" else ics.COMANDO_ANULAR_INGRESO
    assert _auditoria(session, ing.id, comando) == []


def test_mover_rechaza_destino_que_no_es_camara_raiz(session):
    hija_id = session.execute(text("SELECT id FROM app.camaras WHERE camara_padre_id IS NOT NULL ORDER BY id LIMIT 1")).scalar()
    if hija_id is None:
        pytest.skip("dev no tiene cámaras con camara_padre_id")
    origen = _camara_origen(session, excluir=hija_id)
    ing = _ingreso(session, origen)
    session.commit()

    resultado = ics.mover_ingreso_web(session, ingreso_id=ing.id, camara_destino_id=hija_id,
                                      cromo_botella_destino_n_id=None, motivo="prueba", usuario=USUARIO)

    assert resultado.resultado == ics.RESULTADO_DESTINO_NO_RAIZ
    session.expire_all()
    assert session.get(Ingreso, ing.id).camara_id == origen.id
    (fila,) = _auditoria(session, ing.id, ics.COMANDO_MOVER_INGRESO)
    assert fila.resultado == ics.RESULTADO_DESTINO_NO_RAIZ
