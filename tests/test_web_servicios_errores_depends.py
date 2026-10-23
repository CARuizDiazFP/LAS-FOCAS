# Nombre de archivo: test_web_servicios_errores_depends.py
# Ubicación de archivo: tests/test_web_servicios_errores_depends.py
# Descripción: Router de Servicios: sesión vía Depends (401/403) y 500 con ref sin exponer el texto de la excepción

from __future__ import annotations

import logging
import re

import pytest
from fastapi.testclient import TestClient

from web.app.main import app
from web.app.routers import servicios

REF = re.compile(r"^Error interno \(ref ([0-9a-f]{8})\)$")
SECRETO = "secreto-interno-xyz"


def _cliente() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _registro(caplog, accion: str) -> str:
    (registro,) = [
        r for r in caplog.records if r.name == "web" and r.getMessage().startswith(f"action={accion}_error")
    ]
    return registro.getMessage()


def _roto(*_args, **_kwargs):
    raise RuntimeError(SECRETO)


# --- sesión vía Depends ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("metodo", "path", "kwargs"),
    [
        ("POST", "/api/servicios/ingest", {}),
        ("POST", "/api/infra/upload_tracking", {}),
        ("POST", "/api/infra/trackings/resolve", {"json": {}}),
        ("PATCH", "/api/servicios/1/categoria", {"json": {}}),
        ("POST", "/api/admin/infra/servicios-odf/1/pelos-excluidos", {"json": {}}),
        ("GET", "/api/servicios/detail", {}),
        ("GET", "/api/infra/rutas/x/tracking", {}),
    ],
)
def test_sin_sesion_da_401_aunque_el_pedido_sea_invalido(con_sesion, metodo, path, kwargs):
    con_sesion(None)
    res = _cliente().request(metodo, path, **kwargs)
    assert res.status_code == 401
    assert res.json() == {"detail": "No autenticado"}


@pytest.mark.parametrize(
    ("metodo", "path", "cuerpo"),
    [
        ("GET", "/api/admin/infra/servicios-odf/listado", None),
        ("GET", "/api/admin/infra/servicios-odf/1/sugerencia", None),
        ("GET", "/api/admin/infra/servicios-odf/1/senal-direccion?odf_n_id=2", None),
        ("GET", "/api/admin/infra/servicios-odf/1/camino-optico", None),
        ("GET", "/api/admin/infra/servicios-odf/1/odf-confirmadas", None),
        ("POST", "/api/admin/infra/servicios-odf/1/asociar", {"odf_n_id": 2}),
        ("POST", "/api/admin/infra/servicios-odf/1/pelos-excluidos", {"pelos_n_id": [3]}),
        ("PATCH", "/api/servicios/1/categoria", {"categoria": 2}),
        ("PATCH", "/api/servicios/1/categoria/heredar", {}),
        ("PATCH", "/api/servicios/1/verificable", {"es_verificable": True}),
        ("PATCH", "/api/servicios/bulk-categoria", {"servicio_ids": [1], "categoria": 2}),
    ],
)
def test_endpoints_admin_dan_403_a_un_usuario_comun(con_sesion, metodo, path, cuerpo):
    con_sesion("user")
    kwargs = {"json": cuerpo} if cuerpo is not None else {}
    res = _cliente().request(metodo, path, **kwargs)
    assert res.status_code == 403
    assert res.json() == {"detail": "Permisos insuficientes"}


def test_ingest_conserva_su_403_solo_admin(con_sesion):
    con_sesion("user")
    res = _cliente().post(
        "/api/servicios/ingest", files={"file": ("s.xlsx", b"x")}, data={"csrf_token": "t"}
    )
    assert res.status_code == 403
    assert res.json() == {"error": "Solo admin"}


def test_ingest_conserva_su_csrf(con_sesion):
    con_sesion("admin")
    res = _cliente().post(
        "/api/servicios/ingest", files={"file": ("s.xlsx", b"x")}, data={"csrf_token": "otro"}
    )
    assert res.status_code == 403
    assert res.json() == {"error": "CSRF invalido"}


def test_categoria_conserva_su_csrf_fuera_de_tests(con_sesion, monkeypatch):
    con_sesion("admin")
    monkeypatch.setenv("TESTING", "false")
    res = _cliente().patch("/api/servicios/1/categoria", json={"categoria": 2, "csrf_token": "otro"})
    assert res.status_code == 403
    assert res.json() == {"error": "CSRF inválido"}


# --- 500 con ref -------------------------------------------------------------------------------------


def test_search_500_con_ref_sin_texto_interno_para_un_usuario_comun(con_sesion, monkeypatch, caplog):
    con_sesion("user", username="pepe")
    monkeypatch.setattr(servicios, "_internal_api_auth_headers", _roto)
    caplog.set_level(logging.INFO, logger="web")

    res = _cliente().get("/api/servicios/search?q=abc")

    assert res.status_code == 500
    assert SECRETO not in res.text
    assert list(res.json()) == ["error"]
    ref = REF.match(res.json()["error"]).group(1)
    assert (
        _registro(caplog, "servicios_search_proxy")
        == f"action=servicios_search_proxy_error user=pepe error={SECRETO} ref={ref}"
    )


def test_prov_refrescar_500_loguea_el_id(con_sesion, monkeypatch, caplog):
    con_sesion("user", username="pepe")
    monkeypatch.setattr(servicios, "_internal_api_auth_headers", _roto)
    caplog.set_level(logging.INFO, logger="web")

    res = _cliente().post("/api/servicios/prov/refrescar?id=%2012345%20", json={})

    assert res.status_code == 500
    assert SECRETO not in res.text
    ref = REF.match(res.json()["error"]).group(1)
    assert (
        _registro(caplog, "servicio_prov_refrescar")
        == f"action=servicio_prov_refrescar_error user=pepe id=12345 error={SECRETO} ref={ref}"
    )


def test_categoria_500_con_ref(con_sesion, monkeypatch, caplog):
    con_sesion("admin", username="jefa")
    monkeypatch.setattr(servicios, "_internal_api_auth_headers", _roto)
    caplog.set_level(logging.INFO, logger="web")

    res = _cliente().patch("/api/servicios/5/categoria", json={"categoria": 2})

    assert res.status_code == 500
    assert SECRETO not in res.text
    ref = REF.match(res.json()["error"]).group(1)
    assert (
        _registro(caplog, "servicio_categoria")
        == f"action=servicio_categoria_error user=jefa id=5 error={SECRETO} ref={ref}"
    )


def test_rutas_de_servicio_500_con_ref(con_sesion, monkeypatch, caplog):
    from db import session as db_session

    con_sesion("user", username="pepe")
    monkeypatch.setattr(db_session, "SessionLocal", _roto)
    caplog.set_level(logging.INFO, logger="web")

    res = _cliente().get("/api/infra/servicios/ABC/rutas")

    assert res.status_code == 500
    assert SECRETO not in res.text
    ref = REF.match(res.json()["error"]).group(1)
    assert (
        _registro(caplog, "get_servicio_rutas")
        == f"action=get_servicio_rutas_error user=pepe servicio_id=ABC error={SECRETO} ref={ref}"
    )


def test_upload_tracking_500_con_ref(con_sesion, monkeypatch, caplog):
    from core.parsers import tracking_parser

    con_sesion("user", username="pepe")
    monkeypatch.setattr(tracking_parser, "parse_tracking", _roto)
    caplog.set_level(logging.INFO, logger="web")

    res = _cliente().post("/api/infra/upload_tracking", files={"file": ("t.txt", b"contenido")})

    assert res.status_code == 500
    assert SECRETO not in res.text
    ref = REF.match(res.json()["error"]).group(1)
    assert (
        _registro(caplog, "upload_tracking")
        == f"action=upload_tracking_error user=pepe filename=t.txt error={SECRETO} ref={ref}"
    )


def test_asociar_500_con_ref(con_sesion, monkeypatch, caplog):
    async def _categorizado_roto(*_args, **_kwargs):
        raise RuntimeError(SECRETO)

    con_sesion("admin", username="jefa")
    monkeypatch.setattr(servicios, "_obtener_servicio_categorizado", _categorizado_roto)
    caplog.set_level(logging.INFO, logger="web")

    res = _cliente().post("/api/admin/infra/servicios-odf/9/asociar", json={"odf_n_id": 2})

    assert res.status_code == 500
    assert SECRETO not in res.text
    ref = REF.match(res.json()["error"]).group(1)
    assert (
        _registro(caplog, "servicios_sin_odf_asociar")
        == f"action=servicios_sin_odf_asociar_error user=jefa servicio_id=9 error={SECRETO} ref={ref}"
    )


# --- 4xx con mensaje propio: misma respuesta ---------------------------------------------------------


def test_listado_con_offset_negativo_sigue_siendo_400_con_su_mensaje(con_sesion):
    con_sesion("admin")
    res = _cliente().get("/api/admin/infra/servicios-odf/listado?offset=-1")
    assert res.status_code == 400
    assert res.json() == {"error": "offset no puede ser negativo: -1"}


def test_pelo_ajeno_al_excluir_sigue_siendo_409_con_su_mensaje(con_sesion, monkeypatch):
    from core.services.cromo import pelos_excluidos

    async def _existe(*_args, **_kwargs):
        return True

    async def _ajeno(*_args, **_kwargs):
        raise pelos_excluidos.PeloNoPerteneceAlServicio("El pelo 3 no es de este Servicio.")

    con_sesion("admin")
    monkeypatch.setattr(servicios, "_servicio_existe", _existe)
    monkeypatch.setattr(pelos_excluidos, "excluir_pelos", _ajeno)

    res = _cliente().post("/api/admin/infra/servicios-odf/1/pelos-excluidos", json={"pelos_n_id": [3]})

    assert res.status_code == 409
    assert res.json() == {"error": "El pelo 3 no es de este Servicio."}


# --- 502 de Cromo sin texto interno ------------------------------------------------------------------


def test_normalizar_502_de_cromo_sin_texto_interno_y_ref_en_el_log(con_sesion, monkeypatch, caplog):
    from core.services.cromo import client as cromo_client
    from core.services.cromo import config as cromo_config
    from core.services.cromo import normalizacion_consistencia_service as normalizacion

    async def _existe(*_args, **_kwargs):
        return True

    class _ClienteFalso:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    async def _cromo_caido(*_args, **_kwargs):
        raise cromo_client.CromoClientError(f"Cromo respondió 401 en /oauth: {SECRETO}")

    con_sesion("admin", username="jefa")
    monkeypatch.setattr(servicios, "_servicio_existe", _existe)
    monkeypatch.setattr(cromo_client, "CromoClient", _ClienteFalso)
    monkeypatch.setattr(cromo_config, "get_cromo_config", lambda: None)
    monkeypatch.setattr(normalizacion, "normalizar_inconsistencias", _cromo_caido)
    caplog.set_level(logging.INFO, logger="web")

    res = _cliente().post(
        "/api/admin/infra/servicios-odf/4/camino-optico/normalizar", json={"pelo_n_id": 10}
    )

    assert res.status_code == 502
    assert SECRETO not in res.text
    ref = re.fullmatch(r"Cromo no respondió \(ref ([0-9a-f]{8})\)", res.json()["error"]).group(1)
    assert _registro(caplog, "camino_normalizar") == (
        f"action=camino_normalizar_error user=jefa servicio_id=4 "
        f"error=Cromo respondió 401 en /oauth: {SECRETO} ref={ref}"
    )
