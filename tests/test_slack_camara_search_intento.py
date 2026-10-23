# Nombre de archivo: test_slack_camara_search_intento.py
# Ubicación de archivo: tests/test_slack_camara_search_intento.py
# Descripción: Caracterización de _buscar_camara_intento (cascada de búsqueda de Cámaras de Slack) rama por rama

"""Tests de caracterización de `_buscar_camara_intento`.

Se parchean `_buscar_ilike_lista` y `_buscar_tokens_lista` en el módulo donde se leen, igual que
`tests/test_slack_ingreso_listener.py`, así la función se ejercita sin base de datos. Cada caso
fija una rama de la cascada: heurística previa, intentos 1 a 4, desempate exacto, seguimiento del
grupo ambiguo más acotado y resolución final. Al final, el prefijo "Empalme <n_id>" de
`buscar_camara` (2026-10-23).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from modules.slack_baneo_notifier import camara_search as cs
from modules.slack_baneo_notifier.camara_search import (
    AmbiguousSearchError,
    NumeroNoCoincideError,
    _buscar_camara_intento,
)

MOD = "modules.slack_baneo_notifier.camara_search"


def _cam(id_: int, nombre: str) -> SimpleNamespace:
    return SimpleNamespace(id=id_, nombre=nombre)


def _correr(nombre_raw, ilike=None, tokens=None, **kwargs):
    """Corre la función con búsquedas simuladas; devuelve (resultado, llamadas ilike, llamadas tokens).

    `ilike` mapea patrón -> candidatas; `tokens` mapea tuple(tokens) -> candidatas.
    """
    ilike = ilike or {}
    tokens = tokens or {}
    llamadas_ilike: list[str] = []
    llamadas_tokens: list[tuple[str, ...]] = []

    def _fake_ilike(patron, session):
        llamadas_ilike.append(patron)
        return list(ilike.get(patron, []))

    def _fake_tokens(toks, session):
        llamadas_tokens.append(tuple(toks))
        return list(tokens.get(tuple(toks), []))

    with (
        patch(f"{MOD}._buscar_ilike_lista", side_effect=_fake_ilike),
        patch(f"{MOD}._buscar_tokens_lista", side_effect=_fake_tokens),
    ):
        res = _buscar_camara_intento(nombre_raw, object(), **kwargs)
    return res, llamadas_ilike, llamadas_tokens


# ── Heurística previa ────────────────────────────────────────────────────

@pytest.mark.parametrize("texto", ["Mitre", "Av", "ab cd", ""])
def test_nombre_insuficiente_levanta_ambiguo_cantidad_cero_sin_consultar(texto):
    with pytest.raises(AmbiguousSearchError) as exc:
        _correr(texto, ilike={"mitre": [_cam(1, "Mitre")]})
    assert exc.value.cantidad == 0
    assert exc.value.candidatos == []
    assert exc.value.nombre_raw == texto


def test_nombre_insuficiente_con_numero_si_busca():
    # "Mitre 440": un solo token significativo pero hay número -> no es insuficiente.
    cam = _cam(1, "Cra Mitre 440")
    (res, ilikes, tokens) = _correr("Mitre 440", ilike={"mitre 440": [cam]})
    assert res == (cam, "mitre 440")
    assert ilikes == ["mitre 440"]
    assert tokens == []  # intento 2 omitido: sólo 1 token de >=3 chars


# ── Intento 1 ────────────────────────────────────────────────────────────

def test_intento1_un_candidato():
    cam = _cam(1, "Cra Mitre 440")
    res, ilikes, tokens = _correr("Cra Mitre 440", ilike={"cra mitre 440": [cam]})
    assert res == (cam, "cra mitre 440")
    assert ilikes == ["cra mitre 440"]
    assert tokens == []


def test_intento1_aplica_expansion_y_devuelve_nombre_norm_expandido():
    cam = _cam(1, "Calle Principal 100")
    res, _, _ = _correr("Clle Principal 100", ilike={"calle principal 100": [cam]})
    assert res == (cam, "calle principal 100")


def test_intento1_desempate_exacto_elige_la_unica_exacta():
    exacta = _cam(1, "Cra Libertad 991 CF")
    critica = _cam(2, "Cra Libertad 991 CF Piso 3")
    res, _, tokens = _correr("Cra Libertad 991 CF", ilike={"cra libertad 991": [exacta, critica]})
    assert res == (exacta, "cra libertad 991")
    assert tokens == []


def test_desempate_desactivado_deja_ambiguo():
    a = _cam(1, "Cra Libertad 991 CF")
    b = _cam(2, "Cra Libertad 991 CF Piso 3")
    with pytest.raises(AmbiguousSearchError) as exc:
        _correr("Cra Libertad 991 CF", ilike={"cra libertad 991": [a, b]}, desempate_exacto=False)
    assert exc.value.cantidad == 2
    assert exc.value.candidatos == [a.nombre, b.nombre]


def test_desempate_con_gemela_critica_no_elige():
    comun = _cam(1, "Cra Libertad 991 CF")
    critica = _cam(2, "BOTELLA CRITICA Cra Libertad 991 CF")
    with pytest.raises(AmbiguousSearchError) as exc:
        _correr("Cra Libertad 991 CF", ilike={"cra libertad 991": [comun, critica]})
    assert exc.value.cantidad == 2


def test_desempate_con_dos_exactas_sigue_ambiguo():
    a = _cam(1, "Cra Libertad 991 C.F.")
    b = _cam(2, "Cra Libertad 991 CF")
    with pytest.raises(AmbiguousSearchError) as exc:
        _correr("Cra Libertad 991 CF", ilike={"cra libertad 991": [a, b]})
    assert exc.value.cantidad == 2


def test_desempate_sin_ninguna_exacta_sigue_ambiguo():
    a = _cam(1, "Cra Libertad 991 Norte")
    b = _cam(2, "Cra Libertad 991 Sur")
    with pytest.raises(AmbiguousSearchError):
        _correr("Cra Libertad 991", ilike={"cra libertad 991": [a, b]})


# ── Filtros dentro de los helpers de candidatas ──────────────────────────

def test_filtra_por_numeros_requeridos():
    mala = _cam(1, "Cra Mitre 399")
    buena = _cam(2, "Cra Mitre 440")
    res, _, _ = _correr("Cra Mitre 440", ilike={"cra mitre 440": [mala, buena]})
    assert res == (buena, "cra mitre 440")


def test_excluye_bots_secundarios_si_no_se_menciona_bot():
    principal = _cam(1, "Cra Mitre 440")
    secundaria = _cam(2, "Bot 2 Cra Mitre 440")
    res, _, _ = _correr("Cra Mitre 440", ilike={"cra mitre 440": [secundaria, principal]})
    assert res == (principal, "cra mitre 440")


def test_conserva_bots_secundarios_si_se_menciona_bot():
    bot2 = _cam(1, "Bot 2 Cra Mitre 440")
    res, _, _ = _correr("Bot 2 Cra Mitre 440", ilike={"bot 2 cra mitre 440": [bot2]})
    assert res == (bot2, "bot 2 cra mitre 440")


def test_filtra_numero_de_botella_pedido():
    ed2 = _cam(1, "Bot. Avalos 2829 Ed 2 Subs")
    bot2 = _cam(2, "Bot 2 Avalos 2829 Ed 2 Subs")
    res, _, _ = _correr(
        "Avalos 2829 Bot 2 Ed 2 Subs",
        ilike={"avalos 2829 bot 2 ed 2 subs": [ed2, bot2]},
    )
    assert res[0] is bot2


# ── Intento 2 (tokens) ───────────────────────────────────────────────────

def test_intento2_tokens_resuelve_cuando_ilike_no_encuentra():
    cam = _cam(1, "Cra Mitre Esquina 440")
    res, ilikes, tokens = _correr(
        "Cra Mitre 440", tokens={("cra", "mitre", "440"): [cam]}
    )
    assert res == (cam, "cra mitre 440")
    assert ilikes == ["cra mitre 440"]
    assert tokens == [("cra", "mitre", "440")]


def test_intento2_tokens_multiples_sin_exacta_quedan_ambiguos():
    a = _cam(1, "Cra Mitre Norte 440")
    b = _cam(2, "Cra Mitre Sur 440")
    with pytest.raises(AmbiguousSearchError) as exc:
        _correr("Cra Mitre 440", tokens={("cra", "mitre", "440"): [a, b]})
    assert exc.value.cantidad == 2


# ── Intento 3: número que no coincide → sólo sugerencias (2026-10-23) ──

def test_intento3_nunca_amplia_cuando_no_hay_numeros():
    # Sin números no hay nada que quitar: el intento 3 no agrega consultas.
    res, ilikes, tokens = _correr("Cra Mitre Norte")
    assert res == (None, "cra mitre norte")
    assert ilikes == ["cra mitre norte"]
    assert tokens == [("cra", "mitre", "norte")]


def test_intento3_numero_que_no_coincide_sin_parecidas_queda_sin_match():
    res, ilikes, tokens = _correr("Cra Mitre 440")
    assert res == (None, "cra mitre 440")
    assert "cra mitre" not in ilikes  # nunca un ILIKE sin el número
    assert tokens == [("cra", "mitre", "440"), ("cra", "mitre")]


def test_intento3_numero_que_no_coincide_sugiere_parecidas_sin_asignar():
    a399 = _cam(1, "Cra Mitre 399")
    a404 = _cam(2, "Cra Mitre 404")
    with pytest.raises(NumeroNoCoincideError) as exc:
        _correr("Cra Mitre 440", tokens={("cra", "mitre"): [a399, a404]})
    assert isinstance(exc.value, AmbiguousSearchError)  # subclase: los callers existentes no cambian
    assert exc.value.nombre_raw == "Cra Mitre 440"
    assert exc.value.cantidad == 2
    # La más parecida primero ("404" comparte dos "4" con "440").
    assert exc.value.candidatos == ["Cra Mitre 404", "Cra Mitre 399"]


def test_intento3_hasta_tres_sugerencias():
    cams = [_cam(i, f"Cra Mitre {100 + i}") for i in range(1, 6)]
    with pytest.raises(NumeroNoCoincideError) as exc:
        _correr("Cra Mitre 440", tokens={("cra", "mitre"): cams})
    assert exc.value.cantidad == 5
    assert len(exc.value.candidatos) == 3


def test_intento3_aplica_los_filtros_de_bot_y_de_botella():
    principal = _cam(1, "Cra Mitre 399")
    bot2 = _cam(2, "Bot 2 Cra Mitre 399")
    with pytest.raises(NumeroNoCoincideError) as exc:
        _correr("Cra Mitre 440", tokens={("cra", "mitre"): [bot2, principal]})
    assert exc.value.candidatos == ["Cra Mitre 399"]  # sin "bot" en el texto, sin botellas
    # "Bot 3 Cra Mitre 440" pide la botella 3: una Bot 2 no se sugiere.
    res, _, _ = _correr("Bot 3 Cra Mitre 440", tokens={("bot", "cra", "mitre"): [bot2]})
    assert res == (None, "bot 3 cra mitre 440")


def test_intento3_no_busca_si_sin_numeros_queda_insuficiente_o_generico():
    # "Mitre 440" → "mitre" (1 token); "Cra 25 440" → "cra"; "Cra calle 25" → "cra calle" (sólo
    # genéricos): nunca miles de parecidas. Las consultas de tokens son sólo las del intento 2.
    casos = {"Mitre 440": [("mitre", "440")], "Cra 25 440": [("cra", "440")], "Cra calle 25": [("cra", "calle")]}
    for texto, esperadas in casos.items():
        res, _, tokens = _correr(texto)
        assert res[0] is None
        assert tokens == esperadas, texto


def test_intento3_prueba_tambien_la_forma_literal():
    # "Av" expandido a "avenida" no está en el inventario; la forma literal sí.
    cam = _cam(1, "Cra Av Santa Fe 4200")
    with pytest.raises(NumeroNoCoincideError) as exc:
        _correr("Cra Av Santa Fe 4276", tokens={("cra", "santa"): [cam]})
    assert exc.value.candidatos == ["Cra Av Santa Fe 4200"]


def test_intento3_no_reemplaza_a_un_grupo_ambiguo():
    # Si un intento encontró varias con el número correcto, es ambiguo común (no sugerencias).
    a = _cam(1, "Cra Mitre 440 A")
    b = _cam(2, "Cra Mitre 440 B")
    with pytest.raises(AmbiguousSearchError) as exc:
        _correr("Cra Mitre 440", ilike={"cra mitre 440": [a, b]}, tokens={("cra", "mitre"): [_cam(3, "Cra Mitre 1")]})
    assert type(exc.value) is AmbiguousSearchError


def test_intento3_no_corre_si_hubo_match():
    cam = _cam(1, "Cra Mitre 440")
    res, _, tokens = _correr("Cra Mitre 440", ilike={"cra mitre 440": [cam]})
    assert res == (cam, "cra mitre 440")
    assert tokens == []


# ── Intento 4 (sin expansión) ────────────────────────────────────────────

def test_intento4_ilike_con_nombre_raw_sin_expansion():
    cam = _cam(1, "Clle Principal 100")
    res, ilikes, _ = _correr("Clle Principal 100", ilike={"clle principal 100": [cam]})
    assert res == (cam, "clle principal 100")
    assert ilikes == ["calle principal 100", "clle principal 100"]


def test_intento4_tokens_con_nombre_raw_sin_expansion():
    cam = _cam(1, "Clle Principal Esq 100")
    res, ilikes, tokens = _correr(
        "Clle Principal 100", tokens={("clle", "principal", "100"): [cam]}
    )
    assert res == (cam, "clle principal 100")
    assert tokens == [("calle", "principal", "100"), ("clle", "principal", "100")]


def test_intento4_omite_tokens_si_hay_menos_de_dos():
    # "Clle 10": un solo token de >=3 chars en cada variante ("10" no llega a 3).
    res, ilikes, tokens = _correr("Clle 10")
    assert res == (None, "calle 10")
    assert ilikes == ["calle 10", "clle 10"]
    assert tokens == []


def test_intento4_omitido_si_raw_normalizado_coincide():
    res, ilikes, tokens = _correr("Cra Mitre 440")
    assert ilikes == ["cra mitre 440"]
    # La segunda consulta de tokens es la del intento 3 (parecidas sin el número), no la del 4.
    assert tokens == [("cra", "mitre", "440"), ("cra", "mitre")]


# ── Seguimiento del grupo ambiguo y resolución final ─────────────────────

def test_sin_candidatas_devuelve_none_y_nombre_norm():
    res, _, _ = _correr("Cra Mitre 440")
    assert res == (None, "cra mitre 440")


def test_ambiguo_informa_hasta_tres_candidatas():
    cams = [_cam(i, f"Cra Mitre 440 Torre {i}") for i in range(1, 6)]
    with pytest.raises(AmbiguousSearchError) as exc:
        _correr("Cra Mitre 440", ilike={"cra mitre 440": cams})
    assert exc.value.cantidad == 5
    assert exc.value.candidatos == [c.nombre for c in cams[:3]]
    assert exc.value.nombre_raw == "Cra Mitre 440"


def test_ambiguo_conserva_el_grupo_mas_acotado():
    grande = [_cam(i, f"Cra Mitre 440 Torre {i}") for i in range(1, 4)]
    chico = [_cam(10, "Cra Mitre 440 Anexo A"), _cam(11, "Cra Mitre 440 Anexo B")]
    with pytest.raises(AmbiguousSearchError) as exc:
        _correr(
            "Cra Mitre 440",
            ilike={"cra mitre 440": grande},
            tokens={("cra", "mitre", "440"): chico},
        )
    assert exc.value.cantidad == 2
    assert exc.value.candidatos == [c.nombre for c in chico]


def test_ambiguo_no_reemplaza_por_un_grupo_mayor_o_igual():
    primero = [_cam(1, "Cra Mitre 440 A"), _cam(2, "Cra Mitre 440 B")]
    igual = [_cam(3, "Cra Mitre 440 C"), _cam(4, "Cra Mitre 440 D")]
    primero_c = [_cam(1, "Clle Principal 100 A"), _cam(2, "Clle Principal 100 B")]
    mayor = [_cam(i, f"Clle Principal 100 X{i}") for i in range(5, 8)]
    with pytest.raises(AmbiguousSearchError) as exc:
        _correr(
            "Cra Mitre 440",
            ilike={"cra mitre 440": primero},
            tokens={("cra", "mitre", "440"): igual},
        )
    assert exc.value.candidatos == [c.nombre for c in primero]
    with pytest.raises(AmbiguousSearchError) as exc:
        _correr(
            "Clle Principal 100",
            ilike={"calle principal 100": primero_c, "clle principal 100": mayor},
        )
    assert exc.value.candidatos == [c.nombre for c in primero_c]


def test_ambiguo_se_resuelve_si_un_intento_posterior_da_una_sola():
    primero = [_cam(1, "Clle Principal 100 A"), _cam(2, "Clle Principal 100 B")]
    unica = _cam(3, "Clle Principal 100")
    res, _, _ = _correr(
        "Clle Principal 100",
        ilike={"calle principal 100": primero, "clle principal 100": [unica]},
    )
    assert res == (unica, "clle principal 100")


def test_reexporta_sin_cambios_la_firma_publica():
    assert cs._buscar_camara_intento is _buscar_camara_intento


# ── Prefijo "Empalme <n_id>" (2026-10-23) ────────────────────────────────

def _botella(n_id: int, nombre: str, camara) -> SimpleNamespace:
    return SimpleNamespace(
        n_id=n_id, nombre=nombre, camara=camara, camara_id=getattr(camara, "id", None), vigente=True
    )


class _Sesion:
    """Sesión mínima: `get(CromoBotella, n_id)` desde un dict; registra las llamadas."""

    def __init__(self, botellas: dict | None = None) -> None:
        self.botellas = botellas or {}
        self.gets: list[int] = []

    def get(self, _modelo, n_id):
        self.gets.append(n_id)
        return self.botellas.get(n_id)


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Empalme 10245762: Cra 25 de Mayo 302", (10245762, "Cra 25 de Mayo 302")),
        ("empalme 10245762 - Cra 25 de Mayo 302", (10245762, "Cra 25 de Mayo 302")),
        ("EMPALME #10245762:Cra X 1", (10245762, "Cra X 1")),
        ("Empalme 10245762", (10245762, "")),
        ("Cra 25 de Mayo 302", (None, "Cra 25 de Mayo 302")),
        ("Empalme 1024576: Cra X 1", (None, "Empalme 1024576: Cra X 1")),  # 7 dígitos: no es n_id
        ("Empalme 10245762 Cra X 1", (None, "Empalme 10245762 Cra X 1")),  # sin separador
        ("Cra Empalme 10245762: X", (None, "Cra Empalme 10245762: X")),  # sólo al principio
    ],
)
def test_separar_prefijo_empalme(texto, esperado):
    assert cs.separar_prefijo_empalme(texto) == esperado


def test_prefijo_empalme_valido_es_match_directo_sin_buscar_por_nombre():
    camara = _cam(33978, "Cra 25 de Mayo 302 CF")
    sesion = _Sesion({10245762: _botella(10245762, "Cra 25 de Mayo 302 CF", camara)})
    with (
        patch(f"{MOD}._buscar_ilike_lista") as ilike,
        patch(f"{MOD}._buscar_tokens_lista") as tokens,
    ):
        res, _ = cs.buscar_camara("Empalme 10245762: Cra 25 de Mayo 302", sesion)
    assert res is camara
    assert sesion.gets == [10245762]
    ilike.assert_not_called()
    tokens.assert_not_called()


def test_prefijo_empalme_inexistente_busca_por_nombre_sin_exigir_el_numero():
    camara = _cam(33978, "Cra 25 de Mayo 302 CF")
    sesion = _Sesion()
    res, ilikes, _ = _correr_buscar_camara("Empalme 10245762: Cra 25 de Mayo 302", sesion,
                                            ilike={"cra 25 de mayo 302": [camara]})
    assert res[0] is camara
    assert sesion.gets == [10245762]
    assert all("10245762" not in p for p in ilikes)


def test_prefijo_empalme_que_el_resto_contradice_busca_por_nombre():
    # n_id existente pero de otra cámara (typo): el resto no lo corrobora → búsqueda por nombre.
    otra = _cam(1, "Cra Mitre 440")
    buena = _cam(33978, "Cra 25 de Mayo 302 CF")
    sesion = _Sesion({10245762: _botella(10245762, "Cra Mitre 440", otra)})
    res, _, _ = _correr_buscar_camara("Empalme 10245762: Cra 25 de Mayo 302", sesion,
                                      ilike={"cra 25 de mayo 302": [buena]})
    assert res[0] is buena


def test_sin_prefijo_empalme_no_consulta_n_id():
    sesion = _Sesion()
    _correr_buscar_camara("Cra 25 de Mayo 302", sesion)
    assert sesion.gets == []


def _correr_buscar_camara(nombre_raw, sesion, ilike=None, tokens=None):
    ilike = ilike or {}
    tokens = tokens or {}
    llamadas: list[str] = []

    def _fake_ilike(patron, session):
        llamadas.append(patron)
        return list(ilike.get(patron, []))

    with (
        patch(f"{MOD}._buscar_ilike_lista", side_effect=_fake_ilike),
        patch(f"{MOD}._buscar_tokens_lista", side_effect=lambda t, s: list(tokens.get(tuple(t), []))),
    ):
        res = cs.buscar_camara(nombre_raw, sesion)
    return res, llamadas, None
