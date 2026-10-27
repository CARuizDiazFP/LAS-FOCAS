---
name: libreoffice-convert
description: "Usar cuando haya que convertir documentos con office_service o depurar flujos DOCX a PDF con LibreOffice headless"
argument-hint: "Describe archivo o flujo, por ejemplo: convertir DOCX de SLA a PDF desde office_service"
---

# Nombre de archivo: SKILL.md
# Ubicación de archivo: .claude/skills/libreoffice-convert/SKILL.md
# Descripción: Habilidad para conversión de documentos con LibreOffice/office_service (mirror de .agentes-comunes/skills/libreoffice-convert/SKILL.md — fuente de verdad)

# Habilidad: Conversión con LibreOffice

Guía para convertir documentos a PDF en LAS-FOCAS y diagnosticar por qué un PDF no se generó.

## Estado real (verificado 2026-10-27 en dev — reverificar antes de confiar)

Hay **un solo camino**: el cliente `core/services/office_client.py` sube el documento a
`office_service` (`office:8090`, contenedor `lasfocas-office` / `lasfocasdev-office`, el único con
`soffice`). Desde P16 (2026-10-27) ya no existe `modules/common/libreoffice_export.py` ni la variable
`SOFFICE_BIN`: las imágenes `web`/`api` (`focas-base`) no instalan LibreOffice.

| Consumidor | Llamada |
|---|---|
| SLA (`core/sla/report.py`, `core/sla/legacy_report.py`) | `intentar_pdf(docx, contexto=...)` → `DocumentoSLA.pdf_error` |
| SLA consumido (`core/services/sla_consumo.py`) | `intentar_pdf` sólo del ejecutivo → `pdf_omitido` |
| Repetitividad (`modules/informes_repetitividad/service.py`) | `intentar_pdf` → `ReportResult.pdf_error` |
| `modules/informes_sla` (sólo el bot de Telegram) | `maybe_export_pdf(docx)` → `intentar_pdf` |
| MCP `ConvertirDocAPdf` (`core/mcp/registry.py`) | `convertir_a_pdf(origen, destino)` por `asyncio.to_thread` |

`OFFICE_SERVICE_BASE` (default `http://office:8090`) elige el servicio.

## Uso desde código Python

```python
from core.services.office_client import ErrorConversionPdf, convertir_a_pdf, intentar_pdf

# Informes: nunca levanta; el DOCX ya está generado y el motivo va al usuario como pdf_error.
pdf, motivo = intentar_pdf(docx_path, contexto="mi_informe")

# Estricto: levanta DocumentoDemasiadoGrande / OfficeInalcanzable / OfficeTimeout / OfficeRechazo.
pdf = convertir_a_pdf(origen, destino=None)  # destino por defecto: al lado del original
```

- Es **sync** (los builders de informes lo son): desde `async def`, siempre con `asyncio.to_thread`.
- `exc.mensaje` es apto para el usuario; `exc.detalle` (texto de office, error de red) va sólo al log.
- Timeout 150 s (office corta a los 120 s y atiende **de a una**: el margen cubre la cola); tope de
  50 MB antes de subir; valida `%PDF` en la respuesta y escribe el PDF de forma atómica (`.tmp` +
  `replace`).
- Contrato hacia el usuario: web devuelve `pdf_error` (SLA, Repetitividad) o `pdf_omitido` (SLA
  consumido); la API (`api/app/routes/reports.py`, `/reports/*`) manda el header `X-PDF-Error` (ASCII) en Repetitividad y
  `pdf_error` en el JSON de SLA. Nunca un 500 por el PDF.
- Tests: `httpx.MockTransport` parcheando `office_client._cliente` (ver `tests/test_office_client.py`);
  contra un office real: `OFFICE_REAL_URL=http://<host>:8090 pytest -m office_real tests/test_office_client.py`.

Antes de diagnosticar un PDF faltante, mirar el `pdf_error` de la respuesta y el log
`action=<contexto> stage=pdf error=<codigo>` del contenedor que generó el informe:

```bash
docker logs --tail 200 lasfocasdev-web 2>&1 | grep -m 20 "stage=pdf"
docker exec lasfocasdev-web python -c "import httpx; print(httpx.get('http://office:8090/health').json())"
```

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
  (el por defecto lo tiene la instancia UNO), serializado (`Semaphore(1)`).
- Configuración con prefijo `OFFICE_` (`office_service/app/config.py`): `OFFICE_ENABLE_UNO`,
  `OFFICE_SOFFICE_PORT`, `OFFICE_SOFFICE_BINARY`, `OFFICE_UVICORN_PORT` (8090).

## Consideraciones de performance

1. **Tiempos medidos** (dev, 2026-10-27, `soffice` en frío por pedido): Repetitividad (1,8 MB DOCX)
   12,8 s; SLA (1,8 MB) 20,5 s; SLA consumido ejecutivo (0,7 MB) 46,9 s.
2. **Sin concurrencia**: office convierte de a una; dos SLA consumidos en cola entran en los 150 s del
   cliente. Si aparecen más usuarios simultáneos, el síntoma es `pdf_error` por timeout, no un 500.
3. **Límite de tamaño**: no aceptar entradas de más de 50 MB.
4. **Documentos de cientos/miles de páginas no van dentro de un request**: medido el 2026-10-05
   (informe SLA consumido, `docs/cierres/2026-10-05.md`): DOCX ejecutivo de 291 págs → ~45 s; DOCX
   exhaustivo de ~1480 págs → **~6,5 min**. Convertir en línea sólo lo acotado e informar la omisión
   del resto (`pdf_omitido`); el tamaño en bytes del DOCX (1,6 MB) no anticipa este costo, la cantidad
   de páginas/tablas sí.
5. **Inspección visual de un PDF generado**: ni el host ni `lasfocasdev-office` traen `poppler`
   (`pdftoppm`/`pdfinfo`). Renderizar páginas con `pypdfium2` instalado **sólo en el scratchpad**
   (`pip install --target <scratchpad>/pylib pypdfium2` + `PYTHONPATH`), nunca en el `.venv` compartido.

## Troubleshooting (dev)

```bash
docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev ps office
docker logs --tail 100 lasfocasdev-office
docker exec lasfocasdev-office curl -fsS http://localhost:8090/health
```

| `pdf_error` | Causa probable |
|---|---|
| "El servicio de conversión a PDF no está disponible" | `office` caído o fuera de la red del contenedor (`OFFICE_SERVICE_BASE`) |
| "La conversión a PDF tardó demasiado" | 504 de office (> 120 s) o cola de más de 150 s |
| "El servicio de conversión no pudo generar el PDF" | 4xx/5xx de office o respuesta que no es PDF: ver `detalle` en el log |
| "El documento supera los 50 MB…" | DOCX demasiado grande; no se sube |
