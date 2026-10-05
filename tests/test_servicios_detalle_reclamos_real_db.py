# Nombre de archivo: test_servicios_detalle_reclamos_real_db.py
# Ubicación de archivo: tests/test_servicios_detalle_reclamos_real_db.py
# Descripción: El detalle de servicio devuelve sus reclamos (por línea, primer servicio o alias) y fotos de SLA

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.app.main import app
from db.session import SessionLocal, async_engine, get_async_db
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real
_ORIGEN, _LINEA_VIEJA, _LINEA = "999801", "999802", "999803"
API_HEADERS = {"Authorization": "Bearer test-api-key"}


@pytest.fixture
def datos():
    with SessionLocal() as s:
        s.execute(text("""INSERT INTO app.servicios (servicio_id, numero_primer_servicio, numero_linea, nombre_cliente,
                          sla_prometido, alias_ids, estado_servicio)
                          VALUES (:o, :o, :l, 'TEST', '99,7%', ARRAY[:v], 'Activo')"""),
                  {"o": _ORIGEN, "l": _LINEA, "v": _LINEA_VIEJA})
        for numero, linea, grupo in (("TSTD1", _LINEA, "Carrier"), ("TSTD2", _LINEA_VIEJA, "FO (excepto Cod 3)"),
                                     ("TSTD3", "000000", "Carrier"), ("TSTD4", _LINEA, "Cierre Cliente")):
            s.execute(text("""INSERT INTO app.reclamos (numero_reclamo, numero_linea, nombre_cliente, fecha_inicio,
                              horas_netas, grupo_cierre) VALUES (:n, :l, 'TEST', now() - interval '10 days', 13.14, :g)"""),
                      {"n": numero, "l": linea, "g": grupo})
        s.execute(text("""INSERT INTO app.servicio_sla_snapshot (numero_linea, fecha_corte, sla_prometido, sla_entregado)
                          VALUES (:l, CURRENT_DATE, 99.7, 0.997)"""), {"l": _LINEA})
        s.commit()
    try:
        yield
    finally:
        with SessionLocal() as s:
            s.execute(text("DELETE FROM app.reclamos WHERE numero_reclamo LIKE 'TSTD%'"))
            s.execute(text("DELETE FROM app.servicio_sla_snapshot WHERE numero_linea = :l"), {"l": _LINEA})
            s.execute(text("DELETE FROM app.servicios WHERE servicio_id = :o"), {"o": _ORIGEN})
            s.commit()


@pytest.fixture
def client():
    # NullPool: TestClient corre cada request en su propio event loop; el pool global no sirve entre loops.
    engine = create_async_engine(async_engine.url.render_as_string(hide_password=False), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _override():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_async_db] = _override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_async_db, None)


def test_detalle_trae_reclamos_y_sla_historico(datos, client):
    resp = client.get("/servicios/detail", params={"id": _ORIGEN}, headers=API_HEADERS)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    reclamos = body["servicio"]["reclamos"]
    numeros = {r["numero_reclamo"] for r in reclamos}
    assert numeros == {"TSTD1", "TSTD2", "TSTD4"}  # por línea actual y por alias; no el de otra línea
    r1 = next(r for r in reclamos if r["numero_reclamo"] == "TSTD1")
    assert r1["pct_presupuesto"] == pytest.approx(50.0)
    assert r1["cuenta_sla"] is True
    r4 = next(r for r in reclamos if r["numero_reclamo"] == "TSTD4")
    assert r4["cuenta_sla"] is False and r4["pct_presupuesto"] is None
    assert body["sla_historico"][0]["sla_prometido"] == pytest.approx(99.7)


def test_busqueda_no_incluye_reclamos(datos, client):
    resp = client.get("/servicios/search", params={"q": _ORIGEN}, headers=API_HEADERS)
    assert resp.status_code == 200, resp.text
    for s in resp.json()["servicios"]:
        assert s["reclamos"] is None
