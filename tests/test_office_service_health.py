# Nombre de archivo: test_office_service_health.py
# Ubicación de archivo: tests/test_office_service_health.py
# Descripción: Pruebas del endpoint de salud del microservicio LibreOffice/UNO

from fastapi.testclient import TestClient

from office_service.app.config import get_settings
from office_service.app.main import create_app


def test_health_when_uno_disabled(monkeypatch) -> None:
    get_settings.cache_clear()  # type: ignore[attr-defined]
    monkeypatch.setenv("OFFICE_ENABLE_UNO", "false")
    app = create_app()
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "office-service"
    assert payload["uno"]["available"] is False
    assert "deshabilitado" in payload["uno"]["message"].lower()


def test_health_default_configuration(monkeypatch) -> None:
    get_settings.cache_clear()  # type: ignore[attr-defined]
    monkeypatch.delenv("OFFICE_ENABLE_UNO", raising=False)
    app = create_app()
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "office-service"
    assert "uno" in payload
    assert "message" in payload["uno"]
