# Nombre de archivo: test_servicio_empalme_association_retiro_real_db.py
# Ubicación de archivo: tests/test_servicio_empalme_association_retiro_real_db.py
# Descripción: Integración contra Postgres real de la fase A del retiro de app.servicio_empalme_association (P22)

"""Desde la migración `20261029_01` nadie escribe ni limpia la tabla legada: sus FK son
`ON DELETE CASCADE`, así que borrar un servicio o un empalme con filas legadas no puede fallar.
Antes, con las FK sin `ON DELETE`, el `DELETE FROM app.servicios` de la fusión PROV o de los
placeholders fallaba si el código no limpiaba la tabla primero.

Todo corre en una transacción que se revierte: nunca toca datos reales de dev.
"""

from __future__ import annotations

from sqlalchemy import text

from db.session import SessionLocal
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real

_NUMERO = "9999801"


def _sembrar(s) -> tuple[int, int]:
    servicio_id = s.execute(
        text("INSERT INTO app.servicios (servicio_id) VALUES (:n) RETURNING id"), {"n": _NUMERO}
    ).scalar_one()
    empalme_id = s.execute(
        text("INSERT INTO app.empalmes (tracking_empalme_id) VALUES (:t) RETURNING id"), {"t": f"{_NUMERO}_1"}
    ).scalar_one()
    s.execute(
        text("INSERT INTO app.servicio_empalme_association (servicio_id, empalme_id) VALUES (:s, :e)"),
        {"s": servicio_id, "e": empalme_id},
    )
    return servicio_id, empalme_id


def _filas_legadas(s, servicio_id: int) -> int:
    return s.execute(
        text("SELECT count(*) FROM app.servicio_empalme_association WHERE servicio_id = :s"), {"s": servicio_id}
    ).scalar_one()


def test_borrar_servicio_con_filas_legadas_las_borra_en_cascada():
    with SessionLocal() as s:
        try:
            servicio_id, _ = _sembrar(s)
            s.execute(text("DELETE FROM app.servicios WHERE id = :s"), {"s": servicio_id})
            assert _filas_legadas(s, servicio_id) == 0
        finally:
            s.rollback()


def test_borrar_empalme_con_filas_legadas_las_borra_en_cascada():
    with SessionLocal() as s:
        try:
            servicio_id, empalme_id = _sembrar(s)
            s.execute(text("DELETE FROM app.empalmes WHERE id = :e"), {"e": empalme_id})
            assert _filas_legadas(s, servicio_id) == 0
        finally:
            s.rollback()
