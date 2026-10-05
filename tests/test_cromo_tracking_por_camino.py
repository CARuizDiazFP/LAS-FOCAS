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


# ── Caminos esperados y huérfanos (Servicio 94673, 2026-10-05) ──────────────────────────────


def test_moda_de_pelos_por_grupo_toma_la_moda_y_no_el_maximo():
    """Medido real: 42351 tiene 145 cables con 2 pelos, 12 con 3 y 1 con 4 (etiquetas viejas).
    El máximo daría 4 caminos; son 2."""
    from core.services.cromo.camino_optico_service import moda_de_pelos_por_grupo

    assert moda_de_pelos_por_grupo([1] * 26 + [2] * 145 + [3] * 12 + [4]) == 2
    assert moda_de_pelos_por_grupo([2] * 26) == 2  # 94673: sin ODF, 2 por cable
    assert moda_de_pelos_por_grupo([1, 2]) == 2, "empate: el mayor, para no quedarse corto"
    assert moda_de_pelos_por_grupo([]) == 0
    assert moda_de_pelos_por_grupo([0, 0]) == 0


def _hilos_94673():
    """Dos hilos, 3 pelos cada uno; las semillas vienen ordenadas por n_id, alternando hilos."""
    c10 = {6799772, 7410197, 7589083}
    c9 = {6799773, 7410198, 7589084}
    return c10, c9


@pytest.mark.asyncio
async def test_sin_odf_las_semillas_de_cable_dan_un_txt_por_hilo(monkeypatch):
    """94673 no termina en ODF: antes se tomaba sólo la primera semilla y salía 1 `.txt` de 2.
    Con todas las semillas, 2 llamadas a Cromo y 2 caminos."""
    c10, c9 = _hilos_94673()
    pedidos: list[int] = []

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        pedidos.append(pelo_n_id)
        return _generado(pelo_n_id, c10 if pelo_n_id in c10 else c9)

    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)

    resultado = await trackings_por_camino(
        object(), object(), servicio_id=1066, pelos_n_id=sorted(c10 | c9), esperados=2
    )

    assert [t.pelo_n_id for t in resultado.trackings] == [6799772, 6799773]
    assert pedidos == [6799772, 6799773]
    assert resultado.completo is True
    assert resultado.no_cubiertos == []


@pytest.mark.asyncio
async def test_un_huerfano_no_genera_un_tercer_txt_ni_se_pide_a_cromo(monkeypatch):
    c10, c9 = _hilos_94673()
    huerfano = 9999999  # etiqueta vieja de un pelo movido: no está en ningún camino
    pedidos: list[int] = []

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        pedidos.append(pelo_n_id)
        return _generado(pelo_n_id, c10 if pelo_n_id in c10 else c9)

    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)

    resultado = await trackings_por_camino(
        object(),
        object(),
        servicio_id=1066,
        pelos_n_id=sorted(c10 | c9) + [huerfano],
        esperados=2,
    )

    assert len(resultado.trackings) == 2
    assert huerfano not in pedidos
    assert resultado.no_cubiertos == [huerfano]
    assert resultado.completo is True


@pytest.mark.asyncio
async def test_faltan_caminos_se_informa_como_incompleto(monkeypatch):
    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        if pelo_n_id == 2:
            raise TrackingNoDisponible("sin camino", "SIN_CAMINO")
        return _generado(pelo_n_id, {1, 3})

    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)

    resultado = await trackings_por_camino(
        object(), object(), servicio_id=1, pelos_n_id=[1, 2, 3], esperados=2
    )

    assert [t.pelo_n_id for t in resultado.trackings] == [1]
    assert resultado.completo is False
    assert resultado.no_cubiertos == [2]
    assert resultado.errores == ["Pelo 2: sin camino"]


@pytest.mark.asyncio
async def test_max_fallidos_corta_antes_de_pedir_cientos_de_pelos(monkeypatch):
    pedidos: list[int] = []

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        pedidos.append(pelo_n_id)
        raise TrackingNoDisponible("sin camino", "SIN_CAMINO")

    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)

    resultado = await trackings_por_camino(
        object(), object(), servicio_id=1, pelos_n_id=list(range(1, 200)), esperados=2,
        max_fallidos=3,
    )

    assert pedidos == [1, 2, 3]
    assert resultado.completo is False


def _semilla(pelo: int, *, conector: bool = False):
    from core.services.cromo.camino_optico_service import PeloSemilla

    return PeloSemilla(
        pelo_n_id=pelo,
        servicio_numero="94673",
        metodo="REGEX_EXACTO",
        confianza=100,
        numero_pelo="21",
        color="AM",
        cable_n_id=1,
        cable_nombre="F-VIN-TEC",
        tiene_conector_odf=conector,
        servicio_raw=None,
    )


@pytest.mark.asyncio
async def test_trackings_del_servicio_reporta_huerfanos_solo_si_esta_completo(monkeypatch):
    c10, c9 = _hilos_94673()
    semillas = [_semilla(p) for p in sorted(c10 | c9)] + [_semilla(9999999)]

    async def _semillas(_sesion, _servicio_id):
        return semillas

    async def _esperados(_sesion, _servicio_id):
        return 2

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        return _generado(pelo_n_id, c10 if pelo_n_id in c10 else c9)

    monkeypatch.setattr(tracking_service, "semillas_para_tracking", _semillas)
    monkeypatch.setattr(tracking_service, "caminos_esperados", _esperados)
    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 1066)

    assert resultado.esperados == 2
    assert len(resultado.trackings) == 2
    assert [s.pelo_n_id for s in resultado.huerfanos] == [9999999]


@pytest.mark.asyncio
async def test_trackings_del_servicio_sin_grupos_espera_un_camino(monkeypatch):
    async def _semillas(_sesion, _servicio_id):
        return [_semilla(1), _semilla(2)]

    async def _esperados(_sesion, _servicio_id):
        return 0

    pedidos: list[int] = []

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        pedidos.append(pelo_n_id)
        return _generado(pelo_n_id, {pelo_n_id})

    monkeypatch.setattr(tracking_service, "semillas_para_tracking", _semillas)
    monkeypatch.setattr(tracking_service, "caminos_esperados", _esperados)
    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 1)

    assert resultado.esperados == 1
    assert pedidos == [1]


# ── Exclusión local de pelos huérfanos ──────────────────────────────────────────────────────


class _SesionRegistro:
    def __init__(self) -> None:
        self.inserts: list[dict] = []
        self.commits = 0

    async def execute(self, _sql, params):
        self.inserts.append(params)

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_excluir_pelos_separa_ajenos_y_no_escribe_si_todos_lo_son(monkeypatch):
    from core.services.cromo import pelos_excluidos

    async def _pertenece(_sesion, _servicio_id, pelo_n_id):
        return pelo_n_id != 5

    monkeypatch.setattr(pelos_excluidos, "pelo_pertenece_al_servicio", _pertenece)

    sesion = _SesionRegistro()
    excluidos, ajenos = await pelos_excluidos.excluir_pelos(
        sesion, 17, [1, 2, 5, 2], usuario="admin", motivo="  Huérfano  "
    )
    assert excluidos == [1, 2] and ajenos == [5]
    assert [i["pelo_n_id"] for i in sesion.inserts] == [1, 2]
    assert sesion.inserts[0]["motivo"] == "Huérfano"
    assert sesion.commits == 1

    sesion = _SesionRegistro()
    with pytest.raises(pelos_excluidos.PeloNoPerteneceAlServicio):
        await pelos_excluidos.excluir_pelos(sesion, 17, [5], usuario="admin")
    assert sesion.inserts == [] and sesion.commits == 0
