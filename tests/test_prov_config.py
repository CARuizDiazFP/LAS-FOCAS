# Nombre de archivo: test_prov_config.py
# Ubicación de archivo: tests/test_prov_config.py
# Descripción: Tests de validación de configuración del cliente PROV

from __future__ import annotations

import os

import pytest

import core.services.prov.config as prov_config
from core.services.prov.config import ProvConfigError, get_prov_config


@pytest.fixture(autouse=True)
def _limpiar_cache_config():
    get_prov_config.cache_clear()
    yield
    get_prov_config.cache_clear()


@pytest.fixture(autouse=True)
def _secretos_solo_desde_entorno(monkeypatch: pytest.MonkeyPatch):
    """`core.config.get_secret` lee `/run/secrets/<nombre>` ANTES de caer a la variable de entorno,
    y esos archivos SÍ están montados en el contenedor `lasfocasdev-api` (`api_prov_user_v1` /
    `api_prov_pass_v1`): ahí un `monkeypatch.setenv("PROV_USER", ...)` quedaría silenciosamente
    tapado por el secret real y estos tests medirían otra cosa. Se reemplaza `get_secret` en el
    módulo bajo test por una versión que sólo mira el entorno, para que el resultado sea el mismo
    en el host, en CI y dentro del contenedor.
    """

    def _get_secret_desde_entorno(secret_name: str, env_var: str | None = None, default: str = "") -> str:
        return os.getenv(env_var or secret_name, default)

    monkeypatch.setattr(prov_config, "get_secret", _get_secret_desde_entorno)


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
