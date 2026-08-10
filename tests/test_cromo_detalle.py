# Nombre de archivo: test_cromo_detalle.py
# Ubicación de archivo: tests/test_cromo_detalle.py
# Descripción: Pruebas del detalle jerárquico de un cable Cromo (tubos/buffers → pelos → servicio), sin DB real

from __future__ import annotations

from typing import Any, Optional

import pytest

from core.services.cromo import detalle, verificador


class _ResultadoFilas:
    def __init__(self, filas: list[tuple]) -> None:
        self._filas = filas

    def all(self):
        return self._filas

    def first(self):
        return self._filas[0] if self._filas else None


class _SesionFake:
    """Reemplaza sólo `execute`: matchea por substring de la consulta compilada, como en
    test_cromo_verificador.py."""

    def __init__(self, respuestas: Optional[dict[str, list[tuple]]] = None) -> None:
        self._respuestas = respuestas or {}

    async def execute(self, stmt: Any, params: Optional[dict] = None) -> _ResultadoFilas:
        texto = str(stmt)
        for clave, filas in self._respuestas.items():
            if clave in texto:
                return _ResultadoFilas(filas)
        return _ResultadoFilas([])


_FILA_CABLE = (
    51,  # n_id
    "Cable Troncal 1",  # nombre
    "72-BRUG",  # capacidad
    72,  # capacidad_pelos
    "Troncal",  # jerarquia
    "SBASE",  # propietario
    "Aereo",  # tendido
    None,  # distancia_geo
    None,  # distancia_real
    "LEG-51",  # id_legacy
    None,  # notas
    68001,  # extremo_a_n_id
    69,  # extremo_a_clase
    None,  # extremo_a_legacy
    "Botella A",  # extremo_a_nombre
    68002,  # extremo_b_n_id
    69,  # extremo_b_clase
    None,  # extremo_b_legacy
    "Botella B",  # extremo_b_nombre
    True,  # vigente
)

_FILA_TUBO = (129001, 1, "AZUL", True)  # n_id, orden, nombre_color, vigente

_FILA_PELO_SIN_SERVICIO = (
    9001, 129001, "1", 1, "AZUL", "LIBRE", None, None, True,  # pelo
    None, None, None, None, None, None, None, None, None, None,  # servicio (todo None)
)

_FILA_PELO_CON_SERVICIO = (
    9002, 129001, "2", 2, "AZUL", "CLIENTE", "FO 1234 - CLIENTE", "1234", True,  # pelo
    501, "SRV-001", "SRV-001", "Cliente Uno", "Cliente Uno SA", "ACTIVO", 1, "CORPORATIVO", "1234", "REGEX_EXACTO",
)


@pytest.mark.asyncio
async def test_obtener_detalle_cable_no_encontrado():
    sesion = _SesionFake()
    with pytest.raises(verificador.ObjetoNoEncontrado):
        await detalle.obtener_detalle_cable(sesion, 999)


@pytest.mark.asyncio
async def test_obtener_detalle_cable_con_tubos_y_pelos_sin_servicio():
    sesion = _SesionFake(
        respuestas={
            "FROM app.cromo_cables": [_FILA_CABLE],
            "FROM app.cromo_tubos": [_FILA_TUBO],
            "FROM app.cromo_pelos p": [_FILA_PELO_SIN_SERVICIO],
        }
    )
    resultado = await detalle.obtener_detalle_cable(sesion, 51)

    assert resultado.n_id == 51
    assert resultado.nombre == "Cable Troncal 1"
    assert resultado.extremo_a_nombre == "Botella A"
    assert resultado.extremo_b_nombre == "Botella B"
    assert len(resultado.tubos) == 1
    tubo = resultado.tubos[0]
    assert tubo.n_id == 129001
    assert tubo.tiene_fila_propia is True
    assert len(tubo.pelos) == 1
    assert tubo.pelos[0].servicios == []


@pytest.mark.asyncio
async def test_obtener_detalle_cable_con_servicio_matcheado():
    sesion = _SesionFake(
        respuestas={
            "FROM app.cromo_cables": [_FILA_CABLE],
            "FROM app.cromo_tubos": [_FILA_TUBO],
            "FROM app.cromo_pelos p": [_FILA_PELO_CON_SERVICIO],
        }
    )
    resultado = await detalle.obtener_detalle_cable(sesion, 51)

    pelo = resultado.tubos[0].pelos[0]
    assert len(pelo.servicios) == 1
    servicio = pelo.servicios[0]
    assert servicio.servicio_id == 501
    assert servicio.servicio_id_externo == "SRV-001"
    assert servicio.pelo_n_id == 9002
    assert servicio.metodo == "REGEX_EXACTO"


@pytest.mark.asyncio
async def test_obtener_detalle_cable_tubo_referencia_colgada():
    """Un pelo referencia un tubo_n_id sin fila propia en cromo_tubos — no debe perderse, aparece con
    `tiene_fila_propia=False` y metadata en None."""
    sesion = _SesionFake(
        respuestas={
            "FROM app.cromo_cables": [_FILA_CABLE],
            "FROM app.cromo_tubos": [],
            "FROM app.cromo_pelos p": [_FILA_PELO_SIN_SERVICIO],
        }
    )
    resultado = await detalle.obtener_detalle_cable(sesion, 51)

    assert len(resultado.tubos) == 1
    tubo = resultado.tubos[0]
    assert tubo.n_id == 129001
    assert tubo.tiene_fila_propia is False
    assert tubo.orden is None
    assert tubo.nombre_color is None
    assert tubo.vigente is None
    assert len(tubo.pelos) == 1


@pytest.mark.asyncio
async def test_obtener_detalle_cable_referencia_colgada_cable_con_tubos():
    """El cable no tiene fila propia (todavía no bajó en su página de la Fase 2) pero sí hay tubos que
    lo referencian — no debe tratarse como "no encontrado", sólo la metadata del cable queda en None."""
    sesion = _SesionFake(
        respuestas={
            "FROM app.cromo_cables": [],
            "FROM app.cromo_tubos": [_FILA_TUBO],
            "FROM app.cromo_pelos p": [_FILA_PELO_SIN_SERVICIO],
        }
    )
    resultado = await detalle.obtener_detalle_cable(sesion, 10191706)

    assert resultado.n_id == 10191706
    assert resultado.nombre is None
    assert resultado.extremo_a_nombre is None
    assert resultado.vigente is False
    assert len(resultado.tubos) == 1


@pytest.mark.asyncio
async def test_obtener_detalle_cable_sin_tubos_ni_pelos():
    sesion = _SesionFake(respuestas={"FROM app.cromo_cables": [_FILA_CABLE]})
    resultado = await detalle.obtener_detalle_cable(sesion, 51)

    assert resultado.n_id == 51
    assert resultado.tubos == []
