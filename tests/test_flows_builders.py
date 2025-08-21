# Nombre de archivo: test_flows_builders.py
# Ubicación de archivo: tests/test_flows_builders.py
# Descripción: Pruebas de los builders de respuesta de los flujos del bot

from bot_telegram.flows.repetitividad import build_repetitividad_prompt
from bot_telegram.flows.sla import build_sla_response


def test_build_sla_response() -> None:
    """Verifica que el builder de SLA contiene el texto esperado."""
    text = build_sla_response()
    assert "📈" in text
    assert "Excel" in text


def test_build_repetitividad_prompt() -> None:
    """Verifica que el builder de repetitividad solicita correctamente el archivo."""
    text = build_repetitividad_prompt()
    assert ".xlsx" in text
    assert "/cancel" in text
