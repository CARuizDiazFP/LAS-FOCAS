# Nombre de archivo: cache.py
# Ubicación de archivo: nlp_intent/app/cache.py
# Descripción: Caché en memoria con expiración para respuestas de intención

from __future__ import annotations

import time
from typing import Any


class TTLCache:
    """Caché simple con expiración basada en tiempo."""

    def __init__(self, ttl: int) -> None:
        self.ttl = ttl
        self._data: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if not item:
            return None
        timestamp, value = item
        if time.monotonic() - timestamp > self.ttl:
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._data[key] = (time.monotonic(), value)

    def clear(self) -> None:
        """Limpia todo el contenido del caché."""
        self._data.clear()
