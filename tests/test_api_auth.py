# Nombre de archivo: test_api_auth.py
# Ubicación de archivo: tests/test_api_auth.py
# Descripción: Pruebas de autenticación por API key en la API core

from __future__ import annotations

from fastapi.testclient import TestClient

from api.app.main import create_app


def test_health_sigue_publico_sin_credenciales() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200


def test_reports_rechaza_sin_credenciales() -> None:
    client = TestClient(create_app())

    response = client.post("/reports/repetitividad")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_reports_rechaza_api_key_invalida() -> None:
    client = TestClient(create_app())

    response = client.post("/reports/repetitividad", headers={"X-API-Key": "incorrecta"})

    assert response.status_code == 403


def test_reports_acepta_bearer_valido() -> None:
    client = TestClient(create_app())

    response = client.post("/reports/repetitividad", headers={"Authorization": "Bearer test-api-key"})

    assert response.status_code == 422


def test_db_check_queda_protegido() -> None:
    client = TestClient(create_app())

    response = client.get("/db-check")

    assert response.status_code == 401


def test_api_sin_key_configurada_falla_cerrado(monkeypatch) -> None:
    monkeypatch.delenv("LAS_FOCAS_API_KEY", raising=False)
    client = TestClient(create_app())

    response = client.post("/reports/repetitividad")

    assert response.status_code == 503
