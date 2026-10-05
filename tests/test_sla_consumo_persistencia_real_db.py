# Nombre de archivo: test_sla_consumo_persistencia_real_db.py
# Ubicación de archivo: tests/test_sla_consumo_persistencia_real_db.py
# Descripción: Ingesta idempotente del histórico SLA consumido contra Postgres real

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest
from sqlalchemy import text

from core.sla_consumo.parser import RECLAMOS_COLS, SERVICIOS_COLS
from core.sla_consumo.persistencia import cargar_ventana, ingerir
from core.utils.excel_duraciones import TZ_AR
from db.session import SessionLocal
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real
_PREFIJO = "TSTSLA"  # nunca colisiona con números reales (son enteros)


def _reclamos(netas: float, extra: bool = False) -> pd.DataFrame:
    base = {c: None for c in RECLAMOS_COLS}
    filas = [
        {**base, "numero_reclamo": f"{_PREFIJO}1", "numero_linea": f"{_PREFIJO}L1", "nombre_cliente": "X",
         "fecha_inicio": pd.Timestamp("2026-09-01 10:00", tz=TZ_AR),
         "fecha_cierre": pd.Timestamp("2026-09-01 20:00", tz=TZ_AR), "horas_netas": netas,
         "tipo_solucion": "Carrier", "grupo_cierre": "Carrier"},
    ]
    if extra:
        filas.append({**filas[0], "numero_reclamo": f"{_PREFIJO}2",
                      "fecha_inicio": pd.Timestamp("2026-09-20 10:00", tz=TZ_AR),
                      "fecha_cierre": pd.Timestamp("2026-09-21 10:00", tz=TZ_AR)})
    return pd.DataFrame(filas, columns=RECLAMOS_COLS)


def _servicios() -> pd.DataFrame:
    base = {c: None for c in SERVICIOS_COLS}
    return pd.DataFrame([{**base, "numero_linea": f"{_PREFIJO}L1", "nombre_cliente": "X",
                          "sla_prometido": 99.7, "sla_entregado": 0.999, "horas_reclamos_todos": 10.0}],
                        columns=SERVICIOS_COLS)


@pytest.fixture
def limpiar():
    yield
    with SessionLocal() as s:
        s.execute(text("DELETE FROM app.reclamos WHERE numero_reclamo LIKE :p"), {"p": f"{_PREFIJO}%"})
        s.execute(text("DELETE FROM app.servicio_sla_snapshot WHERE numero_linea LIKE :p"), {"p": f"{_PREFIJO}%"})
        s.execute(text("DELETE FROM app.sla_ingestas WHERE hash_servicios LIKE :p"), {"p": f"{_PREFIJO}%"})
        s.commit()


def test_resubir_mismo_par_no_duplica(limpiar):
    r1 = ingerir(_servicios(), _reclamos(10.0), hash_servicios=f"{_PREFIJO}s1", hash_reclamos="r1", usuario="t")
    r2 = ingerir(_servicios(), _reclamos(10.0), hash_servicios=f"{_PREFIJO}s1", hash_reclamos="r1", usuario="t")
    assert (r1.reclamos_insertados, r1.ya_ingestado) == (1, False)
    assert r2.ya_ingestado is True and r2.ingesta_id == r1.ingesta_id
    assert r1.fecha_corte == dt.date(2026, 9, 1)


def test_par_solapado_actualiza_y_agrega(limpiar):
    ingerir(_servicios(), _reclamos(10.0), hash_servicios=f"{_PREFIJO}s1", hash_reclamos="r1", usuario="t")
    r = ingerir(_servicios(), _reclamos(12.5, extra=True), hash_servicios=f"{_PREFIJO}s2", hash_reclamos="r2", usuario="t")
    assert (r.reclamos_insertados, r.reclamos_actualizados) == (1, 1)
    reclamos, servicios = cargar_ventana(r.fecha_corte)
    mios = reclamos[reclamos["numero_reclamo"].str.startswith(_PREFIJO)]
    assert len(mios) == 2
    assert mios.set_index("numero_reclamo").loc[f"{_PREFIJO}1", "horas_netas"] == pytest.approx(12.5)
    assert f"{_PREFIJO}L1" in set(servicios["numero_linea"])
    with SessionLocal() as s:
        fotos = s.execute(text("SELECT COUNT(*) FROM app.servicio_sla_snapshot WHERE numero_linea = :l"),
                          {"l": f"{_PREFIJO}L1"}).scalar_one()
    assert fotos == 2  # una por fecha de corte (2026-09-01 y 2026-09-21)


def test_duplicado_en_mismo_df_gana_el_ultimo(limpiar):
    df = pd.concat([_reclamos(1.0), _reclamos(7.0)], ignore_index=True)
    r = ingerir(_servicios(), df, hash_servicios=f"{_PREFIJO}s3", hash_reclamos="r3", usuario="t")
    assert (r.reclamos_insertados, r.reclamos_actualizados) == (1, 0)
    with SessionLocal() as s:
        h = s.execute(text("SELECT horas_netas FROM app.reclamos WHERE numero_reclamo = :n"),
                      {"n": f"{_PREFIJO}1"}).scalar_one()
    assert float(h) == pytest.approx(7.0)


def test_legacy_preserva_no_nulos_y_linaje(limpiar):
    from sqlalchemy import update

    from core.services.repetitividad import upsert_reclamos
    from db.models.reclamo import Reclamo

    r = ingerir(_servicios(), _reclamos(10.0), hash_servicios=f"{_PREFIJO}s4", hash_reclamos="r4", usuario="t")
    with SessionLocal() as s:
        s.execute(update(Reclamo).where(Reclamo.numero_reclamo == f"{_PREFIJO}1").values(latitud=-34.6, descripcion_solucion="ok"))
        s.commit()
    nuevo = _reclamos(11.0)
    nuevo["latitud"] = pd.NA
    nuevo["descripcion_solucion"] = pd.NA
    assert upsert_reclamos(nuevo) == (0, 1)
    with SessionLocal() as s:
        fila = s.execute(text("SELECT latitud, descripcion_solucion, horas_netas, ingesta_id FROM app.reclamos "
                              "WHERE numero_reclamo = :n"), {"n": f"{_PREFIJO}1"}).one()
    assert float(fila.latitud) == pytest.approx(-34.6)
    assert fila.descripcion_solucion == "ok"
    assert float(fila.horas_netas) == pytest.approx(11.0)
    assert fila.ingesta_id == r.ingesta_id
