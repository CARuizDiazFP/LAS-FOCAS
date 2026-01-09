# Nombre de archivo: test_infra_search.py
# Ubicación de archivo: tests/test_infra_search.py
# Descripción: Tests para el endpoint de búsqueda avanzada de infraestructura

"""Tests para POST /api/infra/search - Búsqueda avanzada de cámaras."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.app.main import app
from api.api_app.routes.infra import (
    FilterField,
    FilterOperator,
    SearchFilter,
    SearchRequest,
    _apply_text_filter,
    _camara_matches_filter,
)
from db.models.infra import Camara, CamaraEstado, CamaraOrigenDatos

client = TestClient(app)


# ──────────────────────────────────────────────────────────────────────────────
# Tests unitarios para funciones auxiliares
# ──────────────────────────────────────────────────────────────────────────────


class TestApplyTextFilter:
    """Tests para la función _apply_text_filter."""

    def test_eq_exact_match(self) -> None:
        assert _apply_text_filter("test", FilterOperator.EQ, "TEST") is True
        assert _apply_text_filter("test", FilterOperator.EQ, "Test") is True
        assert _apply_text_filter("test", FilterOperator.EQ, "test") is True

    def test_eq_no_match(self) -> None:
        assert _apply_text_filter("test", FilterOperator.EQ, "testing") is False
        assert _apply_text_filter("test", FilterOperator.EQ, "other") is False

    def test_contains_match(self) -> None:
        assert _apply_text_filter("riv", FilterOperator.CONTAINS, "Av. Rivadavia 1500") is True
        assert _apply_text_filter("RIVADAVIA", FilterOperator.CONTAINS, "av. rivadavia 1500") is True

    def test_contains_no_match(self) -> None:
        assert _apply_text_filter("florida", FilterOperator.CONTAINS, "Av. Rivadavia 1500") is False

    def test_starts_with_match(self) -> None:
        assert _apply_text_filter("av.", FilterOperator.STARTS_WITH, "Av. Corrientes 1234") is True
        assert _apply_text_filter("AV", FilterOperator.STARTS_WITH, "av. corrientes") is True

    def test_starts_with_no_match(self) -> None:
        assert _apply_text_filter("calle", FilterOperator.STARTS_WITH, "Av. Corrientes") is False

    def test_ends_with_match(self) -> None:
        assert _apply_text_filter("1234", FilterOperator.ENDS_WITH, "Av. Corrientes 1234") is True

    def test_ends_with_no_match(self) -> None:
        assert _apply_text_filter("5678", FilterOperator.ENDS_WITH, "Av. Corrientes 1234") is False

    def test_in_operator_with_list(self) -> None:
        assert _apply_text_filter(["libre", "ocupada"], FilterOperator.IN, "LIBRE") is True
        assert _apply_text_filter(["libre", "ocupada"], FilterOperator.IN, "BANEADA") is False

    def test_none_value_returns_false(self) -> None:
        assert _apply_text_filter("test", FilterOperator.EQ, None) is False
        assert _apply_text_filter("test", FilterOperator.CONTAINS, None) is False


class TestCamaraMatchesFilter:
    """Tests para la función _camara_matches_filter."""

    @pytest.fixture
    def mock_camara(self) -> MagicMock:
        """Crea un mock de Camara para testing."""
        camara = MagicMock(spec=Camara)
        camara.nombre = "Av. Rivadavia 1500"
        camara.direccion = "Caballito, CABA"
        camara.estado = CamaraEstado.OCUPADA
        camara.origen_datos = CamaraOrigenDatos.TRACKING
        return camara

    def test_address_filter_matches_nombre(self, mock_camara: MagicMock) -> None:
        flt = SearchFilter(field=FilterField.ADDRESS, operator=FilterOperator.CONTAINS, value="rivadavia")
        assert _camara_matches_filter(mock_camara, flt, [], []) is True

    def test_address_filter_matches_direccion(self, mock_camara: MagicMock) -> None:
        flt = SearchFilter(field=FilterField.ADDRESS, operator=FilterOperator.CONTAINS, value="caballito")
        assert _camara_matches_filter(mock_camara, flt, [], []) is True

    def test_address_filter_no_match(self, mock_camara: MagicMock) -> None:
        flt = SearchFilter(field=FilterField.ADDRESS, operator=FilterOperator.CONTAINS, value="florida")
        assert _camara_matches_filter(mock_camara, flt, [], []) is False

    def test_status_filter_eq(self, mock_camara: MagicMock) -> None:
        flt = SearchFilter(field=FilterField.STATUS, operator=FilterOperator.EQ, value="OCUPADA")
        assert _camara_matches_filter(mock_camara, flt, [], []) is True

        flt_libre = SearchFilter(field=FilterField.STATUS, operator=FilterOperator.EQ, value="LIBRE")
        assert _camara_matches_filter(mock_camara, flt_libre, [], []) is False

    def test_status_filter_in(self, mock_camara: MagicMock) -> None:
        flt = SearchFilter(field=FilterField.STATUS, operator=FilterOperator.IN, value=["OCUPADA", "BANEADA"])
        assert _camara_matches_filter(mock_camara, flt, [], []) is True

        flt_no_match = SearchFilter(field=FilterField.STATUS, operator=FilterOperator.IN, value=["LIBRE", "DETECTADA"])
        assert _camara_matches_filter(mock_camara, flt_no_match, [], []) is False

    def test_service_filter_matches(self, mock_camara: MagicMock) -> None:
        flt = SearchFilter(field=FilterField.SERVICE_ID, operator=FilterOperator.EQ, value="111995")
        assert _camara_matches_filter(mock_camara, flt, ["111995", "112001"], []) is True

    def test_service_filter_contains(self, mock_camara: MagicMock) -> None:
        flt = SearchFilter(field=FilterField.SERVICE_ID, operator=FilterOperator.CONTAINS, value="1119")
        assert _camara_matches_filter(mock_camara, flt, ["111995", "112001"], []) is True

    def test_service_filter_no_match(self, mock_camara: MagicMock) -> None:
        flt = SearchFilter(field=FilterField.SERVICE_ID, operator=FilterOperator.EQ, value="999999")
        assert _camara_matches_filter(mock_camara, flt, ["111995", "112001"], []) is False

    def test_cable_filter_matches(self, mock_camara: MagicMock) -> None:
        flt = SearchFilter(field=FilterField.CABLE, operator=FilterOperator.CONTAINS, value="cable-1")
        assert _camara_matches_filter(mock_camara, flt, [], ["CABLE-1-NORTE", "CABLE-2-SUR"]) is True

    def test_origen_filter_matches(self, mock_camara: MagicMock) -> None:
        flt = SearchFilter(field=FilterField.ORIGEN, operator=FilterOperator.EQ, value="TRACKING")
        assert _camara_matches_filter(mock_camara, flt, [], []) is True


# ──────────────────────────────────────────────────────────────────────────────
# Tests de integración para el endpoint
# ──────────────────────────────────────────────────────────────────────────────


class TestSearchEndpoint:
    """Tests de integración para POST /api/infra/search.

    Nota: estos tests validan la estructura del request/response y las validaciones
    de Pydantic. Los tests que requieren base de datos están marcados con
    pytest.mark.skipif para entornos sin DB disponible.
    """

    def test_invalid_field_returns_422(self) -> None:
        """Campo de filtro inválido debe retornar 422."""
        response = client.post(
            "/api/infra/search",
            json={
                "filters": [{"field": "invalid_field", "operator": "eq", "value": "test"}],
            },
        )
        assert response.status_code == 422

    def test_too_many_filters_returns_422(self) -> None:
        """Más de 10 filtros debe retornar 422."""
        filters = [{"field": "address", "operator": "contains", "value": f"test{i}"} for i in range(11)]
        response = client.post("/api/infra/search", json={"filters": filters})
        assert response.status_code == 422

    def test_limit_max_enforced(self) -> None:
        """El límite máximo de 500 debe ser respetado."""
        response = client.post(
            "/api/infra/search",
            json={"filters": [], "limit": 1000},
        )
        # Pydantic validation debería rechazarlo
        assert response.status_code == 422

    def test_invalid_operator_returns_422(self) -> None:
        """Operador inválido debe retornar 422."""
        response = client.post(
            "/api/infra/search",
            json={
                "filters": [{"field": "address", "operator": "invalid_op", "value": "test"}],
            },
        )
        assert response.status_code == 422

    def test_missing_field_returns_422(self) -> None:
        """Filtro sin campo debe retornar 422."""
        response = client.post(
            "/api/infra/search",
            json={
                "filters": [{"operator": "eq", "value": "test"}],
            },
        )
        assert response.status_code == 422

    def test_missing_value_returns_422(self) -> None:
        """Filtro sin valor debe retornar 422."""
        response = client.post(
            "/api/infra/search",
            json={
                "filters": [{"field": "address", "operator": "eq"}],
            },
        )
        assert response.status_code == 422

    def test_negative_offset_returns_422(self) -> None:
        """Offset negativo debe retornar 422."""
        response = client.post(
            "/api/infra/search",
            json={"filters": [], "limit": 10, "offset": -1},
        )
        assert response.status_code == 422

    def test_zero_limit_returns_422(self) -> None:
        """Límite cero debe retornar 422."""
        response = client.post(
            "/api/infra/search",
            json={"filters": [], "limit": 0},
        )
        assert response.status_code == 422


class TestSearchModels:
    """Tests para los modelos Pydantic de búsqueda."""

    def test_search_filter_default_operator(self) -> None:
        """El operador por defecto debería ser CONTAINS."""
        flt = SearchFilter(field=FilterField.ADDRESS, value="test")
        assert flt.operator == FilterOperator.CONTAINS

    def test_search_request_defaults(self) -> None:
        """SearchRequest debería tener valores por defecto correctos."""
        req = SearchRequest()
        assert req.filters == []
        assert req.limit == 100
        assert req.offset == 0

    def test_filter_field_values(self) -> None:
        """Verificar los valores del enum FilterField."""
        assert FilterField.SERVICE_ID.value == "service_id"
        assert FilterField.ADDRESS.value == "address"
        assert FilterField.STATUS.value == "status"
        assert FilterField.CABLE.value == "cable"
        assert FilterField.ORIGEN.value == "origen"

    def test_filter_operator_values(self) -> None:
        """Verificar los valores del enum FilterOperator."""
        assert FilterOperator.EQ.value == "eq"
        assert FilterOperator.CONTAINS.value == "contains"
        assert FilterOperator.STARTS_WITH.value == "starts_with"
        assert FilterOperator.ENDS_WITH.value == "ends_with"
        assert FilterOperator.IN.value == "in"
