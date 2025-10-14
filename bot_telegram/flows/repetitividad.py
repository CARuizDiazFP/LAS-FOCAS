# Nombre de archivo: repetitividad.py
# Ubicación de archivo: bot_telegram/flows/repetitividad.py
# Descripción: Flujo para recibir Excel y generar el informe de repetitividad

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile, Message

from modules.informes_repetitividad.config import BASE_UPLOADS
from modules.informes_repetitividad.service import (
    ReportConfig,
    ReportResult,
    generar_informe_desde_excel,
)

router = Router()
logger = logging.getLogger(__name__)
REPORT_SERVICE_CONFIG = ReportConfig.from_settings()

class RepetitividadStates(StatesGroup):
    WAITING_FILE = State()
    WAITING_PERIOD = State()


async def start_repetitividad_flow(msg: Message, state: FSMContext, origin: str) -> None:
    """Inicia el flujo solicitando el archivo Excel."""
    tg_user_id = msg.from_user.id
    logger.info(
        "service=bot route=%s action=start_repetitividad_flow tg_user_id=%s",
        origin,
        tg_user_id,
    )
    await state.clear()
    await msg.answer(
        "📊 Enviá el Excel 'Casos' en formato .xlsx o /cancel para salir"
    )
    await state.set_state(RepetitividadStates.WAITING_FILE)


@router.message(RepetitividadStates.WAITING_FILE, F.document)
async def on_file(msg: Message, state: FSMContext) -> None:
    """Recibe y almacena el archivo enviado por el usuario."""
    document = msg.document
    if not document.file_name.lower().endswith(".xlsx"):
        await msg.answer("El archivo debe tener extensión .xlsx. Intentá nuevamente")
        return

    user_dir = BASE_UPLOADS / "telegram" / str(msg.from_user.id)
    user_dir.mkdir(parents=True, exist_ok=True)
    file_path = user_dir / document.file_name
    await document.download(destination=file_path)
    await state.update_data(file_path=str(file_path))

    prev_month = datetime.now().replace(day=1) - timedelta(days=1)
    sugerencia = prev_month.strftime("%m/%Y")
    await msg.answer(
        f"Ingresá el período a analizar (mm/aaaa). Ejemplo: {sugerencia}"
    )
    await state.set_state(RepetitividadStates.WAITING_PERIOD)


@router.message(RepetitividadStates.WAITING_FILE)
async def on_invalid_file(msg: Message) -> None:
    await msg.answer("Necesito un archivo .xlsx válido o /cancel para salir")


@router.message(RepetitividadStates.WAITING_PERIOD, F.text)
async def on_period(msg: Message, state: FSMContext) -> None:
    """Procesa el período y genera el informe."""
    texto = msg.text.strip()
    try:
        mes, anio = map(int, texto.split("/"))
        if not (1 <= mes <= 12 and anio >= 2000):
            raise ValueError
    except ValueError:
        await msg.answer("Formato inválido. Usá mm/aaaa, ej: 07/2024")
        return

    data = await state.get_data()
    file_path_str = data.get("file_path")
    if not file_path_str:
        await msg.answer("No se encontró el archivo cargado. Enviá el Excel nuevamente.")
        await state.clear()
        return

    file_path = Path(file_path_str)
    original_name = file_path.name

    periodo_titulo = f"{mes:02d}/{anio}"
    try:
        excel_bytes = file_path.read_bytes()
        result: ReportResult = await asyncio.to_thread(
            generar_informe_desde_excel,
            excel_bytes,
            periodo_titulo,
            True,
            REPORT_SERVICE_CONFIG,
        )
    except ValueError as exc:
        logger.warning("service=bot flow=repetitividad error=validation detail=%s", exc)
        await msg.answer(f"No pude procesar el archivo: {exc}")
        await state.clear()
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("service=bot flow=repetitividad error=unexpected msg=%s", exc)
        await msg.answer("Ocurrió un error inesperado generando el informe.")
        await state.clear()
        return
    finally:
        file_path.unlink(missing_ok=True)

    if result.docx:
        await msg.answer_document(FSInputFile(result.docx))
    if result.pdf:
        await msg.answer_document(FSInputFile(result.pdf))
    if result.map_html:
        try:
            await msg.answer_document(FSInputFile(result.map_html))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "service=bot flow=repetitividad map_send_failed path=%s error=%s",
                result.map_html,
                exc,
            )
    if not result.docx and not result.pdf:
        await msg.answer("No se generaron archivos para descargar.")
        await state.clear()
        return

    logger.info(
        "service=bot flow=repetitividad tg_user_id=%s file=%s periodo=%s map=%s filas=%s repetitivos=%s",
        msg.from_user.id,
        original_name,
        periodo_titulo,
        bool(result.map_html),
        result.total_filas,
        result.total_repetitivos,
    )
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
