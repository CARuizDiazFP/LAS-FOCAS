# Nombre de archivo: test_cromo_bajas_service.py
# Ubicación de archivo: tests/test_cromo_bajas_service.py
# Descripción: Señal de borrado de Cromo, confirmación doble y compuertas de la baja lógica de cables fantasma (sin red ni DB)

"""Los payloads de `estado_en_cromo` son recortes de respuestas reales de `GET /db/objects/{id}`
medidas el 2026-10-02 (ver docstring de `core/services/cromo/bajas_service.py`)."""

from __future__ import annotations

from typing import Any

import pytest

from core.services.cromo import bajas_service, ingesta
from core.services.cromo.client import CromoClientError

# F-TIG-003-B 9609095: partido en Cromo el 2026-09-10. La última versión del linaje está cerrada.
FANTASMA_9609095 = {
    "id": 9609095, "class": 51, "vfrom": 125836, "vmax": 275695, "to": 1789029078, "vto": 275694,
    "hist": [
        {"id": 9609095, "next_id": 10276676, "to": 1789029078, "vto": 275694},
        {"id": 10276676, "next_id": 0, "to": 1789029642, "vto": 275695},
    ],
}
# F-ROW-K52JAAA 10259700: el id pedido es una versión vieja (tiene `to`), pero la última sigue abierta.
VIVO_VERSIONADO_10259700 = {
    "id": 10259700, "class": 51, "code": "F-ROW-K52JAAA", "to": 1786639196, "vto": 272213,
    "hist": [
        {"id": 10259700, "next_id": 10259871, "to": 1786639196, "vto": 272213},
        {"id": 10259871, "next_id": 0, "to": 0, "vto": 0},
    ],
}
# F-TIG-003-B 10277060: una sola versión, sin `to`/`vto` ni `hist`.
VIVO_SIMPLE_10277060 = {"id": 10277060, "class": 51, "code": "F-TIG-003-B", "vfrom": 275695, "vmax": 275695}


def test_estado_en_cromo_fantasma_por_ultima_version_cerrada():
    estado = bajas_service.estado_en_cromo(FANTASMA_9609095)
    assert estado.borrado is True
    assert estado.id_ultima_version == 10276676
    assert estado.vto_final == 275695  # = vfrom de sus sucesores F-TIG-003-A/B


def test_estado_en_cromo_vto_del_objeto_pedido_no_alcanza():
    """El caso que descarta "tiene vto ⇒ borrado": hay que mirar la última versión del linaje."""
    estado = bajas_service.estado_en_cromo(VIVO_VERSIONADO_10259700)
    assert estado.borrado is False
    assert estado.id_ultima_version == 10259871
    assert estado.vto_final is None


def test_estado_en_cromo_vivo_sin_historial():
    assert bajas_service.estado_en_cromo(VIVO_SIMPLE_10277060).borrado is False


def test_estado_en_cromo_una_version_cerrada_sin_historial():
    estado = bajas_service.estado_en_cromo({"id": 1, "to": 1700000000, "vto": 99})
    assert estado.borrado is True and estado.vto_final == 99


class _ClienteEstados:
    def __init__(self, respuestas: dict[int, Any]) -> None:
        self.respuestas = respuestas
        self.pedidos: list[int] = []

    async def get_objeto(self, n_id: int) -> dict[str, Any]:
        self.pedidos.append(n_id)
        r = self.respuestas[n_id]
        if isinstance(r, Exception):
            raise r
        return {"st": 0, "response": r}


@pytest.mark.asyncio
async def test_confirmar_borrados_un_error_nunca_cuenta_como_borrado():
    cliente = _ClienteEstados({
        9609095: FANTASMA_9609095,
        10259700: VIVO_VERSIONADO_10259700,
        5: CromoClientError("timeout", status_code=503),
    })
    borrados, vivos, errores = await bajas_service.confirmar_borrados(cliente, [9609095, 10259700, 5])
    assert borrados == [(9609095, 275695)]
    assert vivos == [10259700]
    assert [n for n, _ in errores] == [5]


class _SesionNula:
    def __init__(self) -> None:
        self.eventos: list[Any] = []
        self.commits = 0

    def add(self, obj: Any) -> None:
        self.eventos.append(obj)

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_conciliar_aborta_sobre_el_tope_sin_dar_de_baja(monkeypatch):
    async def _ausentes(sesion, clase, vistos):
        return [1, 2, 3]

    async def _confirmar(cliente, candidatos, **_):
        return [(n, 10) for n in candidatos], [], []

    llamadas: list[int] = []

    async def _baja(*args, **kwargs):  # pragma: no cover - no debe llamarse
        llamadas.append(1)

    monkeypatch.setattr(bajas_service, "cables_ausentes", _ausentes)
    monkeypatch.setattr(bajas_service, "confirmar_borrados", _confirmar)
    monkeypatch.setattr(bajas_service, "aplicar_baja_cable", _baja)
    sesion = _SesionNula()

    resumen = await bajas_service.conciliar_bajas_de_clase(object(), sesion, 7, 51, set(), tope=2)

    assert resumen.abortado is True and resumen.bajas == 0
    assert llamadas == []
    assert [e.accion for e in sesion.eventos] == ["BAJAS_ABORTADAS"]


@pytest.mark.asyncio
async def test_conciliar_vivos_no_listados_no_se_dan_de_baja(monkeypatch):
    async def _ausentes(sesion, clase, vistos):
        return [10259700]

    async def _confirmar(cliente, candidatos, **_):
        return [], [10259700], []

    monkeypatch.setattr(bajas_service, "cables_ausentes", _ausentes)
    monkeypatch.setattr(bajas_service, "confirmar_borrados", _confirmar)
    sesion = _SesionNula()

    resumen = await bajas_service.conciliar_bajas_de_clase(object(), sesion, 7, 51, set())

    assert resumen.bajas == 0 and resumen.vivos_no_listados == 1
    assert [e.accion for e in sesion.eventos] == ["CABLE_AUSENTE_VIVO"]


@pytest.mark.asyncio
async def test_conciliar_bajas_de_ingesta_no_corre_con_barrido_parcial(monkeypatch):
    """Con `max_paginas` el conjunto de vistos es una muestra: todo lo demás parecería borrado."""
    llamadas: list[int] = []

    async def _conciliar(*args, **kwargs):  # pragma: no cover - no debe llamarse
        llamadas.append(1)

    monkeypatch.setattr(bajas_service, "conciliar_bajas_de_clase", _conciliar)

    await ingesta._conciliar_bajas(object(), object(), object(), (51,), set(), max_paginas=3)

    assert llamadas == []


@pytest.mark.asyncio
async def test_registrando_vistos_anota_antes_de_procesar_aunque_falle():
    vistos: set[int] = set()

    async def _falla(obj):
        raise ValueError("parser")

    procesar = ingesta._registrando_vistos(vistos, _falla)
    with pytest.raises(ValueError):
        await procesar({"id": 10259871, "n_id": 10259700})

    assert vistos == {10259871, 10259700}
