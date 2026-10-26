# Nombre de archivo: conversion.py
# Ubicación de archivo: office_service/app/conversion.py
# Descripción: Conversión de documentos con soffice headless en un directorio y perfil temporales

"""Conversión de documentos a PDF con LibreOffice.

Cada conversión corre un `soffice --convert-to` propio con un perfil de usuario temporal: el perfil por
defecto lo tiene tomado la instancia UNO que levanta `runner.py`, y un segundo proceso sobre el mismo
perfil termina sin convertir. Las conversiones se serializan (LibreOffice es pesado y single-threaded).
"""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
from pathlib import Path

LOGGER = logging.getLogger(__name__)

# La imagen sólo instala libreoffice-writer: documentos de texto, no planillas ni presentaciones.
EXTENSIONES_ENTRADA = frozenset({".docx", ".doc", ".odt", ".rtf"})
FORMATOS_SALIDA = frozenset({"pdf"})

_SEMAFORO = asyncio.Semaphore(1)


class ConversionError(RuntimeError):
    """soffice terminó sin generar el archivo de salida."""


class ConversionTimeout(ConversionError):
    """soffice superó el tiempo máximo de conversión."""


def nombre_seguro(nombre: str) -> str:
    """Nombre de archivo sin rutas ni caracteres raros, conservando la extensión."""

    base = Path(nombre or "documento").name
    limpio = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return limpio or "documento"


def armar_comando(binario: str, entrada: Path, directorio: Path, formato: str) -> list[str]:
    perfil = (directorio / "perfil").as_uri()
    return [
        binario,
        f"-env:UserInstallation={perfil}",
        "--headless",
        "--norestore",
        "--nologo",
        "--convert-to",
        formato,
        str(entrada),
        "--outdir",
        str(directorio),
    ]


async def _ejecutar(comando: list[str], directorio: Path, timeout: float) -> None:
    proceso = await asyncio.create_subprocess_exec(
        *comando,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(directorio),
    )
    try:
        salida, _ = await asyncio.wait_for(proceso.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        proceso.kill()
        await proceso.wait()
        raise ConversionTimeout(f"soffice superó {timeout:.0f} s") from exc
    if proceso.returncode != 0:
        LOGGER.warning(
            "action=convert_soffice_error returncode=%s salida=%s",
            proceso.returncode,
            (salida or b"").decode(errors="replace")[-500:],
        )


async def convertir(contenido: bytes, nombre: str, formato: str, binario: str, timeout: float) -> tuple[bytes, str]:
    """Convierte `contenido` al `formato` pedido; devuelve (bytes, nombre del archivo de salida)."""

    entrada_nombre = nombre_seguro(nombre)
    async with _SEMAFORO:
        with tempfile.TemporaryDirectory(prefix="convert_") as tmp:
            directorio = Path(tmp)
            entrada = directorio / entrada_nombre
            entrada.write_bytes(contenido)
            await _ejecutar(armar_comando(binario, entrada, directorio, formato), directorio, timeout)
            salida = directorio / f"{entrada.stem}.{formato}"
            if not salida.exists():
                raise ConversionError(f"soffice no generó {salida.name}")
            return salida.read_bytes(), salida.name


__all__ = [
    "EXTENSIONES_ENTRADA",
    "FORMATOS_SALIDA",
    "ConversionError",
    "ConversionTimeout",
    "armar_comando",
    "convertir",
    "nombre_seguro",
]
