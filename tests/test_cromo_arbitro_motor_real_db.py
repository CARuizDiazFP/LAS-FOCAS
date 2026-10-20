# Nombre de archivo: test_cromo_arbitro_motor_real_db.py
# Ubicación de archivo: tests/test_cromo_arbitro_motor_real_db.py
# Descripción: Tests del motor del árbitro de Cromo con las reglas reales sobre la base de dev

"""Corre `evaluar` con el catálogo real `REGLAS` dentro de una transacción que se revierte. Verifica
que las cinco reglas corren sin error contra los datos reales y que en modo SOMBRA (el sembrado) no
se toca ningún dato real: sólo se escriben propuestas."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from core.services.cromo.arbitro import motor
from core.services.cromo.arbitro.motor import evaluar
from core.services.cromo.arbitro.reglas import REGLAS
from core.services.cromo.arbitro.senales import Alcance
from tests.soporte_postgres_real import requiere_postgres_real
from tests import test_cromo_arbitro_motor as _base

pytestmark = requiere_postgres_real

_CODIGOS = {r.codigo for r in REGLAS}

# Mismas fixtures que los tests con reglas fake.
entorno = _base.entorno
sin_ingesta = _base.sin_ingesta


async def _conteos(conn) -> tuple:
    return (
        await conn.execute(
            text(
                "SELECT (SELECT count(*) FROM app.cromo_servicio_odf_override), "
                "(SELECT count(*) FROM app.cromo_botella_alias), "
                "(SELECT count(*) FROM app.cromo_botellas WHERE vigente)"
            )
        )
    ).one()


async def _sombra(conn) -> None:
    await conn.execute(
        text("UPDATE app.cromo_regla_correccion SET modo = 'SOMBRA' WHERE codigo = ANY(:c)"),
        {"c": list(_CODIGOS)},
    )


@pytest.mark.asyncio
async def test_reglas_reales_alcance_sintetico_no_proponen(entorno, sin_ingesta):
    sesion, conn, _ = entorno
    await _sombra(conn)
    for alcance in (
        Alcance("SERVICIOS", (999_920_690,)),
        Alcance("BOTELLAS", (999_920_691,)),
        Alcance("ODFS", (999_920_692,)),
    ):
        r = await evaluar(sesion, alcance, "VIEWER")
        d = r.a_dict()
        assert set(d["por_regla"]) == _CODIGOS
        assert not any("error" in v for v in d["por_regla"].values()), d
        assert r.nuevas == 0 and r.aplicadas_auto == []


@pytest.mark.asyncio
async def test_reglas_reales_todo_en_sombra_no_mutan_datos(entorno, sin_ingesta):
    sesion, conn, _ = entorno
    await _sombra(conn)
    antes = await _conteos(conn)
    r = await evaluar(sesion, Alcance("TODO"), "INGESTA")
    d = r.a_dict()
    assert json.loads(json.dumps(d)) == d
    assert not any("error" in v for v in d["por_regla"].values()), d
    assert r.aplicadas_auto == []
    assert await _conteos(conn) == antes
    abiertas = (
        await conn.execute(
            text(
                "SELECT count(*) FROM app.cromo_propuesta "
                "WHERE estado IN ('PROPUESTA', 'EN_OBSERVACION') AND regla = ANY(:c)"
            ),
            {"c": list(_CODIGOS)},
        )
    ).scalar_one()
    assert abiertas >= r.nuevas
    # Segunda corrida idéntica: no crea filas nuevas (sólo actualiza).
    r2 = await evaluar(sesion, Alcance("TODO"), "INGESTA")
    assert r2.nuevas == 0
    assert r2.actualizadas == r.nuevas + r.actualizadas


def test_motor_expone_lock_propio():
    from core.services.cromo import inconsistencias_cromo as inc

    assert motor.LOCK_ARBITRO not in (inc._LOCK_DETECTOR, inc._LOCK_CORRIDA)
