---
name: "las-focas-libreoffice-convert"
description: "Usar cuando haya que convertir documentos con office_service o depurar flujos DOCX a PDF con LibreOffice headless"
metadata:
  short-description: "Usar cuando haya que convertir documentos con office_service o depurar flujos DOCX a PDF con LibreOffice headless"
  source: ".agentes-comunes/skills/libreoffice-convert/SKILL.md"
  triggers:
    - "libreoffice-convert"
    - "habilidad"
    - "conversi-n"
    - "libreoffice"
    - "convertir"
    - "documentos"
    - "office-service"
    - "depurar"
    - "flujos"
    - "docx"
    - "pdf"
    - "headless"
  globs:
    - "office_service/**"
  commands:
    - |
      docker exec lasfocasdev-web sh -c 'echo "SOFFICE_BIN=$SOFFICE_BIN"; command -v soffice || echo sin-soffice'
      docker exec lasfocasdev-office sh -c 'command -v soffice'
    - |
      docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev exec office bash
      soffice --headless --convert-to pdf --outdir /tmp /ruta/documento.docx
    - |
      docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev ps office
      docker logs --tail 100 lasfocasdev-office
      docker exec lasfocasdev-office curl -fsS http://localhost:8090/health
---

# Nombre de archivo: SKILL.md
# Ubicación de archivo: .codex-skills/skills/las-focas-libreoffice-convert/SKILL.md
# Descripción: Skill portable Codex migrada desde .github/skills/libreoffice-convert/SKILL.md

# Skill portable: libreoffice-convert

> Fuente original: `.agentes-comunes/skills/libreoffice-convert/SKILL.md`. Copia portable generada porque `.codex/` está montado como solo lectura en esta sesión.

# Habilidad: Conversión con LibreOffice

Guía para convertir documentos a PDF en LAS-FOCAS y diagnosticar por qué un PDF no se generó.

## Estado real (verificado 2026-10-26 en dev — reverificar antes de confiar)

Hay dos caminos; **el subprocess local no funciona en los contenedores `web`/`api`**:

| Camino | Dónde | Estado |
|---|---|---|
| Subprocess local `modules/common/libreoffice_export.py::convert_to_pdf(docx, soffice_bin)` | Corre en el contenedor que lo llama (lo usan `core/sla/report.py`, `core/sla/legacy_report.py`, `core/services/sla_consumo.py`, `modules/informes_sla`, `modules/informes_repetitividad`) | Las imágenes `web`/`api` (`focas-base`) **no instalan LibreOffice**: con `SOFFICE_BIN=/usr/bin/soffice` el subprocess da `FileNotFoundError`; el informe sale sin PDF (sin 500) |
| `office_service` (`office:8090`, UNO en 2002) | Contenedor `office` (`lasfocas-office` / `lasfocasdev-office`), el único con `soffice` | `POST /convert` **convierte** desde el 2026-10-26 (`office_service/app/conversion.py`); ver "API de `office_service`" |

La herramienta MCP `ConvertirDocAPdf` (`core/mcp/registry.py`) es el único consumidor de `/convert`
(`OFFICE_SERVICE_BASE`, default `http://office:8090`). No existe `core/services/office_client.py`.

Antes de diagnosticar un PDF faltante:

```bash
docker exec lasfocasdev-web sh -c 'echo "SOFFICE_BIN=$SOFFICE_BIN"; command -v soffice || echo sin-soffice'
docker exec lasfocasdev-office sh -c 'command -v soffice'
```

## Uso desde código Python (camino vigente)

```python
from modules.common.libreoffice_export import convert_to_pdf

pdf_path = convert_to_pdf(str(docx_path), soffice_bin)  # devuelve la ruta del PDF; propaga excepciones
```

El llamador decide la degradación: nunca un 500 por el PDF; registrar el motivo (`pdf_omitido` en
`core/services/sla_consumo.py`) y entregar el DOCX.

## Uso desde línea de comandos (dentro del contenedor `office`, dev)

```bash
docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev exec office bash
soffice --headless --convert-to pdf --outdir /tmp /ruta/documento.docx
```

## API de `office_service`

- `GET /health` → `{"service", "uno": {"available", "message"}, "version"}`.
- `POST /convert` (multipart `file`; `output_format=pdf` por query, único valor) → bytes del PDF
  (`application/pdf`). Entradas `.docx/.doc/.odt/.rtf` (la imagen sólo trae Writer). 400 formato,
  extensión o vacío; 413 sobre `OFFICE_MAX_FILE_SIZE` (bytes, 50 MB); 503 sin `soffice`; 504 sobre
  `OFFICE_CONVERT_TIMEOUT` (120 s); 500 sin salida. Un `soffice` por pedido con perfil temporal propio
  (el por defecto lo tiene la instancia UNO), serializado; DOCX de una página ≈ 6 s.

  ```python
  async with httpx.AsyncClient(timeout=150.0) as client:
      r = await client.post("http://office:8090/convert", params={"output_format": "pdf"},
                            files={"file": (path.name, path.read_bytes(), "application/octet-stream")})
  r.raise_for_status()  # r.content = PDF
  ```
- Configuración con prefijo `OFFICE_` (`office_service/app/config.py`): `OFFICE_ENABLE_UNO`,
  `OFFICE_SOFFICE_PORT`, `OFFICE_SOFFICE_BINARY`, `OFFICE_UVICORN_PORT` (8090).

## Consideraciones de performance

1. **Timeout generoso**: las conversiones pueden tardar 30-60 s en documentos grandes.
2. **No concurrencia excesiva**: LibreOffice es single-threaded.
3. **Limpiar archivos temporales** generados para la conversión.
4. **Límite de tamaño**: no aceptar entradas de más de 50 MB.
5. **Documentos de cientos/miles de páginas no van dentro de un request**: medido el 2026-10-05
   (informe SLA consumido, `docs/cierres/2026-10-05.md`): DOCX ejecutivo de 291 págs → ~45 s; DOCX
   exhaustivo de ~1480 págs → **~6,5 min**. Convertir en línea sólo lo acotado e informar la omisión
   del resto (`pdf_omitido`); el tamaño en bytes del DOCX (1,6 MB) no anticipa este costo, la cantidad
   de páginas/tablas sí.
6. **Inspección visual de un PDF generado**: ni el host ni `lasfocasdev-office` traen `poppler`
   (`pdftoppm`/`pdfinfo`). Renderizar páginas con `pypdfium2` instalado **sólo en el scratchpad**
   (`pip install --target <scratchpad>/pylib pypdfium2` + `PYTHONPATH`), nunca en el `.venv` compartido.

## Troubleshooting (dev)

```bash
docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev ps office
docker logs --tail 100 lasfocasdev-office
docker exec lasfocasdev-office curl -fsS http://localhost:8090/health
```

Un PDF faltante en un informe casi siempre es el camino 1 sin `soffice` en el contenedor, no el
servicio `office`.
