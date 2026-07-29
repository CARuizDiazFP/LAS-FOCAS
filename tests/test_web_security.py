# Nombre de archivo: test_web_security.py
# Ubicación de archivo: tests/test_web_security.py
# Descripción: Pruebas de hardening del login y cookies de sesión del panel web

from __future__ import annotations

import asyncio

from starlette.middleware.sessions import SessionMiddleware

from web.app import main as web_main


def test_rate_limit_login_no_depende_de_cookie(monkeypatch) -> None:
    monkeypatch.setattr(web_main, "WEB_LOGIN_RATE_LIMIT_MAX", 2)
    monkeypatch.setattr(web_main, "WEB_LOGIN_RATE_LIMIT_WINDOW", 60)
    web_main._LOGIN_ATTEMPTS.clear()
    ip = "192.0.2.10"
    username = "admin"

    assert web_main._login_rate_limit_exceeded(ip, username) is False
    assert web_main._login_rate_limit_exceeded(ip, username) is False
    assert web_main._login_rate_limit_exceeded(ip, username) is True


def test_cookie_sesion_declara_flags_seguridad(monkeypatch) -> None:
    monkeypatch.setattr(web_main, "WEB_SESSION_HTTPS_ONLY", True)
    monkeypatch.setattr(web_main, "WEB_SESSION_MAX_AGE", 3600)

    async def app(scope, receive, send):  # noqa: ANN001
        scope["session"]["username"] = "admin"
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    wrapped = SessionMiddleware(app, **web_main._session_middleware_options())
    messages = []
    received = False

    async def receive():  # noqa: ANN202
        nonlocal received
        if received:
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):  # noqa: ANN001, ANN202
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/login-test",
        "raw_path": b"/login-test",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 443),
    }

    asyncio.run(wrapped(scope, receive, send))
    response_start = next(message for message in messages if message["type"] == "http.response.start")
    headers = {key.lower(): value for key, value in response_start["headers"]}
    cookie = headers[b"set-cookie"].decode("latin-1").lower()

    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "secure" in cookie
