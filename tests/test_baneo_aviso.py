# Nombre de archivo: test_baneo_aviso.py
# Ubicación de archivo: tests/test_baneo_aviso.py
# Descripción: Aviso de baneo por email en core/services (adjuntos, Content-Type único, SMTP fuera del event loop)

from __future__ import annotations

import asyncio
import email
import time
from types import SimpleNamespace

import httpx
import pytest

from core.services import baneo_aviso
from core.services.baneo_aviso import (
    COLUMNAS_XLS_BANEO,
    adjuntos_aviso_baneo,
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
        id=id_, servicio_protegido_id=servicio, ruta_protegida_id=ruta_id, ticket_asociado=None
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


def test_adjuntos_xls_con_columnas_union(monkeypatch):
    camara = SimpleNamespace(
        id=7, nombre="C7", fontine_id="F7", direccion="Calle 1", estado=SimpleNamespace(value="BANEADA"),
        latitud=-34.5, longitud=-58.4,
        empalmes=[SimpleNamespace(servicios=[SimpleNamespace(servicio_id="S1"), SimpleNamespace(servicio_id="S1")])],
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
    assert hoja.iloc[0]["Ticket"] == "INC-5" and hoja.iloc[0]["Servicios"] == "S1"


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
    """B3: el SMTP (simulado con time.sleep) corre en un thread; el loop sigue latiendo."""
    from api.app.main import app
    from api.app.routes import infra

    servicio = SimpleNamespace(
        is_configured=lambda: True,
        send_email=lambda **k: (time.sleep(0.3), EmailResult(True, "ok"))[1],
    )
    monkeypatch.setattr(baneo_aviso, "get_email_service", lambda: servicio)
    monkeypatch.setattr(baneo_aviso, "adjuntos_aviso_baneo", lambda *_a, **_k: [])

    class _SesionFalsa:
        def __enter__(self): return self
        def __exit__(self, *_a): return False

    monkeypatch.setattr(infra, "SessionLocal", lambda: _SesionFalsa())
    latidos: list[float] = []

    async def _latido() -> None:
        for _ in range(6):
            latidos.append(time.monotonic())
            await asyncio.sleep(0.04)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t",
        headers={"Authorization": "Bearer test-api-key"},
    ) as cliente:
        envio = asyncio.create_task(cliente.post(
            "/api/infra/notify/email",
            json={"to": ["a@b.com"], "subject": "s", "body": "b", "incidente_ids": [1]},
        ))
        await asyncio.sleep(0.02)
        await _latido()
        res = await envio

    assert res.status_code == 200 and res.json()["success"] is True
    assert max(b - a for a, b in zip(latidos, latidos[1:])) < 0.2
