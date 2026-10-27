# Nombre de archivo: office_client.py
# Ubicación de archivo: core/services/office_client.py
# Descripción: Cliente único de office_service (POST /convert) para convertir documentos a PDF

"""Conversión DOCX → PDF vía ``office:8090/convert``.

Las imágenes ``web``/``api`` no traen LibreOffice: todos los informes (SLA, SLA consumido,
Repetitividad) y la herramienta MCP ``ConvertirDocAPdf`` convierten con este cliente. Es sync a
propósito (los builders de informes son sync); desde código async se llama con
``asyncio.to_thread``.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# office corta cada conversión a los 120 s (OFFICE_CONVERT_TIMEOUT) y atiende de a una
# (Semaphore(1)): el margen cubre la espera en cola. Medido en dev (2026-10-27): Repetitividad
# 12,8 s, SLA 20,5 s, SLA consumido ejecutivo 46,9 s.
OFFICE_TIMEOUT = 150.0
# Mismo tope que OFFICE_MAX_FILE_SIZE de office_service: no se sube algo que va a rechazar con 413.
MAX_BYTES = 50 * 1024 * 1024


class ErrorConversionPdf(Exception):
    """Falla de conversión: ``mensaje`` es apto para el usuario; ``detalle`` va sólo al log."""

    codigo = "error"

    def __init__(self, mensaje: str, detalle: str = "") -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.detalle = detalle


class DocumentoDemasiadoGrande(ErrorConversionPdf):
    codigo = "documento_grande"


class OfficeInalcanzable(ErrorConversionPdf):
    codigo = "office_inalcanzable"


class OfficeTimeout(ErrorConversionPdf):
    codigo = "timeout"


class OfficeRechazo(ErrorConversionPdf):
    codigo = "rechazo"


def base_url() -> str:
    return os.getenv("OFFICE_SERVICE_BASE", "http://office:8090").rstrip("/")


def _cliente(timeout: float) -> httpx.Client:
    return httpx.Client(timeout=timeout)


def convertir_a_pdf(origen: Path | str, destino: Path | str | None = None, *, timeout: float = OFFICE_TIMEOUT) -> Path:
    """Sube ``origen`` a office y guarda el PDF en ``destino`` (por defecto, al lado del original).

    Levanta una subclase de :class:`ErrorConversionPdf`; nunca deja un PDF a medias.
    """

    origen = Path(origen)
    destino = Path(destino) if destino else origen.with_suffix(".pdf")
    if origen.stat().st_size > MAX_BYTES:
        raise DocumentoDemasiadoGrande(
            "El documento supera los 50 MB y no se convierte a PDF", f"bytes={origen.stat().st_size}"
        )
    contenido = origen.read_bytes()
    inicio = time.monotonic()
    try:
        with _cliente(timeout) as client:
            response = client.post(
                f"{base_url()}/convert",
                params={"output_format": "pdf"},
                files={"file": (origen.name, contenido, "application/octet-stream")},
            )
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise OfficeTimeout("La conversión a PDF tardó demasiado", str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        detalle = exc.response.text[:500]
        if exc.response.status_code == 504:
            raise OfficeTimeout("La conversión a PDF tardó demasiado", detalle) from exc
        raise OfficeRechazo("El servicio de conversión no pudo generar el PDF", detalle) from exc
    except httpx.HTTPError as exc:
        raise OfficeInalcanzable("El servicio de conversión a PDF no está disponible", str(exc)) from exc

    if not response.content.startswith(b"%PDF"):
        raise OfficeRechazo("El servicio de conversión no pudo generar el PDF", "la respuesta no es un PDF")
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name(destino.name + ".tmp")
    temporal.write_bytes(response.content)
    temporal.replace(destino)
    logger.info(
        "action=office_convert origen=%s pdf=%s bytes=%s ms=%.0f",
        origen.name,
        destino,
        len(response.content),
        (time.monotonic() - inicio) * 1000,
    )
    return destino


def intentar_pdf(origen: Path | str, *, contexto: str) -> tuple[Path | None, str | None]:
    """Conversión de un informe: nunca levanta. Devuelve ``(pdf, None)`` o ``(None, motivo)``.

    El informe ya está generado cuando se pide el PDF: una falla de office no puede convertirse en
    un 500; el llamador entrega el DOCX y expone ``motivo`` como ``pdf_error``.
    """

    try:
        return convertir_a_pdf(origen), None
    except ErrorConversionPdf as exc:
        logger.warning(
            "action=%s stage=pdf error=%s detalle=%s origen=%s", contexto, exc.codigo, exc.detalle, Path(origen).name
        )
        return None, exc.mensaje
    except OSError:
        logger.exception("action=%s stage=pdf error=io origen=%s", contexto, Path(origen).name)
        return None, "No se pudo guardar el PDF"


__all__ = [
    "MAX_BYTES",
    "OFFICE_TIMEOUT",
    "DocumentoDemasiadoGrande",
    "ErrorConversionPdf",
    "OfficeInalcanzable",
    "OfficeRechazo",
    "OfficeTimeout",
    "base_url",
    "convertir_a_pdf",
    "intentar_pdf",
]
