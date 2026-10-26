# Nombre de archivo: test_camara_estado_contexto_batch_real_db.py
# Ubicación de archivo: tests/test_camara_estado_contexto_batch_real_db.py
# Descripción: Equivalencia del contexto de estado de Cámara por lote contra el por fila, sobre datos reales de dev

"""`get_camara_estado_contexto_batch` reemplaza al por fila en los listados del panel (N+1). Este
test compara las dos versiones cámara por cámara sobre la DB de dev, con incidentes, ingresos y un
baneo manual sintéticos creados dentro de una transacción que se revierte al terminar (en dev no hay
incidentes activos: sin ellos el test sólo compararía contextos vacíos)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from core.services.camara_estado_service import get_camara_estado_contexto, get_camara_estado_contexto_batch
from db.models.infra import CamaraEstado, IncidenteBaneo, Ingreso, IngresoTipo
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real

TECNICO = "TEST-CONTEXTO-BATCH"


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


def _grupo_con_rutas(s: Session) -> tuple[int, int, int, str]:
    """(raíz, botella, ruta, servicio): una botella legado cuyo empalme tiene una ruta con servicio."""
    fila = s.execute(
        text(
            """
            SELECT c.camara_padre_id, c.id, r.id, sv.servicio_id
            FROM app.camaras c
            JOIN app.empalmes e ON e.camara_id = c.id
            JOIN app.ruta_empalme_association re ON re.empalme_id = e.id
            JOIN app.rutas_servicio r ON r.id = re.ruta_id
            JOIN app.servicios sv ON sv.id = r.servicio_id
            WHERE c.camara_padre_id IS NOT NULL AND sv.servicio_id IS NOT NULL
            ORDER BY c.id, r.id
            LIMIT 1
            """
        )
    ).first()
    assert fila is not None, "dev necesita al menos una botella legado con rutas"
    return fila[0], fila[1], fila[2], fila[3]


def _otra_ruta_del_servicio(s: Session, servicio_id: str, excluir_ruta: int) -> int | None:
    return s.execute(
        text(
            """
            SELECT r.id FROM app.rutas_servicio r JOIN app.servicios sv ON sv.id = r.servicio_id
            WHERE sv.servicio_id = :sid AND r.id <> :rid ORDER BY r.id LIMIT 1
            """
        ),
        {"sid": servicio_id, "rid": excluir_ruta},
    ).scalar()


def _incidente(s: Session, servicio_id: str, *, ruta_id: int | None, ticket: str | None, inicio: datetime) -> None:
    s.add(
        IncidenteBaneo(
            ticket_asociado=ticket,
            servicio_afectado_id=servicio_id,
            servicio_protegido_id=servicio_id,
            ruta_protegida_id=ruta_id,
            usuario_ejecutor=TECNICO,
            motivo="test contexto batch",
            fecha_inicio=inicio,
            activo=True,
        )
    )


def _muestra_de_ids(s: Session, extra: list[int]) -> list[int]:
    """Todas las botellas legado y sus raíces, cámaras con ingresos y un tramo de raíces sueltas."""
    ids = s.execute(
        text(
            """
            (SELECT id FROM app.camaras WHERE camara_padre_id IS NOT NULL)
            UNION (SELECT camara_padre_id FROM app.camaras WHERE camara_padre_id IS NOT NULL)
            UNION (SELECT DISTINCT camara_id FROM app.ingresos WHERE camara_id IS NOT NULL LIMIT 100)
            UNION (SELECT id FROM app.camaras WHERE camara_padre_id IS NULL ORDER BY id LIMIT 300)
            """
        )
    ).scalars().all()
    return sorted(set(ids) | set(extra))


def test_batch_equivale_a_por_fila(session):
    raiz_id, botella_id, ruta_id, servicio_id = _grupo_con_rutas(session)
    ahora = datetime.now(timezone.utc)

    # Incidente de servicio completo + dos con la misma fecha (el desempate decide `ticket_baneo`).
    _incidente(session, servicio_id, ruta_id=None, ticket=None, inicio=ahora - timedelta(hours=3))
    _incidente(session, servicio_id, ruta_id=ruta_id, ticket="TK-EMPATE-1", inicio=ahora - timedelta(hours=1))
    _incidente(session, servicio_id, ruta_id=ruta_id, ticket="TK-EMPATE-2", inicio=ahora - timedelta(hours=1))
    otra_ruta = _otra_ruta_del_servicio(session, servicio_id, ruta_id)
    if otra_ruta is not None:  # incidente de otra ruta del mismo servicio: no afecta a este grupo
        _incidente(session, servicio_id, ruta_id=otra_ruta, ticket="TK-OTRA-RUTA", inicio=ahora)

    # Ingreso abierto en la botella y baneo manual en otra raíz cualquiera.
    session.add(
        Ingreso(
            camara_id=botella_id,
            tecnico_id=TECNICO,
            tipo=IngresoTipo.INGRESO,
            fecha_inicio=ahora - timedelta(minutes=30),
            fecha_fin=None,
        )
    )
    baneada_id = session.execute(
        text("SELECT id FROM app.camaras WHERE camara_padre_id IS NULL AND estado <> 'BANEADA' ORDER BY id LIMIT 1")
    ).scalar()
    session.execute(text("UPDATE app.camaras SET estado = 'BANEADA' WHERE id = :id"), {"id": baneada_id})
    session.flush()

    inexistente = session.execute(text("SELECT coalesce(max(id), 0) + 1000 FROM app.camaras")).scalar()
    ids = _muestra_de_ids(session, [raiz_id, botella_id, baneada_id])

    session.expunge_all()  # el lote arranca con la sesión vacía: tiene que cargar todo él solo
    por_lote = {cid: ctx.to_dict() for cid, ctx in get_camara_estado_contexto_batch(session, [*ids, inexistente]).items()}

    session.expunge_all()
    por_fila = {}
    for cid in ids:
        ctx = get_camara_estado_contexto(session, cid)
        assert ctx is not None
        por_fila[cid] = ctx.to_dict()

    assert get_camara_estado_contexto(session, inexistente) is None
    assert inexistente not in por_lote
    assert set(por_lote) == set(ids)
    distintos = [cid for cid in ids if por_lote[cid] != por_fila[cid]]
    assert distintos == [], f"{len(distintos)} cámaras difieren, p.ej. {distintos[:5]}"

    # Los casos sintéticos tienen que haber ejercitado las ramas no triviales.
    for cid in (raiz_id, botella_id):
        ctx = por_lote[cid]
        assert ctx["tiene_incidente_activo"] and ctx["tiene_ingreso_activo"]
        assert ctx["ticket_baneo"] == "TK-EMPATE-2"  # mismo fecha_inicio: gana el id mayor
        assert "TK-OTRA-RUTA" not in {i["ticket_asociado"] for i in ctx["incidentes_activos"]}
    assert por_lote[baneada_id]["tiene_baneo_activo"] is True
    assert por_lote[baneada_id]["estado_actual"] == CamaraEstado.BANEADA.value


def _contar_queries(session: Session, ids: list[int]) -> int:
    from db.session import engine

    contador = {"n": 0}

    def _contar(*_args, **_kwargs):
        contador["n"] += 1

    event.listen(engine, "before_cursor_execute", _contar)
    try:
        session.expunge_all()
        get_camara_estado_contexto_batch(session, ids)
    finally:
        event.remove(engine, "before_cursor_execute", _contar)
    return contador["n"]


def test_batch_hace_las_mismas_queries_con_5_que_con_200_camaras(session):
    # Algunas etapas sólo consultan si tienen padres (botellas, servicios): las dos muestras
    # arrancan con una botella con rutas y su raíz para que ejerciten todas.
    raiz_id, botella_id, _, _ = _grupo_con_rutas(session)
    resto = session.execute(
        text(
            """
            SELECT c.id FROM app.camaras c
            WHERE EXISTS (SELECT 1 FROM app.empalmes e WHERE e.camara_id = c.id)
              AND c.id NOT IN (:raiz, :botella)
            ORDER BY c.id LIMIT 198
            """
        ),
        {"raiz": raiz_id, "botella": botella_id},
    ).scalars().all()
    ids = [raiz_id, botella_id, *resto]
    assert len(ids) == 200, "dev necesita al menos 200 cámaras con empalmes"
    pocas, muchas = _contar_queries(session, ids[:5]), _contar_queries(session, ids)
    # 12 = cámaras, padres, raíces, botellas, 6 etapas de selectinload, incidentes e ingresos.
    # `selectinload` parte cada 500 padres: las 200 cámaras de dev tienen más de 500 empalmes y suman
    # un lote más (una sentencia cada 500 filas, no una por cámara como antes).
    assert pocas == 12
    assert muchas <= pocas + 2


def test_batch_sin_ids_no_consulta(session):
    assert _contar_queries(session, []) == 0
    assert get_camara_estado_contexto_batch(session, []) == {}
