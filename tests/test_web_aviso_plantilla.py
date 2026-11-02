# Nombre de archivo: test_web_aviso_plantilla.py
# Ubicación de archivo: tests/test_web_aviso_plantilla.py
# Descripción: P27 — el panel y la API guardan asunto y cuerpo del aviso de baneo al descargar el .eml y al enviar por SMTP

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.services import baneo_aviso
from core.services.baneo_aviso import (
    ENVOLTORIO_TEXTO_AVISO,
    armar_y_guardar_eml_baneo,
    enviar_aviso_baneo,
    guardar_plantilla_aviso,
    texto_a_html_aviso,
)
from core.services.email_service import EmailResult
from tests.soporte_login import login_con_rol

RAIZ = Path(__file__).resolve().parents[1]
TEXTO = "Estimados,\n\nTicket: T-1\n  Motivo: a < b & c\n\nSaludos"


class _Consulta:
    """`query(IncidenteBaneo).filter(IncidenteBaneo.id == x)` o `.in_([...])`, filtrando de verdad por id."""

    def __init__(self, datos: list, criterio) -> None:
        valor = criterio.right.value
        ids = set(valor) if isinstance(valor, (list, tuple, set)) else {valor}
        self._datos = [d for d in datos if d.id in ids]

    def first(self):
        return self._datos[0] if self._datos else None

    def all(self) -> list:
        return list(self._datos)


class _Sesion:
    def __init__(self, incidentes: list) -> None:
        self.incidentes = incidentes
        self.commits = 0
        self.rollbacks = 0

    def query(self, _modelo):
        return SimpleNamespace(filter=lambda criterio: _Consulta(self.incidentes, criterio))

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def _incidente(id_: int, *, subject: str | None = None, body: str | None = None):
    return SimpleNamespace(
        id=id_, servicio_protegido_id="S1", ruta_protegida_id=None, ticket_asociado=f"T-{id_}",
        servicio_afectado_id="SA", motivo="Obra", fecha_inicio=None,
        email_subject=subject, email_body=body,
    )


@pytest.fixture
def sin_camaras(monkeypatch):
    class _Proteccion:
        def __init__(self, _sesion) -> None: ...

        def get_camaras_for_servicio(self, *_a):
            return []

    monkeypatch.setattr(baneo_aviso, "ProtectionService", _Proteccion)


def _smtp(monkeypatch, exito: bool = True) -> list[dict]:
    enviados: list[dict] = []

    def _send_email(**kwargs):
        enviados.append(kwargs)
        return EmailResult(exito, "ok" if exito else "fallo")

    servicio = SimpleNamespace(is_configured=lambda: True, send_email=_send_email)
    monkeypatch.setattr(baneo_aviso, "get_email_service", lambda: servicio)
    return enviados


# ── core: guardar_plantilla_aviso ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("vacio", [None, "", "   \n"])
def test_guardar_vacio_no_toca_lo_guardado(vacio):
    inc = _incidente(5, subject="viejo", body="<p>viejo</p>")
    sesion = _Sesion([inc])
    guardar_plantilla_aviso(sesion, 5, vacio, vacio)
    assert (inc.email_subject, inc.email_body, sesion.commits) == ("viejo", "<p>viejo</p>", 0)


def test_guardar_pisa_solo_el_incidente_pedido():
    inc, otro = _incidente(5, subject="viejo", body="b"), _incidente(6, subject="otro", body="o")
    sesion = _Sesion([inc, otro])
    guardar_plantilla_aviso(sesion, 5, "nuevo", None, usuario="ana")
    assert (inc.email_subject, inc.email_body) == ("nuevo", "b")
    assert (otro.email_subject, otro.email_body) == ("otro", "o")


def test_guardar_loguea_sin_el_cuerpo(caplog):
    sesion = _Sesion([_incidente(5)])
    with caplog.at_level(logging.INFO, logger="core.services.baneo_aviso"):
        guardar_plantilla_aviso(sesion, 5, "Asunto", "<div>cuerpo secreto</div>", usuario="ana")
    linea = next(r.getMessage() for r in caplog.records if "guardar_plantilla_aviso" in r.getMessage())
    assert "action=guardar_plantilla_aviso user=ana incident_id=5" in linea
    assert "cuerpo secreto" not in linea and "Asunto" not in linea


# ── core: envoltorio de texto (mismo formato que el front) ─────────────────────────────────────────


def test_texto_a_html_aviso_escapa_y_envuelve_como_el_front():
    assert texto_a_html_aviso("a<b>&\"'") == f"{ENVOLTORIO_TEXTO_AVISO}a&lt;b&gt;&amp;&quot;&#39;</div>"
    front = (RAIZ / "web/frontend/src/utils/textoPlanoAHtml.ts").read_text(encoding="utf-8")
    assert ENVOLTORIO_TEXTO_AVISO in front  # si cambia el envoltorio del front, cambia acá también
    lector = (RAIZ / "web/frontend/src/utils/htmlAvisoATexto.ts").read_text(encoding="utf-8")
    assert "textoDeEnvoltorioPreWrap" in lector and "pre-wrap" in lector


# ── core: .eml ─────────────────────────────────────────────────────────────────────────────────────


def test_eml_guarda_asunto_y_cuerpo_finales(sin_camaras):
    inc = _incidente(5)
    sesion = _Sesion([inc, _incidente(6, subject="otro")])
    eml = armar_y_guardar_eml_baneo(
        sesion, 5, destinatarios=["a@b.c"], subject="Aviso {{x}}", html_body="<p>{{ticket}}</p>",
        include_xls=False, include_txt=False,
    )
    assert eml is not None
    assert inc.email_subject == eml.subject == "Aviso {{x}}"
    assert inc.email_body == eml.html_body == "<p>T-5</p>"  # variables ya reemplazadas, igual que en el .eml
    assert sesion.incidentes[1].email_subject == "otro"


def test_eml_vacio_usa_la_plantilla_pero_no_pisa_lo_guardado(sin_camaras):
    inc = _incidente(5, subject="guardado", body="<p>guardado</p>")
    eml = armar_y_guardar_eml_baneo(
        _Sesion([inc]), 5, destinatarios=[], subject="", html_body="",
        include_xls=False, include_txt=False,
    )
    assert eml.subject == "AVISO DE BANEO - Ticket T-5" and "Protocolo de Protección" in eml.html_body
    assert (inc.email_subject, inc.email_body) == ("guardado", "<p>guardado</p>")


def test_eml_incidente_inexistente_no_guarda(sin_camaras):
    sesion = _Sesion([_incidente(6)])
    assert armar_y_guardar_eml_baneo(sesion, 5, destinatarios=[], subject="s", html_body="b") is None
    assert sesion.commits == 0


def test_eml_error_al_guardar_no_corta_la_descarga(sin_camaras, monkeypatch):
    sesion = _Sesion([_incidente(5)])

    def _falla():
        raise RuntimeError("db caída")

    monkeypatch.setattr(sesion, "commit", _falla)
    eml = armar_y_guardar_eml_baneo(
        sesion, 5, destinatarios=[], subject="s", html_body="b", include_xls=False, include_txt=False
    )
    assert eml is not None and sesion.rollbacks == 1


# ── core: envío SMTP ───────────────────────────────────────────────────────────────────────────────


def _enviar(sesion, ids, body=TEXTO, subject="Asunto"):
    return enviar_aviso_baneo(
        sesion, to=["a@b.c"], cc=None, subject=subject, body=body, incidente_ids=ids,
        include_xls=False, include_txt=False, usuario="ana",
    )


def test_smtp_exitoso_un_incidente_guarda_el_texto_envuelto(monkeypatch):
    enviados = _smtp(monkeypatch)
    inc = _incidente(5)
    assert _enviar(_Sesion([inc]), [5], body=f"  {TEXTO}\n").success
    assert enviados[0]["body"] == f"  {TEXTO}\n"  # el correo sale igual que antes
    assert inc.email_subject == "Asunto" and inc.email_body == texto_a_html_aviso(TEXTO)


def test_smtp_varios_incidentes_no_guarda(monkeypatch):
    _smtp(monkeypatch)
    a, b = _incidente(5), _incidente(6)
    assert _enviar(_Sesion([a, b]), [5, 6]).success
    assert (a.email_body, b.email_body, a.email_subject) == (None, None, None)


def test_smtp_fallido_no_guarda(monkeypatch):
    _smtp(monkeypatch, exito=False)
    inc = _incidente(5)
    assert not _enviar(_Sesion([inc]), [5]).success
    assert (inc.email_subject, inc.email_body) == (None, None)


def test_smtp_cuerpo_vacio_guarda_solo_el_asunto(monkeypatch):
    _smtp(monkeypatch)
    inc = _incidente(5, body="<p>guardado</p>")
    _enviar(_Sesion([inc]), [5], body="  ")
    assert (inc.email_subject, inc.email_body) == ("Asunto", "<p>guardado</p>")


# ── rutas: panel (JSON, sesión + CSRF real) y API (formulario) ─────────────────────────────────────


@pytest.fixture
def panel(monkeypatch, csrf_real, sin_camaras):
    from web.app.main import app

    client = TestClient(app)
    csrf = login_con_rol(client, monkeypatch, role="user", password="userpass")
    sesion = _Sesion([_incidente(5, subject="viejo", body="<p>viejo</p>"), _incidente(6, subject="otro")])
    monkeypatch.setattr("db.session.SessionLocal", lambda: sesion)
    return client, csrf, sesion


def _eml_panel(client, csrf, **extra):
    datos = {
        "incident_id": 5, "recipients": "a@b.c", "subject": "Editado",
        "html_body": texto_a_html_aviso(TEXTO), "include_xls": False, "include_txt": False,
    }
    datos.update(extra)
    return client.post("/api/infra/notify/download-eml", json=datos, headers={"X-CSRF-Token": csrf})


def test_panel_download_eml_guarda_en_el_incidente(panel):
    client, csrf, sesion = panel
    res = _eml_panel(client, csrf)
    assert res.status_code == 200 and res.headers["content-type"] == "message/rfc822"
    inc, otro = sesion.incidentes
    assert (inc.email_subject, inc.email_body) == ("Editado", texto_a_html_aviso(TEXTO))
    assert (otro.email_subject, otro.email_body) == ("otro", None)


def test_panel_download_eml_vacio_no_borra(panel):
    client, csrf, sesion = panel
    assert _eml_panel(client, csrf, subject="", html_body="").status_code == 200
    assert (sesion.incidentes[0].email_subject, sesion.incidentes[0].email_body) == ("viejo", "<p>viejo</p>")


def test_panel_download_eml_sin_csrf_no_guarda(panel):
    client, _csrf, sesion = panel
    assert _eml_panel(client, "token-falso").status_code == 403
    assert sesion.incidentes[0].email_subject == "viejo"


def test_panel_envio_smtp_guarda(panel, monkeypatch):
    client, csrf, sesion = panel
    _smtp(monkeypatch)
    res = client.post(
        "/api/infra/notify/email",
        json={"to": ["a@b.c"], "subject": "Por SMTP", "body": TEXTO, "incidente_ids": [5]},
        headers={"X-CSRF-Token": csrf},
    )
    assert res.status_code == 200 and res.json()["success"] is True
    assert (sesion.incidentes[0].email_subject, sesion.incidentes[0].email_body) == (
        "Por SMTP", texto_a_html_aviso(TEXTO),
    )


@pytest.fixture
def api(monkeypatch, sin_camaras):
    from api.app.main import app
    from api.app.routes import infra

    sesion = _Sesion([_incidente(5, subject="viejo", body="<p>viejo</p>"), _incidente(6)])
    monkeypatch.setattr(infra, "SessionLocal", lambda: sesion)
    return TestClient(app), sesion


def test_api_download_eml_guarda_el_cuerpo_final(api):
    client, sesion = api
    res = client.post(
        "/api/infra/notify/download-eml",
        data={"incident_id": 5, "subject": "Editado", "html_body": "<p>{{ticket}}</p>"},
        headers={"Authorization": "Bearer test-api-key"},
    )
    assert res.status_code == 200
    assert (sesion.incidentes[0].email_subject, sesion.incidentes[0].email_body) == ("Editado", "<p>T-5</p>")
    assert sesion.incidentes[1].email_body is None


def test_api_download_eml_vacio_no_borra(api):
    client, sesion = api
    res = client.post(
        "/api/infra/notify/download-eml", data={"incident_id": 5, "subject": "", "html_body": ""},
        headers={"Authorization": "Bearer test-api-key"},
    )
    assert res.status_code == 200
    assert (sesion.incidentes[0].email_subject, sesion.incidentes[0].email_body) == ("viejo", "<p>viejo</p>")


def test_api_envio_smtp_guarda(api, monkeypatch):
    client, sesion = api
    _smtp(monkeypatch)
    res = client.post(
        "/api/infra/notify/email",
        json={"to": ["a@b.c"], "subject": "Por SMTP", "body": TEXTO, "incidente_ids": [5]},
        headers={"Authorization": "Bearer test-api-key"},
    )
    assert res.status_code == 200 and res.json()["success"] is True
    assert sesion.incidentes[0].email_body == texto_a_html_aviso(TEXTO)
