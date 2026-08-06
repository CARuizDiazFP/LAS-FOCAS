# Nombre de archivo: test_cromo_verificador.py
# Ubicación de archivo: tests/test_cromo_verificador.py
# Descripción: Pruebas del verificador de servicios Cromo (consultas por cable/tubo/botella) sin DB real

from __future__ import annotations

from typing import Any, Optional

import pytest

from core.services.cromo import verificador


class _ResultadoFilas:
    def __init__(self, filas: list[tuple]) -> None:
        self._filas = filas

    def all(self):
        return self._filas

    def first(self):
        return self._filas[0] if self._filas else None


class _SesionFake:
    """Reemplaza sólo `execute`: matchea por substring de la consulta compilada, como en test_cromo_ingesta.py."""

    def __init__(self, respuestas: Optional[dict[str, list[tuple]]] = None) -> None:
        self._respuestas = respuestas or {}

    async def execute(self, stmt: Any, params: Optional[dict] = None) -> _ResultadoFilas:
        texto = str(stmt)
        for clave, filas in self._respuestas.items():
            if clave in texto:
                return _ResultadoFilas(filas)
        return _ResultadoFilas([])


_FILA_SERVICIO = (
    501,  # s.id
    "SRV-001",  # s.servicio_id
    "SRV-001",  # numero_primer_servicio
    "Cliente Uno",  # nombre_cliente
    "Cliente Uno SA",  # cliente
    "ACTIVO",  # estado_servicio
    1,  # categoria
    "CORPORATIVO",  # tipo_servicio
    9001,  # pelo n_id
    "1234",  # servicio_numero (match)
    "REGEX_EXACTO",  # metodo
)


# ── servicios_por_cable ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_servicios_por_cable_no_encontrado():
    sesion = _SesionFake()
    with pytest.raises(verificador.ObjetoNoEncontrado):
        await verificador.servicios_por_cable(sesion, 999)


@pytest.mark.asyncio
async def test_servicios_por_cable_sin_matches():
    sesion = _SesionFake(
        respuestas={"FROM app.cromo_cables": [(51, "Cable Troncal 1", "72-BRUG", "Botella A", "Botella B")]}
    )
    resultado = await verificador.servicios_por_cable(sesion, 51)

    assert resultado.cable_n_id == 51
    assert resultado.nombre == "Cable Troncal 1"
    assert resultado.servicios == []


@pytest.mark.asyncio
async def test_servicios_por_cable_referencia_colgada_con_matches():
    """El cable no tiene fila propia (todavía no bajó en su página de la Fase 2) pero sus pelos sí
    tienen servicio matcheado — caso real encontrado al validar contra `lasfocasdev-postgres`: no debe
    tratarse como "no encontrado", sólo la metadata del cable queda en None."""
    sesion = _SesionFake(respuestas={"cromo_pelos p\n    JOIN app.cromo_servicio_match": [_FILA_SERVICIO]})
    resultado = await verificador.servicios_por_cable(sesion, 10191706)

    assert resultado.cable_n_id == 10191706
    assert resultado.nombre is None
    assert len(resultado.servicios) == 1


@pytest.mark.asyncio
async def test_servicios_por_cable_con_matches():
    sesion = _SesionFake(
        respuestas={
            "FROM app.cromo_cables": [(51, "Cable Troncal 1", "72-BRUG", "Botella A", "Botella B")],
            "cromo_pelos p\n    JOIN app.cromo_servicio_match": [_FILA_SERVICIO],
        }
    )
    resultado = await verificador.servicios_por_cable(sesion, 51)

    assert len(resultado.servicios) == 1
    servicio = resultado.servicios[0]
    assert servicio.servicio_id == 501
    assert servicio.servicio_id_externo == "SRV-001"
    assert servicio.pelo_n_id == 9001
    assert servicio.metodo == "REGEX_EXACTO"


@pytest.mark.asyncio
async def test_servicios_por_cable_referencia_colgada_sin_matches():
    """El cable no tiene fila propia ni pelos con servicio, pero sí hay pelos que lo referencian
    (sin servicio) — existe, pero no tiene ningún servicio matcheado todavía."""
    sesion = _SesionFake(respuestas={"FROM app.cromo_pelos WHERE cable_n_id": [(1,)]})
    resultado = await verificador.servicios_por_cable(sesion, 10191706)

    assert resultado.cable_n_id == 10191706
    assert resultado.nombre is None
    assert resultado.servicios == []


# ── servicios_por_tubo ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_servicios_por_tubo_no_encontrado():
    sesion = _SesionFake()
    with pytest.raises(verificador.ObjetoNoEncontrado):
        await verificador.servicios_por_tubo(sesion, 999)


@pytest.mark.asyncio
async def test_servicios_por_tubo_con_matches():
    sesion = _SesionFake(
        respuestas={
            "FROM app.cromo_tubos": [(129001, 51, 3, "AZUL")],
            "cromo_pelos p\n    JOIN app.cromo_servicio_match": [_FILA_SERVICIO],
        }
    )
    resultado = await verificador.servicios_por_tubo(sesion, 129001)

    assert resultado.tubo_n_id == 129001
    assert resultado.cable_n_id == 51
    assert resultado.nombre_color == "AZUL"
    assert len(resultado.servicios) == 1


@pytest.mark.asyncio
async def test_servicios_por_tubo_referencia_colgada_con_matches():
    """Mismo hallazgo real que en cable: el tubo puede tener servicio matcheado sin fila propia."""
    sesion = _SesionFake(respuestas={"cromo_pelos p\n    JOIN app.cromo_servicio_match": [_FILA_SERVICIO]})
    resultado = await verificador.servicios_por_tubo(sesion, 10191747)

    assert resultado.tubo_n_id == 10191747
    assert resultado.cable_n_id is None
    assert len(resultado.servicios) == 1


# ── servicios_por_botella ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_servicios_por_botella_no_encontrada():
    sesion = _SesionFake()
    with pytest.raises(verificador.ObjetoNoEncontrado):
        await verificador.servicios_por_botella(sesion, 999)


@pytest.mark.asyncio
async def test_servicios_por_botella_con_matches():
    sesion = _SesionFake(
        respuestas={
            "FROM app.cromo_botellas": [(68001, "ODF Central", 69, "CABA")],
            "FROM app.cromo_cables c": [_FILA_SERVICIO],
        }
    )
    resultado = await verificador.servicios_por_botella(sesion, 68001)

    assert resultado.botella_n_id == 68001
    assert resultado.clase == 69
    assert len(resultado.servicios) == 1
    assert resultado.servicios[0].nombre_cliente == "Cliente Uno"


@pytest.mark.asyncio
async def test_servicios_por_botella_referencia_colgada_con_matches():
    """Mismo hallazgo real: la botella puede tener servicios matcheados vía sus cables aunque su
    propia fila todavía no haya bajado (bottella extremo de un cable ya ingerido, ella no)."""
    sesion = _SesionFake(respuestas={"FROM app.cromo_cables c": [_FILA_SERVICIO]})
    resultado = await verificador.servicios_por_botella(sesion, 68003)

    assert resultado.botella_n_id == 68003
    assert resultado.clase is None
    assert len(resultado.servicios) == 1


@pytest.mark.asyncio
async def test_servicios_por_botella_sin_matches():
    sesion = _SesionFake(respuestas={"FROM app.cromo_botellas": [(68002, None, 68, None)]})
    resultado = await verificador.servicios_por_botella(sesion, 68002)

    assert resultado.nombre is None
    assert resultado.servicios == []
