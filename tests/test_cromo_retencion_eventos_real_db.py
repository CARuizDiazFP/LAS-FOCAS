# Nombre de archivo: test_cromo_retencion_eventos_real_db.py
# Ubicación de archivo: tests/test_cromo_retencion_eventos_real_db.py
# Descripción: Retención de cromo_ingesta_eventos contra Postgres real — corte, SIN_CAMBIOS históricos y corridas EN_CURSO, en una transacción revertida

"""Eventos sintéticos fechados en el año 2000, con un corte en 2001: así los conteos y el borrado
sólo alcanzan a estas filas aunque `focas_dev` tenga cientos de miles de eventos reales (el más
viejo es de 2026-08). Todo corre dentro de una transacción externa que se revierte.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from core.services.cromo import retencion_eventos
from db.session import async_engine
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real

VIEJO = datetime(2000, 1, 1, tzinfo=timezone.utc)
CORTE = datetime(2001, 1, 1, tzinfo=timezone.utc)
RECIENTE = datetime(2002, 1, 1, tzinfo=timezone.utc)


async def _corrida(s: AsyncSession, estado: str) -> int:
    fila = await s.execute(
        text(
            "INSERT INTO app.cromo_ingesta_corridas (usuario, estado, params, iniciada_at) "
            "VALUES ('TEST-RETENCION', :estado, '{}', :t) RETURNING id"
        ),
        {"estado": estado, "t": VIEJO},
    )
    return fila.scalar_one()


async def _evento(s: AsyncSession, corrida_id: int, accion: str, creado: datetime) -> int:
    fila = await s.execute(
        text(
            "INSERT INTO app.cromo_ingesta_eventos (corrida_id, accion, created_at) "
            "VALUES (:c, :a, :t) RETURNING id"
        ),
        {"c": corrida_id, "a": accion, "t": creado},
    )
    return fila.scalar_one()


async def _existentes(s: AsyncSession, ids: list[int]) -> set[int]:
    filas = await s.execute(text("SELECT id FROM app.cromo_ingesta_eventos WHERE id = ANY(:ids)"), {"ids": ids})
    return {fila[0] for fila in filas.all()}


@pytest.mark.asyncio
async def test_retencion_borra_solo_lo_anterior_al_corte_y_respeta_en_curso():
    engine = create_async_engine(async_engine.url.render_as_string(hide_password=False), poolclass=NullPool)
    async with engine.connect() as conn:
        externa = await conn.begin()
        try:
            s = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
            cerrada = await _corrida(s, "OK")
            en_curso = await _corrida(s, "EN_CURSO")
            viejo_creada = await _evento(s, cerrada, "CREADA", VIEJO)
            viejo_error = await _evento(s, cerrada, "ERROR", VIEJO)
            reciente_creada = await _evento(s, cerrada, "CREADA", RECIENTE)
            reciente_sin_cambios = await _evento(s, cerrada, "SIN_CAMBIOS", RECIENTE)
            viejo_en_curso = await _evento(s, en_curso, "CABLE_INNER_OK", VIEJO)
            todos = [viejo_creada, viejo_error, reciente_creada, reciente_sin_cambios, viejo_en_curso]

            # Dry-run: cuenta sin borrar. Con SIN_CAMBIOS, el reciente suma (y también los reales de dev).
            assert await retencion_eventos.contar_purgables(s, CORTE, incluir_sin_cambios=False) == {
                "CREADA": 1,
                "ERROR": 1,
            }
            con_sin_cambios = await retencion_eventos.contar_purgables(s, CORTE, incluir_sin_cambios=True)
            assert con_sin_cambios["CREADA"] == 1 and con_sin_cambios["ERROR"] == 1
            assert con_sin_cambios["SIN_CAMBIOS"] >= 1
            assert "CABLE_INNER_OK" not in con_sin_cambios
            assert await _existentes(s, todos) == set(todos)

            # Lote chico frente al rango real de ids de dev: fuerza varios lotes.
            resultado = await retencion_eventos.purgar_eventos(
                s, CORTE, incluir_sin_cambios=False, lote_ids=100_000, commit_por_lote=False
            )
            assert resultado.borrados == 2
            assert resultado.lotes >= 2
            assert await _existentes(s, todos) == {reciente_creada, reciente_sin_cambios, viejo_en_curso}
            corridas = await s.execute(
                text("SELECT count(*) FROM app.cromo_ingesta_corridas WHERE id = ANY(:ids)"),
                {"ids": [cerrada, en_curso]},
            )
            assert corridas.scalar_one() == 2  # las corridas (con sus contadores) se conservan

            # Sin nada purgable no recorre la tabla.
            vacio = await retencion_eventos.purgar_eventos(
                s, CORTE, incluir_sin_cambios=False, commit_por_lote=False
            )
            assert (vacio.borrados, vacio.lotes) == (0, 0)
            await s.close()
        finally:
            await externa.rollback()
    await engine.dispose()
