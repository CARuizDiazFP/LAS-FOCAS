# Nombre de archivo: test_cromo_pon_inventario.py
# Ubicación de archivo: tests/test_cromo_pon_inventario.py
# Descripción: Pruebas del inventario navegable de cajas PON y rosetas Cromo, sin DB real

from __future__ import annotations

from typing import Any, Optional

import pytest

from core.services.cromo import pon_inventario


class _ResultadoFake:
    def __init__(self, escalar: Any = None, filas: Optional[list[tuple]] = None) -> None:
        self._escalar = escalar
        self._filas = filas or []

    def scalar_one(self):
        return self._escalar

    def all(self):
        return self._filas


class _SesionFake:
    """Distingue el conteo de la búsqueda por la paginación, no por `count(*)`.

    Los otros tests de inventario del módulo discriminan buscando `"SELECT count(*)"` en el SQL, y
    acá eso no sirve: la consulta de búsqueda trae un subselect `count(*)` para
    `cantidad_splitters`, así que matchearía las dos. `LIMIT :limit` sólo aparece en la paginada.
    """

    def __init__(self, total: int = 0, filas: Optional[list[tuple]] = None) -> None:
        self._total = total
        self._filas = filas or []
        self.llamadas: list[dict] = []

    async def execute(self, stmt: Any, params: Optional[dict] = None) -> _ResultadoFake:
        self.llamadas.append(params or {})
        if "LIMIT :limit" in str(stmt):
            return _ResultadoFake(filas=self._filas)
        return _ResultadoFake(escalar=self._total)


_FILA = (
    6685166,                                   # n_id
    139,                                       # clase
    "IAAS PON ALBERDI, JUAN  AV.1642 RED",     # nombre
    "Capital Federal",                         # localidad
    "ALBERDI, JUAN BAUTISTA AV.",              # calle
    "1642",                                    # altura
    "Metrotel",                                # propietario
    "Fast connect",                            # tipo_conector
    8,                                         # capacidad_puertos
    -34.6,                                     # latitud
    -58.4,                                     # longitud
    True,                                      # vigente
    3,                                         # cantidad_splitters
)


@pytest.mark.asyncio
async def test_sin_filtros_devuelve_la_pagina():
    sesion = _SesionFake(total=1, filas=[_FILA])

    resultado = await pon_inventario.buscar_pon_elementos(sesion)

    assert resultado.total == 1
    assert len(resultado.elementos) == 1
    assert resultado.elementos[0].nombre == "IAAS PON ALBERDI, JUAN  AV.1642 RED"
    assert resultado.elementos[0].capacidad_puertos == 8
    assert resultado.elementos[0].cantidad_splitters == 3


@pytest.mark.asyncio
async def test_el_texto_de_busqueda_se_normaliza_a_ilike_parcial():
    sesion = _SesionFake()

    await pon_inventario.buscar_pon_elementos(sesion, q="  alberdi  ")

    assert sesion.llamadas[0]["q"] == "%alberdi%"


@pytest.mark.asyncio
async def test_un_texto_en_blanco_no_filtra():
    """Un `q` vacío tiene que ser 'sin filtro', no 'nombre igual a nada'."""
    sesion = _SesionFake()

    await pon_inventario.buscar_pon_elementos(sesion, q="   ")

    assert sesion.llamadas[0]["q"] is None


@pytest.mark.asyncio
async def test_las_clases_llegan_como_lista_para_el_any():
    """Es lo que separa la vista de Cajas PON de la de Rosetas: comparten tabla y se distinguen
    por la lista de clases que pide cada una."""
    sesion = _SesionFake()

    await pon_inventario.buscar_pon_elementos(sesion, clases=[84, 137])

    assert sesion.llamadas[0]["clases"] == [84, 137]


@pytest.mark.asyncio
async def test_sin_clases_no_filtra_por_clase():
    sesion = _SesionFake()

    await pon_inventario.buscar_pon_elementos(sesion)

    assert sesion.llamadas[0]["clases"] is None


@pytest.mark.asyncio
async def test_paginacion_se_propaga_solo_a_la_busqueda():
    """El COUNT no lleva limit/offset: si los llevara, el total sería el de la página."""
    sesion = _SesionFake(total=500, filas=[_FILA])

    resultado = await pon_inventario.buscar_pon_elementos(sesion, limit=10, offset=40)

    assert resultado.total == 500
    assert resultado.limit == 10
    assert resultado.offset == 40
    assert "limit" not in sesion.llamadas[0]
    assert sesion.llamadas[1]["limit"] == 10
    assert sesion.llamadas[1]["offset"] == 40
