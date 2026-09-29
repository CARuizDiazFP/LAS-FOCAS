# Nombre de archivo: test_servicio_botellas_real_db.py
# Ubicación de archivo: tests/test_servicio_botellas_real_db.py
# Descripción: Integración contra Postgres real de core/services/servicio_botellas.py (resolución vigente/alias y SQL de las 3 capas)

"""Los tests unitarios parchean las queries; éstos las ejecutan de verdad. Cubren lo que un mock
no ve: sintaxis y tipos de asyncpg (`ANY(:ids ::bigint[])`, `split_part` + cast), el `NOT EXISTS`
anti-ambigüedad y que ningún nombre devuelto sea algo distinto de una botella de Cromo.

Crea sus propias filas sintéticas (números 99998xx, fuera de lo que SLA/Cromo asigna) y las borra
al terminar; nunca muta datos reales de dev.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.services import servicio_botellas as sb
from db.session import SessionLocal, async_engine
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real

_engine_test = create_async_engine(async_engine.url.render_as_string(hide_password=False), poolclass=NullPool)
AsyncSessionLocal = async_sessionmaker(_engine_test, expire_on_commit=False)

_VIGENTE = "9999851"
_HISTORICO = "9999852"
_SUPERADA = "9999853"


@pytest.fixture
def servicios_sinteticos():
    """Fila vigente con un alias histórico, y fila superada cuyo servicio_id fue absorbido como alias."""

    with SessionLocal() as session:
        ids = []
        for servicio_id, alias in ((_VIGENTE, [_HISTORICO, _SUPERADA]), (_SUPERADA, [])):
            ids.append(
                int(
                    session.execute(
                        text(
                            "INSERT INTO app.servicios "
                            "(servicio_id, numero_primer_servicio, alias_ids, categoria, origen_datos, estado_servicio) "
                            "VALUES (:sid, :sid, CAST(:alias AS varchar[]), 0, 'MANUAL', 'DESCONOCIDO') RETURNING id"
                        ),
                        {"sid": servicio_id, "alias": alias},
                    ).scalar_one()
                )
            )
        session.commit()
    try:
        yield ids
    finally:
        with SessionLocal() as session:
            session.execute(text("DELETE FROM app.servicios WHERE id = ANY(:ids)"), {"ids": ids})
            session.commit()


def _resolver(ident: str):
    async def _run():
        async with AsyncSessionLocal() as s:
            return await sb.resolver_servicio_por_identificador(s, ident)

    return asyncio.run(_run())


def test_resuelve_id_vigente(servicios_sinteticos) -> None:
    r = _resolver(_VIGENTE)
    assert r.servicio.id == servicios_sinteticos[0]
    assert r.es_id_vigente is True


def test_resuelve_alias_historico_a_la_fila_vigente(servicios_sinteticos) -> None:
    r = _resolver(_HISTORICO)
    assert r.servicio.id == servicios_sinteticos[0]
    assert r.servicio.servicio_id == _VIGENTE
    assert r.es_id_vigente is False


def test_fila_superada_pierde_contra_la_que_absorbio_su_id(servicios_sinteticos) -> None:
    r = _resolver(_SUPERADA)
    assert r.servicio.id == servicios_sinteticos[0], "ganó la fila huérfana cuyo servicio_id ya es alias de otra"
    assert r.es_id_vigente is False


def test_inexistente_devuelve_none() -> None:
    assert _resolver("9999899") is None


def _servicio_con_pelos() -> int | None:
    with SessionLocal() as session:
        return session.execute(
            text("SELECT servicio_id FROM app.cromo_servicio_match WHERE servicio_id IS NOT NULL LIMIT 1")
        ).scalar_one_or_none()


def test_las_tres_capas_ejecutan_y_solo_devuelven_botellas_de_cromo() -> None:
    servicio_pk = _servicio_con_pelos()
    if servicio_pk is None:
        pytest.skip("La base no tiene cromo_servicio_match poblado")

    async def _run():
        async with AsyncSessionLocal() as s:
            from datetime import datetime, timezone

            ahora = datetime.now(timezone.utc)
            capas = (
                await sb._botellas_traza_cromo(s, servicio_pk, ahora=ahora),
                await sb._botellas_ruta_legada(s, servicio_pk),
                await sb._botellas_inventario(s, servicio_pk),
            )
            return capas, await sb.botellas_de_servicio(s, servicio_pk)

    (traza, legada, inventario), resultado = asyncio.run(_run())

    assert inventario, "un servicio con pelos matcheados tiene que tener botellas en el inventario"
    assert resultado.orden_fuente != "sin_datos"
    with SessionLocal() as session:
        conocidos = set(
            session.execute(
                text("SELECT nombre FROM app.cromo_botellas WHERE nombre = ANY(:n)"), {"n": resultado.nombres}
            ).scalars()
        )
    assert set(resultado.nombres) <= conocidos
