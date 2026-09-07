# Nombre de archivo: test_cromo_odf_conectores.py
# Ubicación de archivo: tests/test_cromo_odf_conectores.py
# Descripción: Pruebas del servicio de conectores de ODF Cromo (core/services/cromo/odf_conectores.py), sin DB real

from __future__ import annotations

from typing import Any, Optional

import pytest

from core.services.cromo import odf_conectores


class _ResultadoFilas:
    def __init__(self, filas: list[tuple]) -> None:
        self._filas = filas

    def all(self):
        return self._filas

    def first(self):
        return self._filas[0] if self._filas else None


class _SesionFake:
    """Reemplaza sólo `execute`: matchea por substring de la consulta compilada, mismo criterio
    que `test_cromo_verificador.py`."""

    def __init__(self, respuestas: Optional[dict[str, list[tuple]]] = None) -> None:
        self._respuestas = respuestas or {}

    async def execute(self, stmt: Any, params: Optional[dict] = None) -> _ResultadoFilas:
        texto = str(stmt)
        for clave, filas in self._respuestas.items():
            if clave in texto:
                return _ResultadoFilas(filas)
        return _ResultadoFilas([])


_FILA_CONECTOR = (
    8539345,  # n_id
    8539330,  # bandeja_n_id
    "O-1238223-1",  # bandeja_nombre
    "15",  # numero_conector
    6777271,  # pelo_n_id
    "1",  # pelo_numero
    "61943",  # servicio_resuelto
    "41140",  # servicio_id_historico
    "61943",  # s.servicio_id (servicio_id_externo)
    "Banco Comafi SA",  # nombre_cliente
    None,  # cliente
    "Activo",  # estado_servicio
)


@pytest.mark.asyncio
async def test_conectores_de_odf_no_encontrado():
    sesion = _SesionFake()
    with pytest.raises(odf_conectores.ObjetoNoEncontrado):
        await odf_conectores.conectores_de_odf(sesion, 999)


@pytest.mark.asyncio
async def test_conectores_de_odf_sin_conectores_pero_odf_existe():
    sesion = _SesionFake(respuestas={"FROM app.cromo_odfs": [("ODF Test",)]})

    resultado = await odf_conectores.conectores_de_odf(sesion, 6642085)

    assert resultado.odf_n_id == 6642085
    assert resultado.odf_nombre == "ODF Test"
    assert resultado.conectores == []


@pytest.mark.asyncio
async def test_conectores_de_odf_referencia_colgada_via_conectores():
    """La ODF no tiene fila propia (`cromo_odfs`) pero sí tiene conectores que la referencian —
    no debe tratarse como "no encontrado", sólo `odf_nombre` queda en `None`."""
    sesion = _SesionFake(respuestas={"FROM app.cromo_odf_conectores c": [_FILA_CONECTOR]})

    resultado = await odf_conectores.conectores_de_odf(sesion, 6642085)

    assert resultado.odf_nombre is None
    assert len(resultado.conectores) == 1


@pytest.mark.asyncio
async def test_conectores_de_odf_mapea_fila_completa():
    sesion = _SesionFake(
        respuestas={
            "FROM app.cromo_odfs": [("ODF Rack Netizen 5 de Julio 478 C.F.",)],
            "FROM app.cromo_odf_conectores c": [_FILA_CONECTOR],
        }
    )

    resultado = await odf_conectores.conectores_de_odf(sesion, 6642085)

    assert resultado.odf_nombre == "ODF Rack Netizen 5 de Julio 478 C.F."
    assert len(resultado.conectores) == 1
    c = resultado.conectores[0]
    assert c.n_id == 8539345
    assert c.bandeja_nombre == "O-1238223-1"
    assert c.numero_conector == "15"
    assert c.pelo_n_id == 6777271
    assert c.pelo_numero == "1"
    assert c.servicio_resuelto == "61943"
    assert c.servicio_id_historico == "41140"
    assert c.servicio_id_externo == "61943"
    assert c.nombre_cliente == "Banco Comafi SA"
    assert c.estado_servicio == "Activo"
