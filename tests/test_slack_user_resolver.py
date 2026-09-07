# Nombre de archivo: test_slack_user_resolver.py
# Ubicación de archivo: tests/test_slack_user_resolver.py
# Descripción: Pruebas de resolver_nombre_tecnico (Slack users.info -> nombre real del técnico)

from __future__ import annotations

from unittest.mock import MagicMock

from modules.slack_baneo_notifier.slack_user_resolver import resolver_nombre_tecnico


def test_resuelve_display_name_cuando_esta_poblado() -> None:
    client = MagicMock()
    client.users_info.return_value = {
        "user": {
            "real_name": "Rider Fernandez",
            "profile": {"display_name": "rider.fernandez", "real_name": "Rider Fernandez"},
        }
    }

    resultado = resolver_nombre_tecnico(client, "U0AUB6CRE4A")

    assert resultado == "rider.fernandez"
    client.users_info.assert_called_once_with(user="U0AUB6CRE4A")


def test_cae_a_real_name_cuando_display_name_esta_vacio() -> None:
    client = MagicMock()
    client.users_info.return_value = {
        "user": {"real_name": "Rider Fernandez", "profile": {"display_name": "", "real_name": "Rider Fernandez"}}
    }

    resultado = resolver_nombre_tecnico(client, "U0AUB6CRE4A")

    assert resultado == "Rider Fernandez"


def test_cae_al_id_crudo_si_la_api_falla() -> None:
    client = MagicMock()
    client.users_info.side_effect = Exception("boom")

    resultado = resolver_nombre_tecnico(client, "U0AUB6CRE4A")

    assert resultado == "U0AUB6CRE4A"


def test_none_si_no_hay_slack_user_id() -> None:
    client = MagicMock()

    resultado = resolver_nombre_tecnico(client, None)

    assert resultado is None
    client.users_info.assert_not_called()
