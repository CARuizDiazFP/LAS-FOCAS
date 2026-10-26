# Nombre de archivo: Guia_de_Uso.md
# Ubicación de archivo: docs/Guia_de_Uso.md
# Descripción: Guía operativa paso a paso para las funcionalidades clave de LAS-FOCAS

# Guía de uso de LAS-FOCAS

Esta guía describe los prerrequisitos, configuraciones necesarias y pasos detallados para utilizar las funcionalidades disponibles en LAS-FOCAS. Las secciones del panel web se revisaron contra el código el 2026-10-26.

## 1. Prerrequisitos generales

1. Contar con Docker y Docker Compose instalados en la VM Debian 13.
2. Clonar el repositorio LAS-FOCAS y crear el archivo `.env` tomando como referencia `deploy/env.sample`.
3. Definir las variables obligatorias en `.env`:
   - POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB.
   - LLM_PROVIDER y OPENAI_API_KEY para la clasificación por proveedor externo vía API.
   - REPORTS_DIR y UPLOADS_DIR (rutas dentro del contenedor web).
4. Ejecutar `./Start` para levantar el stack base (`postgres`, `api`, `web`, `nlp_intent`, opcionalmente `bot`).
5. Verificar que la API responde en `http://localhost:8001/health` (o el puerto configurado) y que la web está disponible en `http://172.18.208.162:8080`.
6. Aplicar migraciones con Alembic desde la raíz del proyecto:
   ```bash
   source .venv/bin/activate
   export ALEMBIC_URL="postgresql+psycopg://$POSTGRES_USER:$POSTGRES_PASSWORD@localhost:$POSTGRES_PORT/$POSTGRES_DB"
   alembic -c db/alembic.ini upgrade head
   ```
   > Nota: si se ejecuta dentro de Docker Compose, reemplazar `localhost` por `postgres` y omitir el mapeo de puerto externo.

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
2. El endpoint está protegido por la API key interna (`X-API-Key` o `Authorization: Bearer`; secreto
   `api_key_v1`). Invocarlo:
   ```bash
   curl -X POST http://localhost:8001/sync/camaras -H "X-API-Key: <API_KEY>"
   ```
3. Opcionalmente sobreescribir parámetros:
   ```bash
   curl -X POST http://localhost:8001/sync/camaras \
     -H "X-API-Key: <API_KEY>" \
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

## 4. Archivos de tracking FO

1. Desde el panel: **Infraestructura FO → Dashboard** (`/infra`), botón **Subir tracking** (clic o
   arrastrar el `.txt`). El sistema analiza el archivo y, si ya existe algo parecido, ofrece qué hacer
   (crear servicio nuevo, agregar empalmes, reemplazar la ruta, crear un camino alternativo o agregar
   un pelo). Detalle de cada opción en `docs/web.md`, sección "InfraTab — Subir Tracking".
2. Para inspeccionar un archivo a mano, desde el contenedor `api`:
   ```python
   from pathlib import Path
   from core.parsers.tracking_parser import parse_tracking

   ruta = Path("/ruta/al/tracking.txt")
   resultado = parse_tracking(ruta.read_text(), filename=ruta.name)
   ```

## 5. Navegación del panel web

El panel es una sola aplicación: cada módulo tiene su propia dirección (URL) y se abre desde la barra
lateral. No hay pestañas en el inicio; los marcadores viejos del tipo `/?tab=infra` redirigen solos a
la ruta nueva.

| Menú lateral | Opción | Ruta |
|---|---|---|
| Home | Chat operativo | `/` |
| Servicios | Visor de servicios | `/servicios` |
| Infraestructura FO | Dashboard | `/infra` |
| | FO Monitor | `/infra/fo-monitor` |
| | Cables | `/infra/cromo/cables` |
| | Botellas | `/infra/Botellas` |
| | ODFs | `/infra/cromo/odfs` |
| | Cajas PON | `/infra/cromo/pon` |
| | Rosetas | `/infra/cromo/rosetas` |
| Reportes | Repetitividad | `/repetitividad` |
| | SLA | `/sla` |
| | Historial | `/reports-history` |
| DWDM Ciena | Alarmas Ciena | `/dwdm/ciena` |
| Tool Kit | Comparador de VLANs | `/toolkit/vlan` |
| | Comparador FO | `/fo` (todavía no implementado) |
| | Verificador Cromo | `/infra/cromo/verificador` |
| | Validar datos DB Cromo | `/toolkit/validar-datos-cromo` |

La administración (usuarios, ingestas, baneos, dashboards de datos, clientes por categoría) se abre
con el engranaje **Configuración** arriba de la barra lateral; sólo está habilitado para el rol `admin`.

## 6. Informes de Repetitividad

1. Acceso web: iniciar sesión en el panel productivo (`http://172.18.208.162:8080`). Para desarrollo aislado usar `http://localhost:8090`.
2. Abrir **Reportes → Repetitividad** (`/repetitividad`).
3. Elegir la fuente:
   - Excel: arrastrar o seleccionar el `.xlsx`.
   - Base de datos: tildar "Usar reclamos desde la base de datos (ignora archivo)".
4. Completar mes y año y, si hace falta, tildar "Generar PDF si está disponible" e "Incluir mapas GEO por servicio".
5. Presionar **Generar**; la vista muestra el estado y los enlaces de "Salidas de la última corrida".
   "Carpeta de reportes" abre el historial.
6. Los errores quedan en `Logs/web.log` con `action=flow_repetitividad`.

## 7. Informe SLA desde la web

**Reportes → SLA** (`/sla`) tiene dos pestañas.

**Informe SLA**

1. Subir los dos archivos `.xlsx` requeridos:
   - Servicios Fuera de SLA.
   - Reclamos SLA.
   O tildar "Usar reclamos desde la base de datos (ignora archivo)".
2. Seleccionar mes y año; opcionalmente "Generar PDF si LibreOffice está disponible".
3. Presionar **Generar informe**; en "Salidas generadas" aparecen los enlaces de descarga (DOCX y, si
   se pidió y LibreOffice está disponible, PDF).
4. Cualquier validación fallida se muestra en el recuadro "Estado" y se registra en `Logs/web.log`.

**SLA consumido**

1. Subir los mismos dos Excel del corte (Servicios y Reclamos). Los reclamos se guardan en el histórico.
2. Opcionalmente tildar "Generar PDF si LibreOffice está disponible" y presionar **Generar informe**.
3. Se muestran los "Totales del corte" y las salidas: Excel completo, Word ejecutivo y Word
   exhaustivo (y sus PDF si se pidieron). Ver `docs/informes/sla_consumo.md`.

## 8. Herramienta Alarmas Ciena

1. Abrir **DWDM Ciena → Alarmas Ciena** (`/dwdm/ciena`).
2. Arrastrar el CSV exportado desde SiteManager o MCP (o hacer clic para elegirlo).
3. Presionar **Procesar**.
4. El Excel se descarga solo; en pantalla se informa el formato detectado, las filas y las columnas.
5. Para depuración, revisar `Logs/web.log` con prefijo `action=alarmas_ciena`.

## 9. Comparador de VLANs

1. Abrir **Tool Kit → Comparador de VLANs** (`/toolkit/vlan`).
2. Pegar la configuración de cada interfaz en los campos "Interfaz A" e "Interfaz B".
3. Pulsar "Comparar".
4. Revisar los listados "Solo A", "Comunes" y "Solo B".
5. En caso de error (sin VLANs detectadas), la UI muestra mensaje y se registra `action=vlan_compare`.

## 10. Chat operativo (MCP)

1. Iniciar sesión: el chat es la pantalla de inicio (**Home**, `/`).
2. Escribir mensajes; el backend los envía a `nlp_intent` y decide si invocar una herramienta.
3. Los adjuntos se arrastran al área designada; máximo 15 MB por archivo.
4. El historial completo queda disponible en `/api/chat/history` (requiere sesión).
5. Métricas rápidas en `/api/chat/metrics` (contador en memoria, persistido en `METRICS_PERSIST_PATH`).

## 11. Servicios

1. **Servicios** (`/servicios`) lista los servicios con scroll infinito. El buscador acepta ID,
   cliente, domicilio, tipo o estado, y hay filtros por tipo (TLS, VID, INT, RPV, FO, EWS), estado
   (Activo, Observado, Baja) y "Nivel Cliente" (categorías y "Sin cat."). Por defecto se muestran sólo
   los **Activo**. Se puede alternar entre grilla y lista.
2. Al elegir un servicio aparece una vista previa; **Abrir detalle completo** lleva a
   `/servicios/ID/<id>`. El `<id>` es el ID del servicio (también sirve un ID histórico).
3. La ficha muestra identidad, equipos de última milla y métricas, y cinco tarjetas que abren su
   propia página: **Histórico de IDs**, **Camino óptico**, **Ingresos**, **Reclamos** y **Eventos de
   baneo** (`/servicios/ID/<id>/historico`, `/camino`, `/ingresos`, `/reclamos`, `/baneos`).
4. En **Camino óptico** se ven las ODFs del servicio según Cromo, el recorrido que declara Cromo y,
   si existe, el tracking cargado a mano; desde ahí se descargan los `.txt` de tracking por pelo.
5. Con rol `admin`, la ficha permite cambiar la categoría (crea una excepción respecto del cliente) y
   marcar el servicio como verificable o no verificable.

## 12. Infraestructura FO: Dashboard y Botellas

1. **Dashboard** (`/infra`): búsqueda de cámaras por términos (nombre, dirección, servicio), atajos
   por estado en la leyenda (`LIBRE`, `OCUPADA`, `BANEADA`, `DETECTADA`, `TRACKING`), **Protocolo
   Protección** (asistente de baneo en tres pasos), **Baneos activos** (aviso por email y levantar
   baneo), **Subir tracking**, **Limpiar servicio** y **Descargar** (todas o sólo baneadas, XLSX o
   CSV). El botón **Detalle** de cada cámara abre `/infra/Camaras/<id>`.
2. **Botellas** (`/infra/Botellas`): listado único de Botellas de Cromo y del inventario legado, con
   buscador (nombre, calle o localidad), vista grilla/lista y los filtros "Mostrar No operativas" y
   "Sólo huérfanas (sin Cámara asociada)". Con huérfanas seleccionadas aparece **Asociar a Cámara**.
   Al abrir una Botella, el sistema lleva a la vista que corresponde a su origen: legado →
   `/infra/Camaras/<id>`; Cromo → Verificador Cromo (si está huérfana, primero ofrece asociarla).

## 13. Inventario Cromo

Datos ya ingeridos desde Cromo Red (la ingesta la dispara un administrador desde
**Configuración → Servicios → Ingesta → Cromo**).

- **Cables** (`/infra/cromo/cables`): búsqueda por nombre, jerarquía, propietario, vigencia, `n_id`,
  botella de un extremo o servicio. El detalle (`/infra/cromo/cables/ID<n_id>`) muestra extremos,
  buffers y pelos.
- **ODFs** (`/infra/cromo/odfs`): búsqueda por nombre o servicio y filtro por clasificación (ODF, ODF
  Nodo, Empalme, Sin clasificar). El detalle muestra cables asociados, ODFs en la misma dirección,
  conectores y servicios asociados; los conectores se abren en una tabla filtrable por bandeja.
- **Cajas PON** y **Rosetas** (`/infra/cromo/pon`, `/infra/cromo/rosetas`): la misma pantalla con
  filtros por nombre, localidad y propietario.
- **Verificador Cromo** (Tool Kit, `/infra/cromo/verificador`): se elige Cable, Tubo / buffer o
  Botella, se ingresa el `n_id` de Cromo y se ven los servicios que pasan por ese objeto; desde una
  Botella se accede a la tabla de sus empalmes.
- **Validar datos DB Cromo** (Tool Kit, `/toolkit/validar-datos-cromo`): consulta un `n_id` en vivo
  contra Cromo con el mismo parseo que la ingesta, sin tocar la base local; muestra errores de parseo,
  cables, empalmes y tubos/pelos.

## 14. FO Monitor

**Infraestructura FO → FO Monitor** (`/infra/fo-monitor`) muestra en un mapa el estado de los
servicios de cada cable antes y después de un ingreso a cámara o botella.

- La leyenda del semáforo: Operativo (≥ 80 % UP), Caída nueva al egreso, Degradado (< 80 % UP), Caída
  total y Sin dato / sin verificables.
- Sobre el mapa se busca por Servicio, Cable o Cámara; los servicios buscados se resaltan con colores
  propios (hasta 8 a la vez).
- El panel lateral lista las intervenciones con filtros por estado (Activas, Todas, Cerradas, Sin
  egreso), técnico y cable; al elegir una o un cable se abre su ficha.
- Con rol `admin` aparece "Piloto y verificación manual": activar el piloto, ventana horaria y
  "Verificar ahora" por Cámara, Botella o Cable.

Detalle técnico en `docs/fo_monitor.md`.

## 15. Consideraciones de seguridad y próximos pasos

- Mantener `Keys/` fuera del repositorio; las credenciales de los servicios se entregan como Docker
  Secrets (ver `docs/Seguridad.md`).
- `/sync/camaras`, como las demás rutas internas del `api` (salvo `/health` y la API v1, que usa
  OAuth2), exige la API key interna.
- Ejecutar `alembic upgrade head` antes de usar las nuevas tablas de infraestructura.
- Registrar cada nueva herramienta o flujo en `docs/decisiones.md` y actualizar `docs/Mate_y_Ruta.md`.
