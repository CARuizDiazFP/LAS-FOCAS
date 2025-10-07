# Nombre de archivo: test_web_chat_history_metrics.py
# Ubicación de archivo: tests/test_web_chat_history_metrics.py
# Descripción: Pruebas de endpoints /api/chat/history y /api/chat/metrics y conversation_id

from pathlib import Path
import sys
import os

os.environ.setdefault("TESTING", "true")

sys.path.append(str(Path(__file__).resolve().parents[1] / "web"))

from fastapi.testclient import TestClient  # type: ignore
from web_app.main import app, INTENT_COUNTER  # type: ignore

client = TestClient(app)


def test_chat_history_and_metrics(monkeypatch):
    # Forzar usuario autenticado
    from web_app import main as web_main
    monkeypatch.setattr(web_main, "get_current_user", lambda request: "tester")

    # Mocks de persistencia en memoria
    messages: list[dict] = []
    conv_id = 999

    class DummyConn:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
    def dummy_connect(dsn):  # noqa: ARG001
        return DummyConn()
    def dummy_get_or_create(conn, user):  # noqa: ARG001
        return conv_id
    def dummy_insert(conn, conversation_id, tg_user_id, role, text, normalized_text, intent, confidence, provider):  # noqa: D401, ARG001
        messages.append({"role": role, "text": text, "intent": intent, "confidence": confidence, "provider": provider})
    def dummy_get_last(conn, conversation_id, limit=10):  # noqa: ARG001
        return messages[-limit:]

    monkeypatch.setattr(web_main, "psycopg", type("_P", (), {"connect": dummy_connect}))
    monkeypatch.setattr(web_main, "get_or_create_conversation_for_web_user", dummy_get_or_create)
    monkeypatch.setattr(web_main, "insert_message", dummy_insert)
    monkeypatch.setattr(web_main, "get_last_messages", dummy_get_last)

    # Limpia métricas previas para aislamiento
    for k in INTENT_COUNTER.keys():
        INTENT_COUNTER[k] = 0

    # Enviar dos mensajes
    r1 = client.post("/api/chat/message", data={"text": "hola"})
    assert r1.status_code == 200
    data1 = r1.json()
    assert "conversation_id" in data1
    conv_id_resp = data1["conversation_id"]
    assert data1["history"]  # primer turno ya retorna algo (incluye user y assistant)

    r2 = client.post("/api/chat/message", data={"text": "¿cómo genero el informe de repetitividad?"})
    assert r2.status_code == 200
    data2 = r2.json()
    assert data2["conversation_id"] == conv_id_resp
    assert len(data2["history"]) >= 4  # user/assistant de ambos turnos

    # History endpoint
    h = client.get("/api/chat/history", params={"limit": 10})
    assert h.status_code == 200
    hist_payload = h.json()
    assert hist_payload["conversation_id"] == conv_id_resp
    assert len(hist_payload["messages"]) >= 2

    # Metrics endpoint
    m = client.get("/api/chat/metrics")
    assert m.status_code == 200
    metrics = m.json()["intent_counts"]
    # Al menos una de las intenciones debe haber incrementado
    assert any(v > 0 for v in metrics.values())

    # Repetir mensaje para verificar incremento adicional
    r3 = client.post("/api/chat/message", data={"text": "¿cómo genero el informe de repetitividad?"})
    assert r3.status_code == 200
    m2 = client.get("/api/chat/metrics").json()["intent_counts"]
    # Suma total debe aumentar
    assert sum(m2.values()) > sum(metrics.values())
