# Nombre de archivo: test_flows_builders.py
# Ubicación de archivo: tests/test_flows_builders.py
# Descripción: Pruebas de los builders de respuesta de los flujos del bot

from bot_telegram.flows.sla import build_sla_response


def test_build_sla_response() -> None:
    """Verifica que el builder de SLA contiene el texto esperado."""
    text = build_sla_response()
    assert "📈" in text
    assert "implementación pendiente" in text
