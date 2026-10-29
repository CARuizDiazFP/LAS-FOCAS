# Nombre de archivo: test_web_admin_datos_errores_depends.py
# Ubicación de archivo: tests/test_web_admin_datos_errores_depends.py
# Descripción: Router admin_datos: sesión vía Depends (401/403) y 500/5xx con ref sin exponer el texto de la excepción

from __future__ import annotations

import re
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from tests.soporte_login import connect_admin_ok, fake_async_session_local, login
from tests.test_web_cromo_ingesta import (
    _AsyncSesionFake,
    _CromoConfigFake,
    _fake_httpx_async_client,
    _FakeCorrida,
)
from tests.test_web_rutas_contrato import muestra_de_ruta
from web.app.dependencias import usuario_admin
from web.app.main import app
from web.app.routers import admin_datos

SECRETO = "secreto-interno-xyz"


def _cliente() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _registro(caplog, accion: str) -> str:
    (registro,) = [
        r for r in caplog.records if r.name == "web" and r.getMessage().startswith(f"action={accion}_error")
    ]
    return registro.getMessage()


def _con_ref(mensaje: str) -> re.Pattern[str]:
    return re.compile(rf"^{re.escape(mensaje)} \(ref ([0-9a-f]{{8}})\)$")


REF_INTERNO = _con_ref("Error interno")


def _roto(*_args, **_kwargs):
    raise RuntimeError(SECRETO)


class _AsyncClientRoto:
    """`httpx.AsyncClient` que falla al usarse, con el texto secreto en la excepción."""

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def get(self, *_args, **_kwargs):
        raise RuntimeError(SECRETO)

    post = request = get


@pytest.fixture(autouse=True)
def _modo_test(monkeypatch):
    # Varios POST validan CSRF salvo con TESTING=true; no depender del entorno del que corre pytest.
    monkeypatch.setenv("TESTING", "true")


def _llama_a(dependant, objetivo) -> bool:
    return any(d.call is objetivo or _llama_a(d, objetivo) for d in dependant.dependencies)


def _rutas(filtro) -> list[tuple[str, str]]:
    return sorted(
        (metodo, ruta.path)
        for ruta in admin_datos.router.routes
        if filtro(ruta)
        for metodo in ruta.methods - {"HEAD", "OPTIONS"}
    )


_RUTAS_ADMIN = _rutas(lambda ruta: _llama_a(ruta.dependant, usuario_admin))

# Admin con chequeo de rol propio: responden 403 {"error": "Solo admin"} (no el detail de usuario_admin).
_RUTAS_SOLO_ADMIN_PROPIO = [
    ("GET", "/api/admin/servicios/baneos/health"),
    ("POST", "/api/admin/ingesta/camaras"),
    ("POST", "/api/admin/servicios/baneos"),
]


def test_toda_ruta_del_router_es_admin():
    # Hoy no hay rutas de usuario común en este router: las que no usan usuario_admin son las tres de arriba.
    todas = _rutas(lambda _ruta: True)
    assert len(_RUTAS_ADMIN) == 23
    assert sorted(set(todas) - set(_RUTAS_ADMIN)) == _RUTAS_SOLO_ADMIN_PROPIO


@pytest.mark.parametrize(("metodo", "plantilla"), _RUTAS_ADMIN)
def test_toda_ruta_admin_da_403_a_un_usuario_comun(con_sesion, metodo, plantilla):
    # Introspección: cualquier ruta que dependa de usuario_admin, aunque no tenga test propio.
    con_sesion("user")
    kwargs = {"json": {}} if metodo in {"POST", "PUT", "PATCH", "DELETE"} else {}
    res = _cliente().request(metodo, muestra_de_ruta(plantilla), **kwargs)
    assert res.status_code == 403, f"{metodo} {plantilla} respondió {res.status_code}"
    assert res.json() == {"detail": "Permisos insuficientes"}


@pytest.mark.parametrize(
    ("metodo", "path", "kwargs"),
    [
        ("GET", "/api/admin/servicios/baneos/health", {}),
        (
            "POST",
            "/api/admin/servicios/baneos",
            {"data": {"intervalo_horas": "4", "csrf_token": "x"}},
        ),
        (
            "POST",
            "/api/admin/ingesta/camaras",
            {
                "files": {"file": ("c.xlsx", b"x", "application/octet-stream")},
                "data": {"csrf_token": "x", "motivo_baneo": "m"},
            },
        ),
    ],
)
def test_rutas_con_rol_propio_conservan_solo_admin(con_sesion, metodo, path, kwargs):
    con_sesion("user")
    res = _cliente().request(metodo, path, **kwargs)
    assert res.status_code == 403
    assert res.json() == {"error": "Solo admin"}


# --- sesión vía Depends ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("metodo", "path", "kwargs"),
    [
        ("POST", "/api/admin/servicios/baneos", {}),
        ("POST", "/api/admin/servicios/baneos/listener", {}),
        ("POST", "/api/admin/ingesta/camaras", {}),
        ("POST", "/api/admin/ingesta/camaras/asociar", {"json": {}}),
        ("POST", "/api/admin/ingesta/cromo", {"json": {}}),
        ("GET", "/api/admin/ingesta/cromo/corridas/x/stream", {}),
        ("PATCH", "/api/admin/clientes/categoria", {"json": {}}),
        ("DELETE", "/api/admin/clientes/alias/x", {}),
    ],
)
def test_sin_sesion_da_401_aunque_el_pedido_sea_invalido(con_sesion, metodo, path, kwargs):
    con_sesion(None)
    res = _cliente().request(metodo, path, **kwargs)
    assert res.status_code == 401
    assert res.json() == {"detail": "No autenticado"}


@pytest.mark.parametrize("operacion", ["previsualizar", "aplicar"])
def test_lista_clientes_conserva_401_y_403_de_require_admin(con_sesion, operacion):
    # Antes autenticaba `_proxy_lista_clientes` por dentro; ahora Depends(usuario_admin), mismo cuerpo.
    ruta = f"/api/admin/clientes/lista/{operacion}"
    con_sesion(None)
    res = _cliente().post(ruta, content=b"no es json", headers={"content-type": "application/json"})
    assert (res.status_code, res.json()) == (401, {"detail": "No autenticado"})
    con_sesion("user")
    res = _cliente().post(ruta, content=b"no es json", headers={"content-type": "application/json"})
    assert (res.status_code, res.json()) == (403, {"detail": "Permisos insuficientes"})


# --- CSRF intacto ------------------------------------------------------------------------------------

# CSRF: lo valida `requiere_csrf` (router) con sesión real; ver tests/test_web_csrf.py. Con `con_sesion` la
# cookie no tiene usuario y la dependencia no decide, así que acá ya no se puede probar.


# --- 500 / 5xx con ref, sin texto interno ------------------------------------------------------------


def _assert_ref(res, patron: re.Pattern[str], status: int, caplog, accion: str, contexto: str = "") -> None:
    assert res.status_code == status
    assert SECRETO not in res.text
    match = patron.match(res.json()["error"])
    assert match, res.json()
    log = _registro(caplog, accion)
    assert log.startswith(f"action={accion}_error {contexto}".rstrip())
    assert log.endswith(f"error={SECRETO} ref={match.group(1)}")


def test_trigger_baneos_500_con_ref(con_sesion, monkeypatch, caplog):
    con_sesion("admin")
    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClientRoto)
    # Sin csrf en el form ni en la sesión simulada: el chequeo inline (None == None) pasa.
    res = _cliente().post("/api/admin/servicios/baneos/trigger", data={})
    _assert_ref(res, REF_INTERNO, 500, caplog, "servicios_baneos_trigger")


def test_worker_start_500_con_ref(con_sesion, monkeypatch, caplog):
    con_sesion("admin")
    monkeypatch.setitem(sys.modules, "docker", SimpleNamespace(from_env=_roto))
    res = _cliente().post("/api/admin/servicios/baneos/worker/start", data={})
    _assert_ref(res, REF_INTERNO, 500, caplog, "servicios_baneos_worker_start")


def test_listener_get_500_con_ref(con_sesion, monkeypatch, caplog):
    con_sesion("admin")
    monkeypatch.setattr(psycopg, "connect", _roto)
    res = _cliente().get("/api/admin/servicios/baneos/listener")
    _assert_ref(res, REF_INTERNO, 500, caplog, "listener_config_get")


def test_trigger_cromo_500_con_ref(monkeypatch, caplog):
    # CSRF inline sin excepción de tests y `csrf_token: str` obligatorio: hace falta login real.
    monkeypatch.setattr(psycopg, "connect", connect_admin_ok("admin"))
    cliente = _cliente()
    csrf = login(cliente, "admin", "admin")
    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClientRoto)
    res = cliente.post("/api/admin/ingesta/cromo/config/trigger", json={"csrf_token": csrf})
    _assert_ref(res, REF_INTERNO, 500, caplog, "cromo_scheduler_trigger", "user=admin")


def test_asociar_500_con_ref_y_sin_commit(con_sesion, monkeypatch, caplog):
    con_sesion("admin", username="ana")
    sesion = SimpleNamespace(commit=_roto, rollback=lambda: None)

    @contextmanager
    def _session_local():
        yield sesion

    monkeypatch.setattr("db.session.SessionLocal", _session_local)
    monkeypatch.setattr("core.services.camara_ingest_service.asociar_nombres_a_camara", _roto)
    res = _cliente().post("/api/admin/ingesta/camaras/asociar", json={"caso_ids": [1], "camara_id": 2})
    _assert_ref(res, REF_INTERNO, 500, caplog, "ingesta_camaras_asociar", "user=ana")


def test_proxy_clientes_500_con_mensaje_fijo_y_ref(con_sesion, monkeypatch, caplog):
    con_sesion("admin", username="ana")
    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClientRoto)
    res = _cliente().get("/api/admin/clientes/por-categoria")
    _assert_ref(
        res,
        _con_ref("Error en clientes por categoría"),
        500,
        caplog,
        "clientes_por_categoria",
        "user=ana ruta=/por-categoria",
    )


def test_ingesta_camaras_500_con_mensaje_fijo_y_ref(monkeypatch, caplog):
    monkeypatch.setattr(psycopg, "connect", connect_admin_ok("admin"))
    cliente = _cliente()
    csrf = login(cliente, "admin", "admin")
    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClientRoto)
    res = cliente.post(
        "/api/admin/ingesta/camaras",
        files={"file": ("c.xlsx", b"x", "application/octet-stream")},
        data={"csrf_token": csrf, "motivo_baneo": "m"},
    )
    _assert_ref(res, _con_ref("Error en ingesta de cámaras"), 500, caplog, "camaras_ingest_proxy", "user=admin")


def test_cromo_no_configurado_503_sin_detalle(monkeypatch, caplog):
    from core.services.cromo import config as cromo_config
    from core.services.cromo.config import CromoConfigError

    def _config_rota():
        raise CromoConfigError(SECRETO)

    monkeypatch.setattr(psycopg, "connect", connect_admin_ok("admin"))
    cliente = _cliente()
    csrf = login(cliente, "admin", "admin")
    monkeypatch.setattr(cromo_config, "get_cromo_config", _config_rota)
    res = cliente.post("/api/admin/ingesta/cromo", json={"csrf_token": csrf})
    _assert_ref(res, _con_ref("Cromo no está configurado"), 503, caplog, "cromo_ingesta_iniciar", "user=admin")


def test_corrida_fallida_guarda_motivo_fijo_con_ref(monkeypatch, caplog):
    # El motivo se guarda como evento ERROR y la UI lo lee por el detalle y el SSE de la corrida.
    from core.services.cromo import config as cromo_config
    from core.services.cromo import ingesta as cromo_ingesta

    async def _iniciar_corrida_fake(sesion, *, usuario, psize, max_paginas, clases, params_extra=None):
        return _FakeCorrida(id=77, usuario=usuario)

    monkeypatch.setattr(psycopg, "connect", connect_admin_ok("admin"))
    cliente = _cliente()
    csrf = login(cliente, "admin", "admin")
    monkeypatch.setattr(cromo_config, "get_cromo_config", lambda: _CromoConfigFake())
    monkeypatch.setattr(cromo_ingesta, "iniciar_corrida", _iniciar_corrida_fake)
    monkeypatch.setattr(httpx, "AsyncClient", _fake_httpx_async_client(excepcion=RuntimeError(SECRETO)))
    corrida = _FakeCorrida(id=77, estado="EN_CURSO")
    sesion = _AsyncSesionFake(corrida=corrida)
    monkeypatch.setattr("db.session.AsyncSessionLocal", fake_async_session_local(sesion))

    res = cliente.post("/api/admin/ingesta/cromo", json={"csrf_token": csrf})

    # La respuesta 503 no cambia.
    assert res.status_code == 503
    assert res.json() == {"error": "El worker de ingesta no está disponible. Intentá nuevamente en unos segundos."}
    assert corrida.estado == "FALLIDA"
    (evento,) = sesion.agregados
    assert evento.accion == "ERROR"
    match = _con_ref("No se pudo delegar la corrida al worker de ingesta").match(evento.detalle)
    assert match, evento.detalle
    log = _registro(caplog, "cromo_ingesta_iniciar")
    assert log == f"action=cromo_ingesta_iniciar_error corrida_id=77 error={SECRETO} ref={match.group(1)}"


def test_4xx_propios_sin_cambios(con_sesion):
    con_sesion("admin")
    res = _cliente().post("/api/admin/ingesta/camaras/asociar", json={"caso_ids": [], "camara_id": 2})
    assert (res.status_code, res.json()) == (400, {"error": "No se especificaron casos a asociar"})
