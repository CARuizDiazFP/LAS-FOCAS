# Nombre de archivo: integrations.md
# Ubicación de archivo: docs/integrations.md
# Descripción: Documentación de clientes de integraciones externas (Notion y Email)

## Notion

Cliente HTTP sencillo que se comunica con la API oficial de Notion.
Requiere el token almacenado en la variable `NOTION_TOKEN`.

```python
from integrations.notion import NotionClient

cliente = NotionClient()
cliente.create_page({"parent": {"database_id": "db"}, "properties": {}})
```

## Correo SMTP

Cliente para el envío de correos electrónicos.
Utiliza las variables `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`
y `SMTP_FROM` para autenticarse y definir el remitente. Estas credenciales
pueden suministrarse mediante Docker Secrets montados en `/run/secrets/`.

```python
from integrations.email import EmailClient

correo = EmailClient()
correo.send_mail("destino@example.com", "Asunto", "Mensaje")
```
