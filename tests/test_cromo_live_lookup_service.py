# Nombre de archivo: test_cromo_live_lookup_service.py
# Ubicación de archivo: tests/test_cromo_live_lookup_service.py
# Descripción: Pruebas del visor en vivo de un elemento Cromo, sin red ni DB real

from __future__ import annotations

from typing import Any, Optional

import pytest

from core.services.cromo.client import CromoClientError
from core.services.cromo.live_lookup_service import obtener_elemento_vivo
from core.services.cromo.verificador import ObjetoNoEncontrado


class _ClienteFake:
    def __init__(self, respuesta: Optional[dict[str, Any]] = None, error: Optional[Exception] = None) -> None:
        self._respuesta = respuesta
        self._error = error
        self.n_ids_consultados: list[int] = []

    async def get_objeto(self, n_id: int) -> dict[str, Any]:
        self.n_ids_consultados.append(n_id)
        if self._error is not None:
            raise self._error
        return self._respuesta


class _ClaseFake:
    def __init__(self, clase: int, etiqueta: Optional[str], entidad: Optional[str]) -> None:
        self.clase = clase
        self.etiqueta = etiqueta
        self.entidad = entidad


class _SesionFake:
    def __init__(self, clases: Optional[dict[int, _ClaseFake]] = None) -> None:
        self._clases = clases or {}

    async def get(self, modelo_cls: type, pk: int) -> Optional[_ClaseFake]:
        return self._clases.get(pk)


# ── caso feliz ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_obtener_elemento_vivo_arma_atributos_con_etiquetas_conocidas_y_desconocidas():
    obj = {
        "id": 999,
        "n_id": 10178728,
        "class": 68,
        "name": "Cra San Martin 201 Bot 2 CF",
        "at": [
            {"id": 35, "value": "Faltan módulos del Lado B"},
            {"id": 91, "value": "1242388"},
            {"id": 555, "value": "algo sin mapear"},
        ],
    }
    cliente = _ClienteFake(respuesta=obj)
    sesion = _SesionFake({68: _ClaseFake(clase=68, etiqueta="Botella FIST", entidad="BOTELLA")})

    elemento = await obtener_elemento_vivo(cliente, sesion, 10178728)

    assert elemento.n_id == 10178728
    assert elemento.version_id == 999
    assert elemento.clase == 68
    assert elemento.clase_etiqueta == "Botella FIST"
    assert elemento.clase_entidad == "BOTELLA"
    assert elemento.nombre == "Cra San Martin 201 Bot 2 CF"
    assert elemento.notas == "Faltan módulos del Lado B"
    assert elemento.payload_raw is obj
    assert cliente.n_ids_consultados == [10178728]

    por_id = {a.id: a for a in elemento.atributos}
    assert por_id[91].etiqueta == "ID legado"
    assert por_id[91].valor == "1242388"
    # Un id sin mapear no se oculta — cae a un fallback genérico legible.
    assert por_id[555].etiqueta == "Atributo 555"
    assert por_id[555].valor == "algo sin mapear"


@pytest.mark.asyncio
async def test_obtener_elemento_vivo_sin_at_ni_name_no_rompe():
    obj = {"id": 1, "n_id": 1, "class": 51}
    cliente = _ClienteFake(respuesta=obj)
    sesion = _SesionFake()

    elemento = await obtener_elemento_vivo(cliente, sesion, 1)

    assert elemento.nombre is None
    assert elemento.notas is None
    assert elemento.atributos == []


@pytest.mark.asyncio
async def test_obtener_elemento_vivo_clase_sin_fila_en_catalogo_deja_etiquetas_none():
    obj = {"id": 1, "n_id": 1, "class": 9999}
    cliente = _ClienteFake(respuesta=obj)
    sesion = _SesionFake()  # sin la clase 9999 registrada

    elemento = await obtener_elemento_vivo(cliente, sesion, 1)

    assert elemento.clase == 9999
    assert elemento.clase_etiqueta is None
    assert elemento.clase_entidad is None


# ── traducción de errores ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_obtener_elemento_vivo_404_se_traduce_a_objeto_no_encontrado():
    cliente = _ClienteFake(error=CromoClientError("no encontrado", status_code=404))
    sesion = _SesionFake()

    with pytest.raises(ObjetoNoEncontrado):
        await obtener_elemento_vivo(cliente, sesion, 42)


@pytest.mark.asyncio
async def test_obtener_elemento_vivo_error_no_404_se_repropaga_tal_cual():
    cliente = _ClienteFake(error=CromoClientError("Cromo caído", status_code=503))
    sesion = _SesionFake()

    with pytest.raises(CromoClientError):
        await obtener_elemento_vivo(cliente, sesion, 42)
