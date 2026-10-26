# Nombre de archivo: registry.py
# Ubicación de archivo: core/mcp/registry.py
# Descripción: Registro de herramientas MCP y utilidades para invocarlas desde el chatbot

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List

import httpx
from pydantic import BaseModel, ValidationError, field_validator

from modules.informes_repetitividad.service import (
    ReportConfig,
    ReportResult,
    generar_informe_desde_excel,
)

logger = logging.getLogger(__name__)

REPORT_CONFIG = ReportConfig.from_settings()


@dataclass(slots=True)
class ToolContext:
    """Contexto de ejecución con metadatos mínimos."""

    user_id: str
    session_id: int
    role: str = "user"


@dataclass(slots=True)
class ToolRequest:
    """Representa una solicitud de herramienta proveniente del orquestador."""

    name: str
    args: Dict[str, Any]
    attachments: List[Dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class ToolResult:
    """Respuesta uniforme para todos los tool-calls."""

    message: str
    data: Dict[str, Any] | None = None
    metadata: Dict[str, Any] | None = None
    streaming_chunks: List[str] | None = None

    def __post_init__(self) -> None:
        if self.streaming_chunks is None:
            self.streaming_chunks = []
        if self.metadata is None:
            self.metadata = {}
        if self.data is None:
            self.data = {}


class ToolInvocationError(Exception):
    """Error controlado al invocar una herramienta MCP."""

    def __init__(self, code: str, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.user_message = message
        self.detail = detail or message


ToolHandler = Callable[[BaseModel, ToolContext], Awaitable[ToolResult]]


@dataclass(slots=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: ToolHandler
    roles: Iterable[str] = field(default_factory=lambda: ["user", "admin"])


class MCPRegistry:
    """Registro centralizado de herramientas MCP."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        key = tool.name
        if key in self._tools:
            raise ValueError(f"La herramienta {key} ya está registrada")
        self._tools[key] = tool
        logger.debug("action=mcp_register tool=%s roles=%s", key, list(tool.roles))

    async def invoke(self, name: str, args: Dict[str, Any], context: ToolContext) -> ToolResult:
        if name not in self._tools:
            raise ToolInvocationError("TOOL_NOT_FOUND", f"La herramienta {name} no existe")
        tool = self._tools[name]
        if context.role not in tool.roles:
            raise ToolInvocationError("TOOL_FORBIDDEN", "No tenés permisos para usar esta herramienta")
        try:
            parsed_args = tool.input_model(**args)
        except ValidationError as exc:
            raise ToolInvocationError("INVALID_TOOL_ARGS", "Argumentos inválidos", detail=exc.json()) from exc
        start = time.perf_counter()
        try:
            result = await tool.handler(parsed_args, context)
        except ToolInvocationError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "action=mcp_tool_exception tool=%s user_id=%s error=%s", name, context.user_id, exc
            )
            raise ToolInvocationError("TOOL_INTERNAL_ERROR", "La herramienta falló", detail=str(exc))
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "action=mcp_tool_call tool=%s user_id=%s session_id=%s duration_ms=%.2f",
            name,
            context.user_id,
            context.session_id,
            duration_ms,
        )
        return result

    def list_tools(self) -> List[str]:
        return sorted(self._tools.keys())


# --------------------------------------------------------------------------------------
# Modelos de entrada para herramientas
# --------------------------------------------------------------------------------------


class InformeRepetitividadArgs(BaseModel):
    file_path: str
    mes: int
    anio: int
    export_pdf: bool = True
    with_geo: bool = False

    @field_validator("mes")
    @classmethod
    def _validate_mes(cls, value: int) -> int:
        if not 1 <= value <= 12:
            raise ValueError("mes debe estar entre 1 y 12")
        return value

    @field_validator("anio")
    @classmethod
    def _validate_anio(cls, value: int) -> int:
        if value < 2000 or value > 2100:
            raise ValueError("anio fuera de rango razonable")
        return value


class ConvertirDocArgs(BaseModel):
    input_path: str


# --------------------------------------------------------------------------------------
# Implementaciones de herramientas
# --------------------------------------------------------------------------------------


def _reports_href(path: Path, reports_dir: Path) -> str:
    """URL bajo /reports conservando subcarpetas (p. ej. maps_YYYYMM/)."""

    try:
        rel = path.resolve().relative_to(Path(reports_dir).resolve())
    except ValueError:
        return f"/reports/{path.name}"
    return f"/reports/{rel.as_posix()}"


async def _run_informe_repetitividad(args: InformeRepetitividadArgs, context: ToolContext) -> ToolResult:
    uploads_dir = Path(os.getenv("UPLOADS_DIR", "/app/data/uploads"))
    reports_dir = REPORT_CONFIG.reports_dir
    reports_dir.mkdir(parents=True, exist_ok=True)

    file_path = Path(args.file_path)
    if not file_path.is_absolute():
        file_path = uploads_dir / file_path
    if not file_path.exists():
        raise ToolInvocationError("FILE_NOT_FOUND", "No encuentro el archivo para generar el informe")

    periodo_titulo = f"{args.mes:02d}/{args.anio}"
    excel_bytes = file_path.read_bytes()
    result: ReportResult = await asyncio.to_thread(
        generar_informe_desde_excel,
        excel_bytes,
        periodo_titulo,
        args.export_pdf,
        REPORT_CONFIG,
        args.with_geo,
    )
    map_images = [_reports_href(Path(m), reports_dir) for m in result.map_images]
    payload: Dict[str, Any] = {
        "status": "ok",
        "docx": f"/reports/{result.docx.name}" if result.docx else None,
        "pdf": f"/reports/{result.pdf.name}" if result.pdf else None,
        "maps": [],
        "map_images": map_images,
        "with_geo": args.with_geo,
    }
    message = (
        "Informe de Repetitividad generado. Revisá los enlaces en la sección de resultados."
    )
    return ToolResult(message=message, data=payload, metadata={"tool": "GenerarInformeRepetitividad"})


# office_service convierte con un timeout propio de 120 s (OFFICE_CONVERT_TIMEOUT); acá un margen extra.
OFFICE_TIMEOUT = 150.0


def _cliente_office(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout)


def _resolver_documento(input_path: str) -> Path:
    """Ruta real del documento: relativa a UPLOADS_DIR o absoluta dentro de UPLOADS_DIR/REPORTS_DIR.

    El archivo se lee y se sube a office_service, así que cualquier otra ruta (`../`, `/etc/...`) se
    rechaza antes de tocar el disco.
    """

    uploads_dir = Path(os.getenv("UPLOADS_DIR", "/app/data/uploads")).resolve()
    reports_dir = Path(os.getenv("REPORTS_DIR", "/app/data/reports")).resolve()
    ruta = Path(input_path)
    if not ruta.is_absolute():
        ruta = uploads_dir / ruta
    ruta = ruta.resolve()
    if not (ruta.is_relative_to(uploads_dir) or ruta.is_relative_to(reports_dir)):
        raise ToolInvocationError("INVALID_PATH", "El documento tiene que estar entre los adjuntos o los informes")
    if not ruta.is_file():
        raise ToolInvocationError("FILE_NOT_FOUND", "No encuentro el documento a convertir")
    return ruta


async def _run_convertir_doc(args: ConvertirDocArgs, context: ToolContext) -> ToolResult:
    origen = _resolver_documento(args.input_path)
    base_url = os.getenv("OFFICE_SERVICE_BASE", "http://office:8090").rstrip("/")
    reports_dir = Path(os.getenv("REPORTS_DIR", "/app/data/reports"))
    contenido = await asyncio.to_thread(origen.read_bytes)
    try:
        async with _cliente_office(OFFICE_TIMEOUT) as client:
            response = await client.post(
                f"{base_url}/convert",
                params={"output_format": "pdf"},
                files={"file": (origen.name, contenido, "application/octet-stream")},
            )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ToolInvocationError("CONVERT_HTTP_ERROR", "Falló la conversión", detail=exc.response.text) from exc
    except httpx.HTTPError as exc:
        raise ToolInvocationError(
            "CONVERT_NETWORK_ERROR", "No se pudo contactar al servicio de conversión", detail=str(exc)
        ) from exc

    reports_dir.mkdir(parents=True, exist_ok=True)
    destino = reports_dir / f"{origen.stem}.pdf"
    await asyncio.to_thread(destino.write_bytes, response.content)
    payload = {"status": "ok", "input": origen.name, "pdf": _reports_href(destino, reports_dir)}
    return ToolResult(message="Documento convertido a PDF.", data=payload, metadata={"tool": "ConvertirDocAPdf"})


def get_default_registry() -> MCPRegistry:
    registry = MCPRegistry()
    registry.register(
        ToolDefinition(
            name="GenerarInformeRepetitividad",
            description="Genera informe DOCX/PDF a partir de un Excel (.xlsx).",
            input_model=InformeRepetitividadArgs,
            handler=_run_informe_repetitividad,
        )
    )
    registry.register(
        ToolDefinition(
            name="ConvertirDocAPdf",
            description="Envía documentos al servicio de LibreOffice para convertir a PDF.",
            input_model=ConvertirDocArgs,
            handler=_run_convertir_doc,
            roles=["admin", "ownergroup"],
        )
    )
    return registry


__all__ = [
    "MCPRegistry",
    "ToolContext",
    "ToolDefinition",
    "ToolInvocationError",
    "ToolRequest",
    "ToolResult",
    "get_default_registry",
]
