# Nombre de archivo: SKILL.md
# Ubicación de archivo: .github/skills/libreoffice-convert/SKILL.md
# Descripción: Habilidad para conversión de documentos con LibreOffice/office_service

---
name: LibreOffice Convert
description: Habilidad para convertir documentos usando el microservicio office_service
---

# Habilidad: Conversión con LibreOffice

Guía para convertir documentos usando el microservicio `office_service` de LAS-FOCAS.

## Servicio

El microservicio `office_service` encapsula LibreOffice headless para conversión de documentos.

- **Puerto interno**: 8090
- **Contenedor**: `office`
- **Ubicación**: `office_service/`

## Formatos Soportados

| Entrada | Salida | Comando |
|---------|--------|---------|
| DOCX | PDF | `--convert-to pdf` |
| DOCX | ODT | `--convert-to odt` |
| ODT | PDF | `--convert-to pdf` |
| XLSX | PDF | `--convert-to pdf` |
| PPTX | PDF | `--convert-to pdf` |
| HTML | PDF | `--convert-to pdf` |

## Uso desde Código Python

### Cliente HTTP

```python
import httpx

async def convertir_a_pdf(filepath: str) -> bytes:
    """Convertir documento a PDF usando office_service."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        with open(filepath, "rb") as f:
            response = await client.post(
                "http://office:8090/convert",
                files={"file": (filepath, f, "application/octet-stream")},
                params={"output_format": "pdf"}
            )
        response.raise_for_status()
        return response.content

# Uso
pdf_bytes = await convertir_a_pdf("/tmp/documento.docx")
with open("/tmp/documento.pdf", "wb") as f:
    f.write(pdf_bytes)
```

### Con manejo de errores

```python
import httpx
import logging

logger = logging.getLogger(__name__)

async def convertir_documento(
    filepath: str,
    output_format: str = "pdf",
    timeout: float = 60.0
) -> bytes | None:
    """
    Convertir documento a otro formato.
    
    Args:
        filepath: Ruta al archivo de entrada
        output_format: Formato de salida (pdf, odt, etc.)
        timeout: Timeout en segundos
        
    Returns:
        Bytes del documento convertido o None si falla
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            with open(filepath, "rb") as f:
                response = await client.post(
                    "http://office:8090/convert",
                    files={"file": f},
                    params={"output_format": output_format}
                )
            response.raise_for_status()
            logger.info(
                "Documento convertido",
                extra={
                    "input": filepath,
                    "output_format": output_format,
                    "size_bytes": len(response.content)
                }
            )
            return response.content
            
    except httpx.TimeoutException:
        logger.error("Timeout en conversión", extra={"filepath": filepath})
        return None
    except httpx.HTTPStatusError as e:
        logger.error(
            "Error HTTP en conversión",
            extra={"status": e.response.status_code, "filepath": filepath}
        )
        return None
    except Exception as e:
        logger.exception("Error inesperado en conversión")
        return None
```

## Uso desde Línea de Comandos

### Dentro del contenedor

```bash
# Entrar al contenedor
docker compose -f deploy/compose.yml exec office bash

# Convertir directamente con soffice
soffice --headless --convert-to pdf --outdir /tmp /ruta/documento.docx
```

### Con curl desde fuera

```bash
# Convertir archivo
curl -X POST "http://localhost:8090/convert?output_format=pdf" \
  -F "file=@documento.docx" \
  -o documento.pdf
```

## API del Servicio

### POST /convert

Convierte un documento a otro formato.

**Parámetros:**
- `file`: Archivo a convertir (multipart/form-data)
- `output_format`: Formato de salida (query param, default: "pdf")

**Respuesta:** Archivo convertido (application/octet-stream)

**Códigos de estado:**
- 200: Conversión exitosa
- 400: Formato no soportado
- 500: Error en conversión

### GET /health

Verifica estado del servicio.

**Respuesta:**
```json
{
  "status": "ok",
  "libreoffice": true
}
```

## Consideraciones de Performance

1. **Timeout generoso**: Las conversiones pueden tardar 30-60s para documentos grandes
2. **No concurrencia excesiva**: LibreOffice es single-threaded
3. **Limpiar archivos temporales**: El servicio limpia automáticamente
4. **Límite de tamaño**: Configurar `OFFICE_MAX_FILE_SIZE` (default 50MB)

## Integración con Informes

En los módulos de informes (`modules/informes_*`), la conversión se usa así:

```python
# modules/informes_repetitividad/report.py
from core.services.office_client import convertir_documento

async def generar_informe_pdf(datos: dict) -> bytes:
    # 1. Generar DOCX con python-docx
    docx_path = await generar_docx(datos)
    
    # 2. Convertir a PDF con office_service
    pdf_bytes = await convertir_documento(docx_path, "pdf")
    
    # 3. Limpiar archivo temporal
    os.remove(docx_path)
    
    return pdf_bytes
```

## Troubleshooting

### Servicio no responde

```bash
# Verificar que el contenedor está corriendo
docker compose -f deploy/compose.yml ps office

# Ver logs
docker compose -f deploy/compose.yml logs office

# Restart
docker compose -f deploy/compose.yml restart office
```

### Conversión falla

```bash
# Verificar healthcheck
curl http://localhost:8090/health

# Entrar y probar manualmente
docker compose -f deploy/compose.yml exec office bash
soffice --headless --convert-to pdf /tmp/test.docx
```

### Timeout en conversiones

- Aumentar `OFFICE_TIMEOUT` en configuración
- Verificar recursos del contenedor (CPU/RAM)
- Documentos muy grandes pueden requerir más tiempo
