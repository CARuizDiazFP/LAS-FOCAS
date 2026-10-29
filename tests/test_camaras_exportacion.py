# Nombre de archivo: test_camaras_exportacion.py
# Ubicación de archivo: tests/test_camaras_exportacion.py
# Descripción: Tests de la exportación de Cámaras (core/services/camaras_exportacion.py)

from __future__ import annotations

import builtins
import io
import re
from types import SimpleNamespace

import pandas as pd

from core.services import camaras_exportacion as ce
from db.models.infra import CamaraEstado, CamaraOrigenDatos

COLUMNAS = [
    "ID", "Nombre", "Fontine_ID", "Dirección", "Estado", "Servicios_Cat6",
    "Ticket_Baneo", "Latitud", "Longitud", "Origen_Datos",
]


def _camara(**kw):
    base = dict(
        id=1, nombre="Cámara Ñandú", direccion="Av. Rivadavia 100", fontine_id="FON-1",
        estado=CamaraEstado.LIBRE, origen_datos=CamaraOrigenDatos.TRACKING,
        latitud=-34.6, longitud=-58.4, empalmes=[],
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _empalme(*ids):
    """Empalme con una ruta por servicio (P22: los servicios salen de las rutas, no de la tabla legada)."""
    return SimpleNamespace(rutas=[SimpleNamespace(servicio=SimpleNamespace(servicio_id=i)) for i in ids])


def test_fila_claves_y_orden():
    fila = ce._fila(_camara(), {})
    assert list(fila) == COLUMNAS


def test_fila_defaults_de_campos_vacios():
    fila = ce._fila(_camara(nombre=None, fontine_id=None, direccion=None, estado=None,
                            origen_datos=None, latitud=None, longitud=None), {})
    assert fila["Nombre"] == "" and fila["Estado"] == "LIBRE" and fila["Origen_Datos"] == "MANUAL"
    assert fila["Latitud"] == "" and fila["Longitud"] == ""


def test_servicios_sin_duplicados_ni_vacios_en_orden():
    cam = _camara(empalmes=[_empalme("S1", None, "S2"), _empalme("S1", "S3", "")])
    assert ce._servicios_de_camara(cam) == ["S1", "S2", "S3"]
    assert ce._fila(cam, {})["Servicios_Cat6"] == "S1, S2, S3"


def test_ticket_solo_si_baneada_y_primer_servicio_con_ticket():
    tickets = {"S2": "T-2", "S3": "T-3"}
    cam = _camara(estado=CamaraEstado.BANEADA, empalmes=[_empalme("S1", "S2", "S3")])
    assert ce._fila(cam, tickets)["Ticket_Baneo"] == "T-2"
    cam.estado = CamaraEstado.LIBRE
    assert ce._fila(cam, tickets)["Ticket_Baneo"] == ""


def test_csv_bom_encabezados_y_no_ascii():
    filas = [ce._fila(_camara(direccion='Calle "Ñ", 5'), {})]
    datos = ce.a_csv(filas)
    assert datos.startswith(b"\xef\xbb\xbf")
    texto = datos.decode("utf-8-sig")
    assert texto.splitlines()[0] == ",".join(COLUMNAS)
    assert '"Calle ""Ñ"", 5"' in texto and "\r\n" in texto


def test_csv_sin_filas_con_salto_de_linea_real():
    assert ce.a_csv([]) == b"\xef\xbb\xbfSin datos\n"


def test_nombre_archivo_exportacion_usa_timestamp_utc():
    assert re.fullmatch(r"camaras_\d{8}_\d{6}\.xlsx", ce.nombre_archivo_exportacion("xlsx"))
    assert ce.nombre_archivo_exportacion("csv").endswith(".csv")


def test_xlsx_se_lee_de_vuelta():
    filas = [ce._fila(_camara(), {}), ce._fila(_camara(id=2, nombre="Otra"), {})]
    datos = ce.a_xlsx(filas)
    df = pd.read_excel(io.BytesIO(datos), sheet_name="Cámaras")
    assert list(df.columns) == COLUMNAS
    assert df["ID"].tolist() == [1, 2] and df["Nombre"].tolist() == ["Cámara Ñandú", "Otra"]


def test_xlsx_sin_pandas_devuelve_none(monkeypatch):
    real = builtins.__import__

    def falso(nombre, *a, **k):
        if nombre == "pandas":
            raise ImportError("sin pandas")
        return real(nombre, *a, **k)

    monkeypatch.setattr(builtins, "__import__", falso)
    assert ce.a_xlsx([ce._fila(_camara(), {})]) is None


# ------------------------------------------------- filas_exportacion contra Postgres real (transacción revertida)

import pytest  # noqa: E402

from tests.soporte_postgres_real import requiere_postgres_real  # noqa: E402

PREFIJO = "ZZEXPTEST"


@pytest.fixture()
def sesion_real():
    """Sesión sobre la DB real; todo lo sembrado se revierte al terminar."""
    from db.session import SessionLocal

    sesion = SessionLocal()
    try:
        yield sesion
    finally:
        sesion.rollback()
        sesion.close()


def _sembrar_camaras(sesion):
    from db.models.infra import Camara

    # Se insertan fuera de orden alfabético para que el ORDER BY sea observable.
    camaras = {
        nombre: Camara(nombre=f"{PREFIJO}-{nombre}", estado=estado)
        for nombre, estado in (("C", CamaraEstado.LIBRE), ("A", CamaraEstado.BANEADA), ("B", CamaraEstado.LIBRE))
    }
    sesion.add_all(camaras.values())
    sesion.flush()
    return camaras


def _nombres_propios(filas):
    return [f["Nombre"] for f in filas if f["Nombre"].startswith(PREFIJO)]


@requiere_postgres_real
def test_filas_ordenadas_por_nombre(sesion_real):
    _sembrar_camaras(sesion_real)
    filas = ce.filas_exportacion(sesion_real, filter_status=None, servicio_id=None)
    assert _nombres_propios(filas) == [f"{PREFIJO}-A", f"{PREFIJO}-B", f"{PREFIJO}-C"]


@requiere_postgres_real
def test_filtro_estado_valido_filtra_sin_distinguir_mayusculas(sesion_real):
    _sembrar_camaras(sesion_real)
    filas = ce.filas_exportacion(sesion_real, filter_status="baneada", servicio_id=None)
    assert {f["Estado"] for f in filas} == {"BANEADA"}
    assert _nombres_propios(filas) == [f"{PREFIJO}-A"]


@pytest.mark.parametrize("estado", ["ALL", "all", "", None, "NO_EXISTE"])
@requiere_postgres_real
def test_filtro_estado_all_vacio_o_invalido_no_filtra(sesion_real, estado):
    _sembrar_camaras(sesion_real)
    filas = ce.filas_exportacion(sesion_real, filter_status=estado, servicio_id=None)
    assert _nombres_propios(filas) == [f"{PREFIJO}-A", f"{PREFIJO}-B", f"{PREFIJO}-C"]


def _sembrar_servicio(sesion, camaras, servicio_id, con_camaras=True):
    from db.models.infra import Empalme, RutaServicio, Servicio

    servicio = Servicio(servicio_id=servicio_id, estado_servicio="Activo")
    sesion.add(servicio)
    sesion.flush()
    ruta = RutaServicio(servicio_id=servicio.id, nombre="Principal", activa=True)
    sesion.add(ruta)
    if con_camaras:
        for i, nombre in enumerate(("A", "C")):
            empalme = Empalme(tracking_empalme_id=f"{PREFIJO}-E{i}", camara_id=camaras[nombre].id)
            sesion.add(empalme)
            ruta.empalmes.append(empalme)
    sesion.flush()
    return servicio


@requiere_postgres_real
def test_filtro_servicio_existente_restringe_a_sus_camaras(sesion_real):
    camaras = _sembrar_camaras(sesion_real)
    _sembrar_servicio(sesion_real, camaras, f"{PREFIJO}-SRV1")
    filas = ce.filas_exportacion(sesion_real, filter_status=None, servicio_id=f"{PREFIJO}-SRV1")
    assert [f["Nombre"] for f in filas] == [f"{PREFIJO}-A", f"{PREFIJO}-C"]


@requiere_postgres_real
def test_servicios_cat6_sale_de_las_rutas(sesion_real):
    """P22: la columna se arma con las rutas de los empalmes, no con la tabla legada."""
    camaras = _sembrar_camaras(sesion_real)
    _sembrar_servicio(sesion_real, camaras, f"{PREFIJO}-SRV3")
    filas = ce.filas_exportacion(sesion_real, filter_status=None, servicio_id=f"{PREFIJO}-SRV3")
    assert [f["Servicios_Cat6"] for f in filas] == [f"{PREFIJO}-SRV3", f"{PREFIJO}-SRV3"]


@requiere_postgres_real
def test_filtro_servicio_inexistente_no_filtra(sesion_real):
    _sembrar_camaras(sesion_real)
    filas = ce.filas_exportacion(sesion_real, filter_status=None, servicio_id=f"{PREFIJO}-NO-EXISTE")
    assert _nombres_propios(filas) == [f"{PREFIJO}-A", f"{PREFIJO}-B", f"{PREFIJO}-C"]


@requiere_postgres_real
def test_filtro_servicio_sin_camaras_devuelve_vacio(sesion_real):
    camaras = _sembrar_camaras(sesion_real)
    _sembrar_servicio(sesion_real, camaras, f"{PREFIJO}-SRV2", con_camaras=False)
    assert ce.filas_exportacion(sesion_real, filter_status=None, servicio_id=f"{PREFIJO}-SRV2") == []


@requiere_postgres_real
def test_filtros_de_estado_y_servicio_se_combinan(sesion_real):
    camaras = _sembrar_camaras(sesion_real)
    _sembrar_servicio(sesion_real, camaras, f"{PREFIJO}-SRV3")
    filas = ce.filas_exportacion(sesion_real, filter_status="LIBRE", servicio_id=f"{PREFIJO}-SRV3")
    assert [f["Nombre"] for f in filas] == [f"{PREFIJO}-C"]


# --- Routers: sin XLSX disponible se exporta CSV con X-Export-Warning (D4) ---------------------


def _sesion_falsa():
    from unittest.mock import MagicMock

    sesion = MagicMock()
    sesion.__enter__.return_value = sesion
    return MagicMock(return_value=sesion)


def _verificar_fallback_csv(res):
    assert res.status_code == 200, res.text
    assert res.headers["x-export-warning"] == ce.AVISO_SIN_XLSX
    assert res.headers["content-type"] == "text/csv; charset=utf-8"
    assert res.headers["content-disposition"].endswith('.csv"')
    assert res.content == b"\xef\xbb\xbfSin datos\n"


def test_web_xlsx_no_disponible_avisa_y_devuelve_csv(con_sesion, monkeypatch):
    from fastapi.testclient import TestClient

    from web.app.main import app as app_web
    from web.app.routers import camaras as router

    con_sesion("admin")
    monkeypatch.setattr("db.session.SessionLocal", _sesion_falsa())
    monkeypatch.setattr(router, "filas_exportacion", lambda *a, **k: [])
    monkeypatch.setattr(router, "a_xlsx", lambda filas: None)
    _verificar_fallback_csv(TestClient(app_web).get("/api/infra/export/cameras", params={"format": "xlsx"}))


def test_api_xlsx_no_disponible_avisa_y_devuelve_csv(monkeypatch):
    from fastapi.testclient import TestClient

    from api.app.main import app as app_api
    from api.app.routes import infra as router

    monkeypatch.setattr(router, "SessionLocal", _sesion_falsa())
    monkeypatch.setattr(router, "filas_exportacion", lambda *a, **k: [])
    monkeypatch.setattr(router, "a_xlsx", lambda filas: None)
    cliente = TestClient(app_api, headers={"Authorization": "Bearer test-api-key"})
    _verificar_fallback_csv(cliente.get("/api/infra/export/cameras", params={"format": "xlsx"}))
