# Nombre de archivo: test_web_errores_dependencias.py
# Ubicación de archivo: tests/test_web_errores_dependencias.py
# Descripción: Errores tipados + error_interno con ref, handlers globales y dependencias de sesión de la web

from __future__ import annotations

import json
import logging
import re
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from tests.soporte_sesion import sesion_simulada
from web.app import comun
from web.app.dependencias import UsuarioSesion, usuario_admin, usuario_sesion
from web.app.errores import (
    Conflicto,
    DatoInvalido,
    ErrorDeDominio,
    NoEncontrado,
    error_interno,
    manejar_error_de_dominio,
    manejar_error_no_controlado,
)
from web.app.main import app as web_app

REF = re.compile(r"^Error interno \(ref ([0-9a-f]{8})\)$")


def _registros(caplog, accion: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "web" and r.getMessage().startswith(f"action={accion}_error")]


# --- registro en la app real --------------------------------------------------


def test_app_web_registra_handlers_y_no_toca_los_de_fastapi():
    handlers = web_app.exception_handlers
    assert handlers[ErrorDeDominio] is manejar_error_de_dominio
    assert handlers[Exception] is manejar_error_no_controlado
    assert handlers[StarletteHTTPException] is http_exception_handler
    assert handlers[RequestValidationError] is request_validation_exception_handler


def test_app_web_real_500_con_ref_tambien_pasa_por_el_middleware_de_log(monkeypatch, caplog):
    """App real: /health revienta → 500 JSON con ref. El middleware `log_requests` de main.py ya
    logueaba `action=request_error` (con traceback) y lo sigue haciendo: quedan dos líneas."""
    from types import SimpleNamespace as Modulo

    from web.app.routers import sesion

    def _roto():
        raise RuntimeError("secreto-health")

    caplog.set_level(logging.INFO, logger="web")
    monkeypatch.setattr(sesion, "time", Modulo(time=_roto))
    res = TestClient(web_app, raise_server_exceptions=False).get("/health")

    assert res.status_code == 500
    ref = REF.match(res.json()["error"]).group(1)
    assert "secreto" not in res.text
    (registro,) = _registros(caplog, "unhandled")
    assert registro.getMessage() == f"action=unhandled_error method=GET path=/health error=secreto-health ref={ref}"
    assert len(_registros(caplog, "request")) == 1


# --- handlers (mini app con los mismos handlers que main.py) -------------------


def _mini_app() -> FastAPI:
    mini = FastAPI()
    mini.add_exception_handler(ErrorDeDominio, manejar_error_de_dominio)
    mini.add_exception_handler(Exception, manejar_error_no_controlado)

    @mini.get("/dominio/{tipo}")
    async def dominio(tipo: str):
        clases = {"404": NoEncontrado, "422": DatoInvalido, "409": Conflicto, "400": ErrorDeDominio}
        raise clases[tipo](f"mensaje {tipo}")

    @mini.get("/boom")
    async def boom():
        raise RuntimeError("secreto-interno de la base")

    @mini.get("/http")
    async def http():
        raise HTTPException(status_code=404, detail="No existe")

    @mini.get("/validacion")
    async def validacion(n: int):
        return {"n": n}

    return mini


@pytest.mark.parametrize(("tipo", "status"), [("404", 404), ("422", 422), ("409", 409), ("400", 400)])
def test_error_de_dominio_responde_mensaje_y_status(tipo, status):
    res = TestClient(_mini_app()).get(f"/dominio/{tipo}")
    assert res.status_code == status
    assert res.json() == {"error": f"mensaje {tipo}"}


def test_error_de_dominio_status_explicito():
    exc = ErrorDeDominio("x", status_code=418)
    assert (exc.status_code, exc.mensaje, str(exc)) == (418, "x", "x")
    assert NoEncontrado("y").status_code == 404


def test_excepcion_no_controlada_500_con_ref_sin_texto_interno(caplog):
    caplog.set_level(logging.INFO, logger="web")
    res = TestClient(_mini_app(), raise_server_exceptions=False).get("/boom")

    assert res.status_code == 500
    assert res.headers["content-type"] == "application/json"
    assert list(res.json()) == ["error"]
    ref = REF.match(res.json()["error"]).group(1)
    assert "secreto" not in res.text

    (registro,) = _registros(caplog, "unhandled")
    assert registro.getMessage() == (
        f"action=unhandled_error method=GET path=/boom error=secreto-interno de la base ref={ref}"
    )
    assert registro.levelno == logging.ERROR
    assert registro.exc_info and isinstance(registro.exc_info[1], RuntimeError)


def test_con_raise_server_exceptions_la_excepcion_se_sigue_propagando(caplog):
    """ServerErrorMiddleware re-lanza tras el handler: los tests con TestClient por defecto no cambian."""
    caplog.set_level(logging.INFO, logger="web")
    with pytest.raises(RuntimeError, match="secreto-interno"):
        TestClient(_mini_app()).get("/boom")
    # El handler corrió igual (respuesta 500 con ref enviada y logueada antes del re-raise).
    assert len(_registros(caplog, "unhandled")) == 1


def test_http_exception_y_validacion_siguen_como_fastapi():
    client = TestClient(_mini_app())
    res = client.get("/http")
    assert (res.status_code, res.json()) == (404, {"detail": "No existe"})
    res = client.get("/validacion", params={"n": "x"})
    assert res.status_code == 422
    assert res.json()["detail"][0]["loc"] == ["query", "n"]


def test_dominio_dentro_de_un_try_generico_se_trago_si_no_se_relanza():
    """Documenta el porqué de `except (HTTPException, ErrorDeDominio): raise` al migrar routers."""
    mini = _mini_app()

    @mini.get("/tragado")
    async def tragado():
        try:
            raise NoEncontrado("no está")
        except (HTTPException, ErrorDeDominio):
            raise
        except Exception as exc:  # noqa: BLE001
            return error_interno("tragado", exc)

    assert TestClient(mini).get("/tragado").status_code == 404


# --- error_interno -------------------------------------------------------------


def test_error_interno_formato_de_log_igual_al_de_los_routers(caplog):
    caplog.set_level(logging.INFO, logger="web")
    exc = ValueError("boom")
    try:
        raise exc
    except ValueError:
        res = error_interno("get_servicio_rutas", exc, user="ana", servicio_id=7)

    ref = REF.match(json.loads(res.body)["error"]).group(1)
    (registro,) = _registros(caplog, "get_servicio_rutas")
    # Hoy: logger.exception("action=get_servicio_rutas_error user=%s servicio_id=%s error=%s", ...)
    assert registro.getMessage() == f"action=get_servicio_rutas_error user=ana servicio_id=7 error=boom ref={ref}"
    assert registro.exc_info[1] is exc


def test_error_interno_conserva_claves_extra_del_cuerpo_en_orden():
    exc = RuntimeError("detalle interno")
    res = error_interno("create_ban", exc, cuerpo={"success": False, "message": "Error enviando email"})
    cuerpo = json.loads(res.body)
    assert res.status_code == 500
    assert list(cuerpo) == ["success", "message", "error"]
    assert cuerpo["success"] is False and cuerpo["message"] == "Error enviando email"
    assert REF.match(cuerpo["error"])
    assert "detalle interno" not in res.body.decode()


def test_error_interno_pisa_error_del_cuerpo_y_acepta_contexto_con_nombres_posicionales(caplog):
    caplog.set_level(logging.INFO, logger="web")
    res = error_interno("x", RuntimeError("secreto"), cuerpo={"error": "secreto"}, accion="otra", exc="valor")
    assert b"secreto" not in res.body
    (registro,) = _registros(caplog, "x")
    assert registro.getMessage().startswith("action=x_error accion=otra exc=valor error=secreto ref=")


def test_refs_distintas_por_llamada():
    refs = {error_interno("x", RuntimeError()).body for _ in range(20)}
    assert len(refs) == 20


# --- dependencias de sesión ----------------------------------------------------


def _request(sesion: dict) -> SimpleNamespace:
    return SimpleNamespace(session=sesion)


@pytest.mark.asyncio
async def test_usuario_sesion_sin_sesion_401():
    with pytest.raises(HTTPException) as info:
        await usuario_sesion(_request({}))
    assert (info.value.status_code, info.value.detail) == (401, "No autenticado")


@pytest.mark.asyncio
async def test_usuario_sesion_devuelve_usuario_y_rol_por_defecto():
    assert await usuario_sesion(_request({"username": "ana"})) == UsuarioSesion("ana", "user")
    username, role = await usuario_sesion(_request({"username": "jefe", "role": "admin"}))
    assert (username, role) == ("jefe", "admin")


@pytest.mark.asyncio
async def test_usuario_admin_401_403_y_ok():
    with pytest.raises(HTTPException) as info:
        await usuario_admin(_request({}))
    assert info.value.status_code == 401
    with pytest.raises(HTTPException) as info:
        await usuario_admin(_request({"username": "ana", "role": "user"}))
    assert (info.value.status_code, info.value.detail) == (403, "Permisos insuficientes")
    assert await usuario_admin(_request({"username": "jefe", "role": "admin"})) == UsuarioSesion("jefe", "admin")


@pytest.mark.asyncio
async def test_dependencias_usan_comun_como_unica_fuente(monkeypatch):
    monkeypatch.setattr(comun, "_require_auth", lambda request: ("parcheado", "user"))
    monkeypatch.setattr(comun, "_require_admin", lambda request: "parcheado-admin")
    assert await usuario_sesion(_request({})) == UsuarioSesion("parcheado", "user")
    assert await usuario_admin(_request({})) == UsuarioSesion("parcheado-admin", "admin")


class _Cuerpo(BaseModel):
    nombre: str = "x"


class _CuerpoObligatorio(BaseModel):
    nombre: str


def _router_protegido() -> APIRouter:
    router = APIRouter(dependencies=[Depends(usuario_sesion)])

    @router.post("/con-body")
    async def con_body(datos: _CuerpoObligatorio):
        return {"nombre": datos.nombre}

    @router.get("/yo")
    async def yo(usuario: UsuarioSesion = Depends(usuario_sesion)):
        return {"username": usuario.username, "role": usuario.role}

    @router.post("/solo-admin")
    async def solo_admin(datos: _Cuerpo, usuario: UsuarioSesion = Depends(usuario_admin)):
        return {"admin": usuario.username}

    return router


def test_dependencias_por_http_con_cookie_de_sesion_real():
    mini = FastAPI()
    mini.add_middleware(SessionMiddleware, secret_key="test")
    mini.include_router(_router_protegido())

    @mini.get("/login/{rol}")
    async def login(rol: str, request: Request):
        request.session.update({"username": f"u-{rol}", "role": rol})
        return {}

    client = TestClient(mini)
    assert client.get("/yo").status_code == 401
    # Sin sesión es 401 aunque el body no cumpla el modelo: la dependencia del router se resuelve
    # antes que la validación del body (lo que pide el test de exposición con json={}).
    assert client.post("/con-body", json={}).status_code == 401
    # Límite: un JSON MALFORMADO se rechaza al parsear, antes de resolver dependencias → 422.
    res = client.post("/con-body", content=b"no-json", headers={"content-type": "application/json"})
    assert res.status_code == 422 and res.json()["detail"][0]["type"] == "json_invalid"
    client.get("/login/user")
    assert client.get("/yo").json() == {"username": "u-user", "role": "user"}
    assert client.post("/solo-admin", json={}).status_code == 403
    client.get("/login/admin")
    assert client.post("/solo-admin", json={}).json() == {"admin": "u-admin"}


# --- fixture con_sesion / sesion_simulada --------------------------------------


def _mini_que_comparte_overrides_con_la_web() -> TestClient:
    mini = FastAPI()
    mini.dependency_overrides = web_app.dependency_overrides  # mismo dict que la app real
    mini.include_router(_router_protegido())
    return TestClient(mini)


def test_fixture_con_sesion_user_admin_y_sin_sesion(con_sesion):
    client = _mini_que_comparte_overrides_con_la_web()
    assert con_sesion("user", username="pepe") == UsuarioSesion("pepe", "user")
    assert client.get("/yo").json() == {"username": "pepe", "role": "user"}
    res = client.post("/solo-admin", json={})
    assert (res.status_code, res.json()) == (403, {"detail": "Permisos insuficientes"})

    con_sesion("admin")
    assert client.post("/solo-admin", json={}).json() == {"admin": "tester"}

    assert con_sesion(None) is None
    assert client.get("/yo").status_code == 401


def test_sesion_simulada_se_limpia_aunque_falle_y_respeta_overrides_previos():
    def previo():
        return UsuarioSesion("previo", "user")

    def otro_override():
        return None

    overrides = web_app.dependency_overrides
    overrides[usuario_sesion] = previo
    overrides[otro_override] = otro_override
    try:
        with pytest.raises(RuntimeError):
            with sesion_simulada() as activar:
                activar("admin")
                assert overrides[usuario_sesion] is not previo
                raise RuntimeError("falla el test")
        assert overrides[usuario_sesion] is previo
        assert usuario_admin not in overrides
        assert overrides[otro_override] is otro_override
    finally:
        overrides.pop(usuario_sesion, None)
        overrides.pop(otro_override, None)
    assert usuario_sesion not in overrides and usuario_admin not in overrides
