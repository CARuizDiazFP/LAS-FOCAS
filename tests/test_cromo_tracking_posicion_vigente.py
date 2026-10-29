# Nombre de archivo: test_cromo_tracking_posicion_vigente.py
# Ubicación de archivo: tests/test_cromo_tracking_posicion_vigente.py
# Descripción: Tests de tracking por camino de Cromo: posición vigente (semillas de posiciones, roles, retiro y fallback) y caminos de otro Activo

from __future__ import annotations

import pytest

from core.services.cromo import tracking_service
from core.services.cromo.servicio_posicion_vigente import MatchDePelo
from core.services.cromo.tracking_service import TrackingNoDisponible
from tests.soporte_cromo_tracking import (
    _con_resumen,
    _generado,
    _semilla,
)
from tests.soporte_cromo_tracking import (  # noqa: F401 - fixtures (autouse o por argumento)
    _sin_evidencia,
    declaraciones,
)


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
def caso_93150(monkeypatch, declaraciones):  # noqa: F811 - fixture importada
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
async def test_sin_posiciones_ni_declaracion_es_identico_a_hoy(monkeypatch, declaraciones):  # noqa: F811 - fixture importada
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
    # Regla del par: el retiro de :1 arrastra a :2 (misma patchera) con el mismo motivo.
    assert [(a.codigo, a.retirada, a.declaracion_id) for a in avisos] == [
        ("PELO_DANADO", True, 1),
        ("PELO_DANADO", True, 2),
    ]
    # El camino alternativo sano es el nuevo (no el otro hilo declarado).
    assert avisos[0].detalle["camino_alternativo"] == 6799280
    assert avisos[1].detalle == {"arrastrada_por": 8604882, **avisos[0].detalle}
    assert avisos[1].pelo_declarado == 7028863
    assert [(a.codigo, a.declaracion_id) for a in caso_93150["retiros"] if a.retirada] == [
        ("PELO_DANADO", 1),
        ("PELO_DANADO", 2),
    ]
    assert resultado.posicion.aplicada is False
    assert resultado.posicion.declaradas == []
    assert _pelos(resultado.tramos) == [6799280, 6799281]
    assert _pelos(resultado.adicionales) == [7028862, 7028863]


@pytest.mark.asyncio
async def test_pelo_cambio_en_1_arrastra_al_2_y_cae_al_calculo_automatico(caso_93150):
    """Regla del par (93150 = O-1252871-1:1 y :2, siempre 2 trackings): el PELO_CAMBIO de :1 retira
    también a :2 en la MISMA corrida. Ninguno se siembra como declarado, la corrida usa el cálculo
    automático y `posicion.declaradas` queda vacía."""
    caso_93150["declaraciones"]["declaradas"] = [
        _declarada(1, 8604882, "1", 7028862, pelo_actual=1),
        _declarada(2, 8604883, "2", 7028863),
    ]

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 4)

    avisos = resultado.posicion.avisos
    assert [(a.codigo, a.retirada, a.declaracion_id) for a in avisos] == [
        ("PELO_CAMBIO", True, 1),
        ("PELO_CAMBIO", True, 2),
    ]
    assert avisos[1].detalle == {"arrastrada_por": 8604882, "declarado": 7028862, "actual": 1}
    assert [(a.declaracion_id, a.pelo_declarado) for a in caso_93150["retiros"] if a.retirada] == [
        (1, 7028862),
        (2, 7028863),
    ]
    # Ningún pelo declarado se pide como declarado (con el Servicio en el caché).
    assert (7028863, 4) not in caso_93150["pedidos"]
    assert caso_93150["pedidos"][0] == (6799280, 4)
    assert resultado.posicion.aplicada is False
    assert resultado.posicion.declaradas == [] and resultado.posicion.etiqueta == ""
    assert _pelos(resultado.tramos) == [6799280, 6799281]


@pytest.mark.asyncio
async def test_retiro_no_arrastra_declaradas_de_otra_patchera(caso_93150):
    from dataclasses import replace

    otra = replace(
        _declarada(3, 8546314, "1", 6799280), bandeja_n_id=8546313, bandeja_nombre="O-1239922-1"
    )
    caso_93150["declaraciones"]["declaradas"] = [
        _declarada(1, 8604882, "1", 7028862, pelo_actual=1),
        _declarada(2, 8604883, "2", 7028863),
        otra,
    ]

    resultado = await tracking_service.trackings_del_servicio(object(), object(), 4)

    assert [(a.declaracion_id, a.retirada) for a in resultado.posicion.avisos] == [(1, True), (2, True)]
    assert [d.id for d in resultado.posicion.declaradas] == [3]
    assert resultado.posicion.aplicada is False


def _foto(resultado):
    return (
        [t.nombre_archivo for t in resultado.tramos],
        [t.rol for t in resultado.tramos],
        [t.nombre_archivo for t in resultado.adicionales],
        _pelos(resultado.residuales),
        resultado.posicion.aplicada,
        [d.id for d in resultado.posicion.declaradas],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("disparo", ["PELO_CAMBIO", "PELO_DANADO"])
async def test_dos_corridas_seguidas_dan_el_mismo_resultado(caso_93150, disparo):
    """Antes: la corrida 1 retiraba sólo :1 (cálculo automático) y la 2 aplicaba sólo :2 (1
    tracking suelto). Con el par retirado junto, la corrida siguiente da exactamente lo mismo."""
    if disparo == "PELO_CAMBIO":
        declaradas = [_declarada(1, 8604882, "1", 7028862, pelo_actual=1), _declarada(2, 8604883, "2", 7028863)]
    else:
        declaradas = list(_DECLARADAS_93150)
        caso_93150["problemas"][7028862] = ("PELO_DANADO", {"pelo": 7028900, "estado": "Cortado"})
    caso_93150["declaraciones"]["declaradas"] = declaradas

    primera = await tracking_service.trackings_del_servicio(object(), object(), 4)
    caso_93150["declaraciones"]["declaradas"] = list(primera.posicion.declaradas)
    segunda = await tracking_service.trackings_del_servicio(object(), object(), 4)

    assert _foto(primera) == _foto(segunda)
    assert _foto(segunda)[0] == ["93150 CROMO T1 pelo 6799280.txt", "93150 CROMO T2 pelo 6799281.txt"]
    assert segunda.posicion.avisos == []


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
async def test_caminos_resueltos_nunca_descarta_un_tramo_que_termina_en_pelo(monkeypatch, declaraciones):  # noqa: F811 - fixture importada
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
