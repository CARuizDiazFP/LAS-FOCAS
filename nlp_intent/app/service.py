# Nombre de archivo: service.py
# Ubicación de archivo: nlp_intent/app/service.py
# Descripción: Orquestador de clasificación de intención y selección de proveedor

from __future__ import annotations

import hashlib
import logging
import re
import os

from .config import settings
from .schemas import IntentResponse, IntentionResult
from .providers import heuristic, ollama_provider, openai_provider
from .config import settings
from .action_classifier import classify_action
from .answer_generator import generate_answer

logger = logging.getLogger(__name__)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


async def classify_text(text: str) -> IntentResponse:  # pragma: no cover - deprecated wrapper
    """(DEPRECADO) Mantiene contrato anterior para retrocompatibilidad.

    Usar analyze_intention para nueva funcionalidad.
    """
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


def _map_intention(raw: str) -> str:
    if raw == "Acción":
        return "Solicitud de acción"
    if raw == "Consulta":
        return "Consulta/Generico"
    return "Otros"


async def _classify_raw(text: str) -> IntentResponse:
    return await classify_text(text)


async def _clarify(text: str, normalized: str, provider: str) -> str:
    clarify_provider = os.getenv("INTENT_CLARIFY_PROVIDER", provider).lower()
    # off => no pregunta
    if clarify_provider == "off":
        return ""
    # heurístico siempre disponible
    if clarify_provider == "heuristic":
        return heuristic.clarify_question(text)
    # openai
    if clarify_provider == "openai":
        try:
            return await openai_provider.clarify_question(text, normalized)
        except Exception as exc:  # pragma: no cover
            logger.warning("clarify_openai_fallo", extra={"error": str(exc)})
            return heuristic.clarify_question(text)
    if clarify_provider == "ollama":
        try:
            return await ollama_provider.clarify_question(text, normalized)
        except Exception as exc:  # pragma: no cover
            logger.warning("clarify_ollama_fallo", extra={"error": str(exc)})
            return heuristic.clarify_question(text)
    # fallback final heurístico
    return heuristic.clarify_question(text)


async def analyze_intention(text: str) -> IntentionResult:
    raw_resp = await _classify_raw(text)
    mapped = _map_intention(raw_resp.intent)
    need_clar = mapped == "Otros"
    clarification = None
    if need_clar:
        clarification_text = await _clarify(text, raw_resp.normalized_text, raw_resp.provider)
        clarification = clarification_text or None
    # Fase 2: acciones y respuestas
    action_code = None
    action_supported: bool | None = None
    action_reason = None
    answer = None
    answer_source = None
    domain_confidence = None
    next_action = None

    if mapped == "Solicitud de acción":
        ar = classify_action(raw_resp.normalized_text)
        action_code = ar.action_code
        action_reason = ar.reason
        action_supported = ar.action_code in settings.intent_actions_enabled and ar.action_code != "unsupported"
        if action_supported:
            next_action = f"trigger:{action_code}"
        else:
            # Mensaje limitando capacidades actuales
            clarification = None  # ya no aplica
            need_clar = False
    elif mapped == "Consulta/Generico":
        ans, src, dscore = await generate_answer(text, raw_resp.normalized_text)
        answer = ans or None
        answer_source = src
        domain_confidence = dscore

    result = IntentionResult(
        intention_raw=raw_resp.intent,
        intention=mapped,
        confidence=raw_resp.confidence,
        provider=raw_resp.provider,
        normalized_text=raw_resp.normalized_text,
        need_clarification=need_clar and bool(clarification),
        clarification_question=clarification,
        next_action=next_action,
        action_code=action_code,
        action_supported=action_supported,
        action_reason=action_reason,
        answer=answer,
        answer_source=answer_source,
        domain_confidence=domain_confidence,
    )
    return result


