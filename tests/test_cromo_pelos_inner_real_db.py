# Nombre de archivo: test_cromo_pelos_inner_real_db.py
# Ubicación de archivo: tests/test_cromo_pelos_inner_real_db.py
# Descripción: fase_pelos_inner contra Postgres real — at.62/at.63 persistidos y conciliación de cromo_servicio_match, todo en una transacción revertida

"""Réplica del caso real F-PE-AL-99 (2026-09-30) con ids sintéticos, contra el esquema real:

- el pelo 1 conserva su servicio por texto (`REGEX_EXACTO`);
- el pelo 32 gana el servicio que sólo declara `at.62`, resuelto por alias al ID vigente;
- el pelo 4 (ATENUADO, servicio migrado al pelo 1) no toma su `at.62` viejo;
- un vínculo por texto viejo (el texto del pelo cambió) se retira; uno `MANUAL` no se toca;
- un pelo que la ingesta nunca trajo se crea con su tubo.

Todo corre en una transacción externa que se revierte al final (`join_transaction_mode=
"create_savepoint"`, el mismo mecanismo del dry-run del script): no deja nada en la base de dev.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from db.session import async_engine
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real

CABLE = 990_000_001
TUBO_1, TUBO_3, TUBO_NUEVO = 990_000_011, 990_000_013, 990_000_019
P1, P4, P32, P33, P_NUEVO = 990_000_101, 990_000_104, 990_000_132, 990_000_133, 990_000_199
NUM_TEXTO, NUM_ALIAS, NUM_VIGENTE, NUM_VIEJO, NUM_MANUAL = "999801", "999802", "999803", "999804", "999805"


def _at(id_: int, valor: str, vfrom: int = 1) -> dict[str, Any]:
    return {"id": id_, "value": valor, "vfrom": vfrom}


def _pelo(id_: int, tubo: int, numero: str, *ats: dict[str, Any]) -> dict[str, Any]:
    return {"id": id_, "class": 130, "at": [_at(70, str(CABLE)), _at(71, str(tubo)), _at(75, numero), *ats]}


def _tubo(id_: int, orden: int) -> dict[str, Any]:
    return {"id": id_, "class": 129, "at": [_at(70, str(CABLE)), _at(71, str(CABLE)), _at(72, str(orden))]}


INNER = {
    "response": [
        _tubo(TUBO_1, 0),
        _tubo(TUBO_3, 2),
        _tubo(TUBO_NUEVO, 5),
        _pelo(P1, TUBO_1, "1", _at(62, "0", 1), _at(62, NUM_TEXTO, 9), _at(61, f"TLS {NUM_TEXTO} - CLIENTE")),
        _pelo(P4, TUBO_1, "4", _at(62, NUM_TEXTO), _at(61, "ATENUADO 2 DB A LOS 60 MTS")),
        _pelo(P32, TUBO_3, "32", _at(61, "Mz 002-025 IAAS TECO P2"), _at(62, NUM_ALIAS), _at(63, "Utilizado")),
        _pelo(P33, TUBO_3, "33"),
        _pelo(P_NUEVO, TUBO_NUEVO, "61", _at(61, "LIBRE"), _at(62, "0"), _at(63, "Libre")),
    ]
}


class _ClienteInnerFake:
    def __init__(self) -> None:
        self.pedidos: list[int] = []

    async def get_inner(self, n_id: int) -> dict[str, Any]:
        self.pedidos.append(n_id)
        return INNER


async def _sembrar(s: AsyncSession) -> None:
    await s.execute(
        text(
            "INSERT INTO app.cromo_tubos (n_id, cable_n_id, orden) VALUES (:t1, :c, 0), (:t3, :c, 2)"
        ),
        {"t1": TUBO_1, "t3": TUBO_3, "c": CABLE},
    )
    await s.execute(
        text(
            """
            INSERT INTO app.cromo_pelos (n_id, tubo_n_id, cable_n_id, numero_pelo, servicio_raw, servicio_numero, tipo_asociacion)
            VALUES (:p1, :t1, :c, '1', :raw1, :n1, 'CLIENTE'),
                   (:p4, :t1, :c, '4', :raw4, :nviejo, 'CLIENTE'),
                   (:p32, :t3, :c, '32', NULL, NULL, 'INDETERMINADO'),
                   (:p33, :t3, :c, '33', NULL, NULL, 'INDETERMINADO')
            """
        ),
        {
            "p1": P1, "p4": P4, "p32": P32, "p33": P33, "t1": TUBO_1, "t3": TUBO_3, "c": CABLE,
            "raw1": f"TLS {NUM_TEXTO} - CLIENTE", "n1": NUM_TEXTO,
            "raw4": f"TLS {NUM_VIEJO} - TEXTO VIEJO", "nviejo": NUM_VIEJO,
        },
    )
    # NUM_ALIAS (el at.62 del pelo 32) es alias del servicio vigente NUM_VIGENTE, como 56747 → 116550.
    ids = {}
    for numero, alias in ((NUM_TEXTO, None), (NUM_VIGENTE, [NUM_ALIAS]), (NUM_VIEJO, None), (NUM_MANUAL, None)):
        fila = await s.execute(
            text(
                "INSERT INTO app.servicios (servicio_id, numero_primer_servicio, categoria, alias_ids) "
                "VALUES (:n, :n, 0, :alias) RETURNING id"
            ),
            {"n": numero, "alias": alias or []},
        )
        ids[numero] = fila.scalar_one()
    await s.execute(
        text(
            "INSERT INTO app.cromo_servicio_match (pelo_n_id, servicio_numero, servicio_id, metodo, confianza) "
            "VALUES (:p1, :n1, :s1, 'REGEX_EXACTO', 100), (:p4, :nv, :sv, 'REGEX_EXACTO', 100), "
            "(:p33, :nm, :sm, 'MANUAL', 100)"
        ),
        {
            "p1": P1, "n1": NUM_TEXTO, "s1": ids[NUM_TEXTO],
            "p4": P4, "nv": NUM_VIEJO, "sv": ids[NUM_VIEJO],
            "p33": P33, "nm": NUM_MANUAL, "sm": ids[NUM_MANUAL],
        },
    )
    return ids


@pytest.mark.asyncio
async def test_fase_pelos_inner_caso_f_pe_al_99():
    from core.services.cromo import ingesta

    engine = create_async_engine(async_engine.url.render_as_string(hide_password=False), poolclass=NullPool)
    async with engine.connect() as conn:
        externa = await conn.begin()
        try:
            async with AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False) as s:
                ids = await _sembrar(s)
                corrida = await ingesta.iniciar_corrida(
                    s, usuario="test", psize=0, max_paginas=None, clases=(),
                    params_extra={"tipo": "TEST_PELOS_INNER"},
                )
                cliente = _ClienteInnerFake()
                contadores = ingesta.ContadoresCorrida()
                resumen = await ingesta.fase_pelos_inner(
                    cliente, s, corrida, contadores, cables=[CABLE], concurrencia=2, rate_per_second=1000, detallar=True
                )

                assert cliente.pedidos == [CABLE]
                assert resumen.cables_ok == 1 and resumen.cables_error == 0
                assert resumen.pelos_leidos == 5 and resumen.pelos_nuevos == 1 and resumen.tubos_nuevos == 1

                matches = {
                    (r.pelo_n_id, r.servicio_numero): (r.servicio_id, r.metodo)
                    for r in (
                        await s.execute(
                            text(
                                "SELECT pelo_n_id, servicio_numero, servicio_id, metodo FROM app.cromo_servicio_match "
                                "WHERE pelo_n_id = ANY(:ids)"
                            ),
                            {"ids": [P1, P4, P32, P33, P_NUEVO]},
                        )
                    ).all()
                }
                assert matches == {
                    (P1, NUM_TEXTO): (ids[NUM_TEXTO], "REGEX_EXACTO"),
                    (P32, NUM_ALIAS): (ids[NUM_VIGENTE], "ATRIBUTO_PELO"),
                    (P33, NUM_MANUAL): (ids[NUM_MANUAL], "MANUAL"),
                }
                assert resumen.vinculos_retirados == {"REGEX_EXACTO": 1}
                assert resumen.vinculos_creados == {"ATRIBUTO_PELO": 1}
                assert resumen.pelos_con_manual == 1

                pelos = {
                    r.n_id: r
                    for r in (
                        await s.execute(
                            text(
                                "SELECT n_id, servicio_raw, servicio_numero, servicio_atributo, estado_cromo, "
                                "atributos_leidos_at, tubo_n_id FROM app.cromo_pelos WHERE cable_n_id = :c"
                            ),
                            {"c": CABLE},
                        )
                    ).all()
                }
                assert pelos[P1].servicio_atributo == NUM_TEXTO  # el at.62 vigente, no el "0" viejo
                assert pelos[P4].servicio_raw == "ATENUADO 2 DB A LOS 60 MTS" and pelos[P4].servicio_numero is None
                assert pelos[P32].estado_cromo == "Utilizado"
                assert pelos[P_NUEVO].tubo_n_id == TUBO_NUEVO and pelos[P_NUEVO].estado_cromo == "Libre"
                assert all(p.atributos_leidos_at is not None for p in pelos.values())

                eventos = (
                    await s.execute(
                        text("SELECT accion, n_id FROM app.cromo_ingesta_eventos WHERE corrida_id = :id"),
                        {"id": corrida.id},
                    )
                ).all()
                assert ("CABLE_INNER_OK", CABLE) in [tuple(e) for e in eventos]
                assert ("MATCH_RETIRADO", P4) in [tuple(e) for e in eventos]

                # Reanudar la misma corrida no vuelve a pedir el cable.
                cliente2 = _ClienteInnerFake()
                await ingesta.fase_pelos_inner(
                    cliente2, s, corrida, ingesta.ContadoresCorrida(), cables=[CABLE], reanudar=True, concurrencia=2, rate_per_second=1000
                )
                assert cliente2.pedidos == []
        finally:
            await externa.rollback()
    await engine.dispose()
