# Nombre de archivo: test_flows_builders.py
# Ubicación de archivo: tests/test_flows_builders.py
# Descripción: Pruebas de los builders de respuesta de los flujos del bot

from bot_telegram.flows.repetitividad import build_repetitividad_response
from bot_telegram.flows.sla import build_sla_response


def test_build_sla_response() -> None:
    """Verifica que el builder de SLA contiene el texto esperado."""
    text = build_sla_response()
    assert "📈" in text
    assert "implementación pendiente" in text


def test_build_repetitividad_response() -> None:
    """Verifica que el builder de Repetitividad contiene el texto esperado."""
    text = build_repetitividad_response()
    assert "📊" in text
    assert "implementación pendiente" in text
