# Nombre de archivo: test_web_csrf.py
# Ubicación de archivo: tests/test_web_csrf.py
# Descripción: CSRF unificado de la web — inventario de rutas mutantes, 403/éxito por ruta y lectura del body en la dependencia

"""Pruebas de `requiere_csrf` (web/app/dependencias.py).

1. Inventario: toda ruta POST/PUT/PATCH/DELETE de la app web declara la dependencia (salvo
   `RUTAS_SIN_CSRF`, con su motivo). Una ruta nueva sin ella hace fallar el test.
2. Por cada ruta: 403 sin token, con token incorrecto (header y body) y paso con el correcto (header y
   body). El endpoint se reemplaza por un doble (`route.dependant.call`): con el token correcto la
   respuesta es la del doble o un 422 de validación, nunca una ejecución real (sin DB ni red).
3. La dependencia lee el body sin consumírselo al endpoint (JSON, multipart con archivo, urlencoded,
   lectura manual con `request.json()`/`request.form()`).
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi import Depends, FastAPI, File, Form, Request, UploadFile, params
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from core.password import hash_password
from web.app.dependencias import CSRF_HEADER, METODOS_MUTANTES, RUTAS_SIN_CSRF, requiere_csrf
from web.app.errores import ErrorDeDominio, manejar_error_de_dominio
from web.app.main import app

CSRF_INVALIDO = {"error": "CSRF inválido"}


# ── Inventario ────────────────────────────────────────────────────────────────────────────────────


def _rutas_mutantes() -> list[tuple[str, APIRoute]]:
    return [
        (metodo, ruta)
        for ruta in app.routes
        if isinstance(ruta, APIRoute)
        for metodo in sorted(ruta.methods & METODOS_MUTANTES)
    ]


def _exige_csrf(dependant: Any) -> bool:
    return any(d.call is requiere_csrf or _exige_csrf(d) for d in dependant.dependencies)


def test_inventario_toda_ruta_mutante_exige_csrf() -> None:
    sin_csrf = [
        f"{metodo} {ruta.path}"
        for metodo, ruta in _rutas_mutantes()
        if (metodo, ruta.path) not in RUTAS_SIN_CSRF and not _exige_csrf(ruta.dependant)
    ]
    assert sin_csrf == []


def test_inventario_recorre_toda_la_superficie() -> None:
    # Guarda contra un inventario que no ve nada (p. ej. si cambia cómo se montan los routers).
    assert len(_rutas_mutantes()) >= 98


def test_allowlist_sin_csrf_apunta_a_rutas_reales() -> None:
    reales = {(metodo, ruta.path) for metodo, ruta in _rutas_mutantes()}
    assert RUTAS_SIN_CSRF <= reales


# ── 403 / éxito por ruta, con sesión real ─────────────────────────────────────────────────────────


class _Cursor:
    def __init__(self, fila: tuple[str, str]) -> None:
        self._fila = fila

    def execute(self, *_a: Any, **_k: Any) -> None:
        return None

    def fetchone(self) -> tuple[str, str]:
        return self._fila

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_exc: Any) -> bool:
        return False


class _Conexion:
    def __init__(self, fila: tuple[str, str]) -> None:
        self._fila = fila

    def cursor(self) -> _Cursor:
        return _Cursor(self._fila)

    def __enter__(self) -> _Conexion:
        return self

    def __exit__(self, *_exc: Any) -> bool:
        return False


@pytest.fixture(scope="module")
def admin() -> Iterator[tuple[TestClient, str]]:
    """Cliente con sesión admin real (cookie con `username`, `role` y `csrf`), un solo login por módulo."""
    from web.app import main as web_main

    fila = (hash_password("adminpass"), "admin")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(web_main.psycopg, "connect", lambda *_a, **_k: _Conexion(fila))
        cliente = TestClient(app)
        res = cliente.post("/api/auth/login", json={"username": "csrf-admin", "password": "adminpass"})
    assert res.status_code == 200, res.text
    yield cliente, res.json()["csrf"]


@contextmanager
def _endpoint_falso(ruta: APIRoute) -> Iterator[None]:
    """El handler de FastAPI llama a `dependant.call` en cada request: reemplazarlo evita ejecutar el
    endpoint real. Async o sync según el original (FastAPI decide await/threadpool al crear la ruta)."""
    original = ruta.dependant.call

    if inspect.iscoroutinefunction(original):

        async def falso(**_kw: Any) -> JSONResponse:
            return JSONResponse({"doble": True})

    else:

        def falso(**_kw: Any) -> JSONResponse:  # type: ignore[misc]
            return JSONResponse({"doble": True})

    ruta.dependant.call = falso
    try:
        yield
    finally:
        ruta.dependant.call = original


def _url(ruta: APIRoute) -> str:
    return re.sub(r"\{[^}]+\}", "1", ruta.path)


def _es_form(ruta: APIRoute) -> bool:
    return ruta.body_field is not None and isinstance(ruta.body_field.field_info, (params.Form, params.File))


def _pedir(cliente: TestClient, metodo: str, ruta: APIRoute, *, header: str | None = None, body: str | None = None):
    headers = {CSRF_HEADER: header} if header is not None else {}
    datos = {"csrf_token": body} if body is not None else {}
    if _es_form(ruta):
        return cliente.request(metodo, _url(ruta), headers=headers, data=datos)
    return cliente.request(metodo, _url(ruta), headers=headers, json=datos)


_PROTEGIDAS = [(m, r) for m, r in _rutas_mutantes() if (m, r.path) not in RUTAS_SIN_CSRF]


@pytest.mark.parametrize(("metodo", "ruta"), _PROTEGIDAS, ids=[f"{m} {r.path}" for m, r in _PROTEGIDAS])
def test_cada_ruta_mutante_exige_csrf(admin, csrf_real, metodo: str, ruta: APIRoute) -> None:  # noqa: ANN001
    cliente, token = admin
    with _endpoint_falso(ruta):
        for intento in ({}, {"header": "otro"}, {"body": "otro"}, {"header": "otro", "body": token}):
            res = _pedir(cliente, metodo, ruta, **intento)
            assert (res.status_code, res.json()) == (403, CSRF_INVALIDO), intento

        for intento in ({"header": token}, {"body": token}):
            res = _pedir(cliente, metodo, ruta, **intento)
            # El doble respondió, o la validación del body (que corre después de la dependencia) dio 422.
            assert res.status_code in (200, 422), (intento, res.status_code, res.text)
            if res.status_code == 200:
                assert res.json() == {"doble": True}


def test_sin_sesion_responde_la_autenticacion_y_no_csrf(csrf_real) -> None:  # noqa: ANN001
    cliente = TestClient(app)
    # Router con sesión en el router (usuario_sesion corre antes) y router sin ella (informes).
    assert cliente.post("/api/infra/smart-search", json={}).status_code == 401
    assert cliente.post("/api/flows/sla", data={"mes": "1", "anio": "2025"}).status_code == 401


def test_login_no_exige_csrf(csrf_real, monkeypatch) -> None:  # noqa: ANN001
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", lambda *_a, **_k: _Conexion((hash_password("x"), "user")))
    res = TestClient(app).post("/api/auth/login", json={"username": "u-login", "password": "x"})
    assert res.status_code == 200


def test_get_no_se_valida(admin, csrf_real) -> None:  # noqa: ANN001
    cliente, _token = admin
    assert cliente.get("/api/auth/session").json()["authenticated"] is True


# ── La dependencia no le consume el body al endpoint ──────────────────────────────────────────────


class _Cuerpo(BaseModel):
    nombre: str
    ids: list[int] = []


def _mini_app() -> FastAPI:
    mini = FastAPI(dependencies=[Depends(requiere_csrf)])
    mini.add_middleware(SessionMiddleware, secret_key="test")
    mini.add_exception_handler(ErrorDeDominio, manejar_error_de_dominio)  # type: ignore[arg-type]

    @mini.get("/_login")
    def _ruta_login(request: Request) -> dict[str, str]:
        request.session.update({"username": "u", "role": "admin", "csrf": "tok"})
        return {"ok": "1"}

    @mini.post("/modelo")
    async def modelo(cuerpo: _Cuerpo) -> dict[str, Any]:
        return cuerpo.model_dump()

    @mini.post("/json-manual")
    async def json_manual(request: Request) -> dict[str, Any]:
        return await request.json()

    @mini.post("/multipart")
    async def multipart(archivo: UploadFile = File(...), motivo: str = Form(...)) -> dict[str, Any]:
        return {"archivo": (await archivo.read()).decode(), "motivo": motivo}

    @mini.post("/form-manual")
    async def form_manual(request: Request) -> dict[str, Any]:
        form = await request.form()
        archivo = form["archivo"]
        return {"archivo": (await archivo.read()).decode(), "motivo": form["motivo"]}  # type: ignore[union-attr]

    @mini.post("/urlencoded")
    def urlencoded(motivo: str = Form(...)) -> dict[str, str]:
        return {"motivo": motivo}

    return mini


@pytest.fixture
def mini(csrf_real) -> TestClient:  # noqa: ANN001
    cliente = TestClient(_mini_app())
    cliente.get("/_login")
    return cliente


def test_body_json_con_modelo_llega_entero(mini: TestClient) -> None:
    res = mini.post("/modelo", json={"nombre": "x", "ids": [1, 2], "csrf_token": "tok"})
    assert (res.status_code, res.json()) == (200, {"nombre": "x", "ids": [1, 2]})


def test_body_json_leido_a_mano_llega_entero(mini: TestClient) -> None:
    res = mini.post("/json-manual", json={"a": 1, "csrf_token": "tok"})
    assert (res.status_code, res.json()) == (200, {"a": 1, "csrf_token": "tok"})


@pytest.mark.parametrize("ruta", ["/multipart", "/form-manual"])
def test_multipart_con_archivo_llega_entero(mini: TestClient, ruta: str) -> None:
    res = mini.post(ruta, files={"archivo": ("a.txt", b"contenido")}, data={"motivo": "m", "csrf_token": "tok"})
    assert (res.status_code, res.json()) == (200, {"archivo": "contenido", "motivo": "m"})


def test_urlencoded_llega_entero(mini: TestClient) -> None:
    res = mini.post("/urlencoded", data={"motivo": "m", "csrf_token": "tok"})
    assert (res.status_code, res.json()) == (200, {"motivo": "m"})


def test_header_alcanza_sin_token_en_el_body(mini: TestClient) -> None:
    res = mini.post("/modelo", json={"nombre": "x"}, headers={CSRF_HEADER: "tok"})
    assert res.status_code == 200
    res = mini.post("/multipart", files={"archivo": ("a.txt", b"c")}, data={"motivo": "m"}, headers={CSRF_HEADER: "tok"})
    assert res.status_code == 200


def test_header_incorrecto_no_se_salva_con_el_body(mini: TestClient) -> None:
    res = mini.post("/modelo", json={"nombre": "x", "csrf_token": "tok"}, headers={CSRF_HEADER: "otro"})
    assert (res.status_code, res.json()) == (403, CSRF_INVALIDO)


def test_body_ilegible_es_sin_token(mini: TestClient) -> None:
    res = mini.post("/json-manual", content=b"{no es json", headers={"content-type": "application/json"})
    assert (res.status_code, res.json()) == (403, CSRF_INVALIDO)


def test_testing_true_saltea_la_validacion(mini: TestClient, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("TESTING", "true")
    assert mini.post("/modelo", json={"nombre": "x"}).status_code == 200
