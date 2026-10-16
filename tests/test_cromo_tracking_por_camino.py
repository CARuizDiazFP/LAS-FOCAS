# Nombre de archivo: test_cromo_tracking_por_camino.py
# Ubicación de archivo: tests/test_cromo_tracking_por_camino.py
# Descripción: Pruebas de "un .txt por camino distinto" — pelos del camino, descarte de semillas ya recorridas, recorrido sin corte en esperados con tope de llamadas, caché sin pelos o sin extremos y separación en tramos y residuales

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
            extremos=_RESUMEN_JSON,
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


_RESUMEN_JSON = {
    "servicio_at62": "42351",
    "inicio": {"tipo": "CONECTOR_ODF", "id_cromo": 1, "clase": 136, "odf_id": 500,
               "odf_clase": 69, "odf_nombre": "TASA", "patchera_nombre": "O-1", "conector_numero": "3"},
    "fin": {"tipo": "PELO", "id_cromo": 77, "clase": 130},
    "odfs": [500],
    "cables": [900],
}


@pytest.mark.asyncio
async def test_cache_sin_extremos_se_regenera_y_guarda_el_resumen(monkeypatch):
    """Entrada previa a la columna `extremos`: sin ellos no se puede clasificar el camino como
    TRAMO o RESIDUAL, así que se regenera una vez (mismo patrón que `pelos_camino`)."""

    async def _leer(_sesion, pelo_n_id):
        return TrackingCacheado(
            pelo_n_id=pelo_n_id,
            nombre_archivo="42351 CROMO.txt",
            contenido="viejo",
            generado_at=AHORA,
            duracion_ms=1,
            pelos_camino=[10, 77],
            extremos=None,
        )

    guardados: list[dict] = []

    async def _guardar(_sesion, **kwargs):
        guardados.append(kwargs)

    conector = NodoCamino(
        orden=0, lado="B", id_cromo=1, clase=136, tipo="CONECTOR_ODF", odf_id=500, odf_clase=86,
        odf_nombre="NODO KORN", patchera_nombre="O-1259853-2", conector_numero="3",
    )

    async def _resolver(_cliente, _sesion, pelo_n_id):
        return CaminoOptico(
            estado=ESTADO_OK,
            pelo_n_id=pelo_n_id,
            servicio_at62="102452",
            lado_a=[_nodo(0, 77, 130)],
            lado_b=[conector],
        )

    monkeypatch.setattr(tracking_service.tracking_cache, "leer", _leer)
    monkeypatch.setattr(tracking_service.tracking_cache, "guardar", _guardar)
    monkeypatch.setattr(tracking_service, "resolver_camino_de_pelo", _resolver)
    monkeypatch.setattr(tracking_service, "renderizar_tracking_txt", lambda _c, generado_en: "nuevo")

    tracking = await tracking_service.obtener_tracking(
        object(), _SesionNula(), servicio_id=1, pelo_n_id=10
    )

    assert tracking.desde_cache is False
    # secuencia_para_tracking: reversed(lado_b) → raíz → lado_a. El primer nodo es el conector.
    assert tracking.extremos.inicio.tipo == "CONECTOR_ODF"
    assert tracking.extremos.inicio.odf_clase == 86
    assert tracking.extremos.inicio.conector_numero == "3"
    assert tracking.extremos.fin.id_cromo == 77
    assert tracking.extremos.odfs == (500,)
    assert tracking.extremos.servicio_at62 == "102452"
    guardado = guardados[0]["extremos"]
    assert guardado["inicio"]["odf_clase"] == 86 and guardado["odfs"] == [500]


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
            extremos=_RESUMEN_JSON,
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
    assert tracking.extremos.inicio.odf_id == 500
    assert tracking.extremos.cables == (900,)
    assert tracking.extremos.servicio_at62 == "42351"


@pytest.mark.parametrize(
    "extremos",
    [
        {**_RESUMEN_JSON, "odfs": ["no-es-un-id"]},
        {**_RESUMEN_JSON, "cables": [None]},
        {**_RESUMEN_JSON, "inicio": {"tipo": "CONECTOR_ODF", "id_cromo": "x"}},
        ["no", "es", "un", "dict"],
    ],
)
@pytest.mark.asyncio
async def test_cache_con_extremos_corruptos_es_un_miss(monkeypatch, extremos):
    """Una fila de caché con `extremos` ilegibles no rompe la descarga: se regenera."""
    from core.services.cromo.tracking_service import ResumenCamino

    assert ResumenCamino.desde_json(extremos) is None

    async def _leer(_sesion, pelo_n_id):
        return TrackingCacheado(
            pelo_n_id=pelo_n_id, nombre_archivo="42351 CROMO.txt", contenido="viejo",
            generado_at=AHORA, duracion_ms=1, pelos_camino=[10, 77], extremos=extremos,
        )

    async def _guardar(_sesion, **_kwargs):
        return None

    async def _resolver(_cliente, _sesion, pelo_n_id):
        return CaminoOptico(estado=ESTADO_OK, pelo_n_id=pelo_n_id, lado_a=[_nodo(0, 77, 130)])

    monkeypatch.setattr(tracking_service.tracking_cache, "leer", _leer)
    monkeypatch.setattr(tracking_service.tracking_cache, "guardar", _guardar)
    monkeypatch.setattr(tracking_service, "resolver_camino_de_pelo", _resolver)
    monkeypatch.setattr(tracking_service, "renderizar_tracking_txt", lambda _c, generado_en: "nuevo")

    tracking = await tracking_service.obtener_tracking(
        object(), _SesionNula(), servicio_id=1, pelo_n_id=10
    )

    assert tracking.desde_cache is False and tracking.contenido == "nuevo"


# ── Sin corte en esperados: cubrir todas las semillas (tracking por tramos, 2026-10-16) ─────


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
    """94673 no termina en ODF: con todas las semillas, 2 llamadas a Cromo y 2 caminos."""
    c10, c9 = _hilos_94673()
    pedidos: list[int] = []

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        pedidos.append(pelo_n_id)
        return _generado(pelo_n_id, c10 if pelo_n_id in c10 else c9)

    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)

    resultado = await trackings_por_camino(
        object(), object(), servicio_id=1066, pelos_n_id=sorted(c10 | c9)
    )

    assert [t.pelo_n_id for t in resultado.trackings] == [6799772, 6799773]
    assert pedidos == [6799772, 6799773]
    assert resultado.completo is True
    assert resultado.no_cubiertos == []


@pytest.mark.asyncio
async def test_no_corta_en_los_esperados_y_pide_toda_semilla_no_cubierta(monkeypatch):
    """Servicio 102452: Cromo corta /path en una ODF Nodo sin patch, así que el servicio tiene
    más caminos que la moda de pelos por cable. Cortar en los esperados perdía tramos reales:
    ahora se pide un camino por cada semilla que ningún camino anterior recorrió."""
    caminos = {1: {1, 2}, 3: {3, 4}, 5: {5}, 6: {6, 7}}
    pedidos: list[int] = []

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        pedidos.append(pelo_n_id)
        return _generado(pelo_n_id, caminos[pelo_n_id])

    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)

    resultado = await trackings_por_camino(
        object(), object(), servicio_id=1168, pelos_n_id=[1, 2, 3, 4, 5, 6, 7]
    )

    assert pedidos == [1, 3, 5, 6]
    assert [t.pelo_n_id for t in resultado.trackings] == [1, 3, 5, 6]
    assert resultado.no_cubiertos == []
    assert resultado.completo is True
    assert resultado.llamadas == 4


@pytest.mark.asyncio
async def test_max_llamadas_corta_y_se_informa_como_incompleto(monkeypatch):
    pedidos: list[int] = []

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        pedidos.append(pelo_n_id)
        return _generado(pelo_n_id, {pelo_n_id})

    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)

    resultado = await trackings_por_camino(
        object(), object(), servicio_id=1, pelos_n_id=list(range(1, 11)), max_llamadas=3
    )

    assert pedidos == [1, 2, 3]
    assert resultado.completo is False
    assert resultado.no_cubiertos == list(range(4, 11))


@pytest.mark.asyncio
async def test_llegar_justo_al_tope_con_todo_cubierto_es_completo(monkeypatch):
    """El tope sólo marca incompleto si quedó una semilla sin cubrir que no se pudo pedir."""

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        return _generado(pelo_n_id, {1, 2, 3} if pelo_n_id == 1 else {4, 5})

    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)

    resultado = await trackings_por_camino(
        object(), object(), servicio_id=1, pelos_n_id=[1, 2, 3, 4, 5], max_llamadas=2
    )

    assert len(resultado.trackings) == 2
    assert resultado.completo is True


@pytest.mark.asyncio
async def test_lo_servido_del_cache_no_cuenta_contra_el_tope(monkeypatch):
    """El tope protege a Cromo: un camino que sale del caché no le cuesta nada."""

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        generado = _generado(pelo_n_id, {pelo_n_id})
        generado.desde_cache = True
        return generado

    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)

    resultado = await trackings_por_camino(
        object(), object(), servicio_id=1, pelos_n_id=[1, 2, 3, 4], max_llamadas=1
    )

    assert len(resultado.trackings) == 4
    assert resultado.completo is True
    assert resultado.llamadas == 0


def test_tope_de_llamadas_por_entorno(monkeypatch):
    from core.services.cromo.config import tracking_max_llamadas

    monkeypatch.delenv("CROMO_TRACKING_MAX_LLAMADAS", raising=False)
    assert tracking_max_llamadas() == 80
    monkeypatch.setenv("CROMO_TRACKING_MAX_LLAMADAS", "120")
    assert tracking_max_llamadas() == 120
    monkeypatch.setenv("CROMO_TRACKING_MAX_LLAMADAS", "cero")
    assert tracking_max_llamadas() == 80
    monkeypatch.setenv("CROMO_TRACKING_MAX_LLAMADAS", "0")
    assert tracking_max_llamadas() == 80


@pytest.mark.asyncio
async def test_faltan_caminos_por_fallas_se_reportan_como_errores(monkeypatch):
    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        if pelo_n_id == 2:
            raise TrackingNoDisponible("sin camino", "SIN_CAMINO")
        return _generado(pelo_n_id, {1, 3})

    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)

    resultado = await trackings_por_camino(
        object(), object(), servicio_id=1, pelos_n_id=[1, 2, 3]
    )

    assert [t.pelo_n_id for t in resultado.trackings] == [1]
    assert resultado.no_cubiertos == [2]
    assert resultado.errores == ["Pelo 2: sin camino"]
    # Una semilla que falla no es un tope: el recorrido terminó.
    assert resultado.completo is True


@pytest.mark.asyncio
async def test_max_fallidos_corta_antes_de_pedir_cientos_de_pelos(monkeypatch):
    pedidos: list[int] = []

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        pedidos.append(pelo_n_id)
        raise TrackingNoDisponible("sin camino", "SIN_CAMINO")

    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)

    resultado = await trackings_por_camino(
        object(), object(), servicio_id=1, pelos_n_id=list(range(1, 200)), max_fallidos=3,
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


def _con_resumen(tracking: TrackingGenerado, resumen) -> TrackingGenerado:
    tracking.extremos = resumen
    return tracking


@pytest.fixture
def declaraciones(monkeypatch):
    """Sin nada declarado por defecto: la sesión de estos tests es un `object()`, sin DB."""
    from core.services.cromo.servicio_odf_confirmacion import Declaraciones

    estado = {"valor": Declaraciones()}

    async def _leer(_sesion, _servicio_id):
        return estado["valor"]

    monkeypatch.setattr(tracking_service, "declaraciones_del_servicio", _leer)
    return estado


@pytest.mark.asyncio
async def test_trackings_del_servicio_lee_confirmadas_y_esperados_de_la_db(monkeypatch, declaraciones):
    """Un camino sin extremo en ODF que toca una ODF confirmada (por version_id) pasa a TRAMO, y
    los esperados declarados y la lista de confirmadas viajan en el resultado."""
    from core.services.cromo.servicio_odf_confirmacion import Declaraciones
    from core.services.cromo.tracking_service import ExtremoCamino, ResumenCamino

    pelo = ExtremoCamino(tipo="PELO", id_cromo=1, clase=130)
    resumenes = {
        10: ResumenCamino(servicio_at62="1", inicio=pelo, fin=pelo, odfs=(9295436,), cables=(1,)),
        20: ResumenCamino(servicio_at62="1", inicio=pelo, fin=pelo, odfs=(), cables=(2,)),
    }
    # El 10 tiene 1 pelo y el 20 tiene 10: sin confirmación el 10 quedaría fuera por proporción.
    pelos = {10: {10}, 20: set(range(100, 110))}
    declaraciones["valor"] = Declaraciones(
        odf_ids=frozenset({6646686, 9295436}),
        confirmadas=[{"odf_n_id": 6646686, "rol": "TRANSITO"}],
        trackings_esperados=3,
    )

    async def _semillas(_sesion, _servicio_id):
        return [_semilla(p) for p in (10, 20)]

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        return _con_resumen(_generado(pelo_n_id, pelos[pelo_n_id]), resumenes[pelo_n_id])

    monkeypatch.setattr(tracking_service, "semillas_para_tracking", _semillas)
    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 567)

    assert sorted(t.pelo_n_id for t in resultado.tramos) == [10, 20]
    assert resultado.esperados_declarados == 3
    assert resultado.odf_confirmadas == [{"odf_n_id": 6646686, "rol": "TRANSITO"}]

    # El parámetro explícito pisa a las de la DB: sin confirmadas el 10 es residual.
    sin = await tracking_service.trackings_del_servicio(
        object(), object(), 567, odfs_confirmadas=frozenset()
    )
    assert [t.pelo_n_id for t in sin.tramos] == [20]
    assert sin.esperados_declarados == 3


@pytest.mark.asyncio
async def test_trackings_del_servicio_sin_semillas_conserva_lo_declarado(monkeypatch, declaraciones):
    from core.services.cromo.servicio_odf_confirmacion import Declaraciones

    declaraciones["valor"] = Declaraciones(trackings_esperados=2)

    async def _semillas(_sesion, _servicio_id):
        return []

    monkeypatch.setattr(tracking_service, "semillas_para_tracking", _semillas)

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 1)

    assert resultado.esperados_declarados == 2


@pytest.mark.asyncio
async def test_trackings_del_servicio_separa_tramos_y_residuales_y_los_nombra(monkeypatch, declaraciones):
    """Dos caminos que terminan en conector de ODF son TRAMO; uno chico que no toca ODF es
    RESIDUAL. Los tramos se numeran por cantidad de pelos descendente y llevan el nombre
    `{at62} CROMO T{n} pelo {n_id}.txt`."""
    from core.services.cromo.tracking_service import ExtremoCamino, ResumenCamino

    def _odf(odf_id):
        return ExtremoCamino(tipo="CONECTOR_ODF", id_cromo=odf_id + 1, clase=136, odf_id=odf_id,
                             odf_clase=69, patchera_nombre="O-1", conector_numero="1")

    pelo = ExtremoCamino(tipo="PELO", id_cromo=1, clase=130)
    resumenes = {
        10: ResumenCamino(servicio_at62="42351", inicio=_odf(500), fin=_odf(600),
                          odfs=(500, 600), cables=(1, 2)),
        20: ResumenCamino(servicio_at62="42351", inicio=_odf(500), fin=_odf(600),
                          odfs=(500, 600), cables=(1, 2)),
        30: ResumenCamino(servicio_at62="42351", inicio=pelo, fin=pelo, odfs=(), cables=(7,)),
    }
    pelos = {10: {10, 11}, 20: {20, 21, 22}, 30: {30}}

    async def _semillas(_sesion, _servicio_id):
        return [_semilla(p) for p in (10, 20, 30)]

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        return _con_resumen(_generado(pelo_n_id, pelos[pelo_n_id]), resumenes[pelo_n_id])

    monkeypatch.setattr(tracking_service, "semillas_para_tracking", _semillas)
    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 567)

    assert [t.pelo_n_id for t in resultado.tramos] == [20, 10]
    assert [t.nombre_archivo for t in resultado.tramos] == [
        "42351 CROMO T1 pelo 20.txt",
        "42351 CROMO T2 pelo 10.txt",
    ]
    assert all(t.rol == "TRAMO" for t in resultado.tramos)
    assert [t.pelo_n_id for t in resultado.residuales] == [30]
    assert resultado.residuales[0].rol == "RESIDUAL"
    assert resultado.completo is True
    assert resultado.esperados_declarados is None


@pytest.mark.asyncio
async def test_trackings_del_servicio_sin_semillas_devuelve_vacio(monkeypatch, declaraciones):
    async def _semillas(_sesion, _servicio_id):
        return []

    monkeypatch.setattr(tracking_service, "semillas_para_tracking", _semillas)

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 1)

    assert resultado.tramos == [] and resultado.residuales == []
    assert resultado.completo is True


@pytest.mark.asyncio
async def test_trackings_del_servicio_respeta_el_tope_del_entorno(monkeypatch, declaraciones):
    monkeypatch.setenv("CROMO_TRACKING_MAX_LLAMADAS", "2")
    pedidos: list[int] = []

    async def _semillas(_sesion, _servicio_id):
        return [_semilla(p) for p in (1, 2, 3, 4)]

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        pedidos.append(pelo_n_id)
        return _generado(pelo_n_id, {pelo_n_id})

    monkeypatch.setattr(tracking_service, "semillas_para_tracking", _semillas)
    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 1)

    assert pedidos == [1, 2]
    assert resultado.completo is False


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
