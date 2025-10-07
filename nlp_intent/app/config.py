# Nombre de archivo: config.py
# Ubicación de archivo: nlp_intent/app/config.py
# Descripción: Manejo de configuración y variables de entorno para el servicio NLP

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Settings:
    # Proveedor LLM por defecto ahora forzado a "openai" para que todas las
    # clasificaciones (y futuras respuestas generativas) utilicen OpenAI salvo
    # que se configure explícitamente otra cosa vía variable de entorno.
    llm_provider: str = os.getenv("LLM_PROVIDER", "openai")
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    ollama_url: str = os.getenv("OLLAMA_URL", "http://ollama:11434")
    intent_threshold: float = float(os.getenv("INTENT_THRESHOLD", "0.7"))
    lang: str = os.getenv("LANG", "es")
    log_raw_text: bool = os.getenv("LOG_RAW_TEXT", "false").lower() == "true"
    # Fase 2 - configuración extendida
    intent_clarify_provider: str = os.getenv("INTENT_CLARIFY_PROVIDER", "heuristic")
    intent_action_provider: str = os.getenv("INTENT_ACTION_PROVIDER", "heuristic")  # heuristic|llm
    intent_domain_classifier: str = os.getenv("INTENT_DOMAIN_CLASSIFIER", "heuristic")
    intent_enable_answers: bool = os.getenv("INTENT_ENABLE_ANSWERS", "true").lower() == "true"
    intent_max_answer_chars: int = int(os.getenv("INTENT_MAX_ANSWER_CHARS", "800"))
    intent_actions_enabled: list[str] = tuple(
        a.strip() for a in os.getenv("INTENT_ACTIONS_ENABLED", "repetitividad_report").split(",") if a.strip()
    )

    def validate(self) -> None:
        """Validaciones básicas al iniciar el servicio.

        Reglas:
        - Si el proveedor es openai, la API key debe existir.
        """
        if self.llm_provider == "openai" and not self.openai_api_key:
            # Fail-fast para evitar confusión silenciosa (se documenta en docs/decisiones.md)
            raise RuntimeError("OPENAI_API_KEY ausente: defina la variable de entorno antes de iniciar el servicio NLP")


settings = Settings()
# Permitir que la suite de tests omita la validación estricta (por ejemplo para forzar heurística
# o mockear openai) estableciendo TESTING=true en el entorno antes de importar el módulo.
if os.getenv("TESTING", "false").lower() != "true":  # pragma: no branch
    try:  # Validación temprana (no se cubre en tests porque depende de entorno real)
        settings.validate()
    except RuntimeError as _e:  # pragma: no cover
        raise

