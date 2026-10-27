# Nombre de archivo: test_office_client.py
# Ubicación de archivo: tests/test_office_client.py
# Descripción: Pruebas del cliente único de office_service (/convert simulado con httpx.MockTransport)

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from core.services import office_client
from core.services.office_client import (
    DocumentoDemasiadoGrande,
    OfficeInalcanzable,
    OfficeRechazo,
    OfficeTimeout,
    convertir_a_pdf,
    intentar_pdf,
)


@pytest.fixture
def docx(tmp_path: Path) -> Path:
    ruta = tmp_path / "informe.docx"
    ruta.write_bytes(b"docx-original")
    return ruta


@pytest.fixture(autouse=True)
def _sin_base(monkeypatch):
    monkeypatch.delenv("OFFICE_SERVICE_BASE", raising=False)


def _usar_transport(monkeypatch, handler) -> list[httpx.Request]:
    pedidos: list[httpx.Request] = []

    def _registrar(request: httpx.Request) -> httpx.Response:
        pedidos.append(request)
        return handler(request)

    transport = httpx.MockTransport(_registrar)
    monkeypatch.setattr(office_client, "_cliente", lambda timeout: httpx.Client(transport=transport, timeout=timeout))
    return pedidos


def test_sube_multipart_y_guarda_el_pdf_al_lado(monkeypatch, docx) -> None:
    pedidos = _usar_transport(monkeypatch, lambda request: httpx.Response(200, content=b"%PDF-1.7 falso"))

    pdf = convertir_a_pdf(docx)

    assert pdf == docx.with_suffix(".pdf")
    assert pdf.read_bytes() == b"%PDF-1.7 falso"
    assert not pdf.with_name(pdf.name + ".tmp").exists()
    assert str(pedidos[0].url) == "http://office:8090/convert?output_format=pdf"
    assert b'name="file"; filename="informe.docx"' in pedidos[0].content
    assert b"docx-original" in pedidos[0].content


def test_respeta_destino_y_office_service_base(monkeypatch, docx, tmp_path) -> None:
    monkeypatch.setenv("OFFICE_SERVICE_BASE", "http://otro-office:9999/")
    pedidos = _usar_transport(monkeypatch, lambda request: httpx.Response(200, content=b"%PDF"))

    pdf = convertir_a_pdf(docx, tmp_path / "salida" / "x.pdf")

    assert pdf == tmp_path / "salida" / "x.pdf"
    assert pdf.exists()
    assert str(pedidos[0].url) == "http://otro-office:9999/convert?output_format=pdf"


def test_timeout_de_red(monkeypatch, docx) -> None:
    def _lento(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    _usar_transport(monkeypatch, _lento)

    with pytest.raises(OfficeTimeout):
        convertir_a_pdf(docx)
    assert not docx.with_suffix(".pdf").exists()


def test_504_de_office_es_timeout(monkeypatch, docx) -> None:
    _usar_transport(monkeypatch, lambda request: httpx.Response(504, json={"detail": "tardó más de 120 s"}))

    with pytest.raises(OfficeTimeout) as exc_info:
        convertir_a_pdf(docx)
    assert "120 s" in exc_info.value.detalle


@pytest.mark.parametrize("status", [400, 413, 500, 503])
def test_4xx_5xx_es_rechazo_con_detalle_sin_pdf(monkeypatch, docx, status) -> None:
    _usar_transport(
        monkeypatch, lambda request: httpx.Response(status, content='{"detail":"Extensión no soportada"}'.encode())
    )

    with pytest.raises(OfficeRechazo) as exc_info:
        convertir_a_pdf(docx)
    assert "Extensión no soportada" in exc_info.value.detalle
    assert "Extensión" not in exc_info.value.mensaje  # el texto interno no llega al usuario
    assert not docx.with_suffix(".pdf").exists()


def test_respuesta_que_no_es_pdf_es_rechazo(monkeypatch, docx) -> None:
    _usar_transport(monkeypatch, lambda request: httpx.Response(200, content=b"<html>proxy</html>"))

    with pytest.raises(OfficeRechazo):
        convertir_a_pdf(docx)
    assert not docx.with_suffix(".pdf").exists()


def test_office_inalcanzable(monkeypatch, docx) -> None:
    def _sin_red(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Name or service not known", request=request)

    _usar_transport(monkeypatch, _sin_red)

    with pytest.raises(OfficeInalcanzable):
        convertir_a_pdf(docx)


def test_archivo_grande_no_se_sube(monkeypatch, docx) -> None:
    pedidos = _usar_transport(monkeypatch, lambda request: httpx.Response(200, content=b"%PDF"))
    monkeypatch.setattr(office_client, "MAX_BYTES", 5)

    with pytest.raises(DocumentoDemasiadoGrande):
        convertir_a_pdf(docx)
    assert pedidos == []


def test_intentar_pdf_nunca_levanta_y_devuelve_motivo(monkeypatch, docx) -> None:
    _usar_transport(monkeypatch, lambda request: httpx.Response(503, json={"detail": "sin soffice"}))

    pdf, motivo = intentar_pdf(docx, contexto="test")

    assert pdf is None
    assert motivo == "El servicio de conversión no pudo generar el PDF"


def test_intentar_pdf_ok(monkeypatch, docx) -> None:
    _usar_transport(monkeypatch, lambda request: httpx.Response(200, content=b"%PDF"))

    pdf, motivo = intentar_pdf(docx, contexto="test")

    assert pdf == docx.with_suffix(".pdf")
    assert motivo is None


def test_intentar_pdf_docx_inexistente(tmp_path) -> None:
    pdf, motivo = intentar_pdf(tmp_path / "no-existe.docx", contexto="test")

    assert pdf is None
    assert motivo == "No se pudo guardar el PDF"


@pytest.mark.office_real
@pytest.mark.skipif(not os.getenv("OFFICE_REAL_URL"), reason="bajo demanda: OFFICE_REAL_URL=http://<office de dev>:8090")
def test_integracion_contra_office_real(monkeypatch, tmp_path) -> None:
    """Corre contra un office real: ``OFFICE_REAL_URL=... pytest -m office_real tests/test_office_client.py``."""
    from docx import Document

    monkeypatch.setenv("OFFICE_SERVICE_BASE", os.environ["OFFICE_REAL_URL"])
    origen = tmp_path / "prueba.docx"
    documento = Document()
    documento.add_paragraph("Prueba de conversión LAS-FOCAS")
    documento.save(origen)

    pdf = convertir_a_pdf(origen)

    assert pdf.read_bytes()[:5] == b"%PDF-"
