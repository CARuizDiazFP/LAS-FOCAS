# Nombre de archivo: test_menu_keywords.py
# Ubicación de archivo: tests/test_menu_keywords.py
# Descripción: Verifica que ciertas frases disparen la apertura del menú por intención

from bot_telegram.handlers.intent import _has_menu_keyword


def test_menu_keywords_true() -> None:
    """Frases que deberían activar el menú."""
    frases = [
        "bot abrí el menú",
        "abrir menu",
        "mostrar menú",
    ]
    for frase in frases:
        assert _has_menu_keyword(frase)


def test_menu_keywords_false() -> None:
    """Frases que no deberían activar el menú."""
    frases = [
        "hola bot",
        "consulta de sla",
    ]
    for frase in frases:
        assert not _has_menu_keyword(frase)
