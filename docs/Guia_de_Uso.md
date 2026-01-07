# Nombre de archivo: Guia_de_Uso.md
# Ubicación de archivo: docs/Guia_de_Uso.md
# Descripción: Guía operativa paso a paso para las funcionalidades clave de LAS-FOCAS

# Guía de uso de LAS-FOCAS

Esta guía describe los prerrequisitos, configuraciones necesarias y pasos detallados para utilizar las funcionalidades disponibles en LAS-FOCAS al 2026-01-07.

## 1. Prerrequisitos generales

1. Contar con Docker y Docker Compose instalados en la VM Debian 12.4.
2. Clonar el repositorio LAS-FOCAS y crear el archivo `.env` tomando como referencia `deploy/env.sample`.
3. Definir las variables obligatorias en `.env`:
   - POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB.
   - OLLAMA_URL si se consume el servicio Ollama externo.
   - REPORTS_DIR y UPLOADS_DIR (rutas dentro del contenedor web).
4. Ejecutar `./Start` para levantar el stack base (`postgres`, `api`, `web`, `nlp_intent`, opcionalmente `bot`).
5. Verificar que la API responde en `http://localhost:8001/health` (o el puerto configurado) y que la web está disponible en `http://localhost:8080`.

## 2. Gestión de credenciales de Google Sheets

1. Solicitar un Service Account con acceso de lectura al Google Sheet "Camaras".
2. Descargar el archivo JSON de credenciales y guardarlo como `Keys/credentials.json` (carpeta ignorada por git).
3. Alternativamente, copiar el contenido del JSON en la variable de entorno `GOOGLE_CREDENTIALS_JSON`.
4. Actualizar `.env` con:
   - INFRA_SHEET_ID: ID del Sheet (cadena tras `/d/` en la URL).
   - INFRA_SHEET_NAME: nombre exacto de la hoja (por defecto "Camaras").
5. Reiniciar el servicio `api` tras cualquier cambio en credenciales o variables.

## 3. Sincronización de cámaras desde Google Sheets

### 3.1 Desde línea de comandos (servicio interno)

1. Activar el entorno virtual (`source .venv/bin/activate`) si se ejecuta fuera de Docker.
2. Abrir un shell dentro del contenedor `api` (`docker compose exec api bash`).
3. Ejecutar en Python:
   ```python
   from core.services.infra_sync import sync_camaras_from_sheet
   sync_camaras_from_sheet()
   ```
4. Revisar los logs (nivel INFO) para confirmar `processed`, `updated`, `created`, `skipped`.
5. Verificar en la base de datos (`SELECT fontine_id, estado FROM app.camaras`) que los datos se reflejen.

### 3.2 Vía endpoint FastAPI

1. Asegurarse de que el servicio `api` está corriendo y accesible.
2. Invocar el endpoint:
   ```bash
   curl -X POST http://localhost:8001/sync/camaras
   ```
3. Opcionalmente sobreescribir parámetros:
   ```bash
   curl -X POST http://localhost:8001/sync/camaras \
     -H "Content-Type: application/json" \
     -d '{"sheet_id": "<OTRO_ID>", "worksheet_name": "OtraHoja"}'
   ```
4. Revisar la respuesta JSON:
   ```json
   {
     "status": "ok",
     "processed": 120,
     "updated": 17,
     "created": 5
   }
   ```
5. Consultar logs `action=infra_sync` en el contenedor para ver filas omitidas (`skipped`).

## 4. Parser de tracking FO

1. Ubicar el archivo TXT provisto por Operaciones (tracking diario).
2. Desde el contenedor `api`, ejecutar:
   ```python
   from pathlib import Path
   from core.parsers.tracking_parser import parse_tracking_file

   entries = parse_tracking_file(Path("/ruta/al/tracking.txt"))
   print(len(entries))
   ```
3. Cada entrada incluye identificador de empalme, tipo, cámara asociada y metadatos listos para persistencia.
4. TODO (próxima iteración): integrar el parser con un servicio de carga a las tablas `empalmes` y `servicio_empalme_association`.

## 5. Informes de Repetitividad

1. Acceso web: iniciar sesión en el panel (`http://localhost:8080`).
2. Seleccionar la pestaña "Informe de Repetitividad".
3. Elegir modo de operación:
   - Modo Excel: adjuntar archivo `.xlsx` válido.
   - Modo DB: habilitar el toggle "Usar datos de la base".
4. Configurar el período (mes/año) y, si es necesario, activar "Incluir PDF".
5. Enviar la solicitud; la UI mostrará barras de progreso y listará descargas generadas (DOCX, PDF, mapas).
6. Reintentos fallidos quedan registrados en `Logs/api.log` con prefijo `action=repetitividad_report`.

## 6. Informe SLA desde la web

1. En el panel, abrir la sección "Informe SLA".
2. Subir los dos archivos `.xlsx` requeridos:
   - Servicios Fuera de SLA.
   - Reclamos SLA.
3. Seleccionar mes y año, y confirmar opciones disponibles.
4. Presionar "Generar informe"; el sistema devolverá ZIP con DOCX y PDF (si LibreOffice está disponible).
5. Cualquier validación fallida se mostrará en pantalla y se registrará en `Logs/web.log`.

## 7. Herramienta Alarmas Ciena

1. Ir al tab "Alarmas Ciena" en el panel web.
2. Arrastrar el CSV exportado desde SiteManager o MCP.
3. Confirmar la detección automática del formato (se muestra en pantalla).
4. Descargar el Excel limpio generado.
5. Para depuración, revisar `Logs/web.log` con etiqueta `action=alarmas_ciena`.

## 8. Comparador de VLANs

1. Abrir el tab "Comparador de VLANs" en la UI.
2. Pegar la configuración de cada interfaz en los campos "Configuración A" y "Configuración B".
3. Pulsar "Comparar".
4. Revisar los listados "Sólo A", "Comunes" y "Sólo B".
5. En caso de error (sin VLANs detectadas), la UI muestra mensaje y se registra `action=vlan_compare`.

## 9. Chat operativo (MCP)

1. Iniciar sesión en el panel y abrir la pestaña "Chat".
2. Escribir mensajes; el backend los envía a `nlp_intent` y decide si invocar una herramienta.
3. Los adjuntos se arrastran al área designada; máximo 15 MB.
4. El historial completo queda disponible en `/api/chat/history` (requiere sesión).
5. Métricas rápidas en `/api/chat/metrics` (contador en memoria); para persistencia configurar `METRICS_PERSIST_PATH`.

## 10. Consideraciones de seguridad y próximos pasos

- Mantener `Keys/` fuera del repositorio y planificar migración a Docker Secrets.
- Restringir acceso a `/sync/camaras` hasta contar con API keys.
- Ejecutar `alembic upgrade head` antes de usar las nuevas tablas de infraestructura.
- Registrar cada nueva herramienta o flujo en `docs/decisiones.md` y actualizar `docs/Mate_y_Ruta.md`.
