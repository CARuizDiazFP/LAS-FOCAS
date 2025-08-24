# Nombre de archivo: test_rate_limit_api.py
# Ubicación de archivo: tests/test_rate_limit_api.py
# Descripción: Verifica la limitación de tasa en la API principal

from pathlib import Path
import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'api'))
os.environ['API_RATE_LIMIT'] = '2/minute'

from app.main import create_app

def get_client() -> TestClient:
    app = create_app()
    return TestClient(app)

def test_api_rate_limit_por_clave() -> None:
    """Tras dos solicitudes con la misma clave, la tercera es rechazada."""
    client = get_client()
    headers = {'X-API-Key': 'alpha'}
    assert client.get('/health', headers=headers).status_code == 200
    assert client.get('/health', headers=headers).status_code == 200
    assert client.get('/health', headers=headers).status_code == 429

def test_api_rate_limit_independiente() -> None:
    """Superar el límite con una clave no afecta a otra."""
    client = get_client()
    headers_a = {'X-API-Key': 'alpha'}
    headers_b = {'X-API-Key': 'beta'}
    assert client.get('/health', headers=headers_a).status_code == 200
    assert client.get('/health', headers=headers_a).status_code == 200
    assert client.get('/health', headers=headers_a).status_code == 429
    assert client.get('/health', headers=headers_b).status_code == 200
