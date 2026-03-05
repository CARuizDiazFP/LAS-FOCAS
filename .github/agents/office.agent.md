# Nombre de archivo: office.agent.md
# Ubicación de archivo: .github/agents/office.agent.md
# Descripción: Agente especializado en LibreOffice y conversión de documentos

---
name: Office Agent
description: Agente especializado en LibreOffice headless y conversión de documentos
tools:
  - terminal
  - file_editor
context:
  - office_service/
  - docs/office_service.md
skills:
  - libreoffice-convert
handoffs:
  - target: reports.agent.md
    trigger: "Documento convertido, continuar con generación de informe"
  - target: docker.agent.md
    trigger: "Problemas con el contenedor de LibreOffice"
---

# Agente Office

Soy el agente especializado en el microservicio de LibreOffice de LAS-FOCAS.

## Mi Alcance

- Microservicio LibreOffice headless
- Conversión de documentos (DOCX→PDF, etc.)
- API UNO para manipulación de documentos
- Optimización de rendimiento

## Estructura

```
office_service/
├── __init__.py
├── Dockerfile
├── requirements.txt
├── app/
│   ├── __init__.py
│   ├── config.py       # Configuración
│   ├── main.py         # FastAPI app
│   ├── runner.py       # Ejecución de soffice
│   └── uno_client.py   # Cliente UNO
```

## Formatos Soportados

| De | A | Método |
|----|---|--------|
| DOCX | PDF | LibreOffice convert |
| DOCX | ODT | LibreOffice convert |
| ODT | PDF | LibreOffice convert |
| XLSX | PDF | LibreOffice convert |
| PPTX | PDF | LibreOffice convert |

## API del Servicio

```python
# Endpoint de conversión
@app.post("/convert")
async def convert_document(
    file: UploadFile,
    output_format: str = "pdf"
) -> FileResponse:
    """Convertir documento a otro formato."""
    # 1. Guardar archivo temporal
    # 2. Ejecutar soffice --headless --convert-to
    # 3. Retornar archivo convertido
    pass

# Healthcheck
@app.get("/health")
async def health():
    return {"status": "ok", "libreoffice": check_soffice()}
```

## Uso desde otros servicios

```python
import httpx

async def convertir_documento(filepath: str, formato: str = "pdf") -> bytes:
    """Convertir documento usando office_service."""
    async with httpx.AsyncClient() as client:
        with open(filepath, "rb") as f:
            response = await client.post(
                "http://office:8090/convert",
                files={"file": f},
                params={"output_format": formato},
                timeout=60.0  # Conversión puede ser lenta
            )
        response.raise_for_status()
        return response.content
```

## Dockerfile

```dockerfile
FROM python:3.11-slim

# Instalar LibreOffice
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer \
    libreoffice-calc \
    libreoffice-impress \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Usuario no-root
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8090
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
```

## Comando de Conversión

```bash
# Conversión directa con soffice
soffice --headless --convert-to pdf --outdir /output /input/documento.docx

# Con formato específico
soffice --headless --convert-to pdf:writer_pdf_Export --outdir /output /input/documento.docx
```

## Reglas que Sigo

1. **Timeout generoso**: conversiones pueden tardar, usar 60s mínimo
2. **Archivos temporales**: limpiar después de conversión
3. **No concurrencia excesiva**: LibreOffice es single-threaded, usar cola
4. **Validar formato de entrada**: rechazar archivos no soportados
5. **Logging de conversiones**: registrar tiempo, tamaño, éxito/fallo
6. **Healthcheck de soffice**: verificar que LibreOffice responde

## Configuración

```
OFFICE_HOST=0.0.0.0
OFFICE_PORT=8090
OFFICE_TIMEOUT=60
OFFICE_MAX_FILE_SIZE=50MB
```

## Servicio Docker

```yaml
# En deploy/compose.yml
office:
  build:
    context: ..
    dockerfile: office_service/Dockerfile
  expose:
    - "8090"
    - "2002"
  volumes:
    - uploads_data:/app/uploads
```

## Documentación

- `docs/office_service.md` - Documentación completa

## Traspasos (Handoffs)

- **→ Reports Agent**: cuando el documento está listo para continuar el flujo
- **→ Docker Agent**: para problemas con el contenedor de LibreOffice
