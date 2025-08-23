# Nombre de archivo: repetitividad.py
# Ubicación de archivo: bot_telegram/flows/repetitividad.py
# Descripción: Flujo para recibir Excel y generar el informe de repetitividad

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Document, FSInputFile, Message

from modules.informes_repetitividad.config import BASE_UPLOADS, SOFFICE_BIN
from modules.informes_repetitividad.runner import run
from core.logging import request_id_var

router = Router()
logger = logging.getLogger(__name__)


def build_repetitividad_prompt() -> str:
    """Devuelve el texto inicial que solicita el archivo al usuario."""
    return (
        "📊 Enviá el Excel 'Casos' en formato .xlsx (máx 10MB) o /cancel para salir"
    )


def validate_document(document: Document) -> tuple[bool, str]:
    """Valida nombre, extensión y tamaño del archivo recibido."""
    if Path(document.file_name).name != document.file_name:
        return False, "El nombre del archivo es inválido. Intentá nuevamente"
    if not document.file_name.lower().endswith(".xlsx"):
        return False, "El archivo debe tener extensión .xlsx. Intentá nuevamente"
    if document.file_size and document.file_size > 10 * 1024 * 1024:
        return (
            False,
            "El archivo excede el tamaño máximo de 10MB. Intentá nuevamente",
        )
    return True, ""


def validate_period(texto: str) -> tuple[bool, str, int, int]:
    """Valida el período en formato mm/aaaa y devuelve mes y año."""
    if not re.fullmatch(r"\d{2}/\d{4}", texto):
        return False, "Formato inválido. Usá mm/aaaa, ej: 07/2024", 0, 0
    mes, anio = map(int, texto.split("/"))
    if not (1 <= mes <= 12 and anio >= 2000):
        return False, "Período fuera de rango. Usá mm/aaaa, ej: 07/2024", 0, 0
    return True, "", mes, anio


def cleanup_files(*paths: str) -> None:
    """Elimina archivos temporales y registra errores si los hubiera."""
    for p in paths:
        try:
            Path(p).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning(
                json.dumps(
                    {
                        "service": "bot",
                        "flow": "repetitividad",
                        "event": "cleanup_error",
                        "file": p,
                        "error": str(exc),
                        "request_id": request_id_var.get(),
                    }
                )
            )


class RepetitividadStates(StatesGroup):
    WAITING_FILE = State()
    WAITING_PERIOD = State()


async def start_repetitividad_flow(msg: Message, state: FSMContext, origin: str) -> None:
    """Inicia el flujo solicitando el archivo Excel."""
    tg_user_id = msg.from_user.id
    logger.info(
        json.dumps(
            {
                "service": "bot",
                "flow": "repetitividad",
                "tg_user_id": tg_user_id,
                "event": "start",
                "origin": origin,
                "request_id": request_id_var.get(),
            }
        )
    )
    await state.clear()
    await msg.answer(build_repetitividad_prompt())
    await state.set_state(RepetitividadStates.WAITING_FILE)


@router.message(RepetitividadStates.WAITING_FILE, F.document)
async def on_file(msg: Message, state: FSMContext) -> None:
    """Recibe y almacena el archivo enviado por el usuario."""
    document = msg.document
    is_valid, error = validate_document(document)
    if not is_valid:
        logger.warning(
            json.dumps(
                {
                    "service": "bot",
                    "flow": "repetitividad",
                    "tg_user_id": msg.from_user.id,
                    "event": "invalid_file",
                    "reason": error,
                    "request_id": request_id_var.get(),
                }
            )
        )
        await msg.answer(error)
        return

    user_dir = BASE_UPLOADS / "telegram" / str(msg.from_user.id)
    user_dir.mkdir(parents=True, exist_ok=True)
    file_path = user_dir / document.file_name
    await document.download(destination=file_path)
    await state.update_data(file_path=str(file_path))

    logger.info(
        json.dumps(
            {
                "service": "bot",
                "flow": "repetitividad",
                "tg_user_id": msg.from_user.id,
                "event": "file_received",
                "file": document.file_name,
                "request_id": request_id_var.get(),
            }
        )
    )

    prev_month = datetime.now().replace(day=1) - timedelta(days=1)
    sugerencia = prev_month.strftime("%m/%Y")
    await msg.answer(
        f"Ingresá el período a analizar (mm/aaaa). Ejemplo: {sugerencia}"
    )
    await state.set_state(RepetitividadStates.WAITING_PERIOD)


@router.message(RepetitividadStates.WAITING_FILE)
async def on_invalid_file(msg: Message) -> None:
    await msg.answer(
        "Necesito un archivo .xlsx válido (máx 10MB) o /cancel para salir"
    )


@router.message(RepetitividadStates.WAITING_PERIOD, F.text)
async def on_period(msg: Message, state: FSMContext) -> None:
    """Procesa el período y genera el informe."""
    texto = msg.text.strip()
    valido, error, mes, anio = validate_period(texto)
    if not valido:
        await msg.answer(error)
        return

    data = await state.get_data()
    file_path = data.get("file_path")
    soffice_bin = SOFFICE_BIN
    try:
        paths = run(file_path, mes, anio, soffice_bin)
    except ValueError as exc:
        logger.warning(
            json.dumps(
                {
                    "service": "bot",
                    "flow": "repetitividad",
                    "tg_user_id": msg.from_user.id,
                    "event": "invalid_excel",
                    "error": str(exc),
                    "request_id": request_id_var.get(),
                }
            )
        )
        await msg.answer("El Excel no tiene el formato esperado o contiene datos inválidos")
        cleanup_files(file_path)
        await state.clear()
        return
    except Exception as exc:  # pragma: no cover - logging
        logger.exception(
            json.dumps(
                {
                    "service": "bot",
                    "flow": "repetitividad",
                    "tg_user_id": msg.from_user.id,
                    "event": "processing_error",
                    "error": str(exc),
                    "request_id": request_id_var.get(),
                }
            )
        )
        await msg.answer("Ocurrió un error al generar el informe")
        cleanup_files(file_path)
        await state.clear()
        return

    await msg.answer_document(FSInputFile(paths["docx"]))
    if paths.get("pdf"):
        await msg.answer_document(FSInputFile(paths["pdf"]))

    enlaces = [f"DOCX: file://{paths['docx']}"]
    if paths.get("pdf"):
        enlaces.append(f"PDF: file://{paths['pdf']}")
    await msg.answer("Informe generado\n" + "\n".join(enlaces))

    logger.info(
        json.dumps(
            {
                "service": "bot",
                "flow": "repetitividad",
                "tg_user_id": msg.from_user.id,
                "event": "report_generated",
                "file": Path(file_path).name,
                "periodo": f"{mes:02d}/{anio:04d}",
                "request_id": request_id_var.get(),
            }
        )
    )

    async def _cleanup() -> None:
        cleanup_files(file_path, *paths.values())

    asyncio.create_task(_cleanup())
    await state.clear()


@router.message(RepetitividadStates.WAITING_PERIOD)
async def on_invalid_period(msg: Message) -> None:
    await msg.answer("Debés ingresar el período en formato mm/aaaa o /cancel")


@router.message(Command("cancel"))
async def on_cancel(msg: Message, state: FSMContext) -> None:
    """Cancela cualquier estado activo del flujo."""
    if await state.get_state() is not None:
        await state.clear()
        await msg.answer("Operación cancelada")
        logger.info(
            json.dumps(
                {
                    "service": "bot",
                    "flow": "repetitividad",
                    "tg_user_id": msg.from_user.id,
                    "event": "cancel",
                    "request_id": request_id_var.get(),
                }
            )
        )
    else:
        await msg.answer("No hay una operación activa")

