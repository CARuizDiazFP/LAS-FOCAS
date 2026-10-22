# Nombre de archivo: test_cromo_tracking_por_camino.py
# Ubicación de archivo: tests/test_cromo_tracking_por_camino.py
# Descripción: Pruebas de "un .txt por camino distinto" — pelos del camino, descarte de semillas ya recorridas, recorrido sin corte en esperados con tope de llamadas, caché sin pelos o sin extremos, separación en tramos y residuales y posición vigente (semillas de posiciones, vigentes/adicionales, retiro y fallback)

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.services.cromo import tracking_service
from core.services.cromo.camino_optico_service import ESTADO_OK, CaminoOptico, NodoCamino
from core.services.cromo.servicio_posicion_vigente import MatchDePelo
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


@pytest.fixture(autouse=True)
def _sin_evidencia(monkeypatch):
    """Estos tests usan sesiones fake: la evidencia del árbitro (tiene sus propios tests) se anula."""
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "core.services.cromo.arbitro.evidencia.registrar_y_encolar", AsyncMock(return_value=None)
    )


@pytest.fixture
def declaraciones(monkeypatch):
    """Sin nada declarado por defecto: la sesión de estos tests es un `object()`, sin DB."""
    from core.services.cromo.servicio_odf_confirmacion import Declaraciones

    estado = {"valor": Declaraciones()}

    async def _leer(_sesion, _servicio_id):
        return estado["valor"]

    async def _numero(_sesion, _servicio_id):
        return estado.get("numero")

    async def _posiciones(_sesion, _servicio_id, modo):
        # Único punto de lectura de posiciones (posibles y declaradas): vacío por defecto, así los
        # tests de antes de la posición vigente corren igual con la sesión `object()`.
        estado.setdefault("modos", []).append(modo)
        if modo == "ninguna":
            return [], []
        posibles = list(estado.get("posibles", [])) if modo == "todas" else []
        return posibles, list(estado.get("declaradas", []))

    async def _matches(_sesion, servicio_id, pelos):
        # El match vigente de los pelos de los caminos de posición (`estado["matches"]`, pelo →
        # `MatchDePelo`): ninguno por defecto. Se reemplaza sólo la lectura: la moda es la real.
        estado.setdefault("consultas_otro_activo", []).append((servicio_id, sorted(pelos)))
        matches = estado.get("matches", {})
        return {p: matches[p] for p in pelos if p in matches}

    from core.services.cromo import servicio_posicion_vigente as pv

    monkeypatch.setattr(tracking_service, "declaraciones_del_servicio", _leer)
    monkeypatch.setattr(tracking_service, "numero_del_servicio", _numero)
    monkeypatch.setattr(tracking_service, "posiciones_del_servicio", _posiciones)
    monkeypatch.setattr(pv, "_matches_de_pelos", _matches)
    return estado


@pytest.mark.asyncio
async def test_trackings_del_servicio_lee_confirmadas_y_esperados_de_la_db(monkeypatch, declaraciones):
    """Un camino sin par que TERMINA en una ODF confirmada (referida por version_id) pasa a TRAMO,
    y los esperados declarados y la lista de confirmadas viajan en el resultado."""
    from core.services.cromo.servicio_odf_confirmacion import Declaraciones
    from core.services.cromo.tracking_service import ExtremoCamino, ResumenCamino

    def _odf(odf_id):
        return ExtremoCamino(tipo="CONECTOR_ODF", id_cromo=odf_id + 1, clase=136, odf_id=odf_id,
                             odf_clase=86, patchera_nombre="O-1", conector_numero="1")

    pelo = ExtremoCamino(tipo="PELO", id_cromo=1, clase=130)
    resumenes = {
        # El 10 no tiene par y termina en la ODF confirmada (por su version_id 9295436).
        10: ResumenCamino(servicio_at62="1", inicio=pelo, fin=_odf(9295436), odfs=(9295436,), cables=(1,)),
        # El 20 y el 30 son un par (mismos cables): el servicio es bifilar.
        20: ResumenCamino(servicio_at62="1", inicio=pelo, fin=_odf(7000), odfs=(7000,), cables=(2,)),
        30: ResumenCamino(servicio_at62="1", inicio=pelo, fin=_odf(7000), odfs=(7000,), cables=(2,)),
    }
    pelos = {10: set(range(10, 20)), 20: set(range(100, 110)), 30: set(range(200, 210))}
    declaraciones["valor"] = Declaraciones(
        odf_ids=frozenset({6646686, 9295436}),
        confirmadas=[{"odf_n_id": 6646686, "rol": "TRANSITO"}],
        trackings_esperados=3,
    )

    async def _semillas(_sesion, _servicio_id):
        return [_semilla(p) for p in (10, 20, 30)]

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        return _con_resumen(_generado(pelo_n_id, pelos[pelo_n_id]), resumenes[pelo_n_id])

    monkeypatch.setattr(tracking_service, "semillas_para_tracking", _semillas)
    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 567)

    assert sorted(t.pelo_n_id for t in resultado.tramos) == [10, 20, 30]
    assert resultado.esperados_declarados == 3
    assert resultado.odf_confirmadas == [{"odf_n_id": 6646686, "rol": "TRANSITO"}]

    # El parámetro explícito pisa a las de la DB: sin confirmadas el 10 (sin par) es residual.
    sin = await tracking_service.trackings_del_servicio(
        object(), object(), 567, odfs_confirmadas=frozenset()
    )
    assert sorted(t.pelo_n_id for t in sin.tramos) == [20, 30]
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


# ── Auditoría de huérfanos enganchada en trackings_del_servicio ───────────────────────────────


@pytest.mark.asyncio
async def test_trackings_del_servicio_audita_residuales_con_el_mismo_resultado(monkeypatch, declaraciones):
    """Un solo punto de enganche: recibe tramos, residuales, semillas, confirmadas y la corrida."""
    from core.services.cromo import auditoria_huerfanos
    from core.services.cromo.servicio_odf_confirmacion import Declaraciones
    from core.services.cromo.tracking_service import ExtremoCamino, ResumenCamino

    odf = ExtremoCamino(tipo="CONECTOR_ODF", id_cromo=501, clase=136, odf_id=500, odf_clase=69)
    pelo = ExtremoCamino(tipo="PELO", id_cromo=1, clase=130)
    resumenes = {
        10: ResumenCamino(servicio_at62="1", inicio=odf, fin=odf, odfs=(500,), cables=(1,)),
        30: ResumenCamino(servicio_at62="1", inicio=pelo, fin=pelo, cables=(7,)),
    }
    pelos = {10: set(range(10, 20)), 30: {30}}
    declaraciones["valor"] = Declaraciones(odf_ids=frozenset({777}))
    llamadas: list[dict] = []

    async def _semillas(_sesion, _servicio_id):
        return [_semilla(p) for p in (10, 30)]

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        return _con_resumen(_generado(pelo_n_id, pelos[pelo_n_id]), resumenes[pelo_n_id])

    async def _auditar(sesion, servicio_id, **kw):
        llamadas.append({"servicio_id": servicio_id, **kw})
        return auditoria_huerfanos.ResumenAuditoria(nuevos=1)

    monkeypatch.setattr(tracking_service, "semillas_para_tracking", _semillas)
    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)
    monkeypatch.setattr(auditoria_huerfanos, "auditar_sin_romper", _auditar)

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 567, corrida_id=9)

    assert len(llamadas) == 1
    llamada = llamadas[0]
    assert llamada["servicio_id"] == 567 and llamada["corrida_id"] == 9
    assert [t.pelo_n_id for t in llamada["tramos"]] == [10]
    assert [t.pelo_n_id for t in llamada["residuales"]] == [30]
    assert llamada["semillas"] == frozenset({10, 30})
    assert llamada["odfs_confirmadas"] == frozenset({777})
    assert resultado.auditoria.nuevos == 1

    llamadas.clear()
    await tracking_service.trackings_del_servicio(object(), object(), 567, auditar=False)
    assert llamadas == []


class _SesionQueFalla:
    """Sesión mínima: el savepoint abre, la query revienta, el rollback se registra."""

    def __init__(self) -> None:
        self.rollbacks = 0
        self.commits = 0

    def begin_nested(self):
        sesion = self

        class _Ctx:
            async def __aenter__(self):
                return sesion

            async def __aexit__(self, *exc):
                return False

        return _Ctx()

    async def execute(self, *_a, **_k):
        raise RuntimeError("relation app.cromo_auditoria_huerfanos does not exist")

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


@pytest.mark.asyncio
async def test_auditar_sin_romper_nunca_levanta():
    """La auditoría es accesoria: si falla (tabla sin migrar, DB caída), Slack y el portal siguen."""
    from core.services.cromo.auditoria_huerfanos import auditar_sin_romper
    from core.services.cromo.tracking_service import ResumenCamino

    residual = _con_resumen(_generado(30, {30}), ResumenCamino(cables=(7,)))
    sesion = _SesionQueFalla()

    resultado = await auditar_sin_romper(
        sesion, 1, tramos=[], residuales=[residual], semillas=frozenset({30})
    )

    assert resultado is None
    assert sesion.rollbacks == 1 and sesion.commits == 0


def test_resumen_camino_conserva_botellas_y_tolera_cache_sin_ellas():
    from core.services.cromo.tracking_service import ExtremoCamino, ResumenCamino

    resumen = ResumenCamino(
        inicio=ExtremoCamino(tipo="PELO", id_cromo=1, clase=130),
        cables=(5,),
        botellas=(10, 20, 30),
        botella_inicio=10,
        botella_fin=30,
    )
    assert ResumenCamino.desde_json(resumen.a_json()) == resumen

    viejo = resumen.a_json()
    for clave in ("botellas", "botella_inicio", "botella_fin"):
        viejo.pop(clave)
    leido = ResumenCamino.desde_json(viejo)
    assert leido.botellas == () and leido.botella_inicio is None and leido.cables == (5,)


def test_resumen_del_camino_toma_botellas_extremas_en_orden_del_txt():
    """Orden del `.txt`: reversed(lado_b) → raíz → lado_a. La primera y la última fusión son los
    empalmes extremos."""
    from core.services.cromo.camino_optico_service import CaminoOptico, NodoCamino
    from core.services.cromo.tracking_service import resumen_del_camino

    def _fusion(orden, lado, botella):
        return NodoCamino(orden=orden, lado=lado, id_cromo=1000 + botella, clase=131, tipo="FUSION",
                          botella_id=botella)

    camino = CaminoOptico(
        estado="OK",
        pelo_n_id=1,
        raiz=NodoCamino(orden=0, lado="raiz", id_cromo=1, clase=130, tipo="PELO", cable_id=5),
        lado_a=[_fusion(1, "a", 30), _fusion(2, "a", 40)],
        lado_b=[_fusion(1, "b", 20), _fusion(2, "b", 10)],
    )
    resumen = resumen_del_camino(camino)
    assert (resumen.botella_inicio, resumen.botella_fin) == (10, 40)
    assert resumen.botellas == (10, 20, 30, 40)


@pytest.mark.asyncio
async def test_trackings_del_servicio_incompleto_no_audita(monkeypatch, declaraciones):
    """Con el tope de llamadas tocado quedan semillas sin cubrir: pelos de tramos no resueltos
    podrían quedar como huérfanos normalizables. No se escribe ni se borra nada."""
    from core.services.cromo import auditoria_huerfanos
    from core.services.cromo.tracking_service import ExtremoCamino, ResumenCamino

    pelo = ExtremoCamino(tipo="PELO", id_cromo=1, clase=130)
    llamadas: list = []

    async def _semillas(_sesion, _servicio_id):
        return [_semilla(p) for p in (10, 20, 30)]

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        return _con_resumen(
            _generado(pelo_n_id, {pelo_n_id}),
            ResumenCamino(servicio_at62="1", inicio=pelo, fin=pelo, cables=(pelo_n_id,)),
        )

    async def _auditar(*a, **k):
        llamadas.append(k)

    monkeypatch.setenv("CROMO_TRACKING_MAX_LLAMADAS", "1")
    monkeypatch.setattr(tracking_service, "semillas_para_tracking", _semillas)
    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)
    monkeypatch.setattr(auditoria_huerfanos, "auditar_sin_romper", _auditar)

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 1)

    assert resultado.completo is False
    assert llamadas == [] and resultado.auditoria is None


@pytest.mark.asyncio
async def test_trackings_del_servicio_con_semilla_fallida_no_audita(monkeypatch, declaraciones):
    """Una semilla que falla por debajo del tope de fallidas deja `completo=True` pero su pelo no
    tiene camino: si era de un tramo, auditar lo dejaría como huérfano normalizable."""
    from core.services.cromo import auditoria_huerfanos
    from core.services.cromo.tracking_service import ExtremoCamino, ResumenCamino

    pelo = ExtremoCamino(tipo="PELO", id_cromo=1, clase=130)
    llamadas: list = []

    async def _semillas(_sesion, _servicio_id):
        return [_semilla(p) for p in (10, 20)]

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        if pelo_n_id == 20:
            raise TrackingNoDisponible("sin camino", "SIN_CAMINO")
        return _con_resumen(
            _generado(pelo_n_id, {pelo_n_id}),
            ResumenCamino(servicio_at62="1", inicio=pelo, fin=pelo, cables=(1,)),
        )

    async def _auditar(*a, **k):
        llamadas.append(k)

    monkeypatch.setattr(tracking_service, "semillas_para_tracking", _semillas)
    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)
    monkeypatch.setattr(auditoria_huerfanos, "auditar_sin_romper", _auditar)

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 1)

    assert resultado.completo is True and resultado.errores
    assert llamadas == [] and resultado.auditoria is None
    assert resultado.auditoria_omitida == "INCOMPLETO"


# ── I3: fallas parciales y tope de llamadas, por separado ─────────────────────────────────────


@pytest.mark.asyncio
async def test_tope_de_llamadas_se_distingue_del_tope_de_fallidas(monkeypatch):
    async def _ok(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        return _generado(pelo_n_id, {pelo_n_id})

    monkeypatch.setattr(tracking_service, "obtener_tracking", _ok)
    por_tope = await trackings_por_camino(
        object(), object(), servicio_id=1, pelos_n_id=[1, 2, 3], max_llamadas=1
    )
    assert por_tope.completo is False and por_tope.tope_llamadas is True

    async def _falla(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        raise TrackingNoDisponible("sin camino", "SIN_CAMINO")

    monkeypatch.setattr(tracking_service, "obtener_tracking", _falla)
    por_fallidas = await trackings_por_camino(
        object(), object(), servicio_id=1, pelos_n_id=[1, 2, 3], max_fallidos=1
    )
    assert por_fallidas.completo is False and por_fallidas.tope_llamadas is False


@pytest.mark.asyncio
async def test_trackings_del_servicio_expone_no_cubiertos_y_tope(monkeypatch, declaraciones):
    async def _semillas(_sesion, _servicio_id):
        return [_semilla(p) for p in (10, 20)]

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        if pelo_n_id == 20:
            raise TrackingNoDisponible("sin camino", "SIN_CAMINO")
        return _generado(pelo_n_id, {pelo_n_id})

    monkeypatch.setattr(tracking_service, "semillas_para_tracking", _semillas)
    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 1, auditar=False)

    assert resultado.completo is True
    assert resultado.no_cubiertos == [20]
    assert resultado.tope_llamadas is False


@pytest.mark.asyncio
async def test_trackings_del_servicio_cuenta_segmentos_por_pares_de_cables(monkeypatch, declaraciones):
    """I4: dos hilos del mismo camino (mismos cables) son UN segmento; dos pares sobre cables
    distintos son dos."""
    from core.services.cromo.tracking_service import ExtremoCamino, ResumenCamino

    def _odf(odf_id):
        return ExtremoCamino(tipo="CONECTOR_ODF", id_cromo=odf_id + 1, clase=136, odf_id=odf_id,
                             odf_clase=69)

    cables = {10: (1, 2, 3), 11: (1, 2, 3), 20: (7, 8, 9), 21: (7, 8, 9)}

    async def _semillas(_sesion, _servicio_id):
        return [_semilla(p) for p in cables]

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        return _con_resumen(
            _generado(pelo_n_id, {pelo_n_id, pelo_n_id + 100}),
            ResumenCamino(servicio_at62="1", inicio=_odf(5), fin=_odf(6), odfs=(5, 6),
                          cables=cables[pelo_n_id]),
        )

    monkeypatch.setattr(tracking_service, "semillas_para_tracking", _semillas)
    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 1, auditar=False)

    assert len(resultado.tramos) == 4
    assert resultado.segmentos == 2


@pytest.mark.asyncio
async def test_los_tramos_se_nombran_con_el_numero_del_servicio_y_no_con_el_at62(monkeypatch, declaraciones):
    """Medido en dev (2026-10-17): el at.62 de los pelos no es confiable como nombre: el 42351 salía
    "42352 CROMO", un hilo del 93154 "83254 CROMO" y 4 tramos del 102452 sin número. El parser de
    trackings legacy toma el servicio del NOMBRE del archivo, así que tiene que ser el de LAS-FOCAS."""
    from core.services.cromo.tracking_service import ExtremoCamino, ResumenCamino

    def _odf(odf_id):
        return ExtremoCamino(tipo="CONECTOR_ODF", id_cromo=odf_id + 1, clase=136, odf_id=odf_id,
                             odf_clase=69, patchera_nombre="O-1", conector_numero="1")

    resumenes = {
        10: ResumenCamino(servicio_at62="42352", inicio=_odf(500), fin=_odf(600),
                          odfs=(500, 600), cables=(1, 2)),
        20: ResumenCamino(servicio_at62="0", inicio=_odf(500), fin=_odf(600),
                          odfs=(500, 600), cables=(1, 2)),
    }
    pelos = {10: {10, 11}, 20: {20, 21, 22}}
    declaraciones["numero"] = "42351"

    async def _semillas(_sesion, _servicio_id):
        return [_semilla(p) for p in (10, 20)]

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        return _con_resumen(_generado(pelo_n_id, pelos[pelo_n_id]), resumenes[pelo_n_id])

    monkeypatch.setattr(tracking_service, "semillas_para_tracking", _semillas)
    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 567)

    assert [t.nombre_archivo for t in resultado.tramos] == [
        "42351 CROMO T1 pelo 20.txt",
        "42351 CROMO T2 pelo 10.txt",
    ]


def test_extremo_de_nodo_copia_at62_y_pelo_conectado():
    """El conector de ODF trae el at.62 del servicio y el pelo que conecta: el extremo los guarda."""
    from core.services.cromo.tracking_service import _extremo_de_nodo

    conector = NodoCamino(
        orden=1,
        lado="A",
        id_cromo=500,
        clase=136,
        tipo="CONECTOR_ODF",
        servicio_at62="106180",
        pelo_conectado=77,
    )
    extremo = _extremo_de_nodo(conector)
    assert extremo.servicio_at62 == "106180"
    assert extremo.pelo_conectado == 77


def test_desde_json_cache_viejo_sin_campos_nuevos():
    """Un extremo cacheado antes de estos campos se reconstruye con None, sin error."""
    from core.services.cromo.tracking_service import ResumenCamino

    viejo = {"inicio": {"tipo": "CONECTOR_ODF", "id_cromo": 500, "clase": 136}, "fin": None}
    leido = ResumenCamino.desde_json(viejo)
    assert leido is not None
    assert leido.inicio.servicio_at62 is None
    assert leido.inicio.pelo_conectado is None


def test_round_trip_json_con_campos_nuevos():
    """`pelo_conectado` sobrevive a `a_json` → `desde_json` como `int`, no como texto."""
    from core.services.cromo.tracking_service import ExtremoCamino, ResumenCamino

    resumen = ResumenCamino(
        inicio=ExtremoCamino(
            tipo="CONECTOR_ODF",
            id_cromo=500,
            clase=136,
            servicio_at62="106180",
            pelo_conectado=77,
        ),
    )
    leido = ResumenCamino.desde_json(resumen.a_json())
    assert leido == resumen
    assert isinstance(leido.inicio.pelo_conectado, int)
    assert leido.inicio.servicio_at62 == "106180"


# ── Posición vigente: semillas de posiciones, roles, retiro y fallback ────────────────────────
#
# Caso 93150 (`servicios.id=4`), medido en dev el 2026-10-21: los caminos son los de
# `test_cromo_tracking_clasificacion._caminos_93150` (viejo 7028862/63 de 49 pelos entre
# O-1252871-1 y O-1252734-1; nuevo 6799280/81 de 40 pelos; 7469850 de un PELO a Ramos Mejía). Las
# posiciones posibles son las de O-1252871-1:1/2 (pelos con etiqueta 44649) y O-1239922-1:1/2.


def _posible(conector, odf, patchera, numero, pelo, etiqueta, *, ajena=True):
    from core.services.cromo.servicio_posicion_vigente import PosicionPosible

    return PosicionPosible(
        conector_n_id=conector, odf_n_id=odf, odf_nombre=None, odf_clase=69, bandeja_n_id=odf + 1,
        bandeja_nombre=patchera, numero_conector=numero, pelo_n_id=pelo, numero_pelo=None,
        cable_n_id=None, cable_nombre=None, etiqueta_pelo=etiqueta, etiqueta_ajena=ajena,
        estado_pelo=None, servicio_resuelto="93150", servicio_id_historico=None,
        patch_conector_n_id=None, por_resuelto=True, por_pelo=not ajena,
        pelos_candidatos=(pelo,) if pelo else (),
    )


def _declarada(id_, conector, numero, pelo, *, pelo_actual="igual", existe=True):
    from core.services.cromo.servicio_posicion_vigente import PosicionDeclarada

    return PosicionDeclarada(
        id=id_, conector_n_id=conector, odf_n_id=6644560, odf_nombre="ODF San Martin 137 P5 D",
        bandeja_n_id=8604881, bandeja_nombre="O-1252871-1", numero_conector=numero,
        pelo_declarado=pelo, pelos_candidatos=(pelo,),
        pelo_actual=pelo if pelo_actual == "igual" else pelo_actual, conector_existe=existe,
        declarado_por="admin", declarado_en=None,
    )


_POSIBLES_93150 = [
    _posible(8546314, 6642346, "O-1239922-1", "1", 6799280, "93150", ajena=False),
    _posible(8546315, 6642346, "O-1239922-1", "2", 6799281, "93150", ajena=False),
    _posible(8604882, 6644560, "O-1252871-1", "1", 7028862, "44649"),
    _posible(8604883, 6644560, "O-1252871-1", "2", 7028863, "44649"),
]
_DECLARADAS_93150 = [_declarada(1, 8604882, "1", 7028862), _declarada(2, 8604883, "2", 7028863)]


@pytest.fixture
def caso_93150(monkeypatch, declaraciones):
    """Semillas etiquetadas 6799280/81 y 7469850; `obtener_tracking` resuelve cualquier pelo de un
    camino medido. `pedidos` son `(pelo, servicio_id del caché)` en orden; `retiros`, los avisos que
    llegaron a `aplicar_retiros`; `problemas`, el problema de estado/tendido por pelo semilla."""
    from dataclasses import replace

    from core.services.cromo import servicio_posicion_vigente as pv
    from tests.test_cromo_tracking_clasificacion import _caminos_93150

    caminos = _caminos_93150()
    estado = {"pedidos": [], "retiros": [], "problemas": {}, "fallan": set(), "auditorias": []}
    declaraciones["numero"] = "93150"
    declaraciones["posibles"] = list(_POSIBLES_93150)

    async def _semillas(_sesion, _servicio_id):
        return [_semilla(p) for p in (6799280, 6799281, 7469850)]

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        estado["pedidos"].append((pelo_n_id, servicio_id))
        if pelo_n_id in estado["fallan"]:
            raise TrackingNoDisponible("sin camino", "SIN_CAMINO")
        camino = next(c for c in caminos if pelo_n_id in c.pelos_camino)
        return replace(camino, pelo_n_id=pelo_n_id, desde_cache=False)

    async def _problema(_sesion, tracking):
        return estado["problemas"].get(tracking.pelo_n_id)

    async def _retiros(_sesion, avisos, *, usuario="auto"):
        estado["retiros"].extend(avisos)
        return sum(1 for a in avisos if a.retirada)

    async def _auditar(_sesion, servicio_id, **kw):
        estado["auditorias"].append(kw)
        return None

    from core.services.cromo import auditoria_huerfanos

    monkeypatch.setattr(tracking_service, "semillas_para_tracking", _semillas)
    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)
    monkeypatch.setattr(pv, "_problema_del_camino", _problema)
    monkeypatch.setattr(tracking_service, "aplicar_retiros", _retiros)
    monkeypatch.setattr(auditoria_huerfanos, "auditar_sin_romper", _auditar)
    estado["declaraciones"] = declaraciones
    return estado


def _pelos(trackings):
    return [t.pelo_n_id for t in trackings]


@pytest.mark.asyncio
async def test_sin_posiciones_ni_declaracion_es_identico_a_hoy(monkeypatch, declaraciones):
    """Sin posiciones posibles ni declaradas: mismos tramos, residuales y nombres que antes, ningún
    adicional, y los caminos resueltos son los tramos. Se piden posiciones en modo "todas"."""
    from core.services.cromo.tracking_service import ExtremoCamino, ResumenCamino

    def _odf(odf_id):
        return ExtremoCamino(tipo="CONECTOR_ODF", id_cromo=odf_id + 1, clase=136, odf_id=odf_id,
                             odf_clase=69, patchera_nombre="O-1", conector_numero="1")

    pelo = ExtremoCamino(tipo="PELO", id_cromo=1, clase=130)
    resumenes = {
        10: ResumenCamino(servicio_at62="42351", inicio=_odf(500), fin=_odf(600), cables=(1, 2)),
        20: ResumenCamino(servicio_at62="42351", inicio=_odf(500), fin=_odf(600), cables=(1, 2)),
        30: ResumenCamino(servicio_at62="42351", inicio=pelo, fin=pelo, cables=(7,)),
    }
    pelos = {10: {10, 11}, 20: {20, 21, 22}, 30: {30}}
    pedidos: list = []

    async def _semillas(_sesion, _servicio_id):
        return [_semilla(p) for p in (10, 20, 30)]

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        pedidos.append((pelo_n_id, servicio_id))
        return _con_resumen(_generado(pelo_n_id, pelos[pelo_n_id]), resumenes[pelo_n_id])

    monkeypatch.setattr(tracking_service, "semillas_para_tracking", _semillas)
    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 567, auditar=False)

    assert declaraciones["modos"] == ["todas"]
    assert pedidos == [(10, 567), (20, 567), (30, 567)]
    assert [t.nombre_archivo for t in resultado.tramos] == [
        "42351 CROMO T1 pelo 20.txt",
        "42351 CROMO T2 pelo 10.txt",
    ]
    assert _pelos(resultado.residuales) == [30]
    assert resultado.adicionales == [] and resultado.info_adicionales == []
    assert resultado.caminos_resueltos == resultado.tramos
    assert resultado.posicion.aplicada is False and resultado.posicion.avisos == []
    assert resultado.errores_posiciones == [] and resultado.no_cubiertos_posiciones == []


@pytest.mark.asyncio
async def test_semillas_en_orden_declaradas_etiquetadas_y_posiciones(caso_93150):
    """Primero los pelos declarados, después las semillas etiquetadas y al final las posiciones.
    Una posición cuyo pelo ya recorrió un camino anterior no se pide. Las posiciones no declaradas
    se cachean sin servicio (`servicio_id=None`): la traza del servicio lee esa columna."""
    caso_93150["declaraciones"]["declaradas"] = [_declarada(1, 8604882, "1", 7028862)]

    await tracking_service.trackings_del_servicio(object(), object(), 4)

    assert caso_93150["pedidos"] == [
        (7028862, 4),  # declarada
        (6799280, 4), (6799281, 4), (7469850, 4),  # etiquetadas
        (7028863, None),  # posición no declarada (O-1252871-1:2)
    ]


@pytest.mark.asyncio
async def test_93150_sin_declaracion_da_2_tramos_y_2_adicionales_completos(caso_93150):
    resultado = await tracking_service.trackings_del_servicio(object(), object(), 4)

    assert _pelos(resultado.tramos) == [6799280, 6799281]
    assert [t.nombre_archivo for t in resultado.tramos] == [
        "93150 CROMO T1 pelo 6799280.txt",
        "93150 CROMO T2 pelo 6799281.txt",
    ]
    assert _pelos(resultado.adicionales) == [7028862, 7028863]
    assert [t.nombre_archivo for t in resultado.adicionales] == [
        "93150 CROMO A1 pelo 7028862.txt",
        "93150 CROMO A2 pelo 7028863.txt",
    ]
    assert all(t.rol == "ADICIONAL" for t in resultado.adicionales)
    assert _pelos(resultado.residuales) == [7469850]
    assert _pelos(resultado.caminos_resueltos) == [6799280, 6799281, 7028862, 7028863]
    # El aviso de Slack: por qué posición y con qué etiqueta. O-1252734-1 (el otro extremo del
    # camino viejo) no es posición posible en este fake, así que sólo aparece O-1252871-1.
    info = resultado.info_adicionales
    assert [i.pelo_n_id for i in info] == [7028862, 7028863]
    assert info[0].origen == "POSICION"
    assert info[0].posiciones == (("O-1252871-1", "1"),)
    assert info[1].posiciones == (("O-1252871-1", "2"),)
    assert info[0].etiquetas == ("44649",)
    assert resultado.posicion.aplicada is False and resultado.posicion.declaradas == []
    assert resultado.completo is True and resultado.errores == []


@pytest.mark.asyncio
async def test_93150_con_declaracion_vigentes_son_el_viejo_y_el_nuevo_es_adicional(caso_93150):
    caso_93150["declaraciones"]["declaradas"] = list(_DECLARADAS_93150)

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 4)

    assert [t.nombre_archivo for t in resultado.tramos] == [
        "93150 CROMO T1 pelo 7028862.txt",
        "93150 CROMO T2 pelo 7028863.txt",
    ]
    assert all(t.rol == "VIGENTE" for t in resultado.tramos)
    assert [t.nombre_archivo for t in resultado.adicionales] == [
        "93150 CROMO A1 pelo 6799280.txt",
        "93150 CROMO A2 pelo 6799281.txt",
    ]
    assert [i.origen for i in resultado.info_adicionales] == ["ETIQUETADO", "ETIQUETADO"]
    # Sólo O-1239922-1:1 es posición posible en este fake; el otro extremo (O-1239921-1:19) no.
    assert resultado.info_adicionales[0].posiciones == (("O-1239922-1", "1"),)
    assert resultado.info_adicionales[0].etiquetas == ("93150",)
    assert _pelos(resultado.residuales) == [7469850]
    assert resultado.posicion.aplicada is True
    assert resultado.posicion.etiqueta == "O-1252871-1:1,2"
    assert [d.id for d in resultado.posicion.declaradas] == [1, 2]
    assert resultado.posicion.avisos == []
    assert caso_93150["retiros"] == []
    # Los vigentes cuentan como segmento; el nuevo (adicional) no.
    assert resultado.segmentos == 1


@pytest.mark.asyncio
async def test_declarada_sin_pelo_se_retira_y_cae_al_calculo_automatico(caso_93150):
    caso_93150["declaraciones"]["declaradas"] = [
        _declarada(1, 8604882, "1", 7028862, pelo_actual=None),
    ]

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 4)

    # El pelo declarado no se siembra como declarado (sí puede volver como posición posible).
    assert caso_93150["pedidos"][0] == (6799280, 4)
    assert [a.codigo for a in caso_93150["retiros"]] == ["SIN_PELO"]
    assert caso_93150["retiros"][0].retirada is True
    assert resultado.posicion.aplicada is False
    assert resultado.posicion.declaradas == []
    assert [a.codigo for a in resultado.posicion.avisos] == ["SIN_PELO"]
    assert _pelos(resultado.tramos) == [6799280, 6799281]


@pytest.mark.asyncio
async def test_pelo_danado_en_el_declarado_con_otro_camino_sano_retira(caso_93150):
    caso_93150["declaraciones"]["declaradas"] = list(_DECLARADAS_93150)
    caso_93150["problemas"][7028862] = ("PELO_DANADO", {"pelo": 7028900, "estado": "Cortado"})

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 4)

    avisos = resultado.posicion.avisos
    assert [(a.codigo, a.retirada, a.declaracion_id) for a in avisos] == [("PELO_DANADO", True, 1)]
    # El camino alternativo sano es el nuevo (no el otro hilo declarado).
    assert avisos[0].detalle["camino_alternativo"] == 6799280
    assert [a.codigo for a in caso_93150["retiros"] if a.retirada] == ["PELO_DANADO"]
    assert resultado.posicion.aplicada is False
    assert [d.id for d in resultado.posicion.declaradas] == [2]
    assert _pelos(resultado.tramos) == [6799280, 6799281]


@pytest.mark.asyncio
async def test_pelo_danado_sin_otro_camino_sano_solo_avisa_y_se_usa(caso_93150):
    caso_93150["declaraciones"]["declaradas"] = list(_DECLARADAS_93150)
    caso_93150["problemas"][7028862] = ("PELO_DANADO", {"pelo": 7028900, "estado": "Cortado"})
    caso_93150["problemas"][6799280] = ("CABLE_SIN_USO", {"cable": 600, "nombre": "F-SM-37"})
    caso_93150["problemas"][6799281] = ("CABLE_SIN_USO", {"cable": 600, "nombre": "F-SM-37"})

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 4)

    assert [(a.codigo, a.retirada) for a in resultado.posicion.avisos] == [("PELO_DANADO", False)]
    assert not any(a.retirada for a in caso_93150["retiros"])
    # La declaración se mantiene y se usa: no hay un camino mejor.
    assert resultado.posicion.aplicada is True
    assert _pelos(resultado.tramos) == [7028862, 7028863]


@pytest.mark.asyncio
async def test_camino_declarado_incompleto_avisa_no_retira_y_usa_el_automatico(caso_93150):
    caso_93150["declaraciones"]["declaradas"] = [_declarada(9, 8546320, "4", 7469850)]

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 4)

    assert [(a.codigo, a.retirada) for a in resultado.posicion.avisos] == [("CAMINO_INCOMPLETO", False)]
    assert not any(a.retirada for a in caso_93150["retiros"])
    assert resultado.posicion.aplicada is False
    assert [d.id for d in resultado.posicion.declaradas] == [9]
    assert _pelos(resultado.tramos) == [6799280, 6799281]


@pytest.mark.asyncio
async def test_camino_declarado_no_resuelto_avisa_y_no_marca_incompleto(caso_93150):
    caso_93150["declaraciones"]["declaradas"] = list(_DECLARADAS_93150)
    caso_93150["fallan"] = {7028862}

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 4)

    avisos = resultado.posicion.avisos
    assert [(a.codigo, a.retirada) for a in avisos] == [("CAMINO_NO_RESUELTO", False)]
    assert "sin camino" in avisos[0].detalle["motivo"]
    assert resultado.posicion.aplicada is False
    assert resultado.completo is True and resultado.errores == [] and resultado.no_cubiertos == []
    assert resultado.errores_posiciones == ["Pelo 7028862: sin camino"]
    assert resultado.auditoria_omitida is None and len(caso_93150["auditorias"]) == 1
    # El pelo fallido no se vuelve a pedir como posición.
    assert [p for p, _ in caso_93150["pedidos"]].count(7028862) == 1


@pytest.mark.asyncio
async def test_auditoria_recibe_vigentes_y_adicionales_como_tramos_y_solo_semillas_etiquetadas(caso_93150):
    caso_93150["declaraciones"]["declaradas"] = list(_DECLARADAS_93150)

    await tracking_service.trackings_del_servicio(object(), object(), 4)

    (llamada,) = caso_93150["auditorias"]
    assert _pelos(llamada["tramos"]) == [7028862, 7028863, 6799280, 6799281]
    assert _pelos(llamada["residuales"]) == [7469850]
    assert llamada["semillas"] == frozenset({6799280, 6799281, 7469850})


@pytest.mark.asyncio
async def test_evidencia_incluye_vigentes_adicionales_y_residuales(monkeypatch, caso_93150):
    from core.services.cromo.arbitro import evidencia

    registradas: list = []

    async def _registrar(_sesion, _servicio_id, entradas, *, completo, fuente):
        registradas.append(([e.pelo_n_id for e in entradas], completo))

    monkeypatch.setattr(evidencia, "registrar_y_encolar", _registrar)

    await tracking_service.trackings_del_servicio(object(), object(), 4)

    assert registradas == [([6799280, 6799281, 7028862, 7028863, 7469850], True)]


@pytest.mark.asyncio
async def test_sin_semillas_pero_con_posiciones_no_corta(monkeypatch, caso_93150):
    async def _sin_semillas(_sesion, _servicio_id):
        return []

    monkeypatch.setattr(tracking_service, "semillas_para_tracking", _sin_semillas)

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 4)

    # Sólo posiciones: los caminos completos son adicionales (no hay etiquetados que clasificar).
    assert resultado.tramos == []
    assert _pelos(resultado.adicionales) == [7028862, 7028863, 6799280, 6799281]
    assert caso_93150["pedidos"] == [(6799280, None), (6799281, None), (7028862, None), (7028863, None)]


@pytest.mark.asyncio
async def test_sin_semillas_ni_posiciones_corta_sin_pedir_nada(monkeypatch, caso_93150):
    async def _sin_semillas(_sesion, _servicio_id):
        return []

    monkeypatch.setattr(tracking_service, "semillas_para_tracking", _sin_semillas)
    caso_93150["declaraciones"]["posibles"] = []
    caso_93150["declaraciones"]["declaradas"] = [
        _declarada(1, 8604882, "1", 7028862, existe=False),
    ]

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 4)

    assert caso_93150["pedidos"] == []
    assert resultado.tramos == [] and resultado.adicionales == []
    # Aun sin nada que resolver, la declaración que el inventario ya no sostiene se retira.
    assert [a.codigo for a in caso_93150["retiros"]] == ["CONECTOR_INEXISTENTE"]
    assert [a.codigo for a in resultado.posicion.avisos] == ["CONECTOR_INEXISTENTE"]


@pytest.mark.asyncio
async def test_falla_de_semilla_de_posicion_no_omite_la_auditoria(caso_93150):
    caso_93150["fallan"] = {7028862, 7028863}

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 4)

    assert resultado.completo is True
    assert resultado.errores == [] and resultado.no_cubiertos == []
    assert resultado.errores_posiciones == ["Pelo 7028862: sin camino", "Pelo 7028863: sin camino"]
    assert resultado.no_cubiertos_posiciones == [7028862, 7028863]
    assert resultado.auditoria_omitida is None
    assert len(caso_93150["auditorias"]) == 1
    assert resultado.adicionales == []


@pytest.mark.asyncio
async def test_tope_de_llamadas_en_las_posiciones_no_marca_incompleto(monkeypatch, caso_93150):
    """Las posiciones van al final: tocar el tope ahí deja sin pedir sólo posiciones."""
    monkeypatch.setenv("CROMO_TRACKING_MAX_LLAMADAS", "4")

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 4)

    assert [p for p, _ in caso_93150["pedidos"]] == [6799280, 6799281, 7469850, 7028862]
    assert resultado.completo is True and resultado.tope_llamadas is False
    assert resultado.no_cubiertos_posiciones == [7028863]
    assert resultado.auditoria_omitida is None


@pytest.mark.asyncio
async def test_caminos_resueltos_nunca_descarta_un_tramo_que_termina_en_pelo(monkeypatch, declaraciones):
    """Servicio segmentado (forma del 107556): un par de tramos con un extremo en ODF y el otro en
    un PELO. No son caminos completos, pero son tramos: `track N full` los sube igual."""
    from core.services.cromo.tracking_service import ExtremoCamino, ResumenCamino, es_camino_completo

    odf = ExtremoCamino(tipo="CONECTOR_ODF", id_cromo=501, clase=136, odf_id=500, odf_clase=69)
    pelo = ExtremoCamino(tipo="PELO", id_cromo=1, clase=130)

    async def _semillas(_sesion, _servicio_id):
        return [_semilla(p) for p in (10, 20)]

    async def _obtener(_cliente, _sesion, *, servicio_id, pelo_n_id, forzar=False):
        return _con_resumen(
            _generado(pelo_n_id, set(range(pelo_n_id, pelo_n_id + 9))),
            ResumenCamino(servicio_at62="1", inicio=odf, fin=pelo, odfs=(500,), cables=(1, 2)),
        )

    monkeypatch.setattr(tracking_service, "semillas_para_tracking", _semillas)
    monkeypatch.setattr(tracking_service, "obtener_tracking", _obtener)

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 326, auditar=False)

    assert _pelos(resultado.tramos) == [10, 20]
    assert not any(es_camino_completo(t) for t in resultado.tramos)
    assert _pelos(resultado.caminos_resueltos) == [10, 20]


@pytest.mark.asyncio
async def test_posiciones_ninguna_no_lee_ni_siembra_posiciones(caso_93150):
    caso_93150["declaraciones"]["declaradas"] = list(_DECLARADAS_93150)

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 4, posiciones="ninguna")

    assert caso_93150["declaraciones"]["modos"] == ["ninguna"]
    assert [p for p, _ in caso_93150["pedidos"]] == [6799280, 6799281, 7469850]
    assert resultado.adicionales == []


@pytest.mark.asyncio
async def test_posiciones_del_servicio_declaradas_no_usa_posibles(monkeypatch):
    llamadas: list[str] = []

    async def _posibles(_sesion, _servicio_id):
        llamadas.append("posibles")
        return ["no"]

    async def _declaradas(_sesion, _servicio_id):
        llamadas.append("declaradas")
        return ["d"]

    monkeypatch.setattr(tracking_service, "posiciones_posibles", _posibles)
    monkeypatch.setattr(tracking_service, "listar_declaradas", _declaradas)

    assert await tracking_service.posiciones_del_servicio(object(), 4, "declaradas") == ([], ["d"])
    assert llamadas == ["declaradas"]
    assert await tracking_service.posiciones_del_servicio(object(), 4, "ninguna") == ([], [])
    assert llamadas == ["declaradas"]
    assert await tracking_service.posiciones_del_servicio(object(), 4, "todas") == (["no"], ["d"])
    with pytest.raises(ValueError):
        await tracking_service.posiciones_del_servicio(object(), 4, "algunas")


@pytest.mark.asyncio
async def test_corrida_con_posiciones_declaradas_siembra_solo_las_declaradas(caso_93150):
    """Modo de la corrida global: sólo las declaradas se siembran, los posibles no entran."""
    caso_93150["declaraciones"]["declaradas"] = list(_DECLARADAS_93150)

    resultado = await tracking_service.trackings_del_servicio(
        object(), object(), 4, posiciones="declaradas"
    )

    assert caso_93150["declaraciones"]["modos"] == ["declaradas"]
    assert [p for p, _ in caso_93150["pedidos"]] == [7028862, 7028863, 6799280, 6799281, 7469850]
    assert resultado.posicion.aplicada is True


@pytest.mark.asyncio
async def test_retiro_que_falla_no_rompe_el_resultado(monkeypatch, caso_93150):
    caso_93150["declaraciones"]["declaradas"] = [_declarada(1, 8604882, "1", 7028862, pelo_actual=None)]

    class _Sesion:
        rollbacks = 0

        async def rollback(self):
            _Sesion.rollbacks += 1

    async def _revienta(_sesion, _avisos, *, usuario="auto"):
        raise RuntimeError("deadlock detected")

    monkeypatch.setattr(tracking_service, "aplicar_retiros", _revienta)

    resultado = await tracking_service.trackings_del_servicio(object(), _Sesion(), 4)

    assert [a.codigo for a in resultado.posicion.avisos] == ["SIN_PELO"]
    assert _Sesion.rollbacks == 1
    assert _pelos(resultado.tramos) == [6799280, 6799281]


# ── Hallazgos de revisión: camino de otro Activo y semilla declarada fallida ─────────────────


_BAJA_44649 = MatchDePelo("servicio:24547", propio=False, activo=False)
_ACTIVO_61972 = MatchDePelo("servicio:34651", propio=False, activo=True)
_ACTIVO_42351 = MatchDePelo("servicio:567", propio=False, activo=True)


def _matches_reales_93150(caminos):
    """Como en dev (2026-10-22): los 49 pelos de cada hilo viejo llevan la etiqueta 44649 (Baja)
    salvo uno sin match, y el hilo 2 recorre además 4 pelos etiquetados 61972 (BBVA, Activo) mal
    cargados en Cromo (6801908, 7477077, 7487940, 7500336 en la medición real)."""
    hilo_1, hilo_2 = caminos[0], caminos[1]
    matches = {p: _BAJA_44649 for p in sorted(hilo_1.pelos_camino | hilo_2.pelos_camino)}
    sueltos = sorted(hilo_2.pelos_camino - {hilo_2.pelo_n_id})[:5]
    for pelo in sueltos[:4]:
        matches[pelo] = _ACTIVO_61972
    del matches[sueltos[4]]
    return matches


@pytest.mark.asyncio
async def test_93150_hilo_con_etiquetas_sueltas_de_otro_activo_sigue_adicional(caso_93150):
    """Bug real (E2E en dev, 2026-10-22): con el criterio "algún pelo de otro Activo" el hilo 2 del
    camino viejo (4 de 49 pelos con 61972) pasaba a RESIDUAL y `track 93150 full` daba 3 archivos.
    Domina 44649 (Baja): no es ajeno, los dos hilos viejos son ADICIONALES."""
    from tests.test_cromo_tracking_clasificacion import _caminos_93150

    caso_93150["declaraciones"]["matches"] = _matches_reales_93150(_caminos_93150())

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 4)

    assert _pelos(resultado.tramos) == [6799280, 6799281]
    assert _pelos(resultado.adicionales) == [7028862, 7028863]
    assert _pelos(resultado.residuales) == [7469850]


@pytest.mark.asyncio
async def test_camino_de_posicion_mayormente_de_otro_activo_pasa_a_residual(caso_93150):
    """El camino viejo 7028862 (origen POSICION) lleva casi toda la etiqueta de otro servicio
    Activo (como el del 42351 pedido desde el 42352): no puede ofrecerse como ADICIONAL. Se
    consulta UNA sola vez por corrida, sólo con los pelos de los caminos de posición."""
    from tests.test_cromo_tracking_clasificacion import _caminos_93150

    caminos = _caminos_93150()
    matches = _matches_reales_93150(caminos)
    for pelo in sorted(caminos[0].pelos_camino)[:40]:
        matches[pelo] = _ACTIVO_42351
    caso_93150["declaraciones"]["matches"] = matches

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 4)

    assert _pelos(resultado.tramos) == [6799280, 6799281]
    assert _pelos(resultado.adicionales) == [7028863]
    assert sorted(_pelos(resultado.residuales)) == [7028862, 7469850]
    (consulta,) = caso_93150["declaraciones"]["consultas_otro_activo"]
    servicio, pelos = consulta
    assert servicio == 4
    assert set(pelos) == caminos[0].pelos_camino | caminos[1].pelos_camino
    assert 6799280 not in pelos and 7469850 not in pelos


@pytest.mark.asyncio
async def test_camino_declarado_de_otro_activo_sigue_vigente(caso_93150):
    """Lo declarado es decisión explícita del admin: el filtro no lo toca, y sin caminos de
    posición no se consulta."""
    from tests.test_cromo_tracking_clasificacion import _caminos_93150

    caso_93150["declaraciones"]["declaradas"] = list(_DECLARADAS_93150)
    caso_93150["declaraciones"]["matches"] = {
        p: _ACTIVO_42351 for c in _caminos_93150()[:2] for p in c.pelos_camino
    }

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 4)

    assert resultado.posicion.aplicada is True
    assert _pelos(resultado.tramos) == [7028862, 7028863]
    assert caso_93150["declaraciones"].get("consultas_otro_activo", []) == []


@pytest.mark.asyncio
async def test_semilla_etiquetada_declarada_que_falla_cuenta_como_incompleta(caso_93150):
    """7469850 está etiquetada con el Servicio y además declarada. Si su pedido como declarada
    falla, la fase de etiquetadas no puede darla por vista: sigue en `errores`/`no_cubiertos`, la
    corrida no audita y la evidencia sale incompleta. No se vuelve a pedir a Cromo."""
    caso_93150["declaraciones"]["declaradas"] = [_declarada(9, 8546320, "4", 7469850)]
    caso_93150["fallan"] = {7469850}

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 4)

    assert resultado.errores == ["Pelo 7469850: sin camino"]
    assert resultado.no_cubiertos == [7469850]
    assert resultado.auditoria_omitida == "INCOMPLETO"
    assert caso_93150["auditorias"] == []
    assert [p for p, _ in caso_93150["pedidos"]].count(7469850) == 1
    # La falla de la declarada sigue informándose una sola vez entre las de posiciones.
    assert resultado.errores_posiciones == ["Pelo 7469850: sin camino"]
    assert resultado.no_cubiertos_posiciones == [7469850]


@pytest.mark.asyncio
async def test_semilla_declarada_fallida_que_otro_camino_cubre_no_es_incompleta(monkeypatch, caso_93150):
    """Si el pedido como declarada de 6799284 (etiquetada en este caso) falla pero el camino de otra
    semilla etiquetada (7028862, el viejo) lo recorre, quedó cubierta: la corrida es completa."""

    async def _semillas(_sesion, _servicio_id):
        return [_semilla(p) for p in (6799284, 7028862, 6799280, 6799281, 7469850)]

    monkeypatch.setattr(tracking_service, "semillas_para_tracking", _semillas)
    caso_93150["declaraciones"]["declaradas"] = [_declarada(3, 8546318, "5", 6799284)]
    caso_93150["fallan"] = {6799284}

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 4)

    assert resultado.errores == [] and resultado.no_cubiertos == []
    assert resultado.auditoria_omitida is None
    assert [p for p, _ in caso_93150["pedidos"]].count(6799284) == 1
