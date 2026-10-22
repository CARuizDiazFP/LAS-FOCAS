# Nombre de archivo: test_slack_camara_search_intento.py
# Ubicación de archivo: tests/test_slack_camara_search_intento.py
# Descripción: Caracterización de _buscar_camara_intento (cascada de búsqueda de Cámaras de Slack) rama por rama

"""Tests de caracterización de `_buscar_camara_intento`.

Se parchean `_buscar_ilike_lista` y `_buscar_tokens_lista` en el módulo donde se leen, igual que
`tests/test_slack_ingreso_listener.py`, así la función se ejercita sin base de datos. Cada caso
fija una rama de la cascada: heurística previa, intentos 1 a 4, desempate exacto, seguimiento del
grupo ambiguo más acotado y resolución final.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from modules.slack_baneo_notifier import camara_search as cs
from modules.slack_baneo_notifier.camara_search import AmbiguousSearchError, _buscar_camara_intento

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


# ── Intento 3 ────────────────────────────────────────────────────────────

def test_intento3_nunca_amplia_cuando_no_hay_numeros():
    # Sin números, quitar los dígitos deja el mismo texto: el intento 3 no agrega consultas.
    res, ilikes, tokens = _correr("Cra Mitre Norte")
    assert res == (None, "cra mitre norte")
    assert ilikes == ["cra mitre norte"]
    assert tokens == [("cra", "mitre", "norte")]


def test_intento3_omitido_si_el_input_tiene_numeros():
    res, ilikes, _ = _correr("Cra Mitre 440")
    assert res == (None, "cra mitre 440")
    assert "cra mitre" not in ilikes


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
    assert tokens == [("cra", "mitre", "440")]


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
