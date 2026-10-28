# Nombre de archivo: test_web_chat_history_metrics.py
# Ubicación de archivo: tests/test_web_chat_history_metrics.py
# Descripción: Pruebas de endpoints /api/chat/history y /api/chat/metrics y conversation_id

import os

os.environ.setdefault("TESTING", "true")


from fastapi.testclient import TestClient  # type: ignore
from web.app.main import app  # type: ignore
from web.app.routers.chat import INTENT_COUNTER  # type: ignore

client = TestClient(app)


def test_chat_history_and_metrics(monkeypatch):
    # Forzar usuario autenticado
    from web.app.routers import chat as web_main
    from web.app import comun  # usuario_chat lee la sesión vía comun._require_auth (única fuente)
    monkeypatch.setattr(comun, "_require_auth", lambda request: ("tester", "user"))

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


def test_persist_metrics_escribe_la_copia_de_forma_atomica(monkeypatch, tmp_path):
    """`_persist_metrics` corre en el threadpool con una copia de los contadores; no deja el `.tmp`."""
    from web.app.routers import chat as web_chat

    destino = tmp_path / "intent_metrics.json"
    monkeypatch.setattr(web_chat, "METRICS_PERSIST_PATH", str(destino))

    web_chat._persist_metrics({"Otros": 3})

    assert destino.read_text() == '{"Otros": 3}'
    assert not destino.with_suffix(".tmp").exists()


def test_persist_metrics_sin_permiso_solo_loguea(monkeypatch, tmp_path, caplog):
    """El bug de `/app/data` (root, proceso 1001): un error de escritura nunca rompe el chat."""
    from web.app.routers import chat as web_chat

    monkeypatch.setattr(web_chat, "METRICS_PERSIST_PATH", str(tmp_path / "no-existe" / "m.json"))

    web_chat._persist_metrics({"Otros": 1})

    assert "action=metrics_persist error=" in caplog.text


def _subir_adjunto(monkeypatch, tmp_path, contenido: bytes, limite: int):
    from web.app import comun
    from web.app.routers import chat as web_chat

    monkeypatch.setattr(comun, "_require_auth", lambda request: ("tester", "user"))
    monkeypatch.setattr(web_chat, "UPLOADS_DIR", tmp_path)
    monkeypatch.setattr(web_chat, "MAX_CHAT_UPLOAD_BYTES", limite)
    return client.post("/api/chat/uploads", files={"file": ("datos.csv", contenido, "text/csv")})


def test_upload_del_chat_escribe_el_adjunto(monkeypatch, tmp_path):
    contenido = b"a,b\n" * 300_000  # > 1 chunk de 512 KiB
    r = _subir_adjunto(monkeypatch, tmp_path, contenido, limite=10 * 1024 * 1024)

    assert r.status_code == 200, r.text
    assert r.json()["size"] == len(contenido)
    assert (tmp_path / r.json()["path"]).read_bytes() == contenido


def test_upload_del_chat_excedido_no_crea_archivo(monkeypatch, tmp_path):
    r = _subir_adjunto(monkeypatch, tmp_path, b"x" * 2048, limite=1024)

    assert r.status_code == 413
    assert list(tmp_path.iterdir()) == []
