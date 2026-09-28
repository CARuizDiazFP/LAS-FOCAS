# Nombre de archivo: test_ingresos_egreso_web.py
# Ubicación de archivo: tests/test_ingresos_egreso_web.py
# Descripción: Pruebas del egreso registrado desde el panel web (servicio registrar_egreso_web + POST /api/infra/ingresos/{id}/egreso)

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from core.services.ingreso_correccion_service import (
    COMANDO_FORZAR_EGRESO,
    FUENTE_MOMENTO_EXPLICITO,
    ORIGEN_WEB,
    RESULTADO_EGRESO_ANTERIOR_AL_INGRESO,
    RESULTADO_INGRESO_NO_ENCONTRADO,
    RESULTADO_INGRESO_YA_CERRADO,
    RESULTADO_MOMENTO_INVALIDO,
    RESULTADO_OK_EGRESO_CERRADO,
    ResultadoCorreccion,
    registrar_egreso_web,
)
from db.models.infra import Camara, Ingreso, IngresoCorreccion, IngresoTipo
from tests.test_web_ingest_camaras import _fake_session_local, _login

AHORA = datetime(2026, 9, 28, 15, 0, tzinfo=timezone.utc)
INICIO = datetime(2026, 9, 10, 13, 21, tzinfo=timezone.utc)
EGRESO = datetime(2026, 9, 10, 16, 0, tzinfo=timezone.utc)


def _ingreso(*, tipo: IngresoTipo = IngresoTipo.INGRESO, fecha_fin: datetime | None = None) -> Ingreso:
    ingreso = Ingreso(
        id=42,
        camara_id=7,
        tecnico_id="rider.fernandez",
        tipo=tipo,
        fecha_inicio=INICIO,
        fecha_fin=fecha_fin,
    )
    ingreso.camara = Camara(id=7, nombre="Cra Quesada y TBA CF")
    return ingreso


def _session(objetivo: Ingreso | None) -> MagicMock:
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = objetivo
    return session


def _auditoria(session: MagicMock) -> IngresoCorreccion:
    filas = [c.args[0] for c in session.add.call_args_list if isinstance(c.args[0], IngresoCorreccion)]
    assert len(filas) == 1, "cada invocación escribe exactamente una fila de auditoría"
    return filas[0]


def _llamar(session: MagicMock, momento: datetime = EGRESO) -> ResultadoCorreccion:
    return registrar_egreso_web(
        session, ingreso_id=42, momento=momento, motivo="formulario de egreso no llegó",
        usuario_web="admin2", ahora=AHORA,
    )


# ── Servicio ───────────────────────────────────────────────────────────────────────────────────


def test_cierra_el_ingreso_abierto_y_audita_como_web():
    objetivo = _ingreso()
    session = _session(objetivo)

    resultado = _llamar(session)

    assert resultado.resultado == RESULTADO_OK_EGRESO_CERRADO
    assert objetivo.fecha_fin == EGRESO
    fila = _auditoria(session)
    assert fila.origen == ORIGEN_WEB
    assert fila.actor_web_usuario == "admin2"
    assert fila.actor_slack_user_id is None and fila.canal_id is None and fila.mensaje_ts is None
    assert fila.comando == COMANDO_FORZAR_EGRESO
    assert fila.ingreso_id == 42
    assert fila.camara_id_resuelta == 7
    assert fila.momento_efectivo == EGRESO
    assert fila.fuente_momento == FUENTE_MOMENTO_EXPLICITO
    assert fila.motivo == "formulario de egreso no llegó"


def test_nunca_crea_una_fila_de_ingreso_nueva():
    """El camino web reusa `cerrar_ingreso_forzado`, no `registrar_movimiento_ingreso` (que crearía
    un EGRESO huérfano si no encontrara la fila): lo único que se agrega a la sesión es auditoría."""
    session = _session(_ingreso())

    _llamar(session)

    assert not [c for c in session.add.call_args_list if isinstance(c.args[0], Ingreso)]


@pytest.mark.parametrize("objetivo", [None, _ingreso(tipo=IngresoTipo.INTENTO_BLOQUEADO)])
def test_rechaza_inexistente_o_intento_bloqueado(objetivo):
    session = _session(objetivo)

    resultado = _llamar(session)

    assert resultado.resultado == RESULTADO_INGRESO_NO_ENCONTRADO
    assert _auditoria(session).resultado == RESULTADO_INGRESO_NO_ENCONTRADO


def test_rechaza_ingreso_ya_cerrado_sin_pisar_la_fecha():
    cerrado = datetime(2026, 9, 10, 15, 0, tzinfo=timezone.utc)
    objetivo = _ingreso(fecha_fin=cerrado)
    session = _session(objetivo)

    resultado = _llamar(session)

    assert resultado.resultado == RESULTADO_INGRESO_YA_CERRADO
    assert objetivo.fecha_fin == cerrado
    assert _auditoria(session).resultado == RESULTADO_INGRESO_YA_CERRADO


@pytest.mark.parametrize("momento", [INICIO, INICIO - timedelta(minutes=1)])
def test_rechaza_egreso_no_posterior_al_ingreso(momento):
    """Estricto: igual a `fecha_inicio` también se rechaza (visita de duración cero)."""
    objetivo = _ingreso()
    session = _session(objetivo)

    resultado = _llamar(session, momento)

    assert resultado.resultado == RESULTADO_EGRESO_ANTERIOR_AL_INGRESO
    assert objetivo.fecha_fin is None


def test_rechaza_egreso_futuro():
    objetivo = _ingreso()
    session = _session(objetivo)

    resultado = _llamar(session, AHORA + timedelta(minutes=5))

    assert resultado.resultado == RESULTADO_MOMENTO_INVALIDO
    assert objetivo.fecha_fin is None
    assert _auditoria(session).resultado == RESULTADO_MOMENTO_INVALIDO


def test_normaliza_momento_con_offset_a_utc():
    """El navegador puede mandar hora local con offset (-03:00): se guarda el mismo instante en UTC."""
    objetivo = _ingreso()
    session = _session(objetivo)

    _llamar(session, datetime(2026, 9, 10, 13, 0, tzinfo=timezone(timedelta(hours=-3))))

    assert objetivo.fecha_fin == EGRESO


# ── Endpoint ───────────────────────────────────────────────────────────────────────────────────

_URL = "/api/infra/ingresos/42/egreso"


def _payload(**extra: Any) -> dict[str, Any]:
    return {"momento": EGRESO.isoformat(), "motivo": "no llegó el egreso", "csrf_token": "x", **extra}


def _cliente(monkeypatch, resultado: str | None = None) -> tuple[TestClient, list[dict[str, Any]]]:
    from web.app import main as web_main

    llamadas: list[dict[str, Any]] = []

    def _fake(session, **kwargs):
        llamadas.append(kwargs)
        ingreso = _ingreso(fecha_fin=kwargs["momento"]) if resultado == RESULTADO_OK_EGRESO_CERRADO else None
        return ResultadoCorreccion(resultado=resultado or "", respuesta="mensaje", comando="X", ingreso=ingreso)

    monkeypatch.setattr("db.session.SessionLocal", _fake_session_local(MagicMock()))
    monkeypatch.setattr("core.services.ingreso_correccion_service.registrar_egreso_web", _fake)
    client = TestClient(web_main.app)
    _login(client, monkeypatch, role="user", password="userpass")
    return client, llamadas


def test_endpoint_ok_delega_con_el_usuario_de_la_sesion(monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    client, llamadas = _cliente(monkeypatch, RESULTADO_OK_EGRESO_CERRADO)

    response = client.post(_URL, json=_payload())

    assert response.status_code == 200
    assert response.json()["ingreso"]["fecha_fin"] == EGRESO.isoformat()
    assert llamadas[0]["ingreso_id"] == 42
    assert llamadas[0]["usuario_web"] == "user"
    assert llamadas[0]["motivo"] == "no llegó el egreso"


@pytest.mark.parametrize(
    ("resultado", "status"),
    [
        (RESULTADO_INGRESO_NO_ENCONTRADO, 404),
        (RESULTADO_INGRESO_YA_CERRADO, 409),
        (RESULTADO_EGRESO_ANTERIOR_AL_INGRESO, 422),
        (RESULTADO_MOMENTO_INVALIDO, 422),
    ],
)
def test_endpoint_mapea_rechazos_de_negocio(monkeypatch, resultado, status):
    monkeypatch.setenv("TESTING", "true")
    client, _ = _cliente(monkeypatch, resultado)

    response = client.post(_URL, json=_payload())

    assert response.status_code == status
    assert response.json() == {"error": "mensaje", "resultado": resultado}


def test_endpoint_rechaza_momento_sin_zona_horaria(monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    client, llamadas = _cliente(monkeypatch, RESULTADO_OK_EGRESO_CERRADO)

    response = client.post(_URL, json=_payload(momento="2026-09-10T16:00:00"))

    assert response.status_code == 422
    assert llamadas == []


def test_endpoint_rechaza_motivo_vacio(monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    client, llamadas = _cliente(monkeypatch, RESULTADO_OK_EGRESO_CERRADO)

    response = client.post(_URL, json=_payload(motivo="   "))

    assert response.status_code == 422
    assert llamadas == []


def test_endpoint_exige_csrf_valido(monkeypatch):
    monkeypatch.setenv("TESTING", "false")
    client, llamadas = _cliente(monkeypatch, RESULTADO_OK_EGRESO_CERRADO)

    response = client.post(_URL, json=_payload(csrf_token="token-falso"))

    assert response.status_code == 403
    assert llamadas == []


def test_endpoint_exige_sesion(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setenv("TESTING", "true")
    response = TestClient(web_main.app).post(_URL, json=_payload())

    assert response.status_code == 401
