# Nombre de archivo: test_camaras_exportacion.py
# Ubicación de archivo: tests/test_camaras_exportacion.py
# Descripción: Tests de la exportación de Cámaras (core/services/camaras_exportacion.py)

from __future__ import annotations

import builtins
import io
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
    return SimpleNamespace(servicios=[SimpleNamespace(servicio_id=i) for i in ids])


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


def test_csv_sin_filas_literal_con_barra_invertida():
    assert ce.a_csv([]) == "﻿Sin datos\\n".encode("utf-8")


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
