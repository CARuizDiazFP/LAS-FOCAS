# Nombre de archivo: test_web_camaras_errores_depends.py
# Ubicación de archivo: tests/test_web_camaras_errores_depends.py
# Descripción: Router de Cámaras: sesión vía Depends (401/403) y 500 con ref sin exponer el texto de la excepción

from __future__ import annotations

import logging
import re
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from web.app.main import app

REF = re.compile(r"^Error interno \(ref ([0-9a-f]{8})\)$")
SECRETO = "secreto-interno-xyz"


def _cliente() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _registro(caplog, accion: str) -> str:
    (registro,) = [
        r for r in caplog.records if r.name == "web" and r.getMessage().startswith(f"action={accion}_error")
    ]
    return registro.getMessage()


def _session_local_roto(monkeypatch) -> None:
    from db import session as db_session

    def _roto():
        raise RuntimeError(SECRETO)

    monkeypatch.setattr(db_session, "SessionLocal", _roto)


# --- sesión vía Depends ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("metodo", "path", "cuerpo"),
    [
        ("GET", "/api/infra/camaras/1", None),
        ("POST", "/api/infra/smart-search", {}),
        ("POST", "/api/infra/ban/create", {}),
        ("POST", "/api/infra/camaras/merge", {}),
        ("GET", "/api/admin/infra/camaras/viewer", None),
    ],
)
def test_sin_sesion_da_401_aunque_el_body_sea_invalido(con_sesion, metodo, path, cuerpo):
    con_sesion(None)
    kwargs = {"json": cuerpo} if cuerpo is not None else {}
    res = _cliente().request(metodo, path, **kwargs)
    assert res.status_code == 401
    assert res.json() == {"detail": "No autenticado"}


@pytest.mark.parametrize(
    ("metodo", "path", "cuerpo"),
    [
        ("GET", "/api/admin/infra/camaras/viewer", None),
        ("GET", "/api/infra/camaras/1/estado", None),
        ("POST", "/api/infra/camaras/1/estado", {"estado": "LIBRE", "motivo": "motivo valido"}),
        ("POST", "/api/infra/camaras/merge", {"camara_principal_id": 1, "camara_secundaria_id": 2}),
        ("DELETE", "/api/admin/infra/camaras/pendientes/1", None),
    ],
)
def test_endpoints_admin_dan_403_a_un_usuario_comun(con_sesion, metodo, path, cuerpo):
    con_sesion("user")
    kwargs = {"json": cuerpo} if cuerpo is not None else {}
    res = _cliente().request(metodo, path, **kwargs)
    assert res.status_code == 403
    assert res.json() == {"detail": "Permisos insuficientes"}


# --- 500 con ref -------------------------------------------------------------------------------------


def test_smart_search_500_con_ref_sin_texto_interno(con_sesion, monkeypatch, caplog):
    con_sesion("user", username="pepe")
    _session_local_roto(monkeypatch)
    caplog.set_level(logging.INFO, logger="web")

    res = _cliente().post("/api/infra/smart-search", json={"terms": ["x"]})

    assert res.status_code == 500
    assert SECRETO not in res.text
    ref = REF.match(res.json()["error"]).group(1)
    assert list(res.json()) == ["error"]
    assert _registro(caplog, "smart_search") == f"action=smart_search_error user=pepe error={SECRETO} ref={ref}"


def test_detalle_de_camara_500_loguea_camara_id(con_sesion, monkeypatch, caplog):
    con_sesion("user")
    _session_local_roto(monkeypatch)
    caplog.set_level(logging.INFO, logger="web")

    res = _cliente().get("/api/infra/camaras/77")

    assert res.status_code == 500
    ref = REF.match(res.json()["error"]).group(1)
    assert _registro(caplog, "get_camara_detail") == f"action=get_camara_detail_error camara_id=77 error={SECRETO} ref={ref}"


def test_create_ban_500_conserva_success_false(con_sesion, monkeypatch):
    con_sesion("user")
    _session_local_roto(monkeypatch)

    res = _cliente().post(
        "/api/infra/ban/create", json={"servicio_afectado_id": "1", "servicio_protegido_id": "2"}
    )

    assert res.status_code == 500
    cuerpo = res.json()
    assert list(cuerpo) == ["success", "error"]
    assert cuerpo["success"] is False
    assert REF.match(cuerpo["error"])
    assert SECRETO not in res.text


def test_send_email_500_conserva_success_y_message(con_sesion, monkeypatch):
    from core.services import email_service

    def _roto():
        raise RuntimeError(SECRETO)

    con_sesion("user")
    monkeypatch.setattr(email_service, "get_email_service", _roto)

    res = _cliente().post("/api/infra/notify/email", json={"to": ["a@b.c"], "subject": "s", "body": "b"})

    assert res.status_code == 500
    cuerpo = res.json()
    assert list(cuerpo) == ["success", "message", "error"]
    assert cuerpo["success"] is False
    assert cuerpo["message"] == "Error enviando email"
    assert REF.match(cuerpo["error"])
    assert SECRETO not in res.text


def test_config_email_sigue_en_200_pero_sin_texto_interno(con_sesion, monkeypatch, caplog):
    from core.services import email_service

    def _roto():
        raise RuntimeError(SECRETO)

    con_sesion("user")
    monkeypatch.setattr(email_service, "get_email_service", _roto)
    caplog.set_level(logging.INFO, logger="web")

    res = _cliente().get("/api/infra/notify/email/config")

    assert res.status_code == 200
    cuerpo = res.json()
    assert cuerpo["configured"] is False
    ref = REF.match(cuerpo["error"]).group(1)
    assert SECRETO not in res.text
    assert _registro(caplog, "get_email_config") == f"action=get_email_config_error error={SECRETO} ref={ref}"


def test_admin_ingresos_sin_match_500_con_ref(con_sesion, monkeypatch):
    con_sesion("admin")
    _session_local_roto(monkeypatch)

    res = _cliente().get("/api/admin/infra/ingresos-sin-match")

    assert res.status_code == 500
    assert REF.match(res.json()["error"])
    assert SECRETO not in res.text


# --- 4xx con mensaje propio: sin cambios -------------------------------------------------------------


def test_merge_error_de_dominio_sigue_siendo_400_con_su_mensaje(con_sesion, monkeypatch):
    from core.services import camara_merge_service
    from db import session as db_session

    def _falla(*_args, **_kwargs):
        raise camara_merge_service.MergeCamarasError("Cámara principal no encontrada")

    sesion = MagicMock()
    fabrica = MagicMock()
    fabrica.return_value.__enter__.return_value = sesion
    fabrica.return_value.__exit__.return_value = False
    monkeypatch.setattr(db_session, "SessionLocal", fabrica)
    monkeypatch.setattr(camara_merge_service, "unificar_camaras", _falla)
    con_sesion("admin")

    res = _cliente().post("/api/infra/camaras/merge", json={"camara_principal_id": 1, "camara_secundaria_id": 2})

    assert res.status_code == 400
    assert res.json() == {"error": "Cámara principal no encontrada"}
    sesion.rollback.assert_called_once()
