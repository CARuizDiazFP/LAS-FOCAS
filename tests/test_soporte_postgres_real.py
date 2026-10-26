# Nombre de archivo: test_soporte_postgres_real.py
# Ubicación de archivo: tests/test_soporte_postgres_real.py
# Descripción: Tests del guard que impide correr los tests *_real_db contra una DB fuera de la allowlist de dev/test

from __future__ import annotations

import pytest

from tests import soporte_postgres_real as soporte


@pytest.fixture
def sin_ci(monkeypatch):
    # Con CI=true el guard corta antes de conectar; acá interesa el camino local.
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv(soporte.VARIABLE_DBS_EXTRA, raising=False)


def _con_db(monkeypatch, nombre_db):
    monkeypatch.setattr(soporte, "db_real_conectada", lambda: nombre_db)


def test_db_de_dev_corre(sin_ci, monkeypatch):
    _con_db(monkeypatch, "focas_dev")
    assert soporte._condicion_y_razon() == (False, "")


def test_db_de_produccion_se_saltea(sin_ci, monkeypatch):
    _con_db(monkeypatch, "FOCALDB")
    saltear, razon = soporte._condicion_y_razon()
    assert saltear is True
    assert "'FOCALDB'" in razon
    assert "allowlist" in razon


def test_nombre_fuera_de_allowlist_se_saltea(sin_ci, monkeypatch):
    _con_db(monkeypatch, "cualquier_otra")
    saltear, _ = soporte._condicion_y_razon()
    assert saltear is True


def test_comparacion_exacta_sin_ignorar_mayusculas(sin_ci, monkeypatch):
    # Postgres distingue mayúsculas en nombres de DB citados: "FOCAS_DEV" no es "focas_dev".
    _con_db(monkeypatch, "FOCAS_DEV")
    assert soporte._condicion_y_razon()[0] is True


def test_sin_postgres_se_saltea_con_instrucciones(sin_ci, monkeypatch):
    _con_db(monkeypatch, None)
    saltear, razon = soporte._condicion_y_razon()
    assert saltear is True
    assert soporte.COMO_HABILITARLOS in razon


def test_variable_suma_dbs_a_la_allowlist(sin_ci, monkeypatch):
    monkeypatch.setenv(soporte.VARIABLE_DBS_EXTRA, " ci_efimera , otra_test ")
    _con_db(monkeypatch, "ci_efimera")
    assert soporte._condicion_y_razon() == (False, "")
    assert soporte.dbs_permitidas() >= {"focas_dev", "ci_efimera", "otra_test"}


def test_ci_saltea_sin_intentar_conectar(monkeypatch):
    monkeypatch.setenv("CI", "true")

    def _no_conectar():
        raise AssertionError("con CI=true no debe intentar conectar")

    monkeypatch.setattr(soporte, "db_real_conectada", _no_conectar)
    assert soporte._condicion_y_razon()[0] is True
