# Nombre de archivo: test_informes_repetitividad_service.py
# Ubicación de archivo: tests/test_informes_repetitividad_service.py
# Descripción: Pruebas unitarias del helper generate_report para repetitividad

import io
import zipfile
from pathlib import Path

import httpx
import pytest

from modules.informes_repetitividad.service import generate_report


@pytest.mark.asyncio
async def test_generate_report_docx(tmp_path):
    input_file = tmp_path / "casos.xlsx"
    input_file.write_bytes(b"dummy-excel")
    out_dir = tmp_path / "out"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/reports/repetitividad"
        assert request.method == "POST"
        assert "multipart/form-data" in request.headers["content-type"]
        return httpx.Response(
            200,
            headers={
                "content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "content-disposition": 'attachment; filename="reporte.docx"',
            },
            content=b"DOCX-CONTENT",
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://mock") as client:
        result = await generate_report(
            input_file,
            mes=7,
            anio=2024,
            output_dir=out_dir,
            include_pdf=False,
            api_base="http://mock",
            client=client,
        )

    assert result.docx is not None
    assert result.docx.exists()
    assert result.pdf is None
    assert result.docx.read_bytes() == b"DOCX-CONTENT"


@pytest.mark.asyncio
async def test_generate_report_zip(tmp_path):
    input_file = tmp_path / "casos.xlsx"
    input_file.write_bytes(b"dummy-excel")
    out_dir = tmp_path / "out"

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("reporte.docx", b"DOCX-CONTENT")
        archive.writestr("reporte.pdf", b"PDF-CONTENT")
    zip_buffer.seek(0)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "content-type": "application/zip",
                "content-disposition": 'attachment; filename="reporte.zip"',
            },
            content=zip_buffer.getvalue(),
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://mock") as client:
        result = await generate_report(
            input_file,
            mes=8,
            anio=2024,
            output_dir=out_dir,
            include_pdf=True,
            api_base="http://mock",
            client=client,
        )

    assert result.docx is not None
    assert result.pdf is not None
    assert result.docx.exists()
    assert result.pdf.exists()
    assert result.docx.read_bytes() == b"DOCX-CONTENT"
    assert result.pdf.read_bytes() == b"PDF-CONTENT"


@pytest.mark.asyncio
async def test_generate_report_http_error(tmp_path):
    input_file = tmp_path / "casos.xlsx"
    input_file.write_bytes(b"dummy-excel")
    out_dir = tmp_path / "out"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"detail": "Archivo inválido"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://mock") as client:
        with pytest.raises(httpx.HTTPStatusError):
            await generate_report(
                input_file,
                mes=9,
                anio=2024,
                output_dir=out_dir,
                include_pdf=False,
                api_base="http://mock",
                client=client,
            )


@pytest.mark.asyncio
async def test_generate_report_sin_content_disposition(tmp_path):
    input_file = tmp_path / "casos.xlsx"
    input_file.write_bytes(b"dummy-excel")
    out_dir = tmp_path / "out"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            },
            content=b"DOCX-CONTENT",
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://mock") as client:
        result = await generate_report(
            input_file,
            mes=10,
            anio=2024,
            output_dir=out_dir,
            include_pdf=False,
            api_base="http://mock",
            client=client,
        )

    assert result.docx is not None
    assert result.docx.name == "repetitividad_202410.docx"
    assert result.docx.read_bytes() == b"DOCX-CONTENT"


@pytest.mark.asyncio
async def test_generate_report_zip_sin_pdf(tmp_path):
    input_file = tmp_path / "casos.xlsx"
    input_file.write_bytes(b"dummy-excel")
    out_dir = tmp_path / "out"

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("reporte.docx", b"DOCX-CONTENT")
    zip_buffer.seek(0)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "content-type": "application/zip",
            },
            content=zip_buffer.getvalue(),
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://mock") as client:
        result = await generate_report(
            input_file,
            mes=11,
            anio=2024,
            output_dir=out_dir,
            include_pdf=True,
            api_base="http://mock",
            client=client,
        )

    assert result.docx is not None
    assert result.pdf is None
    assert result.docx.read_bytes() == b"DOCX-CONTENT"
