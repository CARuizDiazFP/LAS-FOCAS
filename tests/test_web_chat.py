# Nombre de archivo: test_web_chat.py
# Ubicación de archivo: tests/test_web_chat.py
# Descripción: Pruebas básicas del endpoint del chat del servicio Web

from pathlib import Path
import sys

# Permite importar app.web sin necesidad de instalar el paquete
sys.path.append(str(Path(__file__).resolve().parents[1] / "web"))

from fastapi.testclient import TestClient
from web_app.main import app

client = TestClient(app)


def test_health_ok() -> None:
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_chat_message_returns_json(monkeypatch) -> None:
    # Mock del clasificador para evitar IO
    async def _fake_classify(text: str):
        # Simula respuesta antigua para endpoint deprecado; el nuevo endpoint de analyze se consume internamente.
        from web_app.main import IntentResponse
        return IntentResponse(intent="Consulta", confidence=0.9, provider="heuristic", normalized_text=text)

    from web_app import main as web_main
    web_main.classify_text = _fake_classify

    res = client.post("/api/chat/message", data={"text": "¿Cómo genero el SLA?"})
    assert res.status_code == 200
    data = res.json()
    required = {"reply", "intention_raw", "intention", "confidence", "provider"}
    assert required.issubset(data.keys())
    assert data["intention_raw"] in ("Consulta", "Acción", "Otros")
    assert data["intention"] in ("Consulta/Generico", "Solicitud de acción", "Otros")
