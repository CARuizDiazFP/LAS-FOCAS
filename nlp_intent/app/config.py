# Nombre de archivo: config.py
# Ubicación de archivo: nlp_intent/app/config.py
# Descripción: Manejo de configuración y variables de entorno para el servicio NLP

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Settings:
    llm_provider: str = os.getenv("LLM_PROVIDER", "auto")
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    ollama_url: str = os.getenv("OLLAMA_URL", "http://ollama:11434")
    intent_threshold: float = float(os.getenv("INTENT_THRESHOLD", "0.7"))
    lang: str = os.getenv("LANG", "es")
    log_raw_text: bool = os.getenv("LOG_RAW_TEXT", "false").lower() == "true"


settings = Settings()

