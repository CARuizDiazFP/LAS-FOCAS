# Nombre de archivo: test_web_cromo_errores_depends.py
# Ubicación de archivo: tests/test_web_cromo_errores_depends.py
# Descripción: Router de Cromo: sesión vía Depends (401/403, user vs admin) y 500 con ref sin exponer el texto de la excepción

from __future__ import annotations

import logging
import re
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from tests.test_web_rutas_contrato import muestra_de_ruta
from web.app.dependencias import usuario_admin
from web.app.main import app
from web.app.routers import cromo

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
    monkeypatch.setattr(db_session, "AsyncSessionLocal", _roto)


def _request(metodo: str, path: str, cuerpo: Any):
    kwargs = {"json": cuerpo} if cuerpo is not None else {}
    return _cliente().request(metodo, path, **kwargs)


@pytest.fixture(autouse=True)
def _modo_test(monkeypatch):
    # Los POST/PATCH validan CSRF salvo con TESTING=true; no depender del entorno del que corre pytest.
    monkeypatch.setenv("TESTING", "true")


def _llama_a(dependant, objetivo) -> bool:
    return any(d.call is objetivo or _llama_a(d, objetivo) for d in dependant.dependencies)


_RUTAS_ADMIN = sorted(
    (metodo, ruta.path)
    for ruta in cromo.router.routes
    if _llama_a(ruta.dependant, usuario_admin)
    for metodo in ruta.methods - {"HEAD", "OPTIONS"}
)


def test_hay_rutas_admin_detectadas():
    assert len(_RUTAS_ADMIN) >= 33


@pytest.mark.parametrize(("metodo", "plantilla"), _RUTAS_ADMIN)
def test_toda_ruta_admin_da_403_a_un_usuario_comun(con_sesion, metodo, plantilla):
    # Introspección: cualquier ruta que dependa de usuario_admin, aunque no tenga test propio.
    con_sesion("user")
    kwargs = {"json": {}} if metodo in {"POST", "PUT", "PATCH", "DELETE"} else {}
    res = _cliente().request(metodo, muestra_de_ruta(plantilla), **kwargs)
    assert res.status_code == 403, f"{metodo} {plantilla} respondió {res.status_code}"
    assert res.json() == {"detail": "Permisos insuficientes"}


# --- sesión vía Depends ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("metodo", "path", "cuerpo"),
    [
        ("GET", "/api/infra/cromo/elementos/1/vivo", None),
        ("GET", "/api/infra/cromo/cables/resolver", None),  # falta `q`: antes 422
        ("PUT", "/api/infra/botellas/estado", {}),
        ("POST", "/api/infra/cromo-botellas/asociar", {}),
        ("PATCH", "/api/infra/botellas/1/nombre", {}),
        ("POST", "/api/admin/infra/arbitro-cromo/reglas", {}),
        ("POST", "/api/admin/infra/arbitro-cromo/propuestas/aplicar", {}),
    ],
)
def test_sin_sesion_da_401_aunque_el_request_sea_invalido(con_sesion, metodo, path, cuerpo):
    con_sesion(None)
    res = _request(metodo, path, cuerpo)
    assert res.status_code == 401
    assert res.json() == {"detail": "No autenticado"}


@pytest.mark.parametrize(
    ("metodo", "path", "cuerpo"),
    [
        # admin en el decorador (no necesitan el username)
        ("GET", "/api/admin/infra/botellas/viewer", None),
        ("POST", "/api/admin/infra/botellas/operatividad", {"n_ids": [1]}),
        ("GET", "/api/admin/infra/arbitro-cromo/propuestas", None),
        ("GET", "/api/admin/infra/inconsistencias-cromo/deteccion", None),
        # admin en la firma (usan el username)
        ("PUT", "/api/infra/botellas/estado", {"items": [{"origen": "cromo", "id": 1}], "estado": "LIBRE"}),
        ("POST", "/api/infra/botellas/apropiar", {"legado_id": 1, "cromo_n_id": 2}),
        ("POST", "/api/admin/infra/arbitro-cromo/propuestas/aplicar", {"ids": [1]}),
        ("POST", "/api/admin/infra/arbitro-cromo/normalizar", {}),
        ("POST", "/api/admin/infra/huerfanos/auditoria-global", {}),
        ("POST", "/api/admin/infra/inconsistencias-cromo/deteccion", {}),
        ("POST", "/api/infra/botellas/1/repoblar-cables", {}),
        ("PATCH", "/api/infra/botellas/1/nombre", {"nombre": "x"}),
    ],
)
def test_endpoints_admin_dan_403_a_un_usuario_comun(con_sesion, metodo, path, cuerpo):
    con_sesion("user")
    res = _request(metodo, path, cuerpo)
    assert res.status_code == 403
    assert res.json() == {"detail": "Permisos insuficientes"}


@pytest.mark.parametrize(
    ("metodo", "path", "cuerpo"),
    [
        ("GET", "/api/infra/cromo/elementos/1/vivo", None),
        ("GET", "/api/infra/cromo/cables/1/detalle", None),
        ("POST", "/api/infra/cromo-botellas/asociar", {"n_ids": [1], "camara_id": 2}),
        ("POST", "/api/infra/cromo/cables/1/servicios-unicos/refrescar-prov", {}),
    ],
)
def test_endpoints_de_usuario_siguen_abiertos_a_un_usuario_comun(con_sesion, monkeypatch, metodo, path, cuerpo):
    """Visor en vivo, consultas y los POST de usuario no pasaron a admin: con la DB rota llegan al
    handler (500 con ref), no a un 401/403."""
    con_sesion("user")
    _session_local_roto(monkeypatch)

    res = _request(metodo, path, cuerpo)

    assert res.status_code == 500
    assert SECRETO not in res.text
    assert REF.match(res.json()["error"])


# --- 500 con ref -------------------------------------------------------------------------------------


def test_viewer_de_botellas_500_con_ref_sin_texto_interno(con_sesion, monkeypatch, caplog):
    con_sesion("admin")
    _session_local_roto(monkeypatch)
    caplog.set_level(logging.INFO, logger="web")

    res = _cliente().get("/api/admin/infra/botellas/viewer")

    assert res.status_code == 500
    assert SECRETO not in res.text
    assert list(res.json()) == ["error"]
    ref = REF.match(res.json()["error"]).group(1)
    assert _registro(caplog, "botellas_viewer_listado") == (
        f"action=botellas_viewer_listado_error error={SECRETO} ref={ref}"
    )


def test_estado_masivo_500_loguea_el_usuario(con_sesion, monkeypatch, caplog):
    con_sesion("admin", username="pepe")
    _session_local_roto(monkeypatch)
    caplog.set_level(logging.INFO, logger="web")

    res = _cliente().put(
        "/api/infra/botellas/estado", json={"items": [{"origen": "cromo", "id": 1}], "estado": "LIBRE"}
    )

    assert res.status_code == 500
    assert SECRETO not in res.text
    ref = REF.match(res.json()["error"]).group(1)
    assert _registro(caplog, "botellas_estado_masivo") == (
        f"action=botellas_estado_masivo_error user=pepe error={SECRETO} ref={ref}"
    )


def test_refrescar_prov_500_loguea_cable_n_id(con_sesion, monkeypatch, caplog):
    from core.services.cromo import verificador
    from core.services.prov import frescura

    servicio = MagicMock(servicio_id=7)

    async def _unicos(sesion, cable_n_id):
        return MagicMock(servicios=[servicio])

    async def _vencidos(sesion, ids):
        return {7}

    async def _lote_roto(pendientes):
        raise RuntimeError(SECRETO)

    class _SesionAsync:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr("db.session.AsyncSessionLocal", _SesionAsync)
    monkeypatch.setattr(verificador, "servicios_unicos_por_cable", _unicos)
    monkeypatch.setattr(frescura, "servicios_vencidos", _vencidos)
    monkeypatch.setattr(cromo, "_ejecutar_refresco_prov_lote", _lote_roto)
    con_sesion("user")
    caplog.set_level(logging.INFO, logger="web")

    res = _cliente().post("/api/infra/cromo/cables/55/servicios-unicos/refrescar-prov", json={})

    assert res.status_code == 500
    assert SECRETO not in res.text
    ref = REF.match(res.json()["error"]).group(1)
    assert _registro(caplog, "cromo_servicios_unicos_refrescar_prov") == (
        f"action=cromo_servicios_unicos_refrescar_prov_error cable_n_id=55 error={SECRETO} ref={ref}"
    )


# --- 4xx de dominio: misma respuesta ------------------------------------------------------------------


def test_estado_masivo_error_de_dominio_sigue_dando_400_con_su_mensaje_y_rollback(con_sesion, monkeypatch):
    from core.services import botellas_estado_masivo_service as servicio
    from db import session as db_session

    sesion = MagicMock()
    sesion.__enter__.return_value = sesion
    sesion.__exit__.return_value = False
    monkeypatch.setattr(db_session, "SessionLocal", lambda: sesion)

    def _falla(*args, **kwargs):
        raise servicio.EstadoMasivoError("Origen inválido: 'x'")

    monkeypatch.setattr(servicio, "actualizar_estado_masivo", _falla)
    con_sesion("admin")

    res = _cliente().put(
        "/api/infra/botellas/estado", json={"items": [{"origen": "x", "id": 1}], "estado": "LIBRE"}
    )

    assert res.status_code == 400
    assert res.json() == {"error": "Origen inválido: 'x'"}
    sesion.rollback.assert_called_once()
    sesion.commit.assert_not_called()


def test_regla_del_arbitro_invalida_sigue_dando_422_con_su_mensaje(con_sesion, monkeypatch):
    from core.services.cromo.arbitro import motor

    class _SesionAsync:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def commit(self):
            raise AssertionError("no debe commitear")

    async def _invalida(*args, **kwargs):
        raise ValueError("Modo inválido: 'X'")

    monkeypatch.setattr("db.session.AsyncSessionLocal", _SesionAsync)
    monkeypatch.setattr(motor, "actualizar_regla", _invalida)
    con_sesion("admin")

    res = _cliente().post(
        "/api/admin/infra/arbitro-cromo/reglas",
        json={"codigo": "R1", "modo": "X", "umbral": 1, "presupuesto_por_corrida": 1},
    )

    assert res.status_code == 422
    assert res.json() == {"error": "Modo inválido: 'X'"}


def test_cable_inexistente_sigue_dando_404_con_su_mensaje(con_sesion, monkeypatch):
    from core.services.cromo import verificador

    class _SesionAsync:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    async def _no_existe(sesion, cable_n_id):
        raise verificador.ObjetoNoEncontrado(f"Cable n_id={cable_n_id} no encontrado")

    monkeypatch.setattr("db.session.AsyncSessionLocal", _SesionAsync)
    monkeypatch.setattr(verificador, "servicios_por_cable", _no_existe)
    con_sesion("user")

    res = _cliente().get("/api/infra/cromo/cables/99/servicios")

    assert res.status_code == 404
    assert res.json() == {"error": "Cable n_id=99 no encontrado"}


def test_asociar_huerfanas_registra_el_username_y_no_la_tupla(con_sesion, monkeypatch, caplog):
    """Bug previo a la Task 11: `username = _require_auth(request)` guardaba la tupla (usuario, rol)
    en el log y en la auditoría (`asociar_huerfanas(usuario=...)`). Ahora es el string."""
    from core.services.cromo import orfanas_service
    from db import session as db_session

    sesion = MagicMock()
    sesion.__enter__.return_value = sesion
    sesion.__exit__.return_value = False
    monkeypatch.setattr(db_session, "SessionLocal", lambda: sesion)

    recibido: dict[str, Any] = {}

    def _asociar(session, *, n_ids, camara_id, nombre_nueva_camara, usuario):
        recibido["usuario"] = usuario
        return MagicMock(camara_id=2, camara_creada=False, botellas_vinculadas=1, estado_asignado="LIBRE")

    monkeypatch.setattr(orfanas_service, "asociar_huerfanas", _asociar)
    con_sesion("user", username="pepe")
    caplog.set_level(logging.INFO, logger="web")

    res = _cliente().post("/api/infra/cromo-botellas/asociar", json={"n_ids": [1], "camara_id": 2})

    assert res.status_code == 200
    assert recibido["usuario"] == "pepe"
    (registro,) = [
        r.getMessage() for r in caplog.records if r.name == "web" and r.getMessage().startswith("action=cromo_botellas_asociar ")
    ]
    assert registro.startswith("action=cromo_botellas_asociar user=pepe camara_id=2 ")
    sesion.commit.assert_called_once()


# --- servicios externos: mensaje fijo con ref (error_servicio_externo) -------------------------------


def _registro_unico(caplog, prefijo: str) -> str:
    (registro,) = [r.getMessage() for r in caplog.records if r.name == "web" and r.getMessage().startswith(prefijo)]
    return registro


def test_visor_en_vivo_502_sin_texto_de_cromo_y_con_ref_en_el_log(con_sesion, monkeypatch, caplog):
    import core.services.cromo.client as cromo_client_module
    import core.services.cromo.config as cromo_config_module
    from core.services.cromo.client import CromoClientError

    class _SesionAsync:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _ClienteRoto:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            raise CromoClientError(f"Cromo respondió 500 en /api/objetos: {SECRETO}")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr("db.session.AsyncSessionLocal", _SesionAsync)
    monkeypatch.setattr(cromo_config_module, "get_cromo_config", lambda: None)
    monkeypatch.setattr(cromo_client_module, "CromoClient", _ClienteRoto)
    con_sesion("user")
    caplog.set_level(logging.INFO, logger="web")

    res = _cliente().get("/api/infra/cromo/elementos/123/vivo")

    assert res.status_code == 502
    assert SECRETO not in res.text
    assert list(res.json()) == ["error"]
    ref = re.fullmatch(r"Cromo no respondió \(ref ([0-9a-f]{8})\)", res.json()["error"]).group(1)
    assert _registro_unico(caplog, "action=cromo_elemento_vivo_error") == (
        f"action=cromo_elemento_vivo_error n_id=123 error=Cromo respondió 500 en /api/objetos: {SECRETO} ref={ref}"
    )


def test_refrescar_prov_no_configurado_502_sin_texto_y_un_solo_log(con_sesion, monkeypatch, caplog):
    from core.services.cromo import verificador
    from core.services.prov import frescura
    from core.services.prov.config import ProvConfigError

    async def _unicos(sesion, cable_n_id):
        return MagicMock(servicios=[MagicMock(servicio_id=7)])

    async def _vencidos(sesion, ids):
        return {7}

    async def _lote(pendientes):
        raise ProvConfigError(f"Configuración de PROV incompleta. Definir: {SECRETO}")

    class _SesionAsync:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr("db.session.AsyncSessionLocal", _SesionAsync)
    monkeypatch.setattr(verificador, "servicios_unicos_por_cable", _unicos)
    monkeypatch.setattr(frescura, "servicios_vencidos", _vencidos)
    monkeypatch.setattr(cromo, "_ejecutar_refresco_prov_lote", _lote)
    con_sesion("user")
    caplog.set_level(logging.INFO, logger="web")

    res = _cliente().post("/api/infra/cromo/cables/55/servicios-unicos/refrescar-prov", json={})

    assert res.status_code == 502
    assert SECRETO not in res.text
    ref = re.fullmatch(r"PROV no está configurado \(ref ([0-9a-f]{8})\)", res.json()["error"]).group(1)
    assert _registro_unico(caplog, "action=cromo_servicios_unicos_refrescar_prov") == (
        "action=cromo_servicios_unicos_refrescar_prov_error evento=prov_no_configurado cable_n_id=55 "
        f"error=Configuración de PROV incompleta. Definir: {SECRETO} ref={ref}"
    )


# --- corridas delegadas al worker: el evento ERROR no lleva el texto de la excepción -----------------


@pytest.mark.parametrize(
    ("path", "modulo", "accion", "motivo"),
    [
        (
            "/api/admin/infra/inconsistencias-cromo/deteccion",
            "core.services.cromo.inconsistencias_cromo",
            "cromo_inconsistencias_deteccion",
            "No se pudo delegar la detección al worker de Cromo",
        ),
        (
            "/api/admin/infra/huerfanos/auditoria-global",
            "core.services.cromo.auditoria_huerfanos_global",
            "cromo_huerfanos_auditoria_global",
            "No se pudo delegar la auditoría al worker de Cromo",
        ),
    ],
)
def test_worker_caido_marca_la_corrida_con_motivo_fijo_y_ref(
    con_sesion, monkeypatch, caplog, path, modulo, accion, motivo
):
    import httpx

    class _SesionAsync:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    async def _iniciar(sesion, **kwargs):
        return MagicMock(id=41), None

    class _ClienteHttpRoto:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json):
            raise httpx.ConnectError(f"All connection attempts failed: http://cromo_worker:8096/run {SECRETO}")

    marcadas: list[tuple[int, str]] = []

    async def _marcar(corrida_id, texto):
        marcadas.append((corrida_id, texto))

    monkeypatch.setattr("db.session.AsyncSessionLocal", _SesionAsync)
    monkeypatch.setattr(f"{modulo}.iniciar_si_no_hay_otra", _iniciar)
    monkeypatch.setattr(cromo.httpx, "AsyncClient", _ClienteHttpRoto)
    monkeypatch.setattr(cromo, "_marcar_corrida_fallida", _marcar)
    con_sesion("admin")
    caplog.set_level(logging.INFO, logger="web")

    res = _cliente().post(path, json={})

    assert res.status_code == 503
    assert SECRETO not in res.text
    ((corrida_id, texto),) = marcadas
    assert corrida_id == 41
    assert SECRETO not in texto and "cromo_worker" not in texto
    ref = re.fullmatch(re.escape(motivo) + r" \(ref ([0-9a-f]{8})\)", texto).group(1)
    registro = _registro_unico(caplog, f"action={accion}_error")
    assert registro.startswith(f"action={accion}_error corrida_id=41 error=All connection attempts failed")
    assert SECRETO in registro and registro.endswith(f" ref={ref}")
