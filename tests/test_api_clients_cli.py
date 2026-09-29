# Nombre de archivo: test_api_clients_cli.py
# Ubicación de archivo: tests/test_api_clients_cli.py
# Descripción: Tests del CLI scripts/api_clients.py (alta, rotación y desactivación de clientes OAuth2)

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.password import verify_password
from scripts import api_clients


def test_crear_guarda_solo_el_hash_y_devuelve_el_secret() -> None:
    session = MagicMock()

    client_id, secreto = api_clients.crear(session, " NOC ", ["servicios:read"])

    cliente = session.add.call_args.args[0]
    assert client_id.startswith("lf_") and len(client_id) == 19
    assert len(secreto) >= 40
    assert cliente.client_secret_hash != secreto
    assert verify_password(secreto, cliente.client_secret_hash)
    assert cliente.nombre_area == "NOC"
    assert cliente.scopes == ["servicios:read"]
    session.commit.assert_called_once()


def test_crear_rechaza_scope_desconocido() -> None:
    with pytest.raises(SystemExit, match="desconocidos"):
        api_clients.crear(MagicMock(), "NOC", ["servicios:botellas:write"])


def test_rotar_secret_invalida_el_anterior() -> None:
    session = MagicMock()
    _, viejo = api_clients.crear(session, "NOC", ["servicios:read"])
    cliente = session.add.call_args.args[0]
    session.execute.return_value.scalar_one_or_none.return_value = cliente

    nuevo = api_clients.rotar_secret(session, cliente.client_id)

    assert nuevo != viejo
    assert verify_password(nuevo, cliente.client_secret_hash)
    assert not verify_password(viejo, cliente.client_secret_hash)


def test_desactivar_y_cliente_inexistente() -> None:
    session = MagicMock()
    cliente = MagicMock(activo=True)
    session.execute.return_value.scalar_one_or_none.return_value = cliente
    api_clients.desactivar(session, "lf_x")
    assert cliente.activo is False

    session.execute.return_value.scalar_one_or_none.return_value = None
    with pytest.raises(SystemExit, match="No existe"):
        api_clients.desactivar(session, "lf_nada")


def test_main_crear_y_listar_imprimen_sin_filtrar_hashes(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    import db.session

    session = MagicMock()
    fabrica = MagicMock()
    fabrica.return_value.__enter__.return_value = session
    monkeypatch.setattr(db.session, "SessionLocal", fabrica)

    assert api_clients.main(["crear", "--area", "NOC", "--scopes", "servicios:read"]) == 0
    salida = capsys.readouterr().out
    cliente = session.add.call_args.args[0]
    assert f"client_id:     {cliente.client_id}" in salida
    assert "client_secret: " in salida

    session.execute.return_value.scalars.return_value = [cliente]
    assert api_clients.main(["listar"]) == 0
    listado = capsys.readouterr().out
    assert cliente.client_id in listado
    assert cliente.client_secret_hash not in listado
