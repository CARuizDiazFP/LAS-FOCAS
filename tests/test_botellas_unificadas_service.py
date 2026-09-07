# Nombre de archivo: test_botellas_unificadas_service.py
# Ubicación de archivo: tests/test_botellas_unificadas_service.py
# Descripción: Pruebas del listado unificado de Botellas (Cromo + legado Infra/Baneos), sin DB real

from __future__ import annotations

from typing import Any, Optional

import pytest

from core.services import botellas_unificadas_service as servicio


class _ResultadoFake:
    def __init__(self, escalar: Any = None, filas: Optional[list[tuple]] = None) -> None:
        self._escalar = escalar
        self._filas = filas or []

    def scalar_one(self):
        return self._escalar

    def all(self):
        return self._filas


class _SesionFake:
    """Distingue el conteo de la búsqueda por la forma del SELECT — mismo criterio que
    test_cromo_inventario.py."""

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


_FILA_CROMO = ("cromo", 6638808, "Cra Plaza de los Ingleses CF", "LIBRE")
_FILA_CROMO_NO_OPERATIVA = ("cromo", 9999999, "Cra No Operativa CF", "NO_OPERATIVA")
_FILA_LEGADO = ("legado", 1065, "Cra 14 de Julio 240 CF", "LIBRE")


@pytest.mark.asyncio
async def test_buscar_botellas_sin_filtros_devuelve_pagina_con_ambos_origenes():
    sesion = _SesionFake(total=2, filas=[_FILA_CROMO, _FILA_LEGADO])

    resultado = await servicio.buscar_botellas_unificadas(sesion)

    assert resultado.total == 2
    assert resultado.limit == 30
    assert resultado.offset == 0
    assert len(resultado.botellas) == 2
    cromo, legado = resultado.botellas
    assert cromo.origen == "cromo"
    assert cromo.id == 6638808
    assert cromo.estado == "LIBRE"
    assert legado.origen == "legado"
    assert legado.id == 1065
    assert legado.estado == "LIBRE"


@pytest.mark.asyncio
async def test_buscar_botellas_sin_resultados():
    sesion = _SesionFake(total=0, filas=[])

    resultado = await servicio.buscar_botellas_unificadas(sesion, q="no existe")

    assert resultado.total == 0
    assert resultado.botellas == []


@pytest.mark.asyncio
async def test_buscar_botellas_normaliza_q_a_ilike():
    sesion = _SesionFake(total=0, filas=[])

    await servicio.buscar_botellas_unificadas(sesion, q="  Plaza de los Ingleses  ")

    for llamada in sesion.llamadas:
        assert llamada["q"] == "%Plaza de los Ingleses%"


@pytest.mark.asyncio
async def test_buscar_botellas_q_vacio_no_filtra():
    sesion = _SesionFake(total=0, filas=[])

    await servicio.buscar_botellas_unificadas(sesion, q="   ")

    assert sesion.llamadas[0]["q"] is None


@pytest.mark.asyncio
async def test_buscar_botellas_respeta_limit_offset():
    sesion = _SesionFake(total=100, filas=[_FILA_CROMO])

    resultado = await servicio.buscar_botellas_unificadas(sesion, limit=10, offset=20)

    assert resultado.limit == 10
    assert resultado.offset == 20
    llamada_busqueda = sesion.llamadas[-1]
    assert llamada_busqueda["limit"] == 10
    assert llamada_busqueda["offset"] == 20


@pytest.mark.asyncio
async def test_buscar_botellas_estado_real_para_origen_cromo_post_backfill():
    """Desde 2026-08-11 Cromo aporta estado real (poblado por
    scripts/cromo_backfill_camara_padre.py) — la columna nunca es NULL (NOT NULL DEFAULT
    'LIBRE' desde 2026-08-13, antes 'NO_OPERATIVA'), así que una fila sin backfillear expone
    'LIBRE', no ausencia de dato."""
    sesion = _SesionFake(total=1, filas=[_FILA_CROMO])

    resultado = await servicio.buscar_botellas_unificadas(sesion)

    assert resultado.botellas[0].origen == "cromo"
    assert resultado.botellas[0].estado == "LIBRE"


@pytest.mark.asyncio
async def test_buscar_botellas_default_no_incluye_no_operativas():
    sesion = _SesionFake(total=0, filas=[])

    await servicio.buscar_botellas_unificadas(sesion)

    for llamada in sesion.llamadas:
        assert llamada["incluir_no_operativas"] is False


@pytest.mark.asyncio
async def test_buscar_botellas_incluir_no_operativas_true_viaja_a_la_query():
    sesion = _SesionFake(total=1, filas=[_FILA_CROMO_NO_OPERATIVA])

    resultado = await servicio.buscar_botellas_unificadas(sesion, incluir_no_operativas=True)

    for llamada in sesion.llamadas:
        assert llamada["incluir_no_operativas"] is True
    assert resultado.botellas[0].estado == "NO_OPERATIVA"
