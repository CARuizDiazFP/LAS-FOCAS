# Nombre de archivo: service.py
# Ubicación de archivo: nlp_intent/app/service.py
# Descripción: Orquestador de clasificación de intención y selección de proveedor

from __future__ import annotations

import hashlib
import logging
import re

from .config import settings
from .schemas import IntentResponse
from .providers import heuristic, ollama_provider, openai_provider

logger = logging.getLogger(__name__)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


async def classify_text(text: str) -> IntentResponse:
    normalized = _normalize(text)
    hash_text = hashlib.sha256(text.encode()).hexdigest()
    log_extra = {"len_text": len(text), "hash_sha256": hash_text}

    if settings.llm_provider in ("heuristic", "auto"):
        intent, confidence = heuristic.classify(normalized)
        logger.info(
            "clasificación",
            extra={**log_extra, "provider": "heuristic", "intent": intent, "confidence": confidence},
        )
        if settings.llm_provider != "auto" or confidence >= settings.intent_threshold:
            return IntentResponse(
                intent=intent,
                confidence=confidence,
                provider="heuristic",
                normalized_text=normalized,
            )

    if settings.llm_provider in ("ollama", "auto"):
        try:
            resp = await ollama_provider.classify(text, normalized)
            logger.info(
                "clasificación",
                extra={**log_extra, "provider": resp.provider, "intent": resp.intent, "confidence": resp.confidence},
            )
            if settings.llm_provider != "auto" or resp.confidence >= settings.intent_threshold:
                return resp
        except Exception as exc:  # pragma: no cover - manejo de fallos externo
            logger.warning("ollama_fallo", extra={**log_extra, "error": str(exc)})

    if settings.llm_provider in ("openai", "auto"):
        try:
            resp = await openai_provider.classify(text, normalized)
            logger.info(
                "clasificación",
                extra={**log_extra, "provider": resp.provider, "intent": resp.intent, "confidence": resp.confidence},
            )
            return resp
        except Exception as exc:  # pragma: no cover
            logger.warning("openai_fallo", extra={**log_extra, "error": str(exc)})

    # Fallback final
    return IntentResponse(intent="Otros", confidence=0.0, provider="none", normalized_text=normalized)


