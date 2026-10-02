# Nombre de archivo: test_cromo_bajas_real_db.py
# Ubicación de archivo: tests/test_cromo_bajas_real_db.py
# Descripción: Baja lógica de un cable fantasma contra Postgres real — sucesor, regla MANUAL, tracking cache, fase SERVICIOS y reactivación, en una transacción revertida

"""Réplica sintética del caso real F-TIG-003-B (2026-10-02): el cable viejo (fantasma) murió en la
versión 275695 de Cromo, la misma en que nació su sucesor.

- `REGEX_EXACTO` del fantasma → se retira.
- `MANUAL` cuyo servicio el sucesor también tiene → se retira (regla del usuario).
- `MANUAL` cuyo servicio el sucesor NO tiene → se conserva y se informa.
- El tracking cache del pelo fantasma se borra; cable, tubo y pelos quedan `vigente = false`.
- La fase SERVICIOS no vuelve a vincular un pelo no vigente.
- Si Cromo lo vuelve a listar, `reactivar_cable` enciende cable, tubo y pelos.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from db.session import async_engine
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real

FANTASMA, SUCESOR = 990_100_001, 990_100_002
BOT_A, BOT_B = 990_100_901, 990_100_902
TUBO_F, TUBO_S = 990_100_011, 990_100_012
PF1, PF2, PF3, PS1 = 990_100_101, 990_100_102, 990_100_103, 990_100_201
NUM_A, NUM_B = "999901", "999902"
VTO = 275695


async def _sembrar(s: AsyncSession) -> dict[str, int]:
    await s.execute(
        text(
            "INSERT INTO app.cromo_cables (n_id, version_id, vmax, clase, nombre, extremo_a_n_id, extremo_b_n_id, payload_raw) "
            "VALUES (:f, :f, 1, 51, 'F-TEST-FANTASMA', :a, :b, '{\"vfrom\": 125836}'), "
            "       (:s, :s, 2, 51, 'F-TEST-FANTASMA', :a, :b, CAST(:payload AS jsonb))"
        ),
        {"f": FANTASMA, "s": SUCESOR, "a": BOT_A, "b": BOT_B, "payload": f'{{"vfrom": {VTO}}}'},
    )
    await s.execute(
        text("INSERT INTO app.cromo_tubos (n_id, cable_n_id, orden) VALUES (:tf, :f, 0), (:ts, :s, 0)"),
        {"tf": TUBO_F, "ts": TUBO_S, "f": FANTASMA, "s": SUCESOR},
    )
    await s.execute(
        text(
            "INSERT INTO app.cromo_pelos (n_id, tubo_n_id, cable_n_id, numero_pelo, servicio_raw, servicio_numero) "
            "VALUES (:pf1, :tf, :f, '1', :rawa, :na), (:pf2, :tf, :f, '2', NULL, NULL), "
            "       (:pf3, :tf, :f, '3', NULL, NULL), (:ps1, :ts, :s, '1', :rawa, :na)"
        ),
        {"pf1": PF1, "pf2": PF2, "pf3": PF3, "ps1": PS1, "tf": TUBO_F, "ts": TUBO_S, "f": FANTASMA, "s": SUCESOR,
         "rawa": f"TLS {NUM_A}", "na": NUM_A},
    )
    ids = {}
    for numero in (NUM_A, NUM_B):
        fila = await s.execute(
            text("INSERT INTO app.servicios (servicio_id, numero_primer_servicio, categoria) VALUES (:n, :n, 0) RETURNING id"),
            {"n": numero},
        )
        ids[numero] = fila.scalar_one()
    await s.execute(
        text(
            "INSERT INTO app.cromo_servicio_match (pelo_n_id, servicio_numero, servicio_id, metodo, confianza) VALUES "
            "(:pf1, :na, :sa, 'REGEX_EXACTO', 100), (:pf2, :na, :sa, 'MANUAL', 100), "
            "(:pf3, :nb, :sb, 'MANUAL', 100), (:ps1, :na, :sa, 'REGEX_EXACTO', 100)"
        ),
        {"pf1": PF1, "pf2": PF2, "pf3": PF3, "ps1": PS1, "na": NUM_A, "nb": NUM_B, "sa": ids[NUM_A], "sb": ids[NUM_B]},
    )
    await s.execute(
        text("INSERT INTO app.cromo_tracking_cache (pelo_n_id, nombre_archivo, contenido) VALUES (:p, 'x.txt', 'x')"),
        {"p": PF1},
    )
    return ids


async def _vigencias(s: AsyncSession) -> dict[str, set[bool]]:
    q = {
        "cable": "SELECT vigente FROM app.cromo_cables WHERE n_id = :f",
        "tubos": "SELECT vigente FROM app.cromo_tubos WHERE cable_n_id = :f",
        "pelos": "SELECT vigente FROM app.cromo_pelos WHERE cable_n_id = :f",
    }
    return {k: set((await s.execute(text(v), {"f": FANTASMA})).scalars().all()) for k, v in q.items()}


@pytest.mark.asyncio
async def test_baja_logica_de_cable_fantasma_y_reactivacion():
    from core.services.cromo import bajas_service, ingesta

    engine = create_async_engine(async_engine.url.render_as_string(hide_password=False), poolclass=NullPool)
    async with engine.connect() as conn:
        externa = await conn.begin()
        try:
            async with AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False) as s:
                await _sembrar(s)
                corrida = await ingesta.iniciar_corrida(
                    s, usuario="test", psize=0, max_paginas=None, clases=(), params_extra={"tipo": "TEST_BAJAS"}
                )

                detalle = await bajas_service.detallar_fantasma(s, FANTASMA, VTO, [FANTASMA])
                assert [(x.n_id, x.motivo) for x in detalle.sucesores] == [(SUCESOR, "vfrom=vto")]
                assert detalle.servicios == [NUM_A, NUM_B]
                assert detalle.manual_sin_cobertura == [NUM_B]

                r = await bajas_service.aplicar_baja_cable(s, corrida.id, detalle)
                assert (r.pelos, r.tubos, r.matches_retirados, r.manual_retirados, r.manual_conservados) == (3, 1, 1, 1, 1)
                assert r.tracking_borrados == 1

                assert await _vigencias(s) == {"cable": {False}, "tubos": {False}, "pelos": {False}}
                quedan = (
                    await s.execute(
                        text("SELECT pelo_n_id, metodo FROM app.cromo_servicio_match WHERE pelo_n_id = ANY(:ids)"),
                        {"ids": [PF1, PF2, PF3, PS1]},
                    )
                ).all()
                assert sorted(map(tuple, quedan)) == [(PF3, "MANUAL"), (PS1, "REGEX_EXACTO")]

                # La fase SERVICIOS no vuelve a vincular el pelo fantasma (tiene servicio_numero y ya no match).
                sin_match = (await s.execute(ingesta._SQL_PELOS_SIN_MATCH)).all()
                assert PF1 not in {f.n_id for f in sin_match}

                acciones = sorted(
                    (await s.execute(
                        text("SELECT accion FROM app.cromo_ingesta_eventos WHERE corrida_id = :id"), {"id": corrida.id}
                    )).scalars().all()
                )
                assert acciones == ["CABLE_BAJA_LOGICA", "MATCH_MANUAL_CONSERVADO", "MATCH_MANUAL_RETIRADO", "MATCH_RETIRADO"]

                await bajas_service.reactivar_cable(s, corrida.id, FANTASMA, 51)
                assert await _vigencias(s) == {"cable": {True}, "tubos": {True}, "pelos": {True}}
        finally:
            await externa.rollback()
