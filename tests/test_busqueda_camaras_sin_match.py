# Nombre de archivo: test_busqueda_camaras_sin_match.py
# Ubicación de archivo: tests/test_busqueda_camaras_sin_match.py
# Descripción: Pruebas de las mejoras de búsqueda de cámaras del relevamiento de ingresos sin match (2026-09-28): bot pegado, números pegados, desempates, Cromo literal, ID de Cromo, catálogo de Nodos y sugerencias

"""Cada caso de prueba sale de un texto REAL de `app.ingresos_sin_match` de producción (ver
`docs/relevamiento_ingresos_sin_match_2026-09-28.md`), no de un ejemplo inventado."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("TESTING", "true")

from core.services import camara_sugerencias, nodos_catalogo
from core.services.cromo import camara_botella_busqueda as cb
from modules.slack_baneo_notifier import camara_search as cs

MODULE_CB = "core.services.cromo.camara_botella_busqueda"
MODULE_CS = "modules.slack_baneo_notifier.camara_search"


def _cam(id_: int, nombre: str, padre: int | None = None) -> MagicMock:
    cam = MagicMock()
    cam.id, cam.nombre, cam.camara_padre_id = id_, nombre, padre
    return cam


def _bot(n_id: int, nombre: str, camara_id: int | None) -> MagicMock:
    bot = MagicMock()
    bot.n_id, bot.nombre, bot.camara_id = n_id, nombre, camara_id
    bot.camara = _cam(camara_id, f"padre {camara_id}") if camara_id else None
    return bot


def _session_con_filas(nombres: list[str]) -> MagicMock:
    session = MagicMock()
    session.execute.return_value.all.return_value = [(n,) for n in nombres]
    return session


@pytest.fixture(autouse=True)
def _caches_limpios():
    nodos_catalogo.invalidar_cache()
    camara_sugerencias.invalidar_cache()
    yield
    nodos_catalogo.invalidar_cache()
    camara_sugerencias.invalidar_cache()


# ── Preprocesamiento ───────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("Cra huergo 501 bot2", "Cra huergo 501 Bot 2"),
        ("Cra ausol y parana bo2", "Cra ausol y parana Bot 2"),
        ("BOT2. Cra Marcos Sastre y Colectora Este", "Bot 2. Cra Marcos Sastre y Colectora Este"),
        ("Cra huergo701", "Cra huergo 701"),
        ("Bandeja Solis1702 C.F", "Bandeja Solis 1702 C.F"),
        # No se tocan: ya funcionaban, o no son "bot"+índice.
        ("Cra Rondeau 2988 bot 1", "Cra Rondeau 2988 bot 1"),
        ("Bot 30 de Septiembre y J.M.Estrada", "Bot 30 de Septiembre y J.M.Estrada"),
        ("lizandro de la torre ( R197) y austria", "lizandro de la torre ( R197) y austria"),
    ],
)
def test_preparar_nombre_busqueda(entrada, esperado):
    assert cs.preparar_nombre_busqueda(entrada) == esperado
    assert cs.preparar_nombre_busqueda(esperado) == esperado  # idempotente


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("Cra Rondeau 2988 bot 1", "Cra Rondeau 2988"),
        ("Cámara paseo colon 701 Botella 1.", "Cámara paseo colon 701"),
        ("Cra Rondeau 2988 Bot 2", "Cra Rondeau 2988 Bot 2"),
        ("Cra 14 de julio 240 bot 12", "Cra 14 de julio 240 bot 12"),
    ],
)
def test_quitar_botella_uno(entrada, esperado):
    assert cs.quitar_botella_uno(entrada) == esperado


def test_multi_bot_pegado_y_repetido():
    assert cs.detectar_multi_bot("Cra monteagudo 202 bot1 y bot2") == [
        "Cra monteagudo 202",
        "Bot 2 Cra monteagudo 202",
    ]
    # La forma histórica sigue igual.
    assert cs.detectar_multi_bot("Bartolomé Mitre 301. Botella 1 y 2. CF") == [
        "Bartolomé Mitre 301 CF",
        "Bot 2 Bartolomé Mitre 301 CF",
    ]


def test_extraer_nombre_descarta_prefijo_basura_de_copy_paste():
    texto = (
        "*Nombre: Nodo/Camara/botella*\nme: \n"
        "Cra Acevedo 396 CF - ACEVEDO 396 - Capital Federal - Capital Federa\n"
        "*Ingreso o Egreso*\nEgreso\n"
    )
    assert cs.extraer_nombre_camara(texto).startswith("Cra Acevedo 396 CF")


def test_filtro_numeros_acepta_numero_pegado_a_letras_pero_no_otro_numero():
    exacta = _cam(1, "lizandro de la torre ( R197) y austria")
    b99 = _cam(2, "Cra. Av. 122 99B - La Plata")
    otra = _cam(3, "Cra Mitre 4400")
    assert cs._filtrar_por_numeros([exacta], {"197"}) == [exacta]
    assert cs._filtrar_por_numeros([b99], {"122", "99"}) == [b99]
    assert cs._filtrar_por_numeros([otra], {"440"}) == []


# ── Desempate exacto en `Camara` ───────────────────────────────────────────────────────────────


def test_desempate_exacto_elige_la_unica_coincidencia_exacta():
    exacta = _cam(10, "Cra Libertad 991 CF")
    critica = _cam(11, "BOTELLA CRITICA Cra Libertad 991 CF")
    with patch(f"{MODULE_CS}._buscar_ilike_lista", return_value=[exacta, critica]), patch(
        f"{MODULE_CS}._buscar_tokens_lista", return_value=[exacta, critica]
    ):
        camara, _ = cs.buscar_camara("Cra Libertad 991 CF", MagicMock())
    assert camara is exacta


def test_desempate_exacto_no_elige_entre_duplicados_reales():
    """Dos Cámaras distintas que normalizan igual ("C.F." y "CF") siguen siendo ambiguas."""
    a, b = _cam(20, "Cra Madero 898 C.F"), _cam(21, "Cra Madero 898 CF")
    with patch(f"{MODULE_CS}._buscar_ilike_lista", return_value=[a, b]), patch(
        f"{MODULE_CS}._buscar_tokens_lista", return_value=[a, b]
    ), pytest.raises(cs.AmbiguousSearchError):
        cs.buscar_camara("Cra Madero 898 CF", MagicMock())


def test_desempate_exacto_no_aplica_al_prefijo_antes_del_guion():
    """Regresión medida 2026-09-28: "terraza Viamonte 898- Piso 4 C.F." terminaba en "terraza
    Viamonte 898" porque el recorte coincidía exacto con esa otra cámara."""
    corta = _cam(30, "terraza Viamonte 898")
    larga = _cam(31, "terraza Viamonte 898- Piso 4 C.F.")

    def _ilike(patron, session):
        return [larga] if "piso" in patron else [corta, larga]

    def _tokens(tokens, session):
        return [larga] if "piso" in tokens else [corta, larga]

    with patch(f"{MODULE_CS}._buscar_ilike_lista", side_effect=_ilike), patch(
        f"{MODULE_CS}._buscar_tokens_lista", side_effect=_tokens
    ):
        camara, _ = cs.buscar_camara("terraza Viamonte 898- Piso 4 C.F.", MagicMock())
    assert camara is larga


# ── Cascada Cromo ──────────────────────────────────────────────────────────────────────────────


def test_desempatar_botellas():
    exacta = _bot(1, "Cra A. Frondizi 1413 Bot 2 PILAR", 7657)
    mayus = _bot(2, "Cra A. Frondizi 1413 BOT 2 PILAR", 7657)
    # Mismo padre, ambas normalizan igual → la de menor n_id.
    assert cb._desempatar_botellas([mayus, exacta], "cra a frondizi 1413 bot 2 pilar") is exacta
    # Padres distintos y sin exacta única → ambiguo.
    x, y = _bot(3, "Bot 2 Cra X 10", 1), _bot(4, "Bot 2 Cra X 10 CF", 2)
    assert cb._desempatar_botellas([x, y], "otra cosa") is None
    # Padre desconocido nunca cuenta como "mismo padre".
    assert cb._desempatar_botellas([_bot(5, "A 1", None), _bot(6, "A 1 b", None)], "zzz") is None


def test_cascada_cromo_intento_literal_encuentra_av_sin_expandir():
    """"Cra Av Santa Fe 4276 Bot 2 CF" existe EXACTO en cromo_botellas; la entrada expandida
    ("avenida") no la encontraba."""
    botella = _bot(6631049, "Cra Av Santa Fe 4276 Bot 2 CF", 2810)

    def _ilike(patron, session):
        return [botella] if "avenida" not in patron else []

    with patch(f"{MODULE_CB}._buscar_botella_ilike_lista", side_effect=_ilike), patch(
        f"{MODULE_CB}._buscar_botella_tokens_lista", return_value=[]
    ):
        assert cb._cascada_botella("Cra Av Santa Fe 4276 Bot 2 CF", MagicMock()) == [botella]


def test_id_de_cromo_explicito_resuelve_por_n_id():
    botella = _bot(6631457, "Tza. Florida 142 C.F.", 25769)
    session = MagicMock()
    session.get.return_value = botella
    with patch(f"{MODULE_CB}._buscar_extendida") as cascada:
        r = cb.buscar_camara_o_botella_cromo("ID DE BOTELLA : 6631457 ( TZA. FLORIDA 142)", session)
    cascada.assert_not_called()
    assert r.botella is botella and r.fuente == "cromo_botella"
    assert session.get.call_args.args[1] == 6631457


def test_id_de_cromo_inexistente_cae_a_la_cascada():
    session = MagicMock()
    session.get.return_value = None
    vacio = cb.ResultadoBusquedaExtendida(camara=None, nombre_norm="x", fuente=None, botella=None)
    with patch(f"{MODULE_CB}._buscar_extendida", return_value=vacio) as cascada:
        cb.buscar_camara_o_botella_cromo("Caja cto ID:1274520", session)
    cascada.assert_called_once()


def test_bot_uno_reintenta_sin_la_mencion_solo_si_el_primero_no_resuelve():
    principal = _cam(6733, "Cra Rondeau 2988 C.F.")
    vacio = cb.ResultadoBusquedaExtendida(camara=None, nombre_norm="x", fuente=None, botella=None)
    ok = cb.ResultadoBusquedaExtendida(camara=principal, nombre_norm="y", fuente="camara", botella=None)
    with patch(f"{MODULE_CB}._buscar_extendida", side_effect=[vacio, ok]) as cascada:
        r = cb.buscar_camara_o_botella_cromo("CRA Rondeau 2988 bot 1", MagicMock())
    assert r.camara is principal
    assert [c.args[0] for c in cascada.call_args_list] == ["CRA Rondeau 2988 bot 1", "CRA Rondeau 2988"]


def test_bot_uno_variante_ambigua_no_reemplaza_el_resultado_original():
    vacio = cb.ResultadoBusquedaExtendida(camara=None, nombre_norm="x", fuente=None, botella=None)
    with patch(
        f"{MODULE_CB}._buscar_extendida",
        side_effect=[vacio, cs.AmbiguousSearchError("Paseo colon 701", 2, ["a", "b"])],
    ):
        assert cb.buscar_camara_o_botella_cromo("Paseo colon 701 bot 1", MagicMock()) is vacio


# ── Catálogo de Nodos ──────────────────────────────────────────────────────────────────────────

_NOMBRES_NODO = [
    "Nodo Barrio Norte - Rack 3 Electronica - ME",
    "NODO El Rincon 842 Rack 1 de Electrónica",
    "Rack 2 Nodo Libertador 710 - Vicente Lopez",
    "Nodo Tacuari Sala 2",
    "Nodo Paraguay 2302 Rack 1 de Electrónica METH",
    "Nodo Sta Fe 4965 Rack 6 Electrónica - Facebook",
    "Nodo ODF Mitre 3821(Terraza) - RACK 1  SAN MARTIN",
    "Nodo Retiro - Rack 3 Electronica - ME",
    "Nodo Retiro 2",
]


@pytest.mark.parametrize(
    "texto",
    ["Barrio Norte", "Rincón", "Vicente López", "Tacuari 1", "Tacuari Sala1", "Data Tacuari , sala1",
     "Dc tacuari  sala 1", "Paraguay 2302", "Retiro", "Nodo Escobar Rack 1 de FO"],
)
def test_nodo_reconocido(texto):
    assert nodos_catalogo.corresponde_a_nodo(texto, _session_con_filas(_NOMBRES_NODO))


@pytest.mark.parametrize(
    "texto",
    # Nombre entero, nunca contenido; y sin claves genéricas de calle ("Mitre", "Santa Fe").
    ["Cra Congreso 3449 CF", "Cra Rincon 10", "Mitre", "Santa Fe", "Facebook", "Quilmes", ""],
)
def test_no_es_nodo(texto):
    assert not nodos_catalogo.corresponde_a_nodo(texto, _session_con_filas(_NOMBRES_NODO))


def test_catalogo_se_cachea_y_un_error_no_se_cachea():
    session = _session_con_filas(_NOMBRES_NODO)
    nodos_catalogo.claves_nodo(session)
    nodos_catalogo.claves_nodo(session)
    assert session.execute.call_count == 1

    nodos_catalogo.invalidar_cache()
    rota = MagicMock()
    rota.execute.side_effect = RuntimeError("db caída")
    assert nodos_catalogo.claves_nodo(rota) == frozenset()
    assert nodos_catalogo.claves_nodo(session)  # el fallo anterior no quedó cacheado


# ── Sugerencias ────────────────────────────────────────────────────────────────────────────────

_INVENTARIO = [
    "Bot. 2 Tza. Esmeralda 726 C.F.",
    "Cra Juana Manso 720 CF",
    "Cra Juana Manso 720 Bot 2 CF",
    "Bot Tza Av. Cordoba 720 C.F",
    "Cra Paseo Colon 701 CF",
    "Cra Moreno 701",
]


def test_sugiere_por_altura_y_calle_con_typo():
    sug = camara_sugerencias.sugerir_camaras("Cra juano manso 720", _session_con_filas(_INVENTARIO))
    assert sug[:2] == ["Cra Juana Manso 720 CF", "Cra Juana Manso 720 Bot 2 CF"]
    assert "Bot Tza Av. Cordoba 720 C.F" not in sug


def test_sugerencia_ignora_bot_uno_y_descriptores():
    s = _session_con_filas(_INVENTARIO)
    assert camara_sugerencias.sugerir_camaras("Paseo colon 701 bot 1", s)[0] == "Cra Paseo Colon 701 CF"
    assert camara_sugerencias.sugerir_camaras("Botella 2, terraza. Esmeralda 726. CF", s) == [
        "Bot. 2 Tza. Esmeralda 726 C.F."
    ]


def test_sin_numeros_no_sugiere():
    assert camara_sugerencias.sugerir_camaras("Quesada y TBA", _session_con_filas(_INVENTARIO)) == []


# ── Tracking: una ubicación de Nodo no es un caso sin match ────────────────────────────────────


@pytest.mark.parametrize(("nombre", "registra"), [("Nodo Escobar Rack 1 de FO", False), ("CRA Artigas 2830 - PACHECO", True)])
def test_tracking_no_registra_sin_match_para_nodos(nombre, registra):
    from core.services.infra_service import _resolve_camara_o_registrar_sin_match

    vacio = cb.ResultadoBusquedaExtendida(camara=None, nombre_norm="x", fuente=None, botella=None)
    session = _session_con_filas([])
    with patch(f"{MODULE_CB}.buscar_camara_o_botella_cromo", return_value=vacio):
        assert _resolve_camara_o_registrar_sin_match(session, nombre, filename="t.txt") is None
    assert session.add.called is registra
