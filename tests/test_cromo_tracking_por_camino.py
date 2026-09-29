# Nombre de archivo: test_cromo_tracking_por_camino.py
# Ubicación de archivo: tests/test_cromo_tracking_por_camino.py
# Descripción: Pruebas de "un .txt por camino distinto" — pelos del camino, descarte de semillas ya recorridas y caché sin la lista de pelos

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.services.cromo import tracking_service
from core.services.cromo.camino_optico_service import ESTADO_OK, CaminoOptico, NodoCamino
from core.services.cromo.tracking_cache import TrackingCacheado
from core.services.cromo.tracking_service import (
    TrackingGenerado,
    TrackingNoDisponible,
    pelos_del_camino,
    trackings_por_camino,
)

AHORA = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


def _nodo(orden: int, id_cromo: int, clase: int, lado: str = "A") -> NodoCamino:
    return NodoCamino(orden=orden, lado=lado, id_cromo=id_cromo, clase=clase, tipo="X")


def test_pelos_del_camino_junta_la_raiz_y_los_pelos_de_ambos_lados():
    """Sólo pelos (130): fusiones (132) y conectores (136) no son semillas posibles."""
    camino = CaminoOptico(
        estado=ESTADO_OK,
        pelo_n_id=6976965,
        lado_a=[_nodo(0, 7968011, 130), _nodo(1, 8599229, 136), _nodo(2, 9001, 132)],
        lado_b=[_nodo(0, 7501313, 130, lado="B")],
    )

    assert pelos_del_camino(camino) == frozenset({6976965, 7968011, 7501313})


def _generado(pelo: int, pelos_camino: set[int]) -> TrackingGenerado:
    return TrackingGenerado(
        pelo_n_id=pelo,
        nombre_archivo="42351 CROMO.txt",
        contenido=f"camino de {pelo}",
        desde_cache=False,
        generado_at=AHORA,
        duracion_ms=100,
        pelos_camino=frozenset(pelos_camino),
    )


@pytest.mark.asyncio
async def test_una_semilla_que_ya_aparece_en_un_camino_anterior_no_genera_otro_txt(monkeypatch):
    """Servicio 42351: sus dos pelos (hilo "g" y hilo "gd") tienen posición en varias ODF —TASA,
    TECO, Facebook— y cada posición es una semilla. Todas las del mismo hilo recorren el MISMO
    camino: tienen que dar un solo `.txt`, no uno por ODF. Y la semilla descartada no se pide a
    Cromo."""
    caminos = {
        6976963: {6976963, 7968010, 111},  # hilo "g": pasa por TECO (7968010)
        6976965: {6976965, 7968011, 222},  # hilo "gd": pasa por TECO (7968011)
    }
    pedidos: list[int] = []

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        pedidos.append(pelo_n_id)
        return _generado(pelo_n_id, caminos[pelo_n_id])

    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)

    resultado = await trackings_por_camino(
        object(), object(), servicio_id=567, pelos_n_id=[6976963, 6976965, 7968010, 7968011]
    )

    assert [t.pelo_n_id for t in resultado.trackings] == [6976963, 6976965]
    assert pedidos == [6976963, 6976965]
    assert resultado.omitidos == {7968010: 6976963, 7968011: 6976965}
    assert resultado.errores == []


@pytest.mark.asyncio
async def test_un_pelo_que_falla_no_cancela_los_demas(monkeypatch):
    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        if pelo_n_id == 1:
            raise TrackingNoDisponible("sin camino", "SIN_CAMINO")
        return _generado(pelo_n_id, {pelo_n_id})

    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)

    resultado = await trackings_por_camino(object(), object(), servicio_id=1, pelos_n_id=[1, 2])

    assert [t.pelo_n_id for t in resultado.trackings] == [2]
    assert resultado.errores == ["Pelo 1: sin camino"]


@pytest.mark.asyncio
async def test_la_misma_semilla_repetida_se_pide_una_sola_vez(monkeypatch):
    pedidos: list[int] = []

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        pedidos.append(pelo_n_id)
        return _generado(pelo_n_id, {pelo_n_id})

    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)

    resultado = await trackings_por_camino(object(), object(), servicio_id=1, pelos_n_id=[5, 5])

    assert pedidos == [5]
    assert len(resultado.trackings) == 1


class _SesionNula:
    async def commit(self) -> None:
        return None


@pytest.mark.asyncio
async def test_cache_sin_lista_de_pelos_se_regenera(monkeypatch):
    """Las entradas de caché anteriores a este cambio no saben qué pelos recorre su camino: sin
    esa lista no se pueden descartar repetidos, así que se regeneran una vez."""

    async def _leer(_sesion, pelo_n_id):
        return TrackingCacheado(
            pelo_n_id=pelo_n_id,
            nombre_archivo="viejo.txt",
            contenido="viejo",
            generado_at=AHORA,
            duracion_ms=1,
            pelos_camino=None,
        )

    guardados: list[dict] = []

    async def _guardar(_sesion, **kwargs):
        guardados.append(kwargs)

    async def _resolver(_cliente, _sesion, pelo_n_id):
        return CaminoOptico(estado=ESTADO_OK, pelo_n_id=pelo_n_id, lado_a=[_nodo(0, 77, 130)])

    monkeypatch.setattr(tracking_service.tracking_cache, "leer", _leer)
    monkeypatch.setattr(tracking_service.tracking_cache, "guardar", _guardar)
    monkeypatch.setattr(tracking_service, "resolver_camino_de_pelo", _resolver)
    monkeypatch.setattr(tracking_service, "renderizar_tracking_txt", lambda _c, generado_en: "nuevo")

    tracking = await tracking_service.obtener_tracking(
        object(), _SesionNula(), servicio_id=1, pelo_n_id=10
    )

    assert tracking.desde_cache is False
    assert tracking.contenido == "nuevo"
    assert tracking.pelos_camino == frozenset({10, 77})
    assert guardados[0]["pelos_camino"] == [10, 77]


@pytest.mark.asyncio
async def test_cache_con_lista_de_pelos_se_sirve_sin_ir_a_cromo(monkeypatch):
    async def _leer(_sesion, pelo_n_id):
        return TrackingCacheado(
            pelo_n_id=pelo_n_id,
            nombre_archivo="42351 CROMO.txt",
            contenido="cacheado",
            generado_at=AHORA,
            duracion_ms=1,
            pelos_camino=[10, 77],
        )

    async def _resolver(*_a, **_k):
        raise AssertionError("no debería ir a Cromo")

    monkeypatch.setattr(tracking_service.tracking_cache, "leer", _leer)
    monkeypatch.setattr(tracking_service, "resolver_camino_de_pelo", _resolver)

    tracking = await tracking_service.obtener_tracking(
        object(), _SesionNula(), servicio_id=1, pelo_n_id=10
    )

    assert tracking.desde_cache is True
    assert tracking.pelos_camino == frozenset({10, 77})
