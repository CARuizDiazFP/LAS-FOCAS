# Nombre de archivo: test_camara_estado_service.py
# Ubicación de archivo: tests/test_camara_estado_service.py
# Descripción: Pruebas de la cascada de estado Cámara/Botella (aplicar_estado_a_grupo, miembros_del_grupo)

from __future__ import annotations

from unittest.mock import MagicMock

from core.services.camara_estado_service import aplicar_estado_a_grupo, miembros_del_grupo
from db.models.infra import Camara, CamaraEstado, CamaraOrigenDatos


def _grupo(estado_padre=CamaraEstado.LIBRE, estado_bot1=CamaraEstado.LIBRE, estado_bot2=CamaraEstado.LIBRE):
    padre = Camara(id=1, nombre="Cra Test CF", estado=estado_padre, origen_datos=CamaraOrigenDatos.INFERIDO)
    bot1 = Camara(id=2, nombre="Cra Test Bot 2 CF", estado=estado_bot1, origen_datos=CamaraOrigenDatos.TRACKING)
    bot2 = Camara(id=3, nombre="Cra Test Bot 3 CF", estado=estado_bot2, origen_datos=CamaraOrigenDatos.TRACKING)
    padre.botellas = [bot1, bot2]
    return padre, bot1, bot2


def test_miembros_del_grupo_desde_la_raiz_incluye_toda_la_raiz_y_botellas() -> None:
    padre, bot1, bot2 = _grupo()
    miembros = miembros_del_grupo(padre)
    assert {m.id for m in miembros} == {1, 2, 3}


def test_miembros_del_grupo_desde_una_botella_resuelve_el_mismo_grupo() -> None:
    padre, bot1, bot2 = _grupo()
    miembros = miembros_del_grupo(bot1)
    assert {m.id for m in miembros} == {1, 2, 3}


def test_miembros_del_grupo_camara_sin_padre_ni_botellas_es_ella_misma() -> None:
    sola = Camara(id=42, nombre="Cra Aislada CF", estado=CamaraEstado.LIBRE)
    assert miembros_del_grupo(sola) == [sola]


def test_aplicar_estado_a_grupo_banear_una_botella_banea_padre_y_hermana() -> None:
    """Cascada completa bidireccional: banear la botella 2 debe dejar BANEADA a la raíz Y a la
    botella 3 hermana — no sólo a la botella 2 que originó la acción."""
    padre, bot1, bot2 = _grupo()
    session = MagicMock()

    auditorias = aplicar_estado_a_grupo(
        session, bot1, CamaraEstado.BANEADA, usuario="test", motivo="prueba"
    )

    assert padre.estado == CamaraEstado.BANEADA
    assert bot1.estado == CamaraEstado.BANEADA
    assert bot2.estado == CamaraEstado.BANEADA
    assert {a.camara_id for a in auditorias} == {1, 2, 3}


def test_aplicar_estado_a_grupo_banear_la_camara_banea_todas_las_botellas() -> None:
    """Dirección opuesta: banear la cámara padre directamente también cascada hacia abajo a TODAS
    sus botellas — decisión de negocio explícita (seguridad de campo: acceso a la cámara física
    pone en riesgo a todas las botellas dentro, no sólo a una)."""
    padre, bot1, bot2 = _grupo()
    session = MagicMock()

    aplicar_estado_a_grupo(session, padre, CamaraEstado.BANEADA, usuario="test", motivo="prueba")

    assert bot1.estado == CamaraEstado.BANEADA
    assert bot2.estado == CamaraEstado.BANEADA


def test_aplicar_estado_a_grupo_no_audita_miembros_que_ya_estaban_en_el_estado() -> None:
    padre, bot1, bot2 = _grupo(estado_padre=CamaraEstado.BANEADA, estado_bot1=CamaraEstado.LIBRE, estado_bot2=CamaraEstado.BANEADA)
    session = MagicMock()

    auditorias = aplicar_estado_a_grupo(session, bot1, CamaraEstado.BANEADA, usuario="test", motivo="prueba")

    # Sólo bot1 cambió (LIBRE->BANEADA); padre y bot2 ya estaban BANEADA, no generan auditoría nueva.
    assert {a.camara_id for a in auditorias} == {2}


def test_aplicar_estado_a_grupo_grupo_entero_ya_en_estado_no_hace_nada() -> None:
    padre, bot1, bot2 = _grupo(
        estado_padre=CamaraEstado.BANEADA, estado_bot1=CamaraEstado.BANEADA, estado_bot2=CamaraEstado.BANEADA
    )
    session = MagicMock()

    auditorias = aplicar_estado_a_grupo(session, padre, CamaraEstado.BANEADA, usuario="test", motivo="prueba")

    assert auditorias == []
    session.flush.assert_not_called()


def test_aplicar_estado_a_grupo_contexto_solo_en_el_objetivo_directo() -> None:
    """`estado_sugerido`/`incidentes_activos_ids` sólo describen la acción sobre el objetivo directo
    (`camara`) — las filas de auditoría de los demás miembros del grupo no deben llevar ese contexto,
    que no les pertenece."""
    padre, bot1, bot2 = _grupo()
    session = MagicMock()

    auditorias = aplicar_estado_a_grupo(
        session,
        bot1,
        CamaraEstado.BANEADA,
        usuario="test",
        motivo="prueba",
        estado_sugerido=CamaraEstado.BANEADA,
        incidentes_activos_ids=[11, 12],
    )

    auditoria_directa = next(a for a in auditorias if a.camara_id == bot1.id)
    otras = [a for a in auditorias if a.camara_id != bot1.id]

    assert auditoria_directa.estado_sugerido == CamaraEstado.BANEADA
    assert auditoria_directa.incidentes_activos == [11, 12]
    assert all(a.estado_sugerido is None and a.incidentes_activos is None for a in otras)
