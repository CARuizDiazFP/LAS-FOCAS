# Nombre de archivo: test_cromo_tracking_cache.py
# Ubicación de archivo: tests/test_cromo_tracking_cache.py
# Descripción: Pruebas de la lógica de frescura del caché de trackings — parte pura, sin base ni red

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.services.cromo import tracking_cache

AHORA = datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc)


def test_entrada_recien_generada_esta_fresca():
    assert tracking_cache.esta_vencido(AHORA - timedelta(minutes=1), AHORA, 24) is False


def test_entrada_de_hace_23_horas_sigue_fresca():
    assert tracking_cache.esta_vencido(AHORA - timedelta(hours=23), AHORA, 24) is False


def test_entrada_de_hace_25_horas_esta_vencida():
    assert tracking_cache.esta_vencido(AHORA - timedelta(hours=25), AHORA, 24) is True


def test_el_borde_exacto_del_ttl_cuenta_como_vencido():
    """A las 24 h justas la entrada ya no se sirve.

    El criterio es `>=` y no `>` a propósito: ante la duda, regenerar contra Cromo es correcto y
    sólo cuesta tiempo, mientras que servir un tracking vencido entrega información equivocada.
    """
    assert tracking_cache.esta_vencido(AHORA - timedelta(hours=24), AHORA, 24) is True


def test_entrada_sin_fecha_se_trata_como_vencida():
    assert tracking_cache.esta_vencido(None, AHORA, 24) is True


def test_fecha_ingenua_se_interpreta_como_utc_y_no_revienta():
    """Una fecha sin tzinfo no puede tumbar la descarga con un TypeError.

    Postgres devuelve `timestamptz`, pero un objeto armado a mano (test, backfill, fixture) puede
    venir ingenuo; compararlo crudo contra un `ahora` con tz explota.
    """
    ingenua = (AHORA - timedelta(hours=1)).replace(tzinfo=None)
    assert tracking_cache.esta_vencido(ingenua, AHORA, 24) is False


def test_ttl_por_defecto_es_24_horas(monkeypatch):
    monkeypatch.delenv("CROMO_TRACKING_CACHE_TTL_HORAS", raising=False)
    assert tracking_cache.ttl_horas() == pytest.approx(24.0)


def test_ttl_se_puede_ajustar_por_entorno(monkeypatch):
    monkeypatch.setenv("CROMO_TRACKING_CACHE_TTL_HORAS", "0.5")
    assert tracking_cache.ttl_horas() == pytest.approx(0.5)


@pytest.mark.parametrize("valor", ["", "   "])
def test_ttl_vacio_cae_al_default(monkeypatch, valor):
    monkeypatch.setenv("CROMO_TRACKING_CACHE_TTL_HORAS", valor)
    assert tracking_cache.ttl_horas() == pytest.approx(24.0)


@pytest.mark.parametrize("valor", ["veinticuatro", "0", "-3"])
def test_ttl_invalido_no_rompe_la_descarga_y_cae_al_default(monkeypatch, valor):
    """Un caché mal configurado nunca debe impedir bajar el tracking."""
    monkeypatch.setenv("CROMO_TRACKING_CACHE_TTL_HORAS", valor)
    assert tracking_cache.ttl_horas() == pytest.approx(24.0)
