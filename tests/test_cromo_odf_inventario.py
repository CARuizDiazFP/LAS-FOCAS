# Nombre de archivo: test_cromo_odf_inventario.py
# Ubicación de archivo: tests/test_cromo_odf_inventario.py
# Descripción: Pruebas del inventario navegable de ODFs Cromo (búsqueda + paginación), sin DB real

from __future__ import annotations

from typing import Any, Optional

import pytest

from core.services.cromo import odf_inventario


class _ResultadoFake:
    def __init__(self, escalar: Any = None, filas: Optional[list[tuple]] = None) -> None:
        self._escalar = escalar
        self._filas = filas or []

    def scalar_one(self):
        return self._escalar

    def all(self):
        return self._filas


class _SesionFake:
    """Distingue el conteo de la búsqueda por la forma del SELECT — coincide con test_cromo_inventario.py."""

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


_FILA_ODF = (
    901,  # n_id
    "ODF Calle 9 Nro 593 PILAR",  # nombre
    "ODF",  # tipo_elemento
    "PILAR",  # localidad
    "Calle 9",  # calle
    "593",  # altura
    "Metrotel",  # propietario
    True,  # vigente
    [111, 222],  # cables_asociados
    2,  # cantidad_servicios
)


@pytest.mark.asyncio
async def test_buscar_odfs_sin_filtros_devuelve_pagina():
    sesion = _SesionFake(total=1, filas=[_FILA_ODF])

    resultado = await odf_inventario.buscar_odfs(sesion)

    assert resultado.total == 1
    assert resultado.limit == 50
    assert resultado.offset == 0
    assert len(resultado.odfs) == 1
    odf = resultado.odfs[0]
    assert odf.n_id == 901
    assert odf.nombre == "ODF Calle 9 Nro 593 PILAR"
    assert odf.tipo_elemento == "ODF"
    assert odf.cantidad_cables_asociados == 2
    assert odf.cantidad_servicios == 2
    assert odf.vigente is True


@pytest.mark.asyncio
async def test_buscar_odfs_cantidad_cables_asociados_cero_si_none():
    """`cables_asociados` puede ser NULL (ODF sin `tp` en el payload de Cromo, ver parser) —
    `cantidad_cables_asociados` debe ser 0, no explotar con `len(None)`."""
    fila = (901, "ODF X", "SIN_CLASIFICAR", None, None, None, None, True, None, 0)
    sesion = _SesionFake(total=1, filas=[fila])

    resultado = await odf_inventario.buscar_odfs(sesion)

    assert resultado.odfs[0].cantidad_cables_asociados == 0


@pytest.mark.asyncio
async def test_buscar_odfs_sin_resultados():
    sesion = _SesionFake(total=0, filas=[])

    resultado = await odf_inventario.buscar_odfs(sesion, q="no existe")

    assert resultado.total == 0
    assert resultado.odfs == []


@pytest.mark.asyncio
async def test_buscar_odfs_normaliza_q_a_ilike():
    sesion = _SesionFake(total=0, filas=[])

    await odf_inventario.buscar_odfs(sesion, q="  odf pilar  ")

    for llamada in sesion.llamadas:
        assert llamada["q"] == "%odf pilar%"


@pytest.mark.asyncio
async def test_buscar_odfs_q_vacio_no_filtra():
    sesion = _SesionFake(total=0, filas=[])

    await odf_inventario.buscar_odfs(sesion, q="   ")

    assert sesion.llamadas[0]["q"] is None


@pytest.mark.asyncio
async def test_buscar_odfs_respeta_limit_offset():
    sesion = _SesionFake(total=100, filas=[_FILA_ODF])

    resultado = await odf_inventario.buscar_odfs(sesion, limit=10, offset=20)

    assert resultado.limit == 10
    assert resultado.offset == 20
    llamada_busqueda = sesion.llamadas[-1]
    assert llamada_busqueda["limit"] == 10
    assert llamada_busqueda["offset"] == 20


@pytest.mark.asyncio
async def test_buscar_odfs_filtro_vigente_exacto():
    sesion = _SesionFake(total=0, filas=[])

    await odf_inventario.buscar_odfs(sesion, vigente=False)

    assert sesion.llamadas[0]["vigente"] is False


@pytest.mark.asyncio
async def test_buscar_odfs_filtro_n_id_exacto():
    sesion = _SesionFake(total=0, filas=[])

    await odf_inventario.buscar_odfs(sesion, n_id=901)

    assert sesion.llamadas[0]["n_id"] == 901


@pytest.mark.asyncio
async def test_buscar_odfs_filtro_tipo_elemento_exacto():
    sesion = _SesionFake(total=0, filas=[])

    await odf_inventario.buscar_odfs(sesion, tipo_elemento="ODF")

    assert sesion.llamadas[0]["tipo_elemento"] == "ODF"


@pytest.mark.asyncio
async def test_buscar_odfs_filtro_servicio_ilike():
    sesion = _SesionFake(total=0, filas=[])

    await odf_inventario.buscar_odfs(sesion, servicio="1234")

    assert sesion.llamadas[0]["servicio"] == "%1234%"


@pytest.mark.asyncio
async def test_buscar_odfs_filtros_vacios_no_filtran():
    sesion = _SesionFake(total=0, filas=[])

    await odf_inventario.buscar_odfs(sesion, n_id=None, tipo_elemento="  ", servicio="")

    assert sesion.llamadas[0]["n_id"] is None
    assert sesion.llamadas[0]["tipo_elemento"] is None
    assert sesion.llamadas[0]["servicio"] is None


@pytest.mark.asyncio
async def test_buscar_odfs_orden_por_direccion_en_sql():
    """El orden por defecto (localidad, calle, altura, nombre, n_id) es lo que agrupa a los ODFs de
    la misma dirección física en el listado — sustituye al agrupamiento por sitio del ticket
    original (Tarea 4, ver docstring de `buscar_odfs`)."""
    assert "ORDER BY o.localidad NULLS LAST, o.calle NULLS LAST, o.altura NULLS LAST, o.nombre, o.n_id" in str(
        odf_inventario._SQL_BUSCAR
    )


@pytest.mark.asyncio
async def test_buscar_odfs_filtro_servicio_no_correlacionado():
    """Regresión de la revisión de rama completa: el filtro `servicio` estaba escrito como un
    `EXISTS` correlacionado a `o.cables_asociados` que re-ejecutaba el join
    `cromo_pelos ⋈ cromo_servicio_match ⋈ servicios` una vez por fila de ODF candidata (dos veces
    por request, COUNT + SELECT paginado) — el mismo antipatrón que el comentario de
    `inventario.py::_FILTROS_SQL` advierte evitar para `buscar_cables`, y con un volumen real de
    ODFs (7.955, clase 69) que no lo justifica como excepción. La corrección mantiene el `EXISTS`
    (necesario porque `cables_asociados` es un array JSONB, no una columna escalar como `c.n_id` en
    `inventario.py`) pero el join costoso vive en un subquery aparte que no referencia a `o`, así
    que Postgres puede resolverlo una sola vez por statement en vez de por fila candidata."""
    texto = str(odf_inventario._SQL_BUSCAR)
    # El JOIN a `cromo_servicio_match`/`servicios` no debe aparecer dentro de un WHERE que
    # referencie directamente a `o.cables_asociados` en la misma subquery (el antipatrón viejo).
    assert "p.cable_n_id IN (\n                  SELECT (jsonb_array_elements_text" not in texto
    assert "SELECT p.cable_n_id" in texto
    assert "FROM app.cromo_pelos p" in texto
    assert "jsonb_array_elements_text(COALESCE(o.cables_asociados, '[]'::jsonb)) AS cable_id_texto" in texto
    assert "cable_id_texto::bigint IN (" in texto


@pytest.mark.asyncio
async def test_buscar_odfs_guardia_cast_explicito_en_filtros():
    """Guardrail obligatorio del brief: cada filtro opcional debe usar `CAST(:param AS <tipo>)`
    explícito — sin esto, todos los filtros en NULL a la vez revienta con `AmbiguousParameterError`
    contra un driver real (ver tests/test_cromo_odf_inventario_real_db.py)."""
    texto = str(odf_inventario._SQL_BUSCAR)
    assert "CAST(:q AS text)" in texto
    assert "CAST(:n_id AS bigint)" in texto
    assert "CAST(:vigente AS boolean)" in texto
    assert "CAST(:tipo_elemento AS text)" in texto
    assert "CAST(:servicio AS text)" in texto
