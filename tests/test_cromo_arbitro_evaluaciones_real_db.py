# Nombre de archivo: test_cromo_arbitro_evaluaciones_real_db.py
# Ubicación de archivo: tests/test_cromo_arbitro_evaluaciones_real_db.py
# Descripción: Test contra Postgres real de la reconciliación de evaluaciones del árbitro interrumpidas

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from core.services.cromo.arbitro.evaluaciones import cerrar_evaluaciones_interrumpidas
from tests.soporte_postgres_real import requiere_postgres_real
from tests.test_cromo_arbitro_migracion_real_db import entorno  # noqa: F401 - fixture

pytestmark = requiere_postgres_real


@pytest.mark.asyncio
async def test_cierra_solo_en_curso_anteriores_al_arranque(entorno):
    sesion, conn = entorno
    inicio = datetime.now(timezone.utc)
    ins = (
        "INSERT INTO app.cromo_arbitro_evaluacion (disparo, alcance, estado, iniciada_en) "
        "VALUES ('VIEWER', '{\"tipo\":\"TODO\"}'::jsonb, :e, :i) RETURNING id"
    )
    ids = {}
    for clave, estado, cuando in (
        ("vieja", "EN_CURSO", inicio - timedelta(minutes=5)),
        ("nueva", "EN_CURSO", inicio + timedelta(minutes=5)),
        ("ok", "OK", inicio - timedelta(minutes=5)),
    ):
        ids[clave] = (await conn.execute(text(ins), {"e": estado, "i": cuando})).scalar()
    assert await cerrar_evaluaciones_interrumpidas(sesion, inicio) >= 1
    est = {
        r[0]: r
        for r in (
            await conn.execute(
                text("SELECT id, estado, error, terminada_en FROM app.cromo_arbitro_evaluacion WHERE id = ANY(:i)"),
                {"i": list(ids.values())},
            )
        ).all()
    }
    assert est[ids["vieja"]][1:3] == ("FALLIDA", "interrumpida") and est[ids["vieja"]][3] is not None
    assert est[ids["nueva"]][1] == "EN_CURSO"
    assert est[ids["ok"]][1] == "OK"
