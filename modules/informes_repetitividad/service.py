# Nombre de archivo: service.py
# Ubicación de archivo: modules/informes_repetitividad/service.py
# Descripción: Helper asíncrono para invocar la API de reportes y almacenar resultados

"""Servicios auxiliares para generar informes de repetitividad vía API REST."""

from __future__ import annotations

import io
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import httpx

from .config import REPORTS_API_BASE, REPORTS_API_TIMEOUT


@dataclass(slots=True)
class ReportResult:
    """Resultado de la generación de reportes (paths en disco)."""

    docx: Path | None
    pdf: Path | None
    map_html: Path | None = None


def _extract_filename(content_disposition: str | None, fallback: str) -> str:
    if not content_disposition:
        return fallback
    import re as _re

    match = _re.search(r'filename="?([^";]+)', content_disposition)
    if match:
        return match.group(1)
    return fallback


async def _post_request(
    url: str,
    *,
    data: dict[str, str],
    files: dict[str, tuple[str, object, str]],
    timeout: float,
    client: httpx.AsyncClient | None = None,
) -> httpx.Response:
    close_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=timeout)
        close_client = True
    try:
        response = await client.post(url, data=data, files=files)
    finally:
        files["file"][1].close()
        if close_client:
            await client.aclose()
    response.raise_for_status()
    return response


async def generate_report(
    file_path: Path,
    mes: int,
    anio: int,
    output_dir: Path | str,
    *,
    include_pdf: bool = True,
    api_base: str | None = None,
    timeout: float | None = None,
    client: httpx.AsyncClient | None = None,
) -> ReportResult:
    """Invoca la API de repetitividad y almacena los archivos generados."""

    api_base = (api_base or REPORTS_API_BASE).rstrip("/")
    timeout = timeout or REPORTS_API_TIMEOUT

    files = {
        "file": (
            file_path.name,
            file_path.open("rb"),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }
    data = {
        "periodo_mes": str(mes),
        "periodo_anio": str(anio),
        "incluir_pdf": "true" if include_pdf else "false",
    }

    response = await _post_request(
        f"{api_base}/reports/repetitividad",
        data=data,
        files=files,
        timeout=timeout,
        client=client,
    )

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    content_type = response.headers.get("content-type", "")
    disposition = response.headers.get("content-disposition")
    docx_file: Path | None = None
    pdf_file: Path | None = None
    map_file: Path | None = None

    if "zip" in content_type:
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            for member in archive.infolist():
                filename = Path(member.filename).name
                dest = out_dir / filename
                with archive.open(member) as src, dest.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                if filename.lower().endswith(".docx"):
                    docx_file = dest
                elif filename.lower().endswith(".pdf"):
                    pdf_file = dest
                elif filename.lower().endswith(".html"):
                    map_file = dest
    else:
        filename = _extract_filename(
            disposition,
            f"repetitividad_{anio}{mes:02d}.docx",
        )
        dest = out_dir / filename
        dest.write_bytes(response.content)
        docx_file = dest

        map_hint = response.headers.get("x-map-filename")
        if map_hint:
            candidate = out_dir / map_hint
            if candidate.exists():
                map_file = candidate

    return ReportResult(docx=docx_file, pdf=pdf_file, map_html=map_file)


__all__: Iterable[str] = ["ReportResult", "generate_report"]
