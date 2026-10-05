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


def _horas(numero: str) -> float:
    with SessionLocal() as s:
        return float(s.execute(text("SELECT horas_netas FROM app.reclamos WHERE numero_reclamo = :n"),
                               {"n": numero}).scalar_one())


def test_subida_vieja_no_pisa_reclamo_mas_nuevo(limpiar):
    nuevo = ingerir(_servicios(), _reclamos(12.5, extra=True), hash_servicios=f"{_PREFIJO}s5", hash_reclamos="r5",
                    usuario="t")                                    # corte 2026-09-21
    viejo = ingerir(_servicios(), _reclamos(3.0), hash_servicios=f"{_PREFIJO}s6", hash_reclamos="r6",
                    usuario="t")                                    # corte 2026-09-01 < 09-21
    assert nuevo.fecha_corte > viejo.fecha_corte
    assert _horas(f"{_PREFIJO}1") == pytest.approx(12.5)
    assert (viejo.reclamos_insertados, viejo.reclamos_actualizados, viejo.reclamos_sin_cambios) == (0, 0, 1)
    # mismo corte (o posterior) sí actualiza
    igual = ingerir(_servicios(), _reclamos(4.0, extra=True), hash_servicios=f"{_PREFIJO}s7", hash_reclamos="r7",
                    usuario="t")
    assert igual.reclamos_actualizados == 2 and igual.reclamos_sin_cambios == 0
    assert _horas(f"{_PREFIJO}1") == pytest.approx(4.0)


def test_fila_legacy_sin_ingesta_se_puede_pisar(limpiar):
    with SessionLocal() as s:
        s.execute(text("""INSERT INTO app.reclamos (numero_reclamo, numero_linea, nombre_cliente, fecha_inicio, horas_netas)
                          VALUES (:n, :l, 'X', now(), 99)"""), {"n": f"{_PREFIJO}1", "l": f"{_PREFIJO}L1"})
        s.commit()
    r = ingerir(_servicios(), _reclamos(3.0), hash_servicios=f"{_PREFIJO}s8", hash_reclamos="r8", usuario="t")
    assert (r.reclamos_insertados, r.reclamos_actualizados) == (0, 1)
    assert _horas(f"{_PREFIJO}1") == pytest.approx(3.0)


def test_legacy_con_tipo_solucion_sobrescribe_grupo_y_codigo(limpiar):
    from core.services.repetitividad import upsert_reclamos

    ingerir(_servicios(), _reclamos(10.0), hash_servicios=f"{_PREFIJO}s9", hash_reclamos="r9", usuario="t")
    nuevo = _reclamos(10.0)
    nuevo["tipo_solucion"] = "PE-Corte en bandeja (3)"
    nuevo["grupo_cierre"] = "FO Cod 3 (Corte en Bandeja)"
    nuevo["codigo_cierre"] = 3
    upsert_reclamos(nuevo)
    sin_tipo = _reclamos(10.0)
    sin_tipo["tipo_solucion"] = None
    sin_tipo["grupo_cierre"] = None
    upsert_reclamos(sin_tipo)   # sin tipo_solucion: conserva grupo/código/tipo existentes
    with SessionLocal() as s:
        fila = s.execute(text("SELECT tipo_solucion, grupo_cierre, codigo_cierre FROM app.reclamos "
                              "WHERE numero_reclamo = :n"), {"n": f"{_PREFIJO}1"}).one()
    assert (fila.tipo_solucion, fila.grupo_cierre, fila.codigo_cierre) == (
        "PE-Corte en bandeja (3)", "FO Cod 3 (Corte en Bandeja)", 3)
    # cambia a un tipo sin código: el código viejo (3) no puede sobrevivir vía COALESCE
    carrier = _reclamos(10.0)
    carrier["codigo_cierre"] = None
    upsert_reclamos(carrier)
    with SessionLocal() as s:
        fila = s.execute(text("SELECT grupo_cierre, codigo_cierre FROM app.reclamos WHERE numero_reclamo = :n"),
                         {"n": f"{_PREFIJO}1"}).one()
    assert (fila.grupo_cierre, fila.codigo_cierre) == ("Carrier", None)


def test_ventana_incluye_reclamos_que_solapan(limpiar):
    """Un reclamo iniciado antes de la ventana y cerrado dentro de ella cuenta completo."""
    corte = dt.date(2026, 9, 30)  # ventana: (2025-10-01 00:00, 2026-10-01 00:00) ART
    base = {c: None for c in RECLAMOS_COLS}
    filas = [
        ("A", "2025-09-29 10:00", "2025-10-02 10:00", 50.0),   # empieza antes, cierra dentro -> entra
        ("B", "2025-09-20 10:00", "2025-09-25 10:00", 8.0),    # termina antes -> fuera
        ("C", "2025-12-01 10:00", "2025-12-01 20:00", 10.0),   # dentro
        ("D", "2026-10-01 05:00", "2026-10-01 09:00", 4.0),    # empieza después del corte -> fuera
        ("E", "2025-09-29 10:00", None, 6.0),                  # sin cierre y antes -> fuera
    ]
    df = pd.DataFrame([{**base, "numero_reclamo": f"{_PREFIJO}{k}", "numero_linea": f"{_PREFIJO}L1",
                        "nombre_cliente": "X", "fecha_inicio": pd.Timestamp(i, tz=TZ_AR),
                        "fecha_cierre": pd.Timestamp(c, tz=TZ_AR) if c else pd.NaT, "horas_netas": h,
                        "tipo_solucion": "Carrier", "grupo_cierre": "Carrier"} for k, i, c, h in filas],
                      columns=RECLAMOS_COLS)
    ingerir(_servicios(), df, hash_servicios=f"{_PREFIJO}s10", hash_reclamos="r10", usuario="t")
    reclamos, _ = cargar_ventana(corte)
    mios = set(reclamos[reclamos["numero_reclamo"].str.startswith(_PREFIJO)]["numero_reclamo"])
    assert mios == {f"{_PREFIJO}A", f"{_PREFIJO}C"}


def test_ingesta_guarda_report_history_id(limpiar):
    r = ingerir(_servicios(), _reclamos(1.0), hash_servicios=f"{_PREFIJO}s11", hash_reclamos="r11", usuario="t",
                report_history_id=4242)
    with SessionLocal() as s:
        valor = s.execute(text("SELECT report_history_id FROM app.sla_ingestas WHERE id = :i"),
                          {"i": r.ingesta_id}).scalar_one()
    assert valor == 4242
