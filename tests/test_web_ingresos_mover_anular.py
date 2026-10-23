# Nombre de archivo: test_web_ingresos_mover_anular.py
# Ubicación de archivo: tests/test_web_ingresos_mover_anular.py
# Descripción: Endpoints admin mover/anular ingreso (status, CSRF, rol) y listados que excluyen anulados

"""Capa HTTP de la corrección de ingresos desde el portal (Task 3, 2026-10-23).

Las reglas de negocio (validaciones, auditoría, FO Monitor) están cubiertas en
`tests/test_ingresos_mover_anular*.py`; acá se prueba sólo lo que agrega el router: sesión admin,
CSRF, mapeo resultado → status/cuerpo, la forma de la respuesta y que los listados excluyen los
anulados salvo que un admin pida `?incluir_anulados=1`. Al final, un test real contra el Postgres de
dev (con rollback) recorre los endpoints de punta a punta."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from core.services import ingreso_correccion_service as ics
from core.services.ingreso_correccion_service import IntervencionFomonOmitida, ResultadoCorreccion
from db.models.infra import IngresoTipo
from tests.soporte_postgres_real import requiere_postgres_real
from tests.test_web_infra_camera_state import (
    _build_aliases,
    _build_auditoria,
    _build_baneos,
    _build_contexto,
    _build_fake_camara,
    _build_servicio,
    _build_servicio_camaras,
    _FakeQuery,
    _InfraDetailSession,
    _ServicioIngresosSession,
    _SessionScope,
)
from tests.test_web_ingest_camaras import _fake_session_local, _login

REF = re.compile(r"^Error interno \(ref ([0-9a-f]{8})\)$")
SECRETO = "secreto-interno-xyz"
URL_MOVER = "/api/admin/infra/ingresos/42/mover"
URL_ANULAR = "/api/admin/infra/ingresos/42/anular"
INICIO = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
ANULADO_AT = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


def _cliente() -> TestClient:
    return TestClient(_app(), raise_server_exceptions=False)


def _app():
    from web.app.main import app

    return app


@pytest.fixture(autouse=True)
def _modo_test(monkeypatch):
    # CSRF se valida salvo con TESTING=true; los tests de CSRF lo apagan explícitamente.
    monkeypatch.setenv("TESTING", "true")


def _ingreso(**extra: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": 42,
        "camara_id": 9,
        "camara": SimpleNamespace(nombre="Cámara Destino", camara_padre_id=None),
        "fecha_inicio": INICIO,
        "fecha_fin": None,
        "tecnico_id": "tecnico.lopez",
        "cromo_botella_id": None,
        "cromo_botella": None,
        "tipo": IngresoTipo.INGRESO,
        "anulado_at": None,
        "anulado_por": None,
        "anulado_motivo": None,
    }
    base.update(extra)
    return SimpleNamespace(**base)


def _instalar_servicio(monkeypatch, funcion: str, resultado: str, *, ingreso: Any = None, **campos: Any):
    """Reemplaza `ics.<funcion>` por un fake que registra los kwargs y devuelve `resultado`."""
    llamadas: list[dict[str, Any]] = []

    def _fake(session, **kwargs):
        llamadas.append(kwargs)
        return ResultadoCorreccion(
            resultado=resultado, respuesta=f"texto de {resultado}", comando="X", ingreso=ingreso, **campos
        )

    monkeypatch.setattr("db.session.SessionLocal", _fake_session_local(MagicMock()))
    monkeypatch.setattr(ics, funcion, _fake)
    return llamadas


# ── Mover ──────────────────────────────────────────────────────────────────────────────────────


def test_mover_ok_delega_con_el_usuario_de_la_sesion_y_serializa(con_sesion, monkeypatch):
    con_sesion("admin", username="ana.admin")
    llamadas = _instalar_servicio(
        monkeypatch,
        "mover_ingreso_web",
        ics.RESULTADO_OK_INGRESO_MOVIDO,
        ingreso=_ingreso(cromo_botella_id=555, cromo_botella=SimpleNamespace(nombre="Bot 2")),
        intervenciones_fomon=[7],
        intervenciones_fomon_omitidas=[IntervencionFomonOmitida(8, ics.OMISION_CONSULTAS_YA_ENVIADAS)],
    )

    res = _cliente().post(
        URL_MOVER, json={"camara_destino_id": 9, "cromo_botella_destino_n_id": 555, "motivo": "  fontaine mal  "}
    )

    assert res.status_code == 200
    assert llamadas == [
        {
            "ingreso_id": 42,
            "camara_destino_id": 9,
            "cromo_botella_destino_n_id": 555,
            "motivo": "  fontaine mal  ",  # el servicio recorta y valida (y audita el rechazo)
            "usuario": "ana.admin",
        }
    ]
    cuerpo = res.json()
    assert cuerpo["ok"] is True
    assert cuerpo["resultado"] == ics.RESULTADO_OK_INGRESO_MOVIDO
    assert cuerpo["mensaje"] == f"texto de {ics.RESULTADO_OK_INGRESO_MOVIDO}"
    assert cuerpo["ingreso"] == {
        "id": 42,
        "fecha_inicio": INICIO.isoformat(),
        "fecha_fin": None,
        "tecnico_id": "tecnico.lopez",
        "cromo_botella_id": 555,
        "botella_label": "Bot 2",
        "tipo": "INGRESO",
        "anulado": False,
        "anulado_at": None,
        "anulado_por": None,
        "anulado_motivo": None,
        "camara_id": 9,
        "camara_nombre": "Cámara Destino",
    }
    assert cuerpo["intervenciones_fomon"] == [7]
    assert cuerpo["intervenciones_fomon_omitidas"] == [
        {"intervencion_id": 8, "motivo": ics.OMISION_CONSULTAS_YA_ENVIADAS}
    ]


def test_mover_sin_botella_manda_none(con_sesion, monkeypatch):
    con_sesion("admin")
    llamadas = _instalar_servicio(
        monkeypatch, "mover_ingreso_web", ics.RESULTADO_OK_INGRESO_MOVIDO, ingreso=_ingreso()
    )

    res = _cliente().post(URL_MOVER, json={"camara_destino_id": 9, "motivo": "cámara equivocada"})

    assert res.status_code == 200
    assert llamadas[0]["cromo_botella_destino_n_id"] is None
    assert res.json()["ingreso"]["botella_label"] == "Botella 1"


@pytest.mark.parametrize(
    ("resultado", "status"),
    [
        (ics.RESULTADO_INGRESO_NO_ENCONTRADO, 404),
        (ics.RESULTADO_CAMARA_NO_ENCONTRADA, 404),
        (ics.RESULTADO_MOTIVO_INVALIDO, 422),
        (ics.RESULTADO_BOTELLA_INVALIDA, 422),
        (ics.RESULTADO_INGRESO_ANULADO, 409),
        (ics.RESULTADO_MISMO_DESTINO, 409),
    ],
)
def test_mover_mapea_rechazos_a_errores_tipados(con_sesion, monkeypatch, resultado, status):
    con_sesion("admin")
    _instalar_servicio(monkeypatch, "mover_ingreso_web", resultado)

    res = _cliente().post(URL_MOVER, json={"camara_destino_id": 9, "motivo": "motivo"})

    assert res.status_code == status
    assert res.json() == {"error": f"texto de {resultado}"}


def test_mover_body_invalido_da_422_sin_llamar_al_servicio(con_sesion, monkeypatch):
    con_sesion("admin")
    llamadas = _instalar_servicio(monkeypatch, "mover_ingreso_web", ics.RESULTADO_OK_INGRESO_MOVIDO)

    sin_destino = _cliente().post(URL_MOVER, json={"motivo": "motivo"})
    motivo_abusivo = _cliente().post(URL_MOVER, json={"camara_destino_id": 9, "motivo": "x" * 2001})

    assert sin_destino.status_code == 422
    assert motivo_abusivo.status_code == 422
    assert llamadas == []


# ── Anular ─────────────────────────────────────────────────────────────────────────────────────


def test_anular_ok_delega_con_el_usuario_de_la_sesion_y_serializa(con_sesion, monkeypatch):
    con_sesion("admin", username="ana.admin")
    ingreso = _ingreso(anulado_at=ANULADO_AT, anulado_por="ana.admin", anulado_motivo="nunca ocurrió")
    llamadas = _instalar_servicio(
        monkeypatch,
        "anular_ingreso_web",
        ics.RESULTADO_OK_INGRESO_ANULADO,
        ingreso=ingreso,
        intervenciones_fomon=[3],
        intervenciones_fomon_omitidas=[IntervencionFomonOmitida(4, ics.OMISION_OTROS_INGRESOS_VIGENTES)],
    )

    res = _cliente().post(URL_ANULAR, json={"motivo": "nunca ocurrió"})

    assert res.status_code == 200
    assert llamadas == [{"ingreso_id": 42, "motivo": "nunca ocurrió", "usuario": "ana.admin"}]
    cuerpo = res.json()
    assert cuerpo["resultado"] == ics.RESULTADO_OK_INGRESO_ANULADO
    assert cuerpo["ingreso"]["anulado"] is True
    assert cuerpo["ingreso"]["anulado_at"] == ANULADO_AT.isoformat()
    assert cuerpo["ingreso"]["anulado_por"] == "ana.admin"
    assert cuerpo["ingreso"]["anulado_motivo"] == "nunca ocurrió"
    assert cuerpo["intervenciones_fomon"] == [3]
    assert cuerpo["intervenciones_fomon_omitidas"] == [
        {"intervencion_id": 4, "motivo": ics.OMISION_OTROS_INGRESOS_VIGENTES}
    ]


@pytest.mark.parametrize(
    ("resultado", "status"),
    [
        (ics.RESULTADO_INGRESO_NO_ENCONTRADO, 404),
        (ics.RESULTADO_MOTIVO_INVALIDO, 422),
        (ics.RESULTADO_INGRESO_ANULADO, 409),
    ],
)
def test_anular_mapea_rechazos_a_errores_tipados(con_sesion, monkeypatch, resultado, status):
    con_sesion("admin")
    _instalar_servicio(monkeypatch, "anular_ingreso_web", resultado)

    res = _cliente().post(URL_ANULAR, json={"motivo": "motivo"})

    assert res.status_code == status
    assert res.json() == {"error": f"texto de {resultado}"}


def test_anular_sin_motivo_da_422_sin_llamar_al_servicio(con_sesion, monkeypatch):
    con_sesion("admin")
    llamadas = _instalar_servicio(monkeypatch, "anular_ingreso_web", ics.RESULTADO_OK_INGRESO_ANULADO)

    res = _cliente().post(URL_ANULAR, json={})

    assert res.status_code == 422
    assert llamadas == []


# ── Comunes: rol, sesión, CSRF, 500 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("url", "cuerpo", "funcion"),
    [
        (URL_MOVER, {"camara_destino_id": 9, "motivo": "motivo"}, "mover_ingreso_web"),
        (URL_ANULAR, {"motivo": "motivo"}, "anular_ingreso_web"),
    ],
)
def test_usuario_comun_recibe_403_y_no_llama_al_servicio(con_sesion, monkeypatch, url, cuerpo, funcion):
    con_sesion("user")
    llamadas = _instalar_servicio(monkeypatch, funcion, "OK")

    res = _cliente().post(url, json=cuerpo)

    assert res.status_code == 403
    assert res.json() == {"detail": "Permisos insuficientes"}
    assert llamadas == []


@pytest.mark.parametrize("url", [URL_MOVER, URL_ANULAR])
def test_sin_sesion_da_401(con_sesion, url):
    con_sesion(None)

    res = _cliente().post(url, json={})

    assert res.status_code == 401


@pytest.mark.parametrize(
    ("url", "cuerpo", "funcion", "ok"),
    [
        (URL_MOVER, {"camara_destino_id": 9, "motivo": "motivo"}, "mover_ingreso_web", ics.RESULTADO_OK_INGRESO_MOVIDO),
        (URL_ANULAR, {"motivo": "motivo"}, "anular_ingreso_web", ics.RESULTADO_OK_INGRESO_ANULADO),
    ],
)
def test_csrf_se_exige_fuera_de_testing(monkeypatch, url, cuerpo, funcion, ok):
    """Login real por cookie (la sesión trae el token CSRF), con TESTING apagado."""
    monkeypatch.setenv("TESTING", "false")
    llamadas = _instalar_servicio(monkeypatch, funcion, ok, ingreso=_ingreso())
    client = TestClient(_app())
    csrf = _login(client, monkeypatch, role="admin", password="adminpass")

    sin_token = client.post(url, json=cuerpo)
    token_falso = client.post(url, json={**cuerpo, "csrf_token": "token-falso"})
    assert sin_token.status_code == 403
    assert token_falso.status_code == 403
    assert sin_token.json() == {"error": "CSRF inválido"}
    assert llamadas == []

    valido = client.post(url, json={**cuerpo, "csrf_token": csrf})
    assert valido.status_code == 200
    assert len(llamadas) == 1


@pytest.mark.parametrize(
    ("url", "cuerpo", "funcion", "accion"),
    [
        (URL_MOVER, {"camara_destino_id": 9, "motivo": "motivo"}, "mover_ingreso_web", "admin_mover_ingreso"),
        (URL_ANULAR, {"motivo": "motivo"}, "anular_ingreso_web", "admin_anular_ingreso"),
    ],
)
def test_excepcion_del_servicio_da_500_con_ref_sin_exponer_texto(
    con_sesion, monkeypatch, caplog, url, cuerpo, funcion, accion
):
    con_sesion("admin")

    def _roto(session, **kwargs):
        raise RuntimeError(SECRETO)

    monkeypatch.setattr("db.session.SessionLocal", _fake_session_local(MagicMock()))
    monkeypatch.setattr(ics, funcion, _roto)

    with caplog.at_level(logging.ERROR, logger="web"):
        res = _cliente().post(url, json=cuerpo)

    assert res.status_code == 500
    error = res.json()["error"]
    assert SECRETO not in error
    ref = REF.match(error).group(1)
    (registro,) = [r for r in caplog.records if r.getMessage().startswith(f"action={accion}_error")]
    assert f"ref={ref}" in registro.getMessage()
    assert "ingreso_id=42" in registro.getMessage()


@pytest.mark.parametrize(
    ("url", "cuerpo", "funcion"),
    [
        (URL_MOVER, {"camara_destino_id": 9, "motivo": "motivo"}, "mover_ingreso_web"),
        (URL_ANULAR, {"motivo": "motivo"}, "anular_ingreso_web"),
    ],
)
def test_resultado_desconocido_es_500_no_200(con_sesion, monkeypatch, url, cuerpo, funcion):
    con_sesion("admin")
    _instalar_servicio(monkeypatch, funcion, "RESULTADO_QUE_NO_EXISTE")

    res = _cliente().post(url, json=cuerpo)

    assert res.status_code == 500
    assert REF.match(res.json()["error"])


# ── Listados: anulados excluidos salvo admin con ?incluir_anulados ─────────────────────────────


def _es_filtro_vigente(clausula: Any) -> bool:
    return "anulado_at IS NULL" in str(clausula)


class _QueryIngresos(_FakeQuery):
    """Aplica de verdad el filtro de vigencia sobre la lista fake: si la query recibió
    `Ingreso.vigente()`, devuelve sólo los no anulados (lo demás no se filtra, como `_FakeQuery`)."""

    def __init__(self, many: list[Any]):
        super().__init__(many=many)
        self.filtro_vigente = False

    def filter(self, *clausulas, **kwargs):
        if any(_es_filtro_vigente(c) for c in clausulas):
            self.filtro_vigente = True
        return self

    def all(self):
        if self.filtro_vigente:
            return [i for i in self._many if i.anulado_at is None]
        return list(self._many)


def _ingresos_mixtos() -> list[Any]:
    vigente = _ingreso(id=1, camara_id=7)
    anulado = _ingreso(
        id=2, camara_id=7, anulado_at=ANULADO_AT, anulado_por="ana.admin", anulado_motivo="nunca ocurrió"
    )
    return [vigente, anulado]


def _instalar_registros(monkeypatch) -> None:
    from core.services import camara_estado_service
    from db import session as db_session

    sesion = _InfraDetailSession(
        _build_fake_camara(), _build_aliases(), _build_auditoria(), _build_baneos(), _ingresos_mixtos()
    )
    sesion_query = sesion.query

    def _query(*entidades):
        if getattr(entidades[0], "__name__", "") == "Ingreso":
            return _QueryIngresos(_ingresos_mixtos())
        return sesion_query(*entidades)

    sesion.query = _query
    monkeypatch.setattr(db_session, "SessionLocal", _SessionScope(sesion))
    monkeypatch.setattr(camara_estado_service, "get_camara_estado_contexto", lambda session, camara_id: _build_contexto())


def _instalar_servicio_ingresos(monkeypatch) -> None:
    from core.services.protection_service import ProtectionService
    from db import session as db_session

    sesion = _ServicioIngresosSession(_build_servicio(), [])
    sesion_query = sesion.query

    def _query(*entidades):
        if getattr(entidades[0], "__name__", "") == "Ingreso":
            return _QueryIngresos(_ingresos_mixtos())
        return sesion_query(*entidades)

    sesion.query = _query
    monkeypatch.setattr(db_session, "SessionLocal", _SessionScope(sesion))
    monkeypatch.setattr(ProtectionService, "get_camaras_for_servicio", lambda self, sid: _build_servicio_camaras())


# (rol, query string, ids esperados): el parámetro sólo tiene efecto para un admin; a un usuario común
# se le ignora sin error.
_CASOS_LISTADO = [
    ("user", "", [1]),
    ("user", "?incluir_anulados=1", [1]),
    ("user", "?incluir_anulados=true", [1]),
    ("admin", "", [1]),
    ("admin", "?incluir_anulados=0", [1]),
    ("admin", "?incluir_anulados=1", [1, 2]),
    ("admin", "?incluir_anulados=true", [1, 2]),
]


@pytest.mark.parametrize(("rol", "qs", "ids"), _CASOS_LISTADO)
def test_registros_de_camara_excluye_anulados_salvo_admin(con_sesion, monkeypatch, rol, qs, ids):
    con_sesion(rol)
    _instalar_registros(monkeypatch)

    res = _cliente().get(f"/api/infra/camaras/7/registros{qs}")

    assert res.status_code == 200
    ingresos = res.json()["ingresos"]
    assert [i["id"] for i in ingresos] == ids
    if 2 in ids:
        anulado = ingresos[1]
        assert anulado["anulado"] is True
        assert anulado["anulado_por"] == "ana.admin"
        assert anulado["anulado_motivo"] == "nunca ocurrió"
        assert anulado["anulado_at"] == ANULADO_AT.isoformat()
    assert ingresos[0]["anulado"] is False


@pytest.mark.parametrize(("rol", "qs", "ids"), _CASOS_LISTADO)
def test_ingresos_de_servicio_excluye_anulados_salvo_admin(con_sesion, monkeypatch, rol, qs, ids):
    con_sesion(rol)
    _instalar_servicio_ingresos(monkeypatch)

    res = _cliente().get(f"/api/infra/servicios/2001/ingresos{qs}")

    assert res.status_code == 200
    cuerpo = res.json()
    assert [i["id"] for i in cuerpo["ingresos"]] == ids
    # `total` cuenta siempre sólo los vigentes; `total_anulados` aparece sólo si se incluyeron.
    assert cuerpo["total"] == 1
    if 2 in ids:
        assert cuerpo["total_anulados"] == 1
    else:
        assert "total_anulados" not in cuerpo


def test_listado_con_parametro_invalido_da_422(con_sesion, monkeypatch):
    con_sesion("admin")
    _instalar_registros(monkeypatch)

    res = _cliente().get("/api/infra/camaras/7/registros?incluir_anulados=quizas")

    assert res.status_code == 422


# ── Real contra el Postgres de dev (rollback) ──────────────────────────────────────────────────


@pytest.fixture
def sesion_real():
    from sqlalchemy.orm import Session

    from db.session import engine

    conn = engine.connect()
    trans = conn.begin()
    s = Session(bind=conn, join_transaction_mode="create_savepoint", autoflush=False)
    try:
        yield s
    finally:
        s.close()
        trans.rollback()
        conn.close()


def _camaras_raiz_sin_ingresos(s: Any, cantidad: int) -> list[Any]:
    from sqlalchemy import text

    from db.models.infra import Camara

    ids = s.execute(
        text(
            """
            SELECT c.id FROM app.camaras c
            WHERE c.camara_padre_id IS NULL
              AND NOT EXISTS (SELECT 1 FROM app.camaras h WHERE h.camara_padre_id = c.id)
              AND NOT EXISTS (SELECT 1 FROM app.ingresos i WHERE i.camara_id = c.id)
            ORDER BY c.id
            LIMIT :n
            """
        ),
        {"n": cantidad},
    ).scalars().all()
    assert len(ids) == cantidad, "dev necesita cámaras raíz sin ingresos ni botellas hijas"
    return [s.get(Camara, i) for i in ids]


@requiere_postgres_real
def test_real_anular_y_mover_por_http_y_listados(con_sesion, monkeypatch, sesion_real):
    """Punta a punta contra dev: los POST pasan por el servicio real (auditoría incluida) y los GET
    por la query real con `Ingreso.vigente()`. Todo se revierte al final."""
    from db.models.infra import Ingreso, IngresoCorreccion
    from web.app.routers import servicios as servicios_router

    s = sesion_real
    origen, destino = _camaras_raiz_sin_ingresos(s, 2)
    ahora = datetime.now(timezone.utc)
    a_anular, a_mover = (
        Ingreso(
            camara_id=origen.id, tecnico_id="TEST-WEB-MOVER-ANULAR", tipo=IngresoTipo.INGRESO,
            fecha_inicio=ahora - timedelta(hours=h), canal_id="CTEST",
        )
        for h in (2, 1)
    )
    s.add_all([a_anular, a_mover])
    s.flush()

    monkeypatch.setattr("db.session.SessionLocal", _fake_session_local(s))
    monkeypatch.setattr(
        servicios_router, "_find_servicio_por_identificador_web",
        lambda session, sid: SimpleNamespace(servicio_id=sid),
    )
    from core.services.protection_service import ProtectionService

    monkeypatch.setattr(ProtectionService, "get_camaras_for_servicio", lambda self, sid: [origen, destino])
    cliente = _cliente()

    con_sesion("admin", username="test-web-admin")
    res = cliente.post(f"/api/admin/infra/ingresos/{a_anular.id}/anular", json={"motivo": " nunca ocurrió "})
    assert res.status_code == 200, res.text
    assert res.json()["ingreso"]["anulado"] is True
    assert res.json()["ingreso"]["anulado_motivo"] == "nunca ocurrió"
    assert res.json()["ingreso"]["anulado_por"] == "test-web-admin"

    res = cliente.post(
        f"/api/admin/infra/ingresos/{a_mover.id}/mover", json={"camara_destino_id": destino.id, "motivo": "otra"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["ingreso"]["camara_id"] == destino.id
    assert res.json()["ingreso"]["camara_nombre"] == destino.nombre

    res = cliente.post(f"/api/admin/infra/ingresos/{a_anular.id}/anular", json={"motivo": "de nuevo"})
    assert res.status_code == 409
    res = cliente.post(
        f"/api/admin/infra/ingresos/{a_anular.id}/mover", json={"camara_destino_id": destino.id, "motivo": "x y z"}
    )
    assert res.status_code == 409

    auditoria = (
        s.query(IngresoCorreccion)
        .filter(IngresoCorreccion.ingreso_id.in_([a_anular.id, a_mover.id]))
        .filter(IngresoCorreccion.actor_web_usuario == "test-web-admin")
        .all()
    )
    assert sorted(f.comando for f in auditoria) == sorted(
        [ics.COMANDO_ANULAR_INGRESO, ics.COMANDO_MOVER_INGRESO, ics.COMANDO_ANULAR_INGRESO, ics.COMANDO_MOVER_INGRESO]
    )

    def _ids_registros(camara_id: int, qs: str = "") -> list[int]:
        r = cliente.get(f"/api/infra/camaras/{camara_id}/registros{qs}")
        assert r.status_code == 200, r.text
        return [i["id"] for i in r.json()["ingresos"]]

    def _servicio(qs: str = "") -> dict[str, Any]:
        r = cliente.get(f"/api/infra/servicios/SVC-TEST/ingresos{qs}")
        assert r.status_code == 200, r.text
        return r.json()

    # Admin sin pedirlos: el anulado no aparece; el movido está en el destino.
    assert _ids_registros(origen.id) == []
    assert _ids_registros(destino.id) == [a_mover.id]
    assert _ids_registros(origen.id, "?incluir_anulados=1") == [a_anular.id]
    servicio = _servicio()
    assert [i["id"] for i in servicio["ingresos"]] == [a_mover.id]
    assert servicio["total"] == 1
    servicio = _servicio("?incluir_anulados=1")
    assert [i["id"] for i in servicio["ingresos"]] == [a_mover.id, a_anular.id]
    assert servicio["total"] == 1
    assert servicio["total_anulados"] == 1

    # Usuario común: el parámetro se ignora.
    con_sesion("user")
    assert _ids_registros(origen.id, "?incluir_anulados=1") == []
    servicio = _servicio("?incluir_anulados=1")
    assert [i["id"] for i in servicio["ingresos"]] == [a_mover.id]
    assert "total_anulados" not in servicio
