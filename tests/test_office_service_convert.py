# Nombre de archivo: test_office_service_convert.py
# Ubicación de archivo: tests/test_office_service_convert.py
# Descripción: Pruebas del endpoint POST /convert del microservicio LibreOffice (soffice simulado)

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from office_service.app import conversion
from office_service.app.config import get_settings
from office_service.app.main import create_app


@pytest.fixture
def cliente(monkeypatch, tmp_path):
    get_settings.cache_clear()  # type: ignore[attr-defined]
    binario = tmp_path / "soffice"
    binario.write_text("#!/bin/sh\n")
    monkeypatch.setenv("OFFICE_SOFFICE_BINARY", str(binario))
    monkeypatch.setenv("OFFICE_MAX_FILE_SIZE", "1024")
    yield TestClient(create_app())
    get_settings.cache_clear()  # type: ignore[attr-defined]


def _soffice_que_escribe(contenido: bytes):
    async def _fake(comando, directorio: Path, timeout: float) -> None:
        origen = Path(comando[-3])
        (directorio / f"{origen.stem}.pdf").write_bytes(contenido)

    return _fake


def test_convert_devuelve_el_pdf(cliente, monkeypatch) -> None:
    monkeypatch.setattr(conversion, "_ejecutar", _soffice_que_escribe(b"%PDF-1.7 falso"))

    respuesta = cliente.post(
        "/convert",
        params={"output_format": "pdf"},
        files={"file": ("Informe SLA.docx", b"docx", "application/octet-stream")},
    )

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"] == "application/pdf"
    assert respuesta.content == b"%PDF-1.7 falso"
    assert 'filename="Informe_SLA.pdf"' in respuesta.headers["content-disposition"]


def test_convert_output_format_por_defecto_es_pdf(cliente, monkeypatch) -> None:
    monkeypatch.setattr(conversion, "_ejecutar", _soffice_que_escribe(b"%PDF"))

    respuesta = cliente.post("/convert", files={"file": ("a.odt", b"odt")})

    assert respuesta.status_code == 200
    assert respuesta.content == b"%PDF"


def test_convert_rechaza_formato_de_salida_no_soportado(cliente) -> None:
    respuesta = cliente.post(
        "/convert", params={"output_format": "xlsx"}, files={"file": ("a.docx", b"docx")}
    )

    assert respuesta.status_code == 400


def test_convert_rechaza_extension_de_entrada_no_soportada(cliente) -> None:
    respuesta = cliente.post("/convert", files={"file": ("planilla.xlsx", b"xlsx")})

    assert respuesta.status_code == 400


def test_convert_rechaza_archivo_vacio(cliente) -> None:
    respuesta = cliente.post("/convert", files={"file": ("a.docx", b"")})

    assert respuesta.status_code == 400


def test_convert_rechaza_archivo_que_supera_el_limite(cliente) -> None:
    respuesta = cliente.post("/convert", files={"file": ("a.docx", b"x" * 1025)})

    assert respuesta.status_code == 413


def test_convert_sin_binario_de_libreoffice_responde_503(cliente, monkeypatch, tmp_path) -> None:
    get_settings.cache_clear()  # type: ignore[attr-defined]
    monkeypatch.setenv("OFFICE_SOFFICE_BINARY", str(tmp_path / "no-existe"))

    respuesta = TestClient(create_app()).post("/convert", files={"file": ("a.docx", b"docx")})

    assert respuesta.status_code == 503


def test_convert_si_soffice_no_genera_salida_responde_500(cliente, monkeypatch) -> None:
    async def _fake(comando, directorio: Path, timeout: float) -> None:
        return None

    monkeypatch.setattr(conversion, "_ejecutar", _fake)

    respuesta = cliente.post("/convert", files={"file": ("a.docx", b"docx")})

    assert respuesta.status_code == 500


def test_convert_timeout_responde_504(cliente, monkeypatch) -> None:
    async def _fake(comando, directorio: Path, timeout: float) -> None:
        raise conversion.ConversionTimeout("soffice superó 1 s")

    monkeypatch.setattr(conversion, "_ejecutar", _fake)

    respuesta = cliente.post("/convert", files={"file": ("a.docx", b"docx")})

    assert respuesta.status_code == 504


def test_comando_usa_perfil_propio_y_no_el_de_la_instancia_uno(tmp_path) -> None:
    comando = conversion.armar_comando("/usr/bin/soffice", tmp_path / "a.docx", tmp_path, "pdf")

    assert comando[0] == "/usr/bin/soffice"
    assert "--headless" in comando
    perfil = [p for p in comando if p.startswith("-env:UserInstallation=file://")]
    assert perfil and str(tmp_path) in perfil[0]
    assert comando[-3:] == [str(tmp_path / "a.docx"), "--outdir", str(tmp_path)]
