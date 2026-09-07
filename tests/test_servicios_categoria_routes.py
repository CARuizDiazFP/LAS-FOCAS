# Nombre de archivo: test_servicios_categoria_routes.py
# Ubicación de archivo: tests/test_servicios_categoria_routes.py
# Descripción: Tests HTTP de los endpoints de categoría (individual y masivo) del router de servicios

from __future__ import annotations

from typing import AsyncGenerator
from unittest.mock import MagicMock, patch

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
        self.refreshed = False

    async def get(self, _model, _id):
        return self._servicio

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, _obj) -> None:
        self.refreshed = True


def _make_servicio(**overrides) -> MagicMock:
    defaults = dict(
        id=1,
        servicio_id="12345",
        numero_primer_servicio="12345",
        nombre_cliente="Cliente Test",
        numero_linea=None,
        tipo_servicio=None,
        sla_prometido=None,
        direccion=None,
        localidad=None,
        provincia=None,
        direccion_2=None,
        estado_servicio="ACTIVO",
        categoria=6,
        origen_datos=ServicioOrigenDatos.MANUAL,
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


class TestPatchCategoriaIndividual:
    def teardown_method(self) -> None:
        app.dependency_overrides.pop(get_async_db, None)

    def test_actualiza_y_devuelve_el_item(self) -> None:
        svc = _make_servicio(categoria=6)
        app.dependency_overrides[get_async_db] = _override_con(_FakeAsyncSession(svc))

        response = client.patch("/servicios/1/categoria", json={"categoria": 3}, headers=API_HEADERS)

        assert response.status_code == 200
        body = response.json()
        assert body["categoria"] == 3
        assert svc.categoria == 3

    def test_categoria_fuera_de_rango_devuelve_400_sin_tocar_la_db(self) -> None:
        svc = _make_servicio()
        app.dependency_overrides[get_async_db] = _override_con(_FakeAsyncSession(svc))

        response = client.patch("/servicios/1/categoria", json={"categoria": 9}, headers=API_HEADERS)

        assert response.status_code == 400
        assert svc.categoria == 6  # sin cambios

    def test_servicio_inexistente_devuelve_404(self) -> None:
        app.dependency_overrides[get_async_db] = _override_con(_FakeAsyncSession(None))

        response = client.patch("/servicios/999/categoria", json={"categoria": 2}, headers=API_HEADERS)

        assert response.status_code == 404

    def test_sin_api_key_devuelve_401_o_403(self) -> None:
        response = client.patch("/servicios/1/categoria", json={"categoria": 2})

        assert response.status_code in (401, 403)


class TestPatchCategoriaMasiva:
    @patch("api.app.routes.servicios.SessionLocal")
    def test_actualiza_lote_y_reporta_no_encontrados(self, mock_session_local: MagicMock) -> None:
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = [(1,), (2,)]
        session.query.return_value.filter.return_value.update.return_value = 2
        mock_session_local.return_value.__enter__.return_value = session

        response = client.patch(
            "/servicios/bulk-categoria",
            json={"servicio_ids": [1, 2, 99], "categoria": 5},
            headers=API_HEADERS,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["categoria_nueva"] == 5
        assert body["actualizados"] == 2
        assert body["no_encontrados"] == [99]
        session.commit.assert_called_once()

    @patch("api.app.routes.servicios.SessionLocal")
    def test_lista_vacia_devuelve_400_sin_abrir_sesion(self, mock_session_local: MagicMock) -> None:
        response = client.patch(
            "/servicios/bulk-categoria",
            json={"servicio_ids": [], "categoria": 3},
            headers=API_HEADERS,
        )

        assert response.status_code == 400

    @patch("api.app.routes.servicios.SessionLocal")
    def test_categoria_invalida_devuelve_400(self, mock_session_local: MagicMock) -> None:
        session = MagicMock()
        mock_session_local.return_value.__enter__.return_value = session

        response = client.patch(
            "/servicios/bulk-categoria",
            json={"servicio_ids": [1, 2], "categoria": -1},
            headers=API_HEADERS,
        )

        assert response.status_code == 400
        session.commit.assert_not_called()


class TestSearchServiciosCategoriaFiltro:
    def test_categoria_invalida_en_query_devuelve_400(self) -> None:
        response = client.get("/servicios/search", params={"categoria": "no-es-numero"}, headers=API_HEADERS)

        assert response.status_code == 400
