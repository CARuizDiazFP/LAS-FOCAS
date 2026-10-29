# Nombre de archivo: test_camaras_busqueda_avanzada.py
# Ubicación de archivo: tests/test_camaras_busqueda_avanzada.py
# Descripción: Tests de la búsqueda avanzada de cámaras en core/services (D1 servicios por rutas, B4 status vacío, orden y paginación)

"""Unitarios con sesión simulada (sin base): la carga por lote y el matching se prueban con objetos en memoria."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from core.services import camaras_busqueda_avanzada as cba
from core.services.camaras_busqueda_avanzada import (
    FilterField,
    FilterOperator,
    SearchFilter,
    buscar_camaras_avanzada,
)
from db.models.infra import CamaraEstado, CamaraOrigenDatos


def _ruta(servicio_id: str, ruta_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        id=ruta_id,
        servicio=SimpleNamespace(servicio_id=servicio_id, alias_ids=[]),
        empalmes=[],
        nombre="r",
        tipo=SimpleNamespace(value="PRINCIPAL"),
        punta_a=None,
        punta_b=None,
    )


def _camara(id_: int, nombre: str, *, rutas=(), servicios_legacy=(), estado=CamaraEstado.LIBRE) -> SimpleNamespace:
    empalme = SimpleNamespace(
        rutas=list(rutas), servicios=[SimpleNamespace(servicio_id=s) for s in servicios_legacy]
    )
    return SimpleNamespace(
        id=id_, nombre=nombre, direccion=None, fontine_id=None, estado=estado,
        origen_datos=CamaraOrigenDatos.MANUAL, latitud=None, longitud=None,
        empalmes=[empalme], botellas=[], cables=[],
    )


def _sesion(camaras: list) -> MagicMock:
    sesion = MagicMock()
    sesion.scalars.return_value.all.return_value = camaras
    return sesion


def test_status_eq_lista_vacia_no_rompe():
    """B4: `value: []` con `eq` hacía `flt.value[0]` en el prefiltro (IndexError -> 500)."""
    flt = SearchFilter(field="status", operator="eq", value=[])
    sesion = _sesion([_camara(1, "A")])
    resultado = buscar_camaras_avanzada(sesion, [flt], limit=10, offset=0)
    assert resultado.total == 0 and resultado.camaras == []


def test_filtro_servicio_usa_rutas():
    """D1: el servicio sale de las rutas, no de la asociación legacy sola."""
    cam = _camara(1, "A", rutas=[_ruta("SVC-RUTA")], servicios_legacy=["SVC-LEGACY"])
    flt = SearchFilter(field=FilterField.SERVICE_ID, operator=FilterOperator.EQ, value="SVC-RUTA")
    resultado = buscar_camaras_avanzada(_sesion([cam]), [flt], limit=10, offset=0)
    assert resultado.total == 1
    assert resultado.camaras[0].servicios_ids == ["SVC-RUTA"]
    flt_legacy = SearchFilter(field=FilterField.SERVICE_ID, operator=FilterOperator.EQ, value="SVC-LEGACY")
    assert buscar_camaras_avanzada(_sesion([cam]), [flt_legacy], limit=10, offset=0).total == 0


def test_sin_rutas_no_cae_a_legacy():
    """P22: sin rutas no hay servicios; la asociación legacy ya no se lee."""
    cam = _camara(1, "A", servicios_legacy=["SVC-LEGACY"])
    resultado = buscar_camaras_avanzada(_sesion([cam]), [], limit=10, offset=0)
    assert resultado.camaras[0].servicios_ids == []


def test_paginacion_despues_de_filtrar():
    camaras = [_camara(i, f"Rivadavia {i}") for i in range(5)] + [_camara(9, "Otra")]
    flt = SearchFilter(field="address", operator="contains", value="rivadavia")
    resultado = buscar_camaras_avanzada(_sesion(camaras), [flt], limit=2, offset=1)
    assert resultado.total == 5
    assert [e.camara.id for e in resultado.camaras] == [1, 2]


def test_cables_nombres_unicos_en_orden():
    cam = SimpleNamespace(cables=[SimpleNamespace(nombre="B"), SimpleNamespace(nombre=None),
                                  SimpleNamespace(nombre="A"), SimpleNamespace(nombre="B")])
    assert cba._cables_nombres_unicos(cam) == ["B", "A"]


def test_prefiltro_estado_solo_con_filtro_unico():
    unico = SearchFilter(field="status", operator="in", value=["libre", "x"])
    assert cba._prefiltro_estados([unico]) == [CamaraEstado.LIBRE]
    otro = SearchFilter(field="address", operator="contains", value="a")
    assert cba._prefiltro_estados([unico, otro]) is None
    assert cba._prefiltro_estados([SearchFilter(field="status", operator="eq", value=[])]) is None
