# Nombre de archivo: test_servicios_verificable_routes.py
# Ubicación de archivo: tests/test_servicios_verificable_routes.py
# Descripción: Tests HTTP del endpoint de corrección manual de es_verificable

from __future__ import annotations

from typing import AsyncGenerator
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from api.app.main import app
from db.models.infra import Servicio, ServicioOrigenDatos
from db.session import get_async_db

client = TestClient(app)
API_HEADERS = {"Authorization": "Bearer test-api-key"}


class _FakeAsyncSession:
    def __init__(self, servicio: Servicio | None) -> None:
        self._servicio = servicio
        self.committed = False

    async def get(self, _model, _id):
        return self._servicio

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, _obj) -> None:
        pass


def _make_servicio(**overrides) -> MagicMock:
    defaults = dict(
        id=1,
        servicio_id="12345",
        numero_primer_servicio="12345",
        nombre_cliente="Cliente Test",
        numero_linea=None,
        tipo_servicio="ATI",
        sla_prometido=None,
        direccion=None,
        localidad=None,
        provincia=None,
        direccion_2=None,
        estado_servicio="ACTIVO",
        categoria=6,
        origen_datos=ServicioOrigenDatos.MANUAL,
        es_verificable=False,
        es_verificable_override=None,
        alias_ids=[],
    )
    defaults.update(overrides)
    svc = MagicMock(spec=Servicio)
    for key, value in defaults.items():
        setattr(svc, key, value)
    return svc


def _override_con(fake_session: _FakeAsyncSession):
    async def _dep() -> AsyncGenerator[_FakeAsyncSession, None]:
        yield fake_session

    return _dep


class TestPatchVerificable:
    def teardown_method(self) -> None:
        app.dependency_overrides.pop(get_async_db, None)

    def test_marca_override_manual_y_lo_refleja_en_es_verificable(self) -> None:
        svc = _make_servicio(es_verificable=False, es_verificable_override=None)
        app.dependency_overrides[get_async_db] = _override_con(_FakeAsyncSession(svc))

        response = client.patch("/servicios/1/verificable", json={"es_verificable": True}, headers=API_HEADERS)

        assert response.status_code == 200
        body = response.json()
        assert body["es_verificable"] is True
        assert body["es_verificable_override"] is True
        assert svc.es_verificable_override is True

    def test_servicio_inexistente_devuelve_404(self) -> None:
        app.dependency_overrides[get_async_db] = _override_con(_FakeAsyncSession(None))

        response = client.patch("/servicios/999/verificable", json={"es_verificable": False}, headers=API_HEADERS)

        assert response.status_code == 404

    def test_sin_api_key_devuelve_401_o_403(self) -> None:
        response = client.patch("/servicios/1/verificable", json={"es_verificable": True})

        assert response.status_code in (401, 403)
