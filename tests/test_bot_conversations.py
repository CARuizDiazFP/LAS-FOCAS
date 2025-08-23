# Nombre de archivo: test_bot_conversations.py
# Ubicación de archivo: tests/test_bot_conversations.py
# Descripción: Simula conversaciones completas de los flujos /sla y /repetitividad del bot

import asyncio
import sys
from types import SimpleNamespace
from pathlib import Path

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import FSInputFile

sys.path.append(str(Path(__file__).resolve().parents[1]))
from bot_telegram.handlers.intent import classify_message  # noqa: E402
from bot_telegram.flows import sla as sla_flow  # noqa: E402
from bot_telegram.flows import repetitividad as rep_flow  # noqa: E402


class DummyMessage:
    """Mensaje mínimo para tests que captura respuestas."""

    def __init__(self, text: str | None = None, document: object | None = None):
        self.text = text
        self.document = document
        self.from_user = SimpleNamespace(id=1)
        self.answers: list[str] = []
        self.documents: list[FSInputFile] = []

    async def answer(self, text: str, **kwargs) -> None:  # pragma: no cover - simple
        self.answers.append(text)

    async def answer_document(self, doc: FSInputFile) -> None:  # pragma: no cover - simple
        self.documents.append(doc)


class DummyDocument:
    """Documento que copia un archivo al destino solicitado."""

    def __init__(self, source: Path):
        self.file_name = source.name
        self.file_size = source.stat().st_size
        self._source = source

    async def download(self, destination: Path) -> None:  # pragma: no cover - simple
        destination.write_bytes(self._source.read_bytes())


def test_conversacion_sla(tmp_path, monkeypatch, sla_sample_file):
    """Flujo completo de SLA generando DOCX y PDF."""

    async def run() -> None:
        uploads = tmp_path / "uploads"
        reports = tmp_path / "reports"
        monkeypatch.setattr(sla_flow, "BASE_UPLOADS", uploads)
        monkeypatch.setattr("modules.informes_sla.config.BASE_UPLOADS", uploads)
        monkeypatch.setattr("modules.informes_sla.config.BASE_REPORTS", reports)
        monkeypatch.setattr(sla_flow, "SOFFICE_BIN", "soffice")
        monkeypatch.setattr("modules.informes_sla.config.SOFFICE_BIN", "soffice")

        def fake_convert(docx_path: str, soffice: str) -> str:
            pdf = Path(docx_path).with_suffix(".pdf")
            pdf.write_text("pdf")
            return str(pdf)

        monkeypatch.setattr("modules.common.libreoffice_export.convert_to_pdf", fake_convert)
        monkeypatch.setattr("modules.informes_sla.report.convert_to_pdf", fake_convert)

        class FakeResp:
            def json(self):
                return {
                    "normalized_text": "sla",
                    "intent": "Acción",
                    "confidence": 0.99,
                    "provider": "mock",
                }

        async def fake_post(self, url, json):
            return FakeResp()

        monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
        monkeypatch.setattr(
            "bot_telegram.handlers.intent._get_conn", lambda: SimpleNamespace(close=lambda: None)
        )
        monkeypatch.setattr(
            "bot_telegram.handlers.intent.insert_conversation", lambda conn, user_id: 1
        )
        monkeypatch.setattr(
            "bot_telegram.handlers.intent.insert_message", lambda *a, **k: None
        )

        storage = MemoryStorage()
        ctx = FSMContext(storage=storage, key=StorageKey(bot_id=1, chat_id=1, user_id=1))

        msg_inicio = DummyMessage(text="Necesito el informe de SLA")
        await classify_message(msg_inicio, ctx)
        assert sla_flow.SLAStates.WAITING_FILE.state == await ctx.get_state()

        origen = sla_sample_file
        msg_archivo = DummyMessage(document=DummyDocument(origen))
        await sla_flow.on_file(msg_archivo, ctx)
        assert sla_flow.SLAStates.WAITING_PERIOD.state == await ctx.get_state()

        msg_periodo = DummyMessage(text="06/2024")
        await sla_flow.on_period(msg_periodo, ctx)
        assert await ctx.get_state() is None

        paths = [Path(d.path) for d in msg_periodo.documents]
        docx = next(p for p in paths if p.suffix == ".docx")
        pdf = next(p for p in paths if p.suffix == ".pdf")
        assert docx.exists() and pdf.exists()

    asyncio.run(run())


def test_conversacion_repetitividad(tmp_path, monkeypatch, repetitividad_sample_file):
    """Flujo completo de repetitividad generando DOCX y PDF."""

    async def run() -> None:
        uploads = tmp_path / "uploads"
        reports = tmp_path / "reports"
        monkeypatch.setattr(rep_flow, "BASE_UPLOADS", uploads)
        monkeypatch.setattr("modules.informes_repetitividad.config.BASE_UPLOADS", uploads)
        monkeypatch.setattr("modules.informes_repetitividad.config.BASE_REPORTS", reports)
        monkeypatch.setattr(rep_flow, "SOFFICE_BIN", "soffice")
        monkeypatch.setattr("modules.informes_repetitividad.config.SOFFICE_BIN", "soffice")

        def fake_convert(docx_path: str, soffice: str) -> str:
            pdf = Path(docx_path).with_suffix(".pdf")
            pdf.write_text("pdf")
            return str(pdf)

        monkeypatch.setattr("modules.common.libreoffice_export.convert_to_pdf", fake_convert)
        monkeypatch.setattr("modules.informes_repetitividad.report.convert_to_pdf", fake_convert)

        class FakeResp:
            def json(self):
                return {
                    "normalized_text": "repetitividad",
                    "intent": "Acción",
                    "confidence": 0.99,
                    "provider": "mock",
                }

        async def fake_post(self, url, json):
            return FakeResp()

        monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
        monkeypatch.setattr(
            "bot_telegram.handlers.intent._get_conn", lambda: SimpleNamespace(close=lambda: None)
        )
        monkeypatch.setattr(
            "bot_telegram.handlers.intent.insert_conversation", lambda conn, user_id: 1
        )
        monkeypatch.setattr(
            "bot_telegram.handlers.intent.insert_message", lambda *a, **k: None
        )

        storage = MemoryStorage()
        ctx = FSMContext(storage=storage, key=StorageKey(bot_id=1, chat_id=1, user_id=1))

        msg_inicio = DummyMessage(text="Necesito informe de repetitividad")
        await classify_message(msg_inicio, ctx)
        assert rep_flow.RepetitividadStates.WAITING_FILE.state == await ctx.get_state()

        origen = repetitividad_sample_file
        msg_archivo = DummyMessage(document=DummyDocument(origen))
        await rep_flow.on_file(msg_archivo, ctx)
        assert rep_flow.RepetitividadStates.WAITING_PERIOD.state == await ctx.get_state()

        msg_periodo = DummyMessage(text="06/2024")
        await rep_flow.on_period(msg_periodo, ctx)
        assert await ctx.get_state() is None

        paths = [Path(d.path) for d in msg_periodo.documents]
        docx = next(p for p in paths if p.suffix == ".docx")
        pdf = next(p for p in paths if p.suffix == ".pdf")
        assert docx.exists() and pdf.exists()

    asyncio.run(run())
