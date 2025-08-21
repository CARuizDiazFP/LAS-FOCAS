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
from .cache import TTLCache

MAX_PROVIDER_ERRORS = 3
failure_counts: dict[str, int] = {"ollama": 0, "openai": 0}
disabled_providers: set[str] = set()

logger = logging.getLogger(__name__)
cache = TTLCache(ttl=settings.cache_ttl)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


async def classify_text(text: str) -> IntentResponse:
    normalized = _normalize(text)
    cache_key = hashlib.sha256(normalized.encode()).hexdigest()
    hash_text = hashlib.sha256(text.encode()).hexdigest()
    log_extra = {"len_text": len(text), "hash_sha256": hash_text}

    cached = cache.get(cache_key)
    if cached:
        logger.info(
            "cache_hit",
            extra={
                **log_extra,
                "provider": cached.provider,
                "intent": cached.intent,
                "confidence": cached.confidence,
            },
        )
        return cached

    if settings.llm_provider in ("heuristic", "auto"):
        intent, confidence = heuristic.classify(normalized)
        logger.info(
            "clasificación",
            extra={
                **log_extra,
                "provider": "heuristic",
                "intent": intent,
                "confidence": confidence,
            },
        )
        if settings.llm_provider != "auto" or confidence >= settings.intent_threshold:
            resp = IntentResponse(
                intent=intent,
                confidence=confidence,
                provider="heuristic",
                normalized_text=normalized,
            )
            cache.set(cache_key, resp)
            return resp

    if (
        settings.llm_provider in ("ollama", "auto")
        and "ollama" not in disabled_providers
    ):
        try:
            resp = await ollama_provider.classify(text, normalized)
            failure_counts["ollama"] = 0
            logger.info(
                "clasificación",
                extra={
                    **log_extra,
                    "provider": resp.provider,
                    "intent": resp.intent,
                    "confidence": resp.confidence,
                },
            )
            if (
                settings.llm_provider != "auto"
                or resp.confidence >= settings.intent_threshold
            ):
                cache.set(cache_key, resp)
                return resp
        except Exception as exc:  # pragma: no cover - manejo de fallos externo
            failure_counts["ollama"] += 1
            logger.warning("ollama_fallo", extra={**log_extra, "error": str(exc)})
            if failure_counts["ollama"] >= MAX_PROVIDER_ERRORS:
                disabled_providers.add("ollama")
                logger.error("ollama_desactivado", extra=log_extra)
                if settings.llm_provider == "ollama":
                    settings.llm_provider = "heuristic"

    if (
        settings.llm_provider in ("openai", "auto")
        and "openai" not in disabled_providers
    ):
        try:
            resp = await openai_provider.classify(text, normalized)
            failure_counts["openai"] = 0
            logger.info(
                "clasificación",
                extra={
                    **log_extra,
                    "provider": resp.provider,
                    "intent": resp.intent,
                    "confidence": resp.confidence,
                },
            )
            cache.set(cache_key, resp)
            return resp
        except Exception as exc:  # pragma: no cover
            failure_counts["openai"] += 1
            logger.warning("openai_fallo", extra={**log_extra, "error": str(exc)})
            if failure_counts["openai"] >= MAX_PROVIDER_ERRORS:
                disabled_providers.add("openai")
                logger.error("openai_desactivado", extra=log_extra)
                if settings.llm_provider == "openai":
                    settings.llm_provider = "heuristic"

    # Fallback final
    resp = IntentResponse(
        intent="Otros", confidence=0.0, provider="none", normalized_text=normalized
    )
    cache.set(cache_key, resp)
    return resp
