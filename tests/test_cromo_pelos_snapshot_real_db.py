# Nombre de archivo: test_cromo_pelos_snapshot_real_db.py
# Ubicación de archivo: tests/test_cromo_pelos_snapshot_real_db.py
# Descripción: importar (dry-run) y fase_pelos_desde_inventario contra Postgres real, con ids sintéticos y sin dejar datos

"""El atajo dev → prod tiene que dar lo mismo que el barrido: se importa un CSV de pelos y la
conciliación sin Cromo resuelve igual que `fase_pelos_inner` (mismo caso F-PE-AL-99 sintético que
`test_cromo_pelos_inner_real_db.py`)."""

from __future__ import annotations

import io

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from db.session import SessionLocal, async_engine
from scripts import cromo_pelos_snapshot as snap
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real

CABLE, TUBO = 990_100_001, 990_100_011
P1, P4, P32 = 990_100_101, 990_100_104, 990_100_132
NUM_TEXTO, NUM_ALIAS, NUM_VIGENTE = "999811", "999812", "999813"

CSV_PELOS = (
    "n_id,tubo_n_id,cable_n_id,numero_pelo,orden,color,servicio_raw,servicio_numero,tipo_asociacion,"
    "servicio_atributo,estado_cromo,atributos_leidos_at\n"
    f"{P1},{TUBO},{CABLE},1,0,AZ,TLS {NUM_TEXTO} - CLIENTE,{NUM_TEXTO},CLIENTE,{NUM_TEXTO},Utilizado,2026-10-01 10:00:00+00\n"
    f"{P4},{TUBO},{CABLE},4,3,MR,ATENUADO 2 DB A LOS 60 MTS,,INDETERMINADO,{NUM_TEXTO},,2026-10-01 10:00:00+00\n"
    f"{P32},{TUBO},{CABLE},32,7,NE,Mz 002-025 IAAS TECO P2,,INDETERMINADO,{NUM_ALIAS},Utilizado,2026-10-01 10:00:00+00\n"
)


def test_importar_dry_run_cuenta_y_no_deja_nada():
    with SessionLocal() as s:
        s.execute(text("INSERT INTO app.cromo_pelos (n_id, tubo_n_id, cable_n_id, numero_pelo) VALUES (:p, :t, :c, '1')"),
                  {"p": P1, "t": TUBO, "c": CABLE})
        s.commit()
    try:
        resultado = snap.importar("pelos", io.BytesIO(CSV_PELOS.encode()), aplicar=False)
        assert resultado == {"modo": "dry-run", "tabla": "pelos", "filas_csv": 3, "creadas": 2, "actualizadas": 1}
        with SessionLocal() as s:
            assert s.execute(text("SELECT count(*) FROM app.cromo_pelos WHERE cable_n_id = :c"), {"c": CABLE}).scalar_one() == 1
            assert s.execute(text("SELECT servicio_atributo FROM app.cromo_pelos WHERE n_id = :p"), {"p": P1}).scalar_one() is None
    finally:
        with SessionLocal() as s:
            s.execute(text("DELETE FROM app.cromo_pelos WHERE cable_n_id = :c"), {"c": CABLE})
            s.commit()


def test_importar_rechaza_n_id_repetidos():
    repetido = CSV_PELOS + CSV_PELOS.splitlines()[1] + "\n"
    with pytest.raises(SystemExit, match="repetidos"):
        snap.importar("pelos", io.BytesIO(repetido.encode()), aplicar=False)


@pytest.mark.asyncio
async def test_conciliar_desde_inventario_resuelve_igual_que_el_barrido():
    from core.services.cromo import ingesta

    engine = create_async_engine(async_engine.url.render_as_string(hide_password=False), poolclass=NullPool)
    async with engine.connect() as conn:
        externa = await conn.begin()
        try:
            async with AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False) as s:
                for linea in CSV_PELOS.splitlines()[1:]:
                    c = linea.split(",")
                    await s.execute(
                        text(
                            "INSERT INTO app.cromo_pelos (n_id, tubo_n_id, cable_n_id, numero_pelo, servicio_raw, "
                            "servicio_atributo, estado_cromo, atributos_leidos_at) "
                            "VALUES (:n, :t, :c, :num, :raw, NULLIF(:a62, ''), NULLIF(:a63, ''), now())"
                        ),
                        {"n": int(c[0]), "t": int(c[1]), "c": int(c[2]), "num": c[3], "raw": c[6], "a62": c[9], "a63": c[10]},
                    )
                ids = {}
                for numero, alias in ((NUM_TEXTO, []), (NUM_VIGENTE, [NUM_ALIAS])):
                    ids[numero] = (
                        await s.execute(
                            text("INSERT INTO app.servicios (servicio_id, numero_primer_servicio, categoria, alias_ids) "
                                 "VALUES (:n, :n, 0, :a) RETURNING id"),
                            {"n": numero, "a": alias},
                        )
                    ).scalar_one()
                corrida = await ingesta.iniciar_corrida(
                    s, usuario="test", psize=0, max_paginas=None, clases=(), params_extra={"tipo": "TEST_SNAPSHOT"}
                )
                resumen = await ingesta.fase_pelos_desde_inventario(
                    s, corrida, ingesta.ContadoresCorrida(), cables=[CABLE], tanda=10
                )
                matches = {
                    (r.pelo_n_id, r.servicio_numero): (r.servicio_id, r.metodo)
                    for r in (
                        await s.execute(
                            text("SELECT pelo_n_id, servicio_numero, servicio_id, metodo FROM app.cromo_servicio_match "
                                 "WHERE pelo_n_id = ANY(:ids)"),
                            {"ids": [P1, P4, P32]},
                        )
                    ).all()
                }
                assert matches == {
                    (P1, NUM_TEXTO): (ids[NUM_TEXTO], "REGEX_EXACTO"),
                    (P32, NUM_ALIAS): (ids[NUM_VIGENTE], "ATRIBUTO_PELO"),
                }
                assert resumen.cables_ok == 1 and resumen.pelos_leidos == 3

                # Reanudar la misma corrida no vuelve a procesar el cable.
                segundo = await ingesta.fase_pelos_desde_inventario(
                    s, corrida, ingesta.ContadoresCorrida(), cables=[CABLE], reanudar=True
                )
                assert segundo.cables_ok == 0
        finally:
            await externa.rollback()
    await engine.dispose()
