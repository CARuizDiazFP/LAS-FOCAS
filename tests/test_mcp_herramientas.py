# Nombre de archivo: test_mcp_herramientas.py
# Ubicación de archivo: tests/test_mcp_herramientas.py
# Descripción: Pruebas de las herramientas reales del registro MCP por defecto (HTTP de office simulado)

from __future__ import annotations

import httpx
import pytest

from core.mcp import registry as registry_mod
from core.mcp.registry import ToolContext, ToolInvocationError, get_default_registry
from core.services import office_client

ADMIN = ToolContext(user_id="admin", session_id=1, role="admin")
USUARIO = ToolContext(user_id="ana", session_id=2, role="user")


@pytest.fixture
def directorios(monkeypatch, tmp_path):
    uploads = tmp_path / "uploads"
    reports = tmp_path / "reports"
    uploads.mkdir()
    monkeypatch.setenv("UPLOADS_DIR", str(uploads))
    monkeypatch.setenv("REPORTS_DIR", str(reports))
    monkeypatch.delenv("OFFICE_SERVICE_BASE", raising=False)
    return uploads, reports


def _usar_transport(monkeypatch, handler) -> list[httpx.Request]:
    pedidos: list[httpx.Request] = []

    def _registrar(request: httpx.Request) -> httpx.Response:
        pedidos.append(request)
        return handler(request)

    transport = httpx.MockTransport(_registrar)
    monkeypatch.setattr(office_client, "_cliente", lambda timeout: httpx.Client(transport=transport, timeout=timeout))
    return pedidos


def test_registro_por_defecto_expone_solo_herramientas_funcionales() -> None:
    assert get_default_registry().list_tools() == ["ConvertirDocAPdf", "GenerarInformeRepetitividad"]


@pytest.mark.asyncio
@pytest.mark.parametrize("nombre", ["GenerarMapaGeo", "CompararTrazasFO", "RegistrarEnNotion"])
async def test_herramientas_retiradas_no_existen(nombre: str) -> None:
    with pytest.raises(ToolInvocationError) as exc_info:
        await get_default_registry().invoke(nombre, {}, ADMIN)
    assert exc_info.value.code == "TOOL_NOT_FOUND"


# --------------------------------------------------------------------------------------
# ConvertirDocAPdf
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_convertir_doc_sube_multipart_a_office_y_guarda_el_pdf(monkeypatch, directorios) -> None:
    uploads, reports = directorios
    (uploads / "chat_1_informe.docx").write_bytes(b"docx-original")
    pedidos = _usar_transport(
        monkeypatch,
        lambda request: httpx.Response(200, content=b"%PDF-falso", headers={"content-type": "application/pdf"}),
    )

    result = await get_default_registry().invoke("ConvertirDocAPdf", {"input_path": "chat_1_informe.docx"}, ADMIN)

    assert len(pedidos) == 1
    pedido = pedidos[0]
    assert str(pedido.url) == "http://office:8090/convert?output_format=pdf"
    assert pedido.headers["content-type"].startswith("multipart/form-data")
    cuerpo = pedido.content
    assert b'name="file"; filename="chat_1_informe.docx"' in cuerpo
    assert b"docx-original" in cuerpo
    assert (reports / "chat_1_informe.pdf").read_bytes() == b"%PDF-falso"
    assert result.data["status"] == "ok"
    assert result.data["pdf"] == "/reports/chat_1_informe.pdf"


@pytest.mark.asyncio
async def test_convertir_doc_respeta_office_service_base(monkeypatch, directorios) -> None:
    uploads, _ = directorios
    (uploads / "a.docx").write_bytes(b"x")
    monkeypatch.setenv("OFFICE_SERVICE_BASE", "http://otro-office:9999/")
    pedidos = _usar_transport(monkeypatch, lambda request: httpx.Response(200, content=b"%PDF"))

    await get_default_registry().invoke("ConvertirDocAPdf", {"input_path": "a.docx"}, ADMIN)

    assert str(pedidos[0].url) == "http://otro-office:9999/convert?output_format=pdf"


@pytest.mark.asyncio
async def test_convertir_doc_acepta_documento_ya_generado_en_reports(monkeypatch, directorios) -> None:
    _, reports = directorios
    reports.mkdir()
    origen = reports / "Informe_SLA.docx"
    origen.write_bytes(b"x")
    _usar_transport(monkeypatch, lambda request: httpx.Response(200, content=b"%PDF"))

    result = await get_default_registry().invoke("ConvertirDocAPdf", {"input_path": str(origen)}, ADMIN)

    assert result.data["pdf"] == "/reports/Informe_SLA.pdf"


@pytest.mark.asyncio
async def test_convertir_doc_error_http_de_office(monkeypatch, directorios) -> None:
    uploads, reports = directorios
    (uploads / "a.docx").write_bytes(b"x")
    _usar_transport(
        monkeypatch,
        lambda request: httpx.Response(
            400, content='{"detail":"Extensión no soportada"}'.encode(), headers={"content-type": "application/json"}
        ),
    )

    with pytest.raises(ToolInvocationError) as exc_info:
        await get_default_registry().invoke("ConvertirDocAPdf", {"input_path": "a.docx"}, ADMIN)

    assert exc_info.value.code == "CONVERT_HTTP_ERROR"
    assert "Extensión no soportada" in exc_info.value.detail
    assert not (reports / "a.pdf").exists()


@pytest.mark.asyncio
async def test_convertir_doc_office_inalcanzable(monkeypatch, directorios) -> None:
    uploads, _ = directorios
    (uploads / "a.docx").write_bytes(b"x")

    def _sin_red(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Name or service not known", request=request)

    _usar_transport(monkeypatch, _sin_red)

    with pytest.raises(ToolInvocationError) as exc_info:
        await get_default_registry().invoke("ConvertirDocAPdf", {"input_path": "a.docx"}, ADMIN)

    assert exc_info.value.code == "CONVERT_NETWORK_ERROR"


@pytest.mark.asyncio
async def test_convertir_doc_archivo_inexistente(monkeypatch, directorios) -> None:
    pedidos = _usar_transport(monkeypatch, lambda request: httpx.Response(200, content=b"%PDF"))

    with pytest.raises(ToolInvocationError) as exc_info:
        await get_default_registry().invoke("ConvertirDocAPdf", {"input_path": "no-existe.docx"}, ADMIN)

    assert exc_info.value.code == "FILE_NOT_FOUND"
    assert pedidos == []


@pytest.mark.asyncio
@pytest.mark.parametrize("ruta", ["../secreto.docx", "/etc/passwd"])
async def test_convertir_doc_rechaza_rutas_fuera_de_uploads_y_reports(monkeypatch, directorios, ruta) -> None:
    pedidos = _usar_transport(monkeypatch, lambda request: httpx.Response(200, content=b"%PDF"))

    with pytest.raises(ToolInvocationError) as exc_info:
        await get_default_registry().invoke("ConvertirDocAPdf", {"input_path": ruta}, ADMIN)

    assert exc_info.value.code == "INVALID_PATH"
    assert pedidos == []


@pytest.mark.asyncio
async def test_convertir_doc_sigue_restringida_a_admin_y_ownergroup(directorios) -> None:
    with pytest.raises(ToolInvocationError) as exc_info:
        await get_default_registry().invoke("ConvertirDocAPdf", {"input_path": "a.docx"}, USUARIO)
    assert exc_info.value.code == "TOOL_FORBIDDEN"


# --------------------------------------------------------------------------------------
# GenerarInformeRepetitividad
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_informe_repetitividad_genera_enlaces(monkeypatch, directorios, tmp_path) -> None:
    uploads, _ = directorios
    (uploads / "casos.xlsx").write_bytes(b"xlsx")
    reports = tmp_path / "reports_informe"
    monkeypatch.setattr(registry_mod.REPORT_CONFIG, "reports_dir", reports)
    recibido: dict = {}

    def _fake_generar(excel_bytes, periodo, export_pdf, config, with_geo):
        recibido.update(excel=excel_bytes, periodo=periodo, export_pdf=export_pdf, with_geo=with_geo)
        return registry_mod.ReportResult(
            docx=reports / "Informe_Repetitividad_2025-09.docx",
            pdf=None,
            map_images=[reports / "maps_202509" / "mapa.png"],
        )

    monkeypatch.setattr(registry_mod, "generar_informe_desde_excel", _fake_generar)

    result = await get_default_registry().invoke(
        "GenerarInformeRepetitividad", {"file_path": "casos.xlsx", "mes": 9, "anio": 2025}, USUARIO
    )

    assert recibido == {"excel": b"xlsx", "periodo": "09/2025", "export_pdf": True, "with_geo": False}
    assert result.data["docx"] == "/reports/Informe_Repetitividad_2025-09.docx"
    assert result.data["map_images"] == ["/reports/maps_202509/mapa.png"]


@pytest.mark.asyncio
async def test_informe_repetitividad_archivo_inexistente(monkeypatch, directorios, tmp_path) -> None:
    monkeypatch.setattr(registry_mod.REPORT_CONFIG, "reports_dir", tmp_path / "reports_informe")

    with pytest.raises(ToolInvocationError) as exc_info:
        await get_default_registry().invoke(
            "GenerarInformeRepetitividad", {"file_path": "no-existe.xlsx", "mes": 9, "anio": 2025}, USUARIO
        )

    assert exc_info.value.code == "FILE_NOT_FOUND"
