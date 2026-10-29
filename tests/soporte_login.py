# Nombre de archivo: soporte_login.py
# Ubicación de archivo: tests/soporte_login.py
# Descripción: Login real de la SPA en tests (psycopg falso + POST /api/auth/login) y AsyncSessionLocal falso

"""Helpers compartidos por los tests web que hacen **login real** (cookie de sesión + token CSRF).

Antes vivían copiados en ~20 archivos `tests/test_web_*.py` (`_Cur`, `_Conn`, `_connect_ok`,
`_connect_user_ok`, `_connect_admin_ok`, `_login`, `_fake_async_session_local`).

- `connect_ok(password, role)` y sus atajos devuelven un reemplazo de `psycopg.connect` cuya consulta
  de usuario devuelve `(hash_password(password), role)`. El test lo instala con
  `monkeypatch.setattr(psycopg, "connect", connect_user_ok())` y después llama a `login(...)`.
- `login_con_rol` hace las dos cosas y además exige 200 y `ok: true`.

Quién NO usa esto, a propósito:
- Los tests que sólo necesitan un usuario en sesión usan `con_sesion` (`tests/soporte_sesion.py`).
- Los tests de CSRF usan la fixture `csrf_real` + este login real: con `con_sesion` la cookie no
  tiene `username` y `requiere_csrf` no decide (responde 401 antes).
- `tests/test_web_admin.py` y `tests/test_web_baneos.py` conservan su propio `_Conn`: el de admin
  registra el SQL y responde distinto según la consulta.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi.testclient import TestClient

from core.password import hash_password


class CursorFila:
    """Cursor falso de psycopg: `fetchone()` devuelve siempre la misma fila."""

    def __init__(self, row: Optional[tuple[Any, ...]] = None) -> None:
        self._row = row

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params=None) -> None:
        return None

    def fetchone(self):
        return self._row


class ConexionFila:
    """Conexión falsa de psycopg con un único `CursorFila`."""

    def __init__(self, row: Optional[tuple[Any, ...]]) -> None:
        self.cur = CursorFila(row)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cur

    def commit(self) -> None:
        return None


def connect_ok(password: str, role: str) -> Callable[[str], ConexionFila]:
    """Reemplazo de `psycopg.connect` para un usuario `role` con contraseña `password`."""
    pwd_hash = hash_password(password)

    def _connect(dsn: str) -> ConexionFila:
        return ConexionFila((pwd_hash, role))

    return _connect


def connect_user_ok(password: str = "userpass") -> Callable[[str], ConexionFila]:
    return connect_ok(password, "user")


def connect_admin_ok(password: str = "adminpass") -> Callable[[str], ConexionFila]:
    return connect_ok(password, "admin")


def login(client: TestClient, username: str, password: str) -> str:
    """Login real contra `/api/auth/login` (con `psycopg.connect` ya parcheado); devuelve el CSRF."""
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    return res.json()["csrf"]


def login_con_rol(client: TestClient, monkeypatch, *, role: str = "user", password: str = "secret") -> str:
    """Parchea `psycopg.connect` para `role`, hace login (exige 200 y `ok: true`) y devuelve el CSRF."""
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", connect_ok(password, role))
    response = client.post("/api/auth/login", json={"username": role, "password": password})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    return data["csrf"]


def fake_async_session_local(sesion: Any):
    """Reemplazo de `AsyncSessionLocal`: `async with AsyncSessionLocal() as s` entrega `sesion`."""

    class _CM:
        async def __aenter__(self):
            return sesion

        async def __aexit__(self, *a):
            return False

    def factory():
        return _CM()

    return factory
