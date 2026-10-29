# Nombre de archivo: test_web_cromo_inventario.py
# Ubicación de archivo: tests/test_web_cromo_inventario.py
# Descripción: Pruebas del endpoint de inventario de cables Cromo (auth, búsqueda, paginación), sin red ni DB real

from __future__ import annotations

from typing import Any, Optional

from fastapi.testclient import TestClient  # type: ignore

from tests.soporte_login import connect_user_ok, fake_async_session_local, login
from web.app.main import app


class _ResultadoFake:
    def __init__(self, escalar: Any = None, filas: Optional[list[tuple]] = None) -> None:
        self._escalar = escalar
        self._filas = filas or []

    def scalar_one(self):
        return self._escalar

    def all(self):
        return self._filas


class _SesionFake:
    def __init__(self, total: int = 0, filas: Optional[list[tuple]] = None) -> None:
        self._total = total
        self._filas = filas or []

    async def execute(self, stmt: Any, params: Optional[dict] = None) -> _ResultadoFake:
        if "SELECT count(*)" in str(stmt):
            return _ResultadoFake(escalar=self._total)
        return _ResultadoFake(filas=self._filas)


_FILA_CABLE = (
    51, "Cable Troncal 1", "72-BRUG", 72, "Troncal", "SBASE", "Botella A", "Botella B", True, 3,
)


def test_inventario_cables_requiere_autenticacion():
    client = TestClient(app)
    res = client.get("/api/infra/cromo/cables")
    assert res.status_code == 401


def test_inventario_cables_no_requiere_admin(monkeypatch):
    """Consulta de sólo lectura, mismo criterio que el verificador — alcanza con estar autenticado."""
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", connect_user_ok())
    sesion = _SesionFake(total=1, filas=[_FILA_CABLE])
    monkeypatch.setattr("db.session.AsyncSessionLocal", fake_async_session_local(sesion))

    client = TestClient(app)
    login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/cables")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert len(body["cables"]) == 1
    assert body["cables"][0]["nombre"] == "Cable Troncal 1"
    assert body["cables"][0]["cantidad_servicios"] == 3


def test_inventario_cables_sin_resultados(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", connect_user_ok())
    monkeypatch.setattr("db.session.AsyncSessionLocal", fake_async_session_local(_SesionFake(total=0, filas=[])))

    client = TestClient(app)
    login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/cables?q=no-existe")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 0
    assert body["cables"] == []


def test_inventario_cables_limit_acotado_a_200(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", connect_user_ok())
    sesion = _SesionFake(total=0, filas=[])
    monkeypatch.setattr("db.session.AsyncSessionLocal", fake_async_session_local(sesion))

    client = TestClient(app)
    login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/cables?limit=9999")
    assert res.status_code == 200
    assert res.json()["limit"] == 200


def test_inventario_cables_query_params_pasan_a_buscar_cables(monkeypatch):
    from web.app import main as web_main
    from core.services.cromo import inventario as cromo_inventario

    monkeypatch.setattr(web_main.psycopg, "connect", connect_user_ok())
    monkeypatch.setattr("db.session.AsyncSessionLocal", fake_async_session_local(_SesionFake()))

    llamada = {}

    async def _buscar_cables_fake(sesion, **kwargs):
        llamada.update(kwargs)
        return cromo_inventario.ResultadoBusquedaCables(total=0, limit=kwargs["limit"], offset=kwargs["offset"], cables=[])

    monkeypatch.setattr(cromo_inventario, "buscar_cables", _buscar_cables_fake)

    client = TestClient(app)
    login(client, "user", "userpass")

    res = client.get(
        "/api/infra/cromo/cables"
        "?q=troncal&jerarquia=Troncal&propietario=SBASE&vigente=true"
        "&n_id=51&botella=Botella&servicio=1234&limit=10&offset=5"
    )

    assert res.status_code == 200
    assert llamada == {
        "q": "troncal", "jerarquia": "Troncal", "propietario": "SBASE", "vigente": True,
        "n_id": 51, "botella": "Botella", "servicio": "1234", "limit": 10, "offset": 5,
    }
