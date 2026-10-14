# Nombre de archivo: test_fo_monitor_alcance_real_db.py
# Ubicación de archivo: tests/test_fo_monitor_alcance_real_db.py
# Descripción: Alcance de FO Monitor contra Postgres real (SQL de cables por clase y botellas de una cámara)

from sqlalchemy import text

from core.services.fo_monitor.alcance import resolver_alcance
from db.session import SessionLocal
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real


def _camara_con_varias_botellas(session):
    return session.execute(
        text(
            """
            SELECT b.camara_id
            FROM app.cromo_botellas b
            JOIN app.cromo_cables c ON c.vigente AND (c.extremo_a_n_id = b.n_id OR c.extremo_b_n_id = b.n_id)
            WHERE b.vigente AND b.camara_id IS NOT NULL
            GROUP BY b.camara_id
            HAVING count(DISTINCT b.n_id) >= 2
            ORDER BY count(DISTINCT c.n_id) DESC
            LIMIT 1
            """
        )
    ).scalar()


def test_alcance_real_objetivo_primero_y_solo_activos_verificables():
    with SessionLocal() as session:
        camara_id = _camara_con_varias_botellas(session)
        assert camara_id is not None
        alcance = resolver_alcance(session, camara_id, None)

    assert len(alcance.botellas) >= 2
    assert alcance.botella_objetivo_n_id in alcance.botellas
    assert alcance.cables, "la cámara elegida tiene cables por construcción"
    assert {c.clase for c in alcance.cables} <= {51, 52, 59, 60}
    # Objetivo primero: una vez que aparece un cable no objetivo, no vuelve a aparecer uno objetivo.
    banderas = [c.es_objetivo for c in alcance.cables]
    assert banderas == sorted(banderas, reverse=True)
    for cable in alcance.cables:
        for s in cable.servicios:
            assert s.es_verificable and (s.estado_servicio or "").lower() == "activo"
    unicos = alcance.servicios_unicos()
    assert len({s.servicio_id for s in unicos}) == len(unicos)


def test_botella_objetivo_inexistente_cae_a_botella_1():
    with SessionLocal() as session:
        camara_id = _camara_con_varias_botellas(session)
        alcance = resolver_alcance(session, camara_id, botella_objetivo_n_id=-1)
    assert alcance.botella_objetivo_n_id in alcance.botellas
