# Nombre de archivo: test_baneo_aviso.py
# Ubicación de archivo: tests/test_baneo_aviso.py
# Descripción: Aviso de baneo por email en core/services (adjuntos, Content-Type único, SMTP fuera del event loop)

from __future__ import annotations

import asyncio
import email
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from core.services import baneo_aviso
from core.services.baneo_aviso import (
    COLUMNAS_XLS_BANEO,
    PLANTILLA_AVISO_BANEO,
    adjuntos_aviso_baneo,
    armar_eml_baneo,
    guardar_plantilla_aviso,
    parsear_destinatarios,
    enviar_aviso_baneo,
)
from core.services.email_service import EmailAttachment, EmailResult, EmailService


class _Consulta:
    """Doble de `session.query(Modelo).filter(...)`: ignora el filtro y devuelve los datos cargados."""

    def __init__(self, datos: list) -> None:
        self._datos = datos

    def filter(self, *_a, **_k) -> "_Consulta":
        return self

    def all(self) -> list:
        return list(self._datos)

    def first(self):
        return self._datos[0] if self._datos else None


class _Sesion:
    def __init__(self, incidentes: list, servicios: list) -> None:
        self._por_modelo = {"IncidenteBaneo": incidentes, "Servicio": servicios}

    def query(self, modelo) -> _Consulta:
        return _Consulta(self._por_modelo[modelo.__name__])


def _ruta(id_: int, contenido: str | None, nombre: str | None = None):
    return SimpleNamespace(id=id_, raw_file_content=contenido, nombre_archivo_origen=nombre)


def _incidente(id_: int, servicio: str, ruta_id: int | None = None):
    return SimpleNamespace(
        id=id_, servicio_protegido_id=servicio, ruta_protegida_id=ruta_id, ticket_asociado=None,
        servicio_afectado_id="AFEC", motivo="corte de prueba",
        fecha_inicio=datetime(2026, 1, 6, 0, 30, tzinfo=timezone.utc),
    )


def _servicio(servicio_id: str, rutas: list):
    return SimpleNamespace(servicio_id=servicio_id, rutas=rutas)


def test_adjuntos_un_txt_por_incidente():
    # Los dos incidentes comparten servicio protegido: igual salen dos TXT (uno por incidente).
    sesion = _Sesion(
        [_incidente(1, "S1"), _incidente(2, "S1")],
        [_servicio("S1", [_ruta(10, "uno", "a.txt")])],
    )

    adjuntos = adjuntos_aviso_baneo(sesion, [1, 2], include_xls=False, include_txt=True)

    assert [a.filename for a in adjuntos] == ["a.txt", "a.txt"]
    assert [a.content for a in adjuntos] == [b"uno", b"uno"]


def test_adjuntos_prioriza_ruta_protegida():
    rutas = [_ruta(1, "primera", "p.txt"), _ruta(2, "protegida", "q.txt")]
    sesion = _Sesion([_incidente(1, "S1", ruta_id=2)], [_servicio("S1", rutas)])

    adjuntos = adjuntos_aviso_baneo(sesion, [1], include_xls=False, include_txt=True)

    assert [a.filename for a in adjuntos] == ["q.txt"]


def test_adjuntos_sin_ruta_protegida_con_contenido_toma_la_primera_con_contenido():
    rutas = [_ruta(1, None), _ruta(2, "segunda", None), _ruta(3, "tercera", "t.txt")]
    sesion = _Sesion([_incidente(1, "S1", ruta_id=1)], [_servicio("S1", rutas)])

    adjuntos = adjuntos_aviso_baneo(sesion, [1], include_xls=False, include_txt=True)

    assert [(a.filename, a.content) for a in adjuntos] == [("tracking_S1.txt", b"segunda")]


def test_adjuntos_none_sin_incidentes():
    sesion = _Sesion([], [])

    assert adjuntos_aviso_baneo(sesion, [99], include_xls=True, include_txt=True) is None
    assert adjuntos_aviso_baneo(sesion, [], include_xls=True, include_txt=True) is None


def _ruta_de_servicio(ruta_id, servicio_id):
    """Ruta mínima que recorre `_collect_camara_rutas_info` (P22: los servicios salen sólo de las rutas)."""
    return SimpleNamespace(
        id=ruta_id, servicio=SimpleNamespace(servicio_id=servicio_id, alias_ids=None), nombre="Principal",
        tipo=SimpleNamespace(value="PRINCIPAL"), empalmes=[], punta_a=None, punta_b=None,
    )


@pytest.mark.filterwarnings("ignore::DeprecationWarning:openpyxl")
def test_adjuntos_xls_con_columnas_union(monkeypatch):
    camara = SimpleNamespace(
        id=7, nombre="C7", fontine_id="F7", direccion="Calle 1", estado=SimpleNamespace(value="BANEADA"),
        latitud=-34.5, longitud=-58.4,
        empalmes=[SimpleNamespace(rutas=[_ruta_de_servicio(1, "S1"), _ruta_de_servicio(2, "S1")])],
    )

    class _Proteccion:
        def __init__(self, _sesion) -> None: ...

        def get_camaras_for_servicio(self, *_a):
            return [camara]

    monkeypatch.setattr(baneo_aviso, "ProtectionService", _Proteccion)
    sesion = _Sesion([_incidente(5, "S1")], [])

    (xls,) = adjuntos_aviso_baneo(sesion, [5], include_xls=True, include_txt=False)

    import io

    import pandas as pd

    hoja = pd.read_excel(io.BytesIO(xls.content), sheet_name="Baneos_Activos")
    assert list(hoja.columns) == COLUMNAS_XLS_BANEO
    fila = hoja.iloc[0]
    assert fila["Ticket"] == "INC-5" and fila["Servicios"] == "S1"
    assert fila["Incidente ID"] == 5 and fila["Servicio Protegido"] == "S1" and fila["ID"] == 7
    assert fila["Fecha Inicio"] == "05/01/2026 21:30" and fila["Motivo"] == "corte de prueba"
    assert fila["Servicio Afectado"] == "AFEC"


def test_send_email_un_solo_content_type_por_adjunto(monkeypatch):
    enviados: list[str] = []

    class _Smtp:
        def __init__(self, *_a, **_k) -> None: ...
        def __enter__(self): return self
        def __exit__(self, *_a): return False
        def starttls(self): ...
        def login(self, *_a): ...
        def sendmail(self, _de, _para, mensaje): enviados.append(mensaje)

    monkeypatch.setattr("core.services.email_service.smtplib.SMTP", _Smtp)
    servicio = EmailService()
    servicio.settings = SimpleNamespace(
        enabled=True, host="h", port=25, timeout=5, use_tls=False, user=None, password=None,
        from_email="de@x.com", from_name="De",
    )
    resultado = servicio.send_email(
        to=["a@x.com"], subject="s", body="b",
        attachments=[
            EmailAttachment("a.xlsx", b"PK\x00", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            EmailAttachment("t.txt", "tracking ñ".encode("utf-8"), "text/plain; charset=utf-8"),
        ],
    )

    assert resultado.success
    partes = [p for p in email.message_from_string(enviados[0]).walk() if p.get_filename()]
    assert len(partes) == 2
    for parte in partes:
        assert len(parte.get_all("Content-Type")) == 1
    assert partes[0].get_content_type() == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert partes[1].get_content_type() == "text/plain"
    assert partes[1].get_payload(decode=True).decode("utf-8") == "tracking ñ"


def test_enviar_aviso_smtp_sin_configurar_no_lanza(monkeypatch):
    monkeypatch.setattr(baneo_aviso, "get_email_service", lambda: SimpleNamespace(is_configured=lambda: False))

    r = enviar_aviso_baneo(
        _Sesion([], []), to=["a@b.com"], cc=None, subject="s", body="b",
        incidente_ids=[1], include_xls=True, include_txt=True,
    )

    assert (r.success, r.message) == (False, "Servicio de email no configurado")


def test_enviar_aviso_sin_incidentes(monkeypatch):
    monkeypatch.setattr(baneo_aviso, "get_email_service", lambda: SimpleNamespace(is_configured=lambda: True))

    r = enviar_aviso_baneo(
        _Sesion([], []), to=["a@b.com"], cc=None, subject="s", body="b",
        incidente_ids=[1], include_xls=True, include_txt=True,
    )

    assert (r.success, r.message) == (False, "No se encontraron incidentes con los IDs especificados")


def test_enviar_aviso_cuenta_destinatarios(monkeypatch):
    servicio = SimpleNamespace(
        is_configured=lambda: True,
        send_email=lambda **k: EmailResult(True, "ok"),
    )
    monkeypatch.setattr(baneo_aviso, "get_email_service", lambda: servicio)

    r = enviar_aviso_baneo(
        _Sesion([_incidente(1, "S1")], [_servicio("S1", [])]), to=["a@b.com"], cc=["c@d.com", "e@f.com"],
        subject="s", body="b", incidente_ids=[1], include_xls=False, include_txt=True,
    )

    assert (r.success, r.recipients_count) == (True, 3)


@pytest.mark.asyncio
async def test_api_notify_email_no_bloquea_el_loop(monkeypatch):
    """B3: el SMTP (simulado con time.sleep) corre en otro thread; el loop sigue latiendo durante el POST."""
    import threading

    from api.app.main import app
    from api.app.routes import infra

    hilos: list[int] = []

    def _send_email(**_k):
        hilos.append(threading.get_ident())
        time.sleep(0.3)
        return EmailResult(True, "ok")

    servicio = SimpleNamespace(is_configured=lambda: True, send_email=_send_email)
    monkeypatch.setattr(baneo_aviso, "get_email_service", lambda: servicio)
    monkeypatch.setattr(baneo_aviso, "adjuntos_aviso_baneo", lambda *_a, **_k: [])

    class _SesionFalsa:
        def __enter__(self): return self
        def __exit__(self, *_a): return False

    monkeypatch.setattr(infra, "SessionLocal", lambda: _SesionFalsa())
    latidos: list[float] = []
    terminado = asyncio.Event()

    async def _latido() -> None:
        while not terminado.is_set():
            latidos.append(time.monotonic())
            await asyncio.sleep(0.02)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t",
        headers={"Authorization": "Bearer test-api-key"},
    ) as cliente:
        # El latido arranca ANTES del POST: un bloqueo del loop se vería como un hueco entre latidos.
        tarea = asyncio.create_task(_latido())
        await asyncio.sleep(0.05)
        res = await cliente.post(
            "/api/infra/notify/email",
            json={"to": ["a@b.com"], "subject": "s", "body": "b", "incidente_ids": [1]},
        )
        terminado.set()
        await tarea

    assert res.status_code == 200 and res.json()["success"] is True
    assert hilos and hilos[0] != threading.get_ident()
    assert len(latidos) >= 8
    assert max(b - a for a, b in zip(latidos, latidos[1:])) < 0.15


# --- .eml del aviso (Task 9: D7, D8, D9, B6, B7) ---


def _camara_con_servicios():
    return SimpleNamespace(
        id=7, nombre="C7", fontine_id="F7", direccion="Calle 1", estado=SimpleNamespace(value="BANEADA"),
        latitud=-34.5, longitud=-58.4,
        empalmes=[SimpleNamespace(rutas=[_ruta_de_servicio(1, "S1")])],
    )


def _con_camaras(monkeypatch, camaras):
    class _Proteccion:
        def __init__(self, _sesion) -> None: ...

        def get_camaras_for_servicio(self, *_a):
            return camaras

    monkeypatch.setattr(baneo_aviso, "ProtectionService", _Proteccion)


def _incidente_aviso(ticket, id_=5, **extra):
    datos = dict(
        id=id_, servicio_protegido_id="S1", ruta_protegida_id=None, ticket_asociado=ticket,
        servicio_afectado_id="SA", motivo="Obra", fecha_inicio=None,
    )
    datos.update(extra)
    return SimpleNamespace(**datos)


def test_parsear_destinatarios():
    assert parsear_destinatarios("a@x.com; b@y.com  c@z.com,sin_arroba") == ["a@x.com", "b@y.com", "c@z.com"]
    assert parsear_destinatarios(None) == [] and parsear_destinatarios("  ") == []


def test_eml_incidente_inexistente_devuelve_none():
    assert armar_eml_baneo(_Sesion([], []), 1, destinatarios=[], subject=None, html_body=None) is None


def test_eml_ticket_none_usa_el_id_en_nombre_y_asunto(monkeypatch):
    _con_camaras(monkeypatch, [])
    eml = armar_eml_baneo(_Sesion([_incidente_aviso(None, 42)], []), 42, destinatarios=["a@b.c"], subject=None, html_body=None)
    assert eml.nombre_archivo.startswith("notificacion_INC_42_") and eml.nombre_archivo.endswith(".eml")
    assert eml.subject == "AVISO DE BANEO - Ticket 42"


def test_eml_nombre_sanea_ticket(monkeypatch):
    _con_camaras(monkeypatch, [])
    eml = armar_eml_baneo(_Sesion([_incidente_aviso('A"B/C')], []), 5, destinatarios=[], subject="x", html_body="x")
    assert eml.nombre_archivo.startswith("notificacion_A_B_C_")
    assert '"' not in eml.nombre_archivo and "/" not in eml.nombre_archivo


@pytest.mark.filterwarnings("ignore::DeprecationWarning:openpyxl")
def test_eml_headers_un_content_type_y_xls_con_servicios(monkeypatch):
    import io

    import pandas as pd

    _con_camaras(monkeypatch, [_camara_con_servicios()])
    sesion = _Sesion([_incidente_aviso("T-1")], [_servicio("S1", [_ruta(1, "a b c", "t.txt")])])
    eml = armar_eml_baneo(sesion, 5, destinatarios=["a@b.c", "d@e.f"], subject="Asunto", html_body=None)
    msg = email.message_from_bytes(eml.contenido)
    assert msg["X-Unsent"] == "1" and msg["X-Mailer"] and msg["Date"]
    assert msg["To"] == "a@b.c, d@e.f" and msg["Subject"] == "Asunto"
    partes = [p for p in msg.walk() if not p.is_multipart()]
    assert len(partes) == 3  # cuerpo + XLS + TXT
    for parte in partes:
        assert len(parte.get_all("Content-Type")) == 1
    xls = next(p for p in partes if p.get_filename() == "baneos_activos.xlsx")
    hoja = pd.read_excel(io.BytesIO(xls.get_payload(decode=True)), sheet_name="Baneos_Activos")
    assert hoja.iloc[0]["Servicios"] == "S1"


def test_eml_sin_adjuntos_si_se_desactivan(monkeypatch):
    _con_camaras(monkeypatch, [_camara_con_servicios()])
    sesion = _Sesion([_incidente_aviso("T")], [_servicio("S1", [_ruta(1, "x")])])
    eml = armar_eml_baneo(sesion, 5, destinatarios=[], subject=None, html_body="hola", include_xls=False, include_txt=False)
    msg = email.message_from_bytes(eml.contenido)
    assert len([p for p in msg.walk() if not p.is_multipart()]) == 1 and msg["To"] is None


def test_eml_escapa_variables_html(monkeypatch):
    _con_camaras(monkeypatch, [])
    sesion = _Sesion([_incidente_aviso("<script>alert(1)</script>", motivo="a<b>")], [])
    eml = armar_eml_baneo(sesion, 5, destinatarios=[], subject="s", html_body=None)
    assert "<script>alert(1)" not in eml.html_body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in eml.html_body and "a&lt;b&gt;" in eml.html_body
    assert "{{" not in eml.html_body
    custom = armar_eml_baneo(sesion, 5, destinatarios=[], subject="s", html_body="<p>{{ticket}}</p>")
    assert custom.html_body == "<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>"


def test_plantilla_por_defecto_es_la_del_panel():
    assert "{{ticket}}" in PLANTILLA_AVISO_BANEO and "Notificación de Protocolo de Protección" in PLANTILLA_AVISO_BANEO


def test_guardar_plantilla_aviso_persiste_y_commitea():
    incidente = SimpleNamespace(id=5, email_subject=None, email_body=None)
    confirmaciones = []
    sesion = _Sesion([incidente], [])
    sesion.commit = lambda: confirmaciones.append(1)
    guardar_plantilla_aviso(sesion, 5, "Asu", None)
    assert incidente.email_subject == "Asu" and incidente.email_body is None and confirmaciones == [1]


def test_eml_nombre_solo_ascii_con_ticket_unicode(monkeypatch):
    _con_camaras(monkeypatch, [])
    eml = armar_eml_baneo(_Sesion([_incidente_aviso("Ñandú日本€")], []), 5, destinatarios=[], subject="s", html_body="x")
    assert eml.nombre_archivo.isascii() and '"' not in eml.nombre_archivo


def test_api_download_eml_ticket_unicode_responde_200(monkeypatch):
    from fastapi.testclient import TestClient

    from api.app.main import app
    from api.app.routes import infra

    _con_camaras(monkeypatch, [])
    sesion = _Sesion([_incidente_aviso("Ñandú日本€")], [])
    monkeypatch.setattr(infra, "SessionLocal", lambda: _CtxSesion(sesion))
    res = TestClient(app, raise_server_exceptions=False).post(
        "/api/infra/notify/download-eml", data={"incident_id": 5},
        headers={"Authorization": "Bearer test-api-key"},
    )
    assert res.status_code == 200
    assert res.headers["content-disposition"].isascii() and res.headers["content-type"] == "message/rfc822"


class _CtxSesion:
    def __init__(self, sesion) -> None:
        self._s = sesion

    def __enter__(self):
        return self._s

    def __exit__(self, *a):
        return False
