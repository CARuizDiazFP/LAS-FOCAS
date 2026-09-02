# Nombre de archivo: test_prov_config.py
# Ubicación de archivo: tests/test_prov_config.py
# Descripción: Tests de validación de configuración del cliente PROV

from __future__ import annotations

import pytest

from core.services.prov.config import ProvConfigError, get_prov_config


@pytest.fixture(autouse=True)
def _limpiar_cache_config():
    get_prov_config.cache_clear()
    yield
    get_prov_config.cache_clear()


def test_get_prov_config_lee_variables_de_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROV_BASE_URL", "https://prov.metrotel.com.ar/api/v1/ADMEQ")
    monkeypatch.setenv("PROV_USER", "api-claude")
    monkeypatch.setenv("PROV_PASSWORD", "secreto123")
    monkeypatch.delenv("PROV_TIMEOUT", raising=False)
    monkeypatch.delenv("PROV_RATE_LIMIT_PER_SECOND", raising=False)

    config = get_prov_config()

    assert config.base_url == "https://prov.metrotel.com.ar/api/v1/ADMEQ"
    assert config.user == "api-claude"
    assert config.password == "secreto123"
    assert config.timeout == 30.0
    assert config.rate_limit_per_second == 5.0


def test_get_prov_config_falla_si_falta_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROV_BASE_URL", raising=False)
    monkeypatch.setenv("PROV_USER", "api-claude")
    monkeypatch.setenv("PROV_PASSWORD", "secreto123")

    with pytest.raises(ProvConfigError, match="PROV_BASE_URL"):
        get_prov_config()


def test_get_prov_config_falla_si_rate_limit_no_es_numerico(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROV_BASE_URL", "https://prov.metrotel.com.ar/api/v1/ADMEQ")
    monkeypatch.setenv("PROV_USER", "api-claude")
    monkeypatch.setenv("PROV_PASSWORD", "secreto123")
    monkeypatch.setenv("PROV_RATE_LIMIT_PER_SECOND", "no-numero")

    with pytest.raises(ProvConfigError, match="PROV_RATE_LIMIT_PER_SECOND"):
        get_prov_config()
