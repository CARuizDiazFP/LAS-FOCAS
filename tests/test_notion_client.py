# Nombre de archivo: test_notion_client.py
# Ubicación de archivo: tests/test_notion_client.py
# Descripción: Pruebas para el cliente de Notion

import httpx

from integrations.notion import NotionClient


def test_create_page_uses_token() -> None:
    """Verifica que create_page envía el token en la cabecera."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test_token"
        return httpx.Response(200, json={"id": "1"})

    transport = httpx.MockTransport(handler)
    client = NotionClient(token="test_token")
    client.http_client = httpx.Client(
        transport=transport,
        base_url="https://api.notion.com/v1",
        headers=client.http_client.headers,
    )
    result = client.create_page(
        {"parent": {"database_id": "db"}, "properties": {}}
    )
    assert result["id"] == "1"
