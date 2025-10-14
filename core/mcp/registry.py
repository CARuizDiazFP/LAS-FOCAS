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


class GenerarMapaGeoArgs(BaseModel):
    points: List[Dict[str, float]]
    out_path: str | None = None


class CompararTrazasArgs(BaseModel):
    file_a: str
    file_b: str


class ConvertirDocArgs(BaseModel):
    input_path: str
    out_dir: str | None = None


class RegistrarNotionArgs(BaseModel):
    page: str
    payload: Dict[str, Any]


# --------------------------------------------------------------------------------------
# Implementaciones de herramientas
# --------------------------------------------------------------------------------------


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
    )
    payload: Dict[str, Any] = {
        "status": "ok",
        "docx": f"/reports/{result.docx.name}" if result.docx else None,
        "pdf": f"/reports/{result.pdf.name}" if result.pdf else None,
        "map": f"/reports/{result.map_html.name}" if result.map_html else None,
    }
    message = (
        "Informe de Repetitividad generado. Revisá los enlaces en la sección de resultados."
    )
    return ToolResult(message=message, data=payload, metadata={"tool": "GenerarInformeRepetitividad"})


async def _run_generar_mapa(args: GenerarMapaGeoArgs, context: ToolContext) -> ToolResult:
    try:
        import folium  # noqa: WPS433
    except ImportError as exc:  # pragma: no cover - import guard
        raise ToolInvocationError("MISSING_DEPENDENCY", "folium no está instalado", detail=str(exc)) from exc

    if not args.points:
        raise ToolInvocationError("INVALID_POINTS", "Se requieren puntos para generar el mapa")

    latitudes = [float(p.get("lat", 0.0)) for p in args.points]
    longitudes = [float(p.get("lon", 0.0)) for p in args.points]
    center = (sum(latitudes) / len(latitudes), sum(longitudes) / len(longitudes))
    fmap = folium.Map(location=center, zoom_start=6)
    for point in args.points:
        folium.Marker(
            location=[float(point.get("lat", 0.0)), float(point.get("lon", 0.0))],
            popup=point.get("label", "Punto"),
            tooltip=point.get("label", "Punto"),
        ).add_to(fmap)
    reports_dir = Path(os.getenv("REPORTS_DIR", "/app/data/reports"))
    reports_dir.mkdir(parents=True, exist_ok=True)
    output_name = args.out_path or f"mapa_{int(time.time())}.html"
    output_path = reports_dir / output_name
    fmap.save(str(output_path))
    payload = {"status": "ok", "map": f"/reports/{output_path.name}"}
    return ToolResult(
        message="Mapa generado correctamente.",
        data=payload,
        metadata={"tool": "GenerarMapaGeo"},
    )


async def _run_comparar_trazas(args: CompararTrazasArgs, context: ToolContext) -> ToolResult:
    # TODO: Integrar cuando el comparador FO esté disponible.
    payload = {
        "status": "pending",
        "detail": "Comparador de trazas FO en desarrollo",
        "inputs": {"file_a": args.file_a, "file_b": args.file_b},
    }
    return ToolResult(
        message="El comparador FO todavía está en desarrollo. Guardé tu pedido para seguimiento.",
        data=payload,
        metadata={"tool": "CompararTrazasFO"},
    )


async def _run_convertir_doc(args: ConvertirDocArgs, context: ToolContext) -> ToolResult:
    base_url = os.getenv("OFFICE_SERVICE_BASE", "http://office_service:8003")
    target_dir = args.out_dir or os.getenv("REPORTS_DIR", "/app/data/reports")
    payload = {
        "status": "pending",
        "message": "Conversión delegada al office_service",
        "input": args.input_path,
        "output_dir": target_dir,
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{base_url}/convert",
                json={
                    "input_path": args.input_path,
                    "output_dir": target_dir,
                },
            )
        response.raise_for_status()
        data = response.json()
        payload.update(data)
        status_msg = data.get("status", "ok")
        message = data.get("message", "Documento convertido.")
        metadata = {"tool": "ConvertirDocAPdf", "status": status_msg}
        return ToolResult(message=message, data=payload, metadata=metadata)
    except httpx.HTTPStatusError as exc:
        raise ToolInvocationError("CONVERT_HTTP_ERROR", "Falló la conversión", detail=exc.response.text) from exc
    except httpx.HTTPError as exc:  # noqa: BLE001
        raise ToolInvocationError("CONVERT_NETWORK_ERROR", "No se pudo contactar al servicio de conversión", detail=str(exc)) from exc


async def _run_registrar_notion(args: RegistrarNotionArgs, context: ToolContext) -> ToolResult:
    # Placeholder: se registrará la integración real con Notion.
    logger.info(
        "action=notion_placeholder user_id=%s page=%s payload_keys=%s",
        context.user_id,
        args.page,
        sorted(args.payload.keys()),
    )
    payload = {
        "status": "pending",
        "detail": "Integración con Notion en preparación",
        "page": args.page,
    }
    return ToolResult(
        message="Notion aún no está integrado. Avisaremos cuando esté disponible.",
        data=payload,
        metadata={"tool": "RegistrarEnNotion"},
    )


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
            name="GenerarMapaGeo",
            description="Construye un mapa Folium desde puntos lat/lon.",
            input_model=GenerarMapaGeoArgs,
            handler=_run_generar_mapa,
        )
    )
    registry.register(
        ToolDefinition(
            name="CompararTrazasFO",
            description="Compara archivos de trazas FO (en desarrollo).",
            input_model=CompararTrazasArgs,
            handler=_run_comparar_trazas,
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
    registry.register(
        ToolDefinition(
            name="RegistrarEnNotion",
            description="Registra información en una página de Notion (placeholder).",
            input_model=RegistrarNotionArgs,
            handler=_run_registrar_notion,
            roles=["admin"],
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
