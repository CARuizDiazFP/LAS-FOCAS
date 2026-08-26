# Nombre de archivo: test_servicios_ingest_routes.py
# Ubicación de archivo: tests/test_servicios_ingest_routes.py
# Descripción: Tests de integración de la consolidación de identidad dentro de POST /servicios/ingest contra un Postgres real de test

from __future__ import annotations

import io

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from api.app.main import app
from db.session import SessionLocal

API_HEADERS = {"Authorization": "Bearer test-api-key"}


def _excel_bytes(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    return buffer.getvalue()


@pytest.fixture(scope="module")
def client():
    # `with TestClient(app) as client:` (en vez de `TestClient(app)` a nivel de módulo, usado
    # "en frío" por request) mantiene un único blocking portal/event loop mientras dure el bloque.
    # Sin esto, cada llamada suelta del cliente abre su propio loop nuevo y el pool de asyncpg
    # (motor async global, ver db/session.py) intenta reusar una conexión creada en un loop ya
    # cerrado -> `RuntimeError: ... attached to a different loop`. Se reproduce incluso con 2 GET
    # simples sin tocar código de este endpoint. Scope "module" (no función) porque el pool asyncpg
    # es un singleton a nivel de proceso (`db.session.async_engine`): si cada test abriera y cerrara
    # su propio portal, el segundo test heredaría en el pool una conexión atada al loop ya cerrado
    # del primero y volvería a romper — un solo loop para todo el archivo evita la colisión.
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _limpiar_servicios_de_test():
    yield
    with SessionLocal() as session:
        session.execute(text("DELETE FROM app.servicios WHERE numero_primer_servicio IN ('900001', '900002')"))
        session.commit()


def test_ingest_calcula_servicio_id_como_el_id_mas_alto_de_la_cadena(client: TestClient) -> None:
    df = pd.DataFrame(
        {
            "Número Primer Servicio": ["900001"],
            "Número Línea": ["900050"],
            "Línea Upgrade (De)": ["900010"],
            "Tipo Servicio": ["TLS"],
            "Nivel Cliente": ["4"],
            "Estado Servicio": ["Activo"],
        }
    )

    response = client.post(
        "/servicios/ingest",
        files={"file": ("servicios.xlsx", _excel_bytes(df), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=API_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["inserted"] == 1

    detail = client.get("/servicios/detail", params={"id": "900001"}, headers=API_HEADERS)
    body = detail.json()["servicio"]
    assert body["numero_linea"] == "900050"
    assert set(body["alias_ids"]) == {"900001", "900010"}
    assert body["categoria"] == 4
    assert body["es_verificable"] is True


def test_ingest_no_pisa_servicio_id_no_numerico_de_tracking(client: TestClient) -> None:
    with SessionLocal() as session:
        session.execute(
            text(
                "INSERT INTO app.servicios (servicio_id, numero_primer_servicio, numero_linea, estado_servicio) "
                "VALUES ('TRK-900002', '900002', '900002', 'DESCONOCIDO')"
            )
        )
        session.commit()

    df = pd.DataFrame(
        {
            "Número Primer Servicio": ["900002"],
            "Número Línea": ["900070"],
            "Tipo Servicio": ["INT"],
        }
    )

    response = client.post(
        "/servicios/ingest",
        files={"file": ("servicios.xlsx", _excel_bytes(df), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=API_HEADERS,
    )
    assert response.status_code == 200

    detail = client.get("/servicios/detail", params={"id": "900002"}, headers=API_HEADERS)
    body = detail.json()["servicio"]
    assert body["numero_linea"] == "900070"
    assert "TRK-900002" not in body["alias_ids"]  # servicio_id de tracking no se toca
