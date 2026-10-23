# Nombre de archivo: test_cromo_tracking_red_proyectada.py
# Ubicación de archivo: tests/test_cromo_tracking_red_proyectada.py
# Descripción: Pruebas del tracking de un camino que `/path` corta en un pelo con varias continuaciones — detección del corte, reintento con red proyectada/actual, elección por at.62 y domicilio, cabecera y marcas del .txt y aviso en Slack

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from core.services.cromo import tracking_service
from core.services.cromo.camino_optico_service import (
    ESTADO_OK,
    STP_PROYECTADO,
    STP_PROYECTADO_DESINSTALACION,
    TIPO_CONECTOR_ODF,
    TIPO_FUSION,
    TIPO_PELO,
    CaminoOptico,
    CompletadoConRed,
    CorteDeCamino,
    EstadisticasCamino,
    NodoCamino,
    detectar_cortes,
)
from core.services.cromo.camino_optico_txt import renderizar_tracking_txt
from core.services.cromo.client import CromoClientError
from core.services.cromo.tracking_service import (
    ResumenCamino,
    coincide_domicilio,
    completar_camino_cortado,
    extiende_camino,
    resumen_del_camino,
)
from modules.slack_baneo_notifier.tracking_servicio import (
    ESTADO_OK as ESTADO_TRACK_OK,
    ResultadoTrack,
    mensaje_resumen,
)

AHORA = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)

# Ids reales del Servicio 83693 (pelo semilla 6721024), medidos contra Cromo el 2026-10-23.
RAIZ = 6721024
PELO_CORTE = 6712055  # FL-CTB-330:2, con fusiones 8003436 (recorrida), 8015402 y 10086140
FUSION_A_DESINSTALAR = 8015402
FUSION_PROYECTADA = 10086140


def _pelo(id_cromo: int, lado: str = "B", *, cable: str = "FL-CTB-330", numero: str = "2", stp: int = 30) -> NodoCamino:
    return NodoCamino(
        orden=0, lado=lado, id_cromo=id_cromo, clase=130, tipo=TIPO_PELO,
        cable_nombre=cable, numero_pelo=numero, stp=stp,
    )


def _fusion(id_cromo: int, botella: str, lado: str = "B", *, stp: int = 30) -> NodoCamino:
    return NodoCamino(
        orden=0, lado=lado, id_cromo=id_cromo, clase=132, tipo=TIPO_FUSION,
        botella_id=id_cromo + 1, botella_nombre=botella, stp=stp,
    )


def _conector(id_cromo: int, odf_id: int, odf: str, at62: str | None, lado: str = "A") -> NodoCamino:
    return NodoCamino(
        orden=0, lado=lado, id_cromo=id_cromo, clase=136, tipo=TIPO_CONECTOR_ODF,
        odf_id=odf_id, odf_nombre=odf, odf_clase=69, patchera_nombre=f"O-{odf_id}", conector_numero="1",
        servicio_at62=at62,
    )


PILAR = _conector(8500367, 6640813, "ODF Florida 9563 - Pilar - Panam 45.5  PILAR", "47838")
TRAMO_GARDEL = [_fusion(8003436, "Tunel Gardel LB C.F."), _pelo(PELO_CORTE)]


def _camino(lado_b: list[NodoCamino], *, projview: int | None = None, longitud: float = 64908.4,
            cortes: list[CorteDeCamino] | None = None) -> CaminoOptico:
    return CaminoOptico(
        estado=ESTADO_OK,
        pelo_n_id=RAIZ,
        id_raiz=RAIZ,
        servicio_at62="47838",
        raiz=_pelo(RAIZ, "RAIZ", cable="FL-ANT-01", numero="3"),
        lado_a=[PILAR],
        lado_b=lado_b,
        estadisticas=EstadisticasCamino(longitud_optica_m=longitud),
        projview=projview,
        cortes=cortes or [],
    )


CORTE = CorteDeCamino(lado="B", pelo_n_id=PELO_CORTE, cable_nombre="FL-CTB-330", numero_pelo="2",
                      sin_recorrer=(FUSION_A_DESINSTALAR, FUSION_PROYECTADA))
CORTADO = _camino(TRAMO_GARDEL, cortes=[CORTE])
# projview=2: sigue por la fusión proyectada hasta la ODF del cliente (Córdoba 3016, at.62 47838).
PROYECTADO = _camino(
    TRAMO_GARDEL + [
        _fusion(FUSION_PROYECTADA, "Cra. Guardia Vieja 3302 C.F.", stp=STP_PROYECTADO),
        _pelo(6743352, cable="FL-TCM-528BA", numero="23"),
        _conector(8496369, 6640665, "ODF Cordoba 3016 Subsuelo. C.F.", "47838", lado="B"),
    ],
    projview=2, longitud=65756.1,
)
# projview=1: sigue por la fusión a desinstalar hasta una ODF sin servicio.
ACTUAL = _camino(
    TRAMO_GARDEL + [
        _fusion(FUSION_A_DESINSTALAR, "Cra. Guardia Vieja 3302 C.F.", stp=STP_PROYECTADO_DESINSTALACION),
        _pelo(6763735, cable="F-GRD-58", numero="1"),
        _conector(8533161, 6641855, "Guardia Vieja 3458 Piso 1 Of 2", None, lado="B"),
    ],
    projview=1, longitud=65249.7,
)


class _Sesion:
    def __init__(self, domicilios=("CORDOBA AV. 3016", "FLORIDA 9563")):
        self.domicilios = domicilios

    async def execute(self, _sql, _params=None):
        return SimpleNamespace(first=lambda: self.domicilios)


def _resolver_por_projview(caminos: dict, pedidos: list):
    async def _resolver(_cliente, _sesion, pelo_n_id, *, projview=None):
        pedidos.append(projview)
        resultado = caminos[projview]
        if isinstance(resultado, Exception):
            raise resultado
        return resultado
    return _resolver


# ── detectar_cortes ──────────────────────────────────────────────────────────────────────────


def test_detectar_cortes_extremo_en_pelo_con_tp_sin_recorrer():
    """FL-CTB-330:2 trae tres fusiones en `tp[]` y el camino sólo recorre una."""
    dic = {PELO_CORTE: {"tp": [{"id_to": 8003436}, {"id_to": FUSION_A_DESINSTALAR}, {"id_to": FUSION_PROYECTADA}]}}
    raiz = _pelo(RAIZ, "RAIZ")

    cortes = detectar_cortes(dic, raiz, [PILAR], TRAMO_GARDEL)

    assert cortes == [CorteDeCamino("B", PELO_CORTE, "FL-CTB-330", "2", (FUSION_A_DESINSTALAR, FUSION_PROYECTADA))]


def test_detectar_cortes_pelo_que_termina_de_verdad_no_es_corte():
    """Medido 2026-10-23: los 4 servicios que terminan en un pelo sin señal (p. ej. 100561) tienen
    un único `tp`, el que el camino ya recorrió, y el reintento no les agrega nada."""
    dic = {PELO_CORTE: {"tp": [{"id_to": 8003436}]}}

    assert detectar_cortes(dic, _pelo(RAIZ, "RAIZ"), [PILAR], TRAMO_GARDEL) == []


def test_detectar_cortes_extremos_en_odf_o_splitter_no_se_miran():
    dic = {8496369: {"tp": [{"id_to": 999}]}}
    conector = _conector(8496369, 1, "ODF", None, lado="B")

    assert detectar_cortes(dic, _pelo(RAIZ, "RAIZ"), [PILAR], [conector]) == []


def test_detectar_cortes_lado_vacio_mira_la_raiz():
    dic = {RAIZ: {"tp": [{"id_to": 8500367}, {"id_to": 555}]}}

    cortes = detectar_cortes(dic, _pelo(RAIZ, "RAIZ", cable="FL-ANT-01", numero="3"), [PILAR], [])

    assert [(c.lado, c.pelo_n_id, c.sin_recorrer) for c in cortes] == [("B", RAIZ, (555,))]


# ── extiende_camino / coincide_domicilio ─────────────────────────────────────────────────────


def test_extiende_camino_acepta_prefijo_y_rechaza_reemplazo():
    assert extiende_camino(CORTADO, PROYECTADO)
    assert not extiende_camino(PROYECTADO, CORTADO)
    assert not extiende_camino(CORTADO, CORTADO)
    # 105553 (2026-10-23): con projview=2 Cromo siguió OTRA rama, más corta. No extiende.
    otra_rama = _camino([_fusion(1, "otra"), _pelo(2)], projview=2)
    assert not extiende_camino(CORTADO, otra_rama)


def test_extiende_camino_acepta_lados_invertidos():
    """Cromo decide a su criterio cuál lado es `a` y cuál `b`."""
    invertido = _camino([PILAR], projview=2)
    invertido.lado_a = PROYECTADO.lado_b
    assert extiende_camino(CORTADO, invertido)


@pytest.mark.parametrize(
    ("domicilio", "odf", "esperado"),
    [
        ("CORDOBA AV. 3016", "ODF Cordoba 3016 Subsuelo. C.F.", True),
        ("FLORIDA 9563", "ODF Florida 9563 - Pilar - Panam 45.5  PILAR", True),
        ("DEL LIBERTADOR AV. 6220 P.6", "ODF Libertador 6220 Piso 6", True),
        ("RIVADAVIA 733", "ODF Av. Rivadavia 733 CF.", True),
        ("CORDOBA AV. 3016", "Guardia Vieja 3458 Piso 1 Of 2", False),
        ("RIVADAVIA 733", "ODF Rivadavia 7330", False),
        (None, "ODF Cordoba 3016", False),
        ("Estacion Chacarita", "ODF Est Chacarita  Anden PILAR", False),
    ],
)
def test_coincide_domicilio(domicilio, odf, esperado):
    assert coincide_domicilio(domicilio, odf) is esperado


# ── completar_camino_cortado ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sin_corte_no_reintenta(monkeypatch):
    pedidos: list = []
    monkeypatch.setattr(tracking_service, "resolver_camino_de_pelo", _resolver_por_projview({}, pedidos))
    sin_corte = _camino(TRAMO_GARDEL)

    assert await completar_camino_cortado(object(), _Sesion(), sin_corte, servicio_id=620) is sin_corte
    assert pedidos == []


@pytest.mark.asyncio
async def test_83693_se_completa_con_la_red_proyectada_y_avisa_la_alternativa(monkeypatch):
    pedidos: list = []
    monkeypatch.setattr(
        tracking_service, "resolver_camino_de_pelo", _resolver_por_projview({2: PROYECTADO, 1: ACTUAL}, pedidos)
    )

    camino = await completar_camino_cortado(object(), _Sesion(), CORTADO, servicio_id=620)

    assert pedidos == [2, 1]
    assert camino.lado_b == PROYECTADO.lado_b
    assert camino.completado.projview == 2
    assert camino.completado.corte == CORTE
    assert camino.completado.botella == "Cra. Guardia Vieja 3302 C.F."
    assert camino.completado.metros_agregados == pytest.approx(847.7)
    assert "Guardia Vieja 3458" in camino.completado.alternativa
    assert resumen_del_camino(camino).projview == 2


@pytest.mark.asyncio
async def test_gana_la_red_actual_si_la_proyectada_no_extiende(monkeypatch):
    """105553: la red proyectada iba por otra rama y la actual llegaba a la ODF del cliente."""
    otra_rama = _camino([_fusion(1, "otra"), _pelo(2)], projview=2)
    monkeypatch.setattr(
        tracking_service, "resolver_camino_de_pelo", _resolver_por_projview({2: otra_rama, 1: ACTUAL}, [])
    )

    camino = await completar_camino_cortado(object(), _Sesion(), CORTADO, servicio_id=620)

    assert camino.lado_b == ACTUAL.lado_b
    assert camino.completado.projview == 1
    assert camino.completado.alternativa is None


@pytest.mark.asyncio
async def test_el_at62_y_el_domicilio_desempatan_aunque_la_actual_venga_primero(monkeypatch):
    monkeypatch.setattr(tracking_service, "PROJVIEWS_REINTENTO", (1, 2))
    monkeypatch.setattr(
        tracking_service, "resolver_camino_de_pelo", _resolver_por_projview({2: PROYECTADO, 1: ACTUAL}, [])
    )

    camino = await completar_camino_cortado(object(), _Sesion(), CORTADO, servicio_id=620)

    assert camino.lado_b == PROYECTADO.lado_b


@pytest.mark.asyncio
async def test_ningun_reintento_sirve_queda_el_original(monkeypatch):
    monkeypatch.setattr(
        tracking_service,
        "resolver_camino_de_pelo",
        _resolver_por_projview({2: CromoClientError("timeout"), 1: _camino(TRAMO_GARDEL, projview=1)}, []),
    )

    camino = await completar_camino_cortado(object(), _Sesion(), CORTADO, servicio_id=None)

    assert camino is CORTADO
    assert camino.completado is None


# ── .txt, caché y Slack ──────────────────────────────────────────────────────────────────────


def test_txt_declara_el_completado_y_marca_lo_proyectado():
    camino = _camino(PROYECTADO.lado_b, projview=2, longitud=65756.1)
    camino.completado = CompletadoConRed(
        projview=2, corte=CORTE, botella="Cra. Guardia Vieja 3302 C.F.", metros_agregados=847.7,
        alternativa="con la red actual el camino termina en Guardia Vieja 3458 Piso 1 Of 2",
    )

    txt = renderizar_tracking_txt(camino, generado_en=AHORA)

    assert (
        "# ATENCIÓN: el camino por omisión de Cromo se cortaba en FL-CTB-330:2 "
        "(Cra. Guardia Vieja 3302 C.F.), un pelo con más de una continuación." in txt
    )
    assert "# Se completó con la red proyectada de Cromo (projview=2), que agrega 847.7 mts." in txt
    assert "# Alternativa: con la red actual el camino termina en Guardia Vieja 3458 Piso 1 Of 2." in txt
    assert f"Empalme {FUSION_PROYECTADA + 1}: Cra. Guardia Vieja 3302 C.F.  - Proyectado\r\n" in txt
    assert txt.count("Proyectado") == 2  # la línea de marcas de la cabecera + el empalme


def test_txt_sin_completado_no_cambia_la_cabecera_pero_marca_la_desinstalacion():
    """Igual que la UI de Cromo, que marca "Proyectado Desinstalación" también en la vista por omisión."""
    txt = renderizar_tracking_txt(ACTUAL, generado_en=AHORA)

    assert "ATENCIÓN" not in txt
    assert "Cra. Guardia Vieja 3302 C.F.  - Proyectado Desinstalación" in txt


def test_resumen_conserva_el_projview_en_el_cache():
    resumen = ResumenCamino(projview=2)

    assert ResumenCamino.desde_json(resumen.a_json()).projview == 2
    # Entradas de caché anteriores a este campo.
    assert ResumenCamino.desde_json({"odfs": [1]}).projview is None


def test_slack_avisa_los_trackings_completados():
    resultado = ResultadoTrack(estado=ESTADO_TRACK_OK, completados_con_red=1)

    assert mensaje_resumen(resultado).startswith(":construction: 1 tracking(s) se completaron")
    assert mensaje_resumen(ResultadoTrack(estado=ESTADO_TRACK_OK)) is None
