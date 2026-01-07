# Nombre de archivo: test_vlan_comparator.py
# Ubicación de archivo: tests/test_vlan_comparator.py
# Descripción: Pruebas para el parser y endpoint del comparador de VLANs

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[1] / "web"))

from tests.test_web_admin import _connect_user_ok  # noqa: E402
from web_app import main as web_main  # type: ignore  # noqa: E402
from web_app.main import app  # type: ignore  # noqa: E402
from web.tools.vlan_comparator import compare_vlan_sets, parse_cisco_vlans  # noqa: E402


def _login_user(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok("userpass"))
    client.post("/login", data={"username": "user", "password": "userpass"})
    html = client.get("/").text
    return re.search(r"window.CSRF_TOKEN = \"([\w-]+)\";", html).group(1)  # type: ignore[union-attr]


def test_parse_cisco_vlans_expande_rangos_y_unifica() -> None:
    config = """
    interface GigabitEthernet0/1
      description Uplink
      switchport trunk allowed vlan 1-3, 10 , 20-22,2000
      switchport trunk allowed vlan add 30, 40-41
      spanning-tree portfast trunk
    !
    interface GigabitEthernet0/2
      switchport trunk allowed vlan 100-99,5000-5005
    """
    vlans = parse_cisco_vlans(config)
    assert vlans == {1, 2, 3, 10, 20, 21, 22, 30, 40, 41, 99, 100, 2000}


def test_compare_vlan_sets_retorna_listas_ordenadas() -> None:
    diff = compare_vlan_sets({1, 2, 3, 100}, {2, 3, 4})
    assert diff.only_a == [1, 100]
    assert diff.only_b == [4]
    assert diff.common == [2, 3]
    assert diff.vlans_a == [1, 2, 3, 100]
    assert diff.vlans_b == [2, 3, 4]


def test_endpoint_compare_vlans_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(app)
    csrf = _login_user(client, monkeypatch)
    payload = {
        "text_a": "switchport trunk allowed vlan 1-4,10",
        "text_b": "switchport trunk allowed vlan add 3-6",
        "csrf_token": csrf,
    }
    response = client.post("/api/tools/compare-vlans", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["only_a"] == [1, 2, 10]
    assert body["only_b"] == [5, 6]
    assert body["common"] == [3, 4]
    assert body["total_a"] == 5
    assert body["total_b"] == 4


def test_endpoint_compare_vlans_detecta_falta_de_datos(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(app)
    csrf = _login_user(client, monkeypatch)
    payload = {
        "text_a": "description sin vlans",
        "text_b": "switchport trunk allowed vlan 1-2",
        "csrf_token": csrf,
    }
    response = client.post("/api/tools/compare-vlans", json=payload)
    assert response.status_code == 400
    body = response.json()
    assert "No se detectaron VLANs" in body["error"]


def test_parse_cisco_vlans_soporta_rangos_altos_y_descarta_fuera_de_rango() -> None:
    config = """
    interface HundredGig0/1/0
      switchport trunk allowed vlan 0-2, 4026-4096, 5000
    """
    vlans = parse_cisco_vlans(config)
    # Rango inferior se normaliza a partir de la VLAN 1
    assert {1, 2}.issubset(vlans)
    # Rango alto conserva valores hasta 4094 aunque el límite declarado sea mayor
    assert 4026 in vlans and 4094 in vlans
    # Se descartan VLANs fuera de los límites permitidos
    assert 0 not in vlans
    assert 4095 not in vlans
    assert 5000 not in vlans
