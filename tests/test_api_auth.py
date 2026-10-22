# Nombre de archivo: test_api_auth.py
# Ubicación de archivo: tests/test_api_auth.py
# Descripción: Pruebas de autenticación por API key en la API core

from __future__ import annotations

from fastapi.testclient import TestClient

from db.session import async_engine

from api.app.main import create_app


def test_health_sigue_publico_sin_credenciales() -> None:
    # `/health` hace un SELECT 1 con el engine async global (`db.session.async_engine`). Con un
    # `TestClient` suelto el portal/loop se cierra al terminar la request y la conexión asyncpg
    # queda en el pool singleton atada a ese loop muerto: el siguiente test que use el pool desde
    # otro loop (p. ej. test_servicios_ingest_routes) fallaba con "attached to a different loop".
    # Dentro de `with`, el `dispose()` corre en el mismo loop que creó la conexión y la cierra limpia.
    with TestClient(create_app()) as client:
        response = client.get("/health")
        client.portal.call(async_engine.dispose)

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
