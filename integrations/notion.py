# Nombre de archivo: notion.py
# Ubicación de archivo: integrations/notion.py
# Descripción: Cliente simple para interactuar con la API de Notion

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


class NotionClient:
    """Cliente para la API de Notion usando HTTPX."""

    def __init__(
        self,
        token: Optional[str] = None,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self.token = token or os.getenv("NOTION_TOKEN", "")
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }
        self.http_client = http_client or httpx.Client(
            base_url="https://api.notion.com/v1", headers=headers
        )

    def create_page(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Crea una página en Notion."""
        logger.info("service=notion action=create_page")
        response = self.http_client.post("/pages", json=payload, timeout=15.0)
        response.raise_for_status()
        return response.json()
