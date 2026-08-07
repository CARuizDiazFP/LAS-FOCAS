# Nombre de archivo: test_cromo_inventario.py
# Ubicación de archivo: tests/test_cromo_inventario.py
# Descripción: Pruebas del inventario navegable de cables Cromo (búsqueda + paginación), sin DB real

from __future__ import annotations

from typing import Any, Optional

import pytest

from core.services.cromo import inventario


class _ResultadoFake:
    def __init__(self, escalar: Any = None, filas: Optional[list[tuple]] = None) -> None:
        self._escalar = escalar
        self._filas = filas or []

    def scalar_one(self):
        return self._escalar

    def all(self):
        return self._filas


class _SesionFake:
    """Distingue el conteo de la búsqueda por la forma del SELECT — coincide con test_cromo_verificador.py."""

    def __init__(self, total: int = 0, filas: Optional[list[tuple]] = None) -> None:
        self._total = total
        self._filas = filas or []
        self.llamadas: list[dict] = []

    async def execute(self, stmt: Any, params: Optional[dict] = None) -> _ResultadoFake:
        self.llamadas.append(params or {})
        texto = str(stmt)
        if "SELECT count(*)" in texto:
            return _ResultadoFake(escalar=self._total)
        return _ResultadoFake(filas=self._filas)


_FILA_CABLE = (
    51,  # n_id
    "Cable Troncal 1",  # nombre
    "72-BRUG",  # capacidad
    72,  # capacidad_pelos
    "Troncal",  # jerarquia
    "SBASE",  # propietario
    "Botella A",  # extremo_a_nombre
    "Botella B",  # extremo_b_nombre
    True,  # vigente
    3,  # cantidad_servicios
)


@pytest.mark.asyncio
async def test_buscar_cables_sin_filtros_devuelve_pagina():
    sesion = _SesionFake(total=1, filas=[_FILA_CABLE])

    resultado = await inventario.buscar_cables(sesion)

    assert resultado.total == 1
    assert resultado.limit == 50
    assert resultado.offset == 0
    assert len(resultado.cables) == 1
    cable = resultado.cables[0]
    assert cable.n_id == 51
    assert cable.nombre == "Cable Troncal 1"
    assert cable.cantidad_servicios == 3
    assert cable.vigente is True


@pytest.mark.asyncio
async def test_buscar_cables_sin_resultados():
    sesion = _SesionFake(total=0, filas=[])

    resultado = await inventario.buscar_cables(sesion, q="no existe")

    assert resultado.total == 0
    assert resultado.cables == []


@pytest.mark.asyncio
async def test_buscar_cables_normaliza_q_jerarquia_propietario_a_ilike():
    sesion = _SesionFake(total=0, filas=[])

    await inventario.buscar_cables(sesion, q="  troncal  ", jerarquia=" Troncal ", propietario=" sbase ")

    # Ambas llamadas (conteo + búsqueda) reciben los mismos params normalizados.
    for llamada in sesion.llamadas:
        assert llamada["q"] == "%troncal%"
        assert llamada["jerarquia"] == "%Troncal%"
        assert llamada["propietario"] == "%sbase%"


@pytest.mark.asyncio
async def test_buscar_cables_q_vacio_no_filtra():
    sesion = _SesionFake(total=0, filas=[])

    await inventario.buscar_cables(sesion, q="   ")

    assert sesion.llamadas[0]["q"] is None


@pytest.mark.asyncio
async def test_buscar_cables_respeta_limit_offset():
    sesion = _SesionFake(total=100, filas=[_FILA_CABLE])

    resultado = await inventario.buscar_cables(sesion, limit=10, offset=20)

    assert resultado.limit == 10
    assert resultado.offset == 20
    # La llamada de búsqueda (la segunda) debe llevar limit/offset; el conteo no los necesita pero
    # buscar_cables los pasa igual en el dict de params — no rompe nada, sólo no se usan en ese SQL.
    llamada_busqueda = sesion.llamadas[-1]
    assert llamada_busqueda["limit"] == 10
    assert llamada_busqueda["offset"] == 20


@pytest.mark.asyncio
async def test_buscar_cables_filtro_vigente_exacto():
    sesion = _SesionFake(total=0, filas=[])

    await inventario.buscar_cables(sesion, vigente=False)

    assert sesion.llamadas[0]["vigente"] is False
