# Nombre de archivo: answer_generator.py
# Ubicación de archivo: nlp_intent/app/answer_generator.py
# Descripción: Generación de respuestas para consultas (fase 2)

from __future__ import annotations

import re
from .config import settings
from modules.common.faq_data import match_faq
from .providers import openai_provider, ollama_provider, heuristic

DOMAIN_KEYWORDS = [
    "sla", "latencia", "fibra", "telecom", "red", "uptime", "paquete", "packet", "perdida", "pérdida", "link", "enlace", "nodo", "traza", "alarma"
]


def domain_score(normalized: str) -> float:
    hits = sum(1 for k in DOMAIN_KEYWORDS if k in normalized)
    if not hits:
        return 0.0
    return min(1.0, 0.2 * hits)


async def generate_answer(text: str, normalized: str) -> tuple[str, str, float]:
    """Genera una respuesta (answer, source, domain_confidence)."""
    dscore = domain_score(normalized)
    # FAQ plantilla
    faq = match_faq(normalized)
    if faq:
        return faq, "faq", dscore
    if not settings.intent_enable_answers:
        return "", "disabled", dscore
    # Si dominio bajo y no hay signos de pregunta, pedir reformulación
    if dscore < 0.2 and "?" not in text:
        return (
            "¿Podrías detallar cómo se relaciona tu consulta con operaciones de red o telecomunicaciones?",
            "heuristic",
            dscore,
        )
    provider = settings.llm_provider
    if provider == "openai":
        try:
            ans = await _answer_openai(text, normalized, dscore)
            return ans, "openai", dscore
        except Exception:  # pragma: no cover
            pass
    if provider == "ollama":
        try:
            ans = await _answer_ollama(text, normalized, dscore)
            return ans, "ollama", dscore
        except Exception:  # pragma: no cover
            pass
    # Fallback heurístico
    return heuristic.clarify_question(text), "heuristic", dscore


async def _answer_openai(text: str, normalized: str, dscore: float) -> str:
    prompt = (
        "Respondé en español de forma clara y concisa. Contexto: asistente de operaciones de telecomunicaciones y redes. "
        "Si la pregunta no pertenece al dominio, respondé brevemente y recordá el foco. Max 3 párrafos cortos.\n"
        f"Mensaje: '{text}'\nRespuesta:"
    )
    # Reutilizamos API chat completions vía provider (clarify style adaptado)
    return await openai_provider.clarify_question(prompt, normalized)


async def _answer_ollama(text: str, normalized: str, dscore: float) -> str:
    prompt = (
        "Eres un asistente de redes/telecom. Responde brevemente (<=3 párrafos). "
        "Si fuera de dominio, indica brevemente y redirige al foco técnico.\n"
        f"Mensaje: '{text}'\nRespuesta:"
    )
    # Reutilizamos la función de clarify de ollama para no crear nueva ruta (simplicidad)
    return await ollama_provider.clarify_question(prompt, normalized)
