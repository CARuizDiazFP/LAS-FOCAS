# Nombre de archivo: test_cromo_validador_datos_service.py
# Ubicación de archivo: tests/test_cromo_validador_datos_service.py
# Descripción: Pruebas del validador de datos en vivo contra Cromo (Tool Kit "Validar datos DB Cromo"), sin red ni DB real

from __future__ import annotations

from typing import Any, Optional

import pytest

from core.services.cromo.client import CromoClientError
from core.services.cromo.validador_datos_service import validar_elemento_cromo
from core.services.cromo.verificador import ObjetoNoEncontrado


class _ClienteFake:
    def __init__(self, respuesta: Optional[dict[str, Any]] = None, error: Optional[Exception] = None) -> None:
        self._respuesta = respuesta
        self._error = error

    async def get_objeto(self, n_id: int) -> dict[str, Any]:
        if self._error is not None:
            raise self._error
        return self._respuesta


# ── Botella con árbol completo ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_botella_arma_arbol_completo_con_cables_tubos_pelos_fusiones():
    obj = {
        "id": 999,
        "n_id": 10178728,
        "class": 68,
        "name": "Cra San Martin 201 Bot 2 CF",
        "at": [
            {"seq": 1, "id": 34, "value": "Cra San Martin 201 Bot 2 CF"},
            {"seq": 2, "id": 35, "value": "Faltan módulos del Lado B"},
            {"seq": 3, "id": 41, "value": "FIST-BC16"},
            {"seq": 4, "id": 91, "value": "1242388"},
        ],
        "inner": [
            {
                "id": 90099,
                "n_id": 90010,
                "class": 132,
                "parent": 10178728,
                "name": "53-17",
                "at": [{"seq": 1, "id": 84, "value": "53-17"}, {"seq": 2, "id": 85, "value": "FUSION"}],
                "tp": [
                    {"type": 1, "nfrom": 0, "id_to": 70010, "nto": 0, "class": 130},
                    {"type": 1, "nfrom": 1, "id_to": 70020, "nto": 0, "class": 130},
                ],
            }
        ],
        "tp": [
            {
                "type": 2,
                "nfrom": 0,
                "id_to": 50010,
                "nto": 1,
                "class": 51,
                "id": 50099,
                "n_id": 50010,
                "vmax": 2,
                "name": "F-PLB-ART",
                "at": [{"seq": 1, "id": 26, "value": "F-PLB-ART"}],
                "inner": [
                    {"id": 60099, "n_id": 60010, "class": 129, "parent": 50010, "at": []},
                    {
                        "id": 70010,
                        "n_id": 70010,
                        "class": 130,
                        "parent": 60010,
                        "at": [{"seq": 1, "id": 61, "value": "FO 12345 - Cliente Uno"}],
                    },
                ],
            }
        ],
    }
    cliente = _ClienteFake(respuesta=obj)

    resultado = await validar_elemento_cromo(cliente, 10178728)

    assert resultado.tipo_objeto == "Botella"
    assert resultado.nombre == "Cra San Martin 201 Bot 2 CF"
    assert resultado.notas == "Faltan módulos del Lado B"
    assert resultado.codigo_modelo == "FIST-BC16"
    assert resultado.id_legacy == "1242388"
    assert len(resultado.cables) == 1
    assert resultado.cables[0].n_id == 50010
    assert len(resultado.tubos) == 1
    assert len(resultado.pelos) == 1
    assert resultado.pelos[0].servicio_raw == "FO 12345 - Cliente Uno"
    assert len(resultado.fusiones) == 1
    assert resultado.fusiones[0].nombre_par == "53-17"
    assert resultado.errores_parseo == []
    assert resultado.payload_raw is obj


# ── Cable consultado directo ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cable_directo_sin_inner_no_trae_tubos_ni_pelos():
    obj = {
        "id": 50199,
        "n_id": 50010,
        "class": 51,
        "name": "F-PLB-ART",
        "at": [{"seq": 1, "id": 26, "value": "F-PLB-ART"}],
        "tp": [
            {"type": 1, "nfrom": 0, "id_to": 10178728, "nto": 0, "class": 68},
            {"type": 1, "nfrom": 1, "id_to": 10444555, "nto": 0, "class": 124},
        ],
    }
    cliente = _ClienteFake(respuesta=obj)

    resultado = await validar_elemento_cromo(cliente, 50010)

    assert resultado.tipo_objeto == "Cable"
    assert resultado.nombre == "F-PLB-ART"
    assert len(resultado.cables) == 1
    assert resultado.cables[0].extremo_a_n_id == 10178728
    assert resultado.tubos == []
    assert resultado.pelos == []


@pytest.mark.asyncio
async def test_cable_directo_con_inner_trae_sus_propios_tubos_y_pelos():
    obj = {
        "id": 50199,
        "n_id": 50010,
        "class": 51,
        "name": "F-PLB-ART",
        "at": [],
        "inner": [
            {"id": 60099, "n_id": 60010, "class": 129, "parent": 50010, "at": []},
            {"id": 70010, "n_id": 70010, "class": 130, "parent": 60010, "at": []},
        ],
    }
    cliente = _ClienteFake(respuesta=obj)

    resultado = await validar_elemento_cromo(cliente, 50010)

    assert len(resultado.tubos) == 1
    assert resultado.tubos[0].n_id == 60010
    assert len(resultado.pelos) == 1
    assert resultado.pelos[0].n_id == 70010
    assert resultado.pelos[0].cable_n_id == 50010


# ── Fusión, tubo y pelo consultados directo ──────────────────────────────────


@pytest.mark.asyncio
async def test_fusion_directa():
    obj = {
        "id": 90099,
        "n_id": 90010,
        "class": 132,
        "name": "53-17",
        "at": [{"seq": 1, "id": 84, "value": "53-17"}],
        "tp": [
            {"type": 1, "nfrom": 0, "id_to": 70010, "nto": 0, "class": 130},
            {"type": 1, "nfrom": 1, "id_to": 70020, "nto": 0, "class": 130},
        ],
    }
    cliente = _ClienteFake(respuesta=obj)

    resultado = await validar_elemento_cromo(cliente, 90010)

    assert resultado.tipo_objeto == "Fusion"
    assert resultado.nombre == "53-17"
    assert len(resultado.fusiones) == 1
    assert resultado.fusiones[0].pelo_a_n_id == 70010


@pytest.mark.asyncio
async def test_tubo_directo():
    obj = {"id": 60099, "n_id": 60010, "class": 129, "parent": 50010, "at": [{"seq": 1, "id": 73, "value": "AZ"}]}
    cliente = _ClienteFake(respuesta=obj)

    resultado = await validar_elemento_cromo(cliente, 60010)

    assert resultado.tipo_objeto == "Tubo"
    assert len(resultado.tubos) == 1
    assert resultado.tubos[0].nombre_color == "AZ"


@pytest.mark.asyncio
async def test_pelo_directo_expone_servicio_crudo_sin_matchear():
    obj = {
        "id": 70010,
        "n_id": 70010,
        "class": 130,
        "parent": 60010,
        "at": [
            {"seq": 1, "id": 74, "value": "1"},
            {"seq": 2, "id": 61, "value": "FO 12345 - Cliente Uno"},
        ],
    }
    cliente = _ClienteFake(respuesta=obj)

    resultado = await validar_elemento_cromo(cliente, 70010)

    assert resultado.tipo_objeto == "Pelo"
    assert len(resultado.pelos) == 1
    assert resultado.pelos[0].servicio_raw == "FO 12345 - Cliente Uno"
    assert resultado.pelos[0].servicio_numero == "12345"  # parseado por parser.py, no matcheado contra DB


# ── ODF consultado directo (class 69) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_odf_directo_expone_sus_propios_campos_no_blanks():
    """Regresión de la revisión de rama completa: registrar la clase 69 en `parser._DISPATCH`
    (otra tarea de este mismo plan) hizo que `parse_objeto` devolviera un `Odf` en vez de lanzar
    `ClaseNoSoportadaError` — pero este validador no tenía ninguna rama `isinstance` para `Odf`,
    así que `tipo_objeto` quedaba en el string crudo `"Odf"` y todo lo demás (`nombre`, `notas`,
    `codigo_modelo`, `id_legacy`, `latitud`, `longitud`) quedaba en `None` sin ningún error en
    `errores_parseo`. Este test prueba que ahora se puebla desde los campos propios del `Odf`."""
    obj = {
        "id": 900004,
        "n_id": 800004,
        "class": 69,
        "ll": [-58.4173, -34.6037],
        "at": [
            {"id": 34, "value": "ODF Calle 9 Nro 593 PILAR"},
            {"id": 41, "value": "MOD-1"},
            {"id": 91, "value": "LEGACY-1"},
            {"id": 35, "value": "una nota"},
            {"id": 68, "value": "PILAR"},
        ],
    }
    cliente = _ClienteFake(respuesta=obj)

    resultado = await validar_elemento_cromo(cliente, 800004)

    assert resultado.tipo_objeto == "Odf"
    assert resultado.nombre == "ODF Calle 9 Nro 593 PILAR"
    assert resultado.notas == "una nota"
    assert resultado.codigo_modelo == "MOD-1"
    assert resultado.id_legacy == "LEGACY-1"
    assert resultado.latitud == pytest.approx(-34.6037)
    assert resultado.longitud == pytest.approx(-58.4173)
    assert resultado.errores_parseo == []


# ── Clases problemáticas — nunca rompe, siempre informa ──────────────────────


@pytest.mark.asyncio
async def test_clase_excluida_no_rompe_y_queda_en_errores():
    obj = {"id": 1, "n_id": 1, "class": 120, "at": []}
    cliente = _ClienteFake(respuesta=obj)

    resultado = await validar_elemento_cromo(cliente, 1)

    assert resultado.tipo_objeto == "Desconocido"
    assert len(resultado.errores_parseo) == 1
    assert "excluida" in resultado.errores_parseo[0].motivo


@pytest.mark.asyncio
async def test_clase_no_soportada_no_rompe_y_queda_en_errores():
    obj = {"id": 1, "n_id": 1, "class": 999999, "at": []}
    cliente = _ClienteFake(respuesta=obj)

    resultado = await validar_elemento_cromo(cliente, 1)

    assert resultado.tipo_objeto == "Desconocido"
    assert len(resultado.errores_parseo) == 1


# ── Traducción de errores del cliente ────────────────────────────────────────


@pytest.mark.asyncio
async def test_404_se_traduce_a_objeto_no_encontrado():
    cliente = _ClienteFake(error=CromoClientError("no encontrado", status_code=404))

    with pytest.raises(ObjetoNoEncontrado):
        await validar_elemento_cromo(cliente, 42)


@pytest.mark.asyncio
async def test_error_no_404_se_repropaga_tal_cual():
    cliente = _ClienteFake(error=CromoClientError("Cromo caído", status_code=503))

    with pytest.raises(CromoClientError):
        await validar_elemento_cromo(cliente, 42)
