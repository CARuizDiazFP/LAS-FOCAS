# Nombre de archivo: 2026-10-27-p12-matriz-divergencias-web-api.md
# Ubicación de archivo: docs/superpowers/specs/2026-10-27-p12-matriz-divergencias-web-api.md
# Descripción: Matriz de divergencias entre las rutas duplicadas de web/app y api/app (P12, auditoría 2026-10-24) y decisiones a tomar

# P12 — Matriz de divergencias web ↔ API

Base: `dev` @ `330f621`. Abreviaturas: **W** = `web/app/routers/camaras.py` (cámaras, baneos, aviso)
o `web/app/routers/servicios.py` (tracking, rutas); **A** = `api/app/routes/infra.py`.

## Hechos que condicionan el diseño (verificados)

- **Son 16 rutas duplicadas, no 13**: además de las 13 del prompt están `GET /api/infra/tracking/{ruta_id}/download`,
  `GET /api/infra/servicios/{servicio_id}/rutas` y `DELETE /api/infra/servicios/{servicio_id}/empalmes`.
- **Nadie usa las copias de la API.** El SPA llama siempre al mismo origen (`web`), el panel no proxea ninguna
  `/api/infra/*` (sólo `/servicios/*`, `/ingest/camaras` y `/clientes*`) y no hay otro cliente HTTP en
  `modules/`, `core/` ni `scripts/`. `Logs/api.log` (prod, 2026-10-01 → 10-27) registra **0 accesos reales** a
  `/api/infra/*`: las 23 líneas que aparecen son errores provocados por tests. El puerto de la API está expuesto
  con API key, así que no se puede descartar un cliente externo.
- **Auth y formato de error son contratos de cada app** y quedan en el router: W usa sesión + CSRF y devuelve
  `{"error": …}`; A usa API key (`require_api_key`) y devuelve `{"detail": …}`.
- **La API ya corre casi todo en sync**: baneos, aviso, upload/analyze/resolve y export usan `SessionLocal`
  dentro de `asyncio.to_thread`. Sólo `GET /camaras`, `search`, `smart-search`, `rutas`, `DELETE empalmes` y
  `download` usan `AsyncSession`. Por eso core puede ser **sync con `Session`**: W lo llama directo (rutas
  `def`) y A con `to_thread`.
- `web/Dockerfile` no copia `api/` y `api/Dockerfile` no copia `web/`: lo compartido tiene que vivir en `core/`.
- **Coordinación con P10** (plan `df7b794d`): P10 pasa `downloadEml` a JSON (el contrato JSON del panel se
  mantiene), borra el `fetch` muerto a `GET /api/infra/ban/{id}` y unifica la lectura de errores
  (`error` → `detail` → `message`). P12 no toca el frontend.

## Bugs reales encontrados (no son divergencias, son errores)

| # | Dónde | Bug | Efecto hoy |
|---|---|---|---|
| B1 | W `servicios.py:2392` | CONFIRM_UPGRADE exige `old_service_db_id` y el SPA sólo manda `old_service_id` (`InfraTab.vue:298`) | **El upgrade de servicio desde el panel siempre da 400** |
| B2 | W `execute_upgrade` (`infra_service.py:714-832`) | Si falla, devuelve 200 con el texto de la excepción | Expone detalles internos; sólo lo usa W y no tiene tests |
| B3 | A `infra.py:1929` | `send_email` (SMTP, hasta 15 s) se llama dentro del event loop, fuera de `to_thread` | Bloquea toda la API mientras manda |
| B4 | A `infra.py:510` | `search` con `status`/`eq` y `value: []` → `value[0]` → IndexError | 500 |
| B5 | core `camaras_exportacion.py:125` | CSV vacío escribe el literal `Sin datos\n` (barra invertida) | Archivo con `\n` visible |
| B6 | core `email_service.py:120` y armado del `.eml` de A | `add_header("Content-Type")` sobre `MIMEApplication` deja dos `Content-Type` | Los adjuntos salen como `octet-stream` |
| B7 | A download-eml | XLS lee `cam.empalmes` con la sesión cerrada; el error se traga | Columna "Servicios" vacía (no verificado en ejecución) |
| B8 | A download-eml | Nombre `Aviso_Baneo_{ticket}.eml` sin sanear | `Aviso_Baneo_None.eml`; una comilla rompe el header |
| B9 | W `GET /camaras:257` | `list(set(...))` | Orden de `servicios` no determinista |
| B10 | A upload_tracking / analyze | `await file.read()` sin tope | Un archivo grande entra entero a memoria (W tiene 5 MB) |
| B11 | A `ingest_servicios` | pandas/openpyxl y loops de CPU dentro de `async def` | Bloquea el event loop durante la ingesta |

## Matriz por ruta

Sólo se listan diferencias reales. "Recomendación" = qué versión toma `core/services`.

### Cámaras y búsqueda

| Ruta | Diferencia | W | A | Recomendación |
|---|---|---|---|---|
| `GET /camaras` | Origen de `servicios` | rutas (modelo vigente) | `servicio_empalme_association` (legacy; la retira P22) | **D1**: rutas en las dos, ordenado |
| | Forma de cada cámara | 21 claves (estado, baneo, botellas, `editable`…) | 9 claves (`CamaraResponse`) | Cada app conserva su forma; core devuelve los datos y cada router serializa |
| | Fallback por servicio | `servicio.rutas` (todas) | `Servicio.empalmes` legacy | D1 |
| `POST /search` (filtros) | Validación | ninguna: field/operator inválido → 200 vacío; `limit` sin rango | Enums, `max 10` filtros, `limit 1..500` → 422 | **D2**: validación de A en las dos (el SPA no usa esta ruta del panel) + fix B4 |
| | Origen de `servicios` | legacy | legacy | D1: rutas |
| `POST /smart-search` | Universo | sólo raíces, sin NO_OPERATIVA salvo toggle/chip | todas (Botellas y NO_OPERATIVA incluidas) | **D3**: cada app conserva su universo (`solo_raiz` como kwarg de core) |
| | Servicios para el matching | rutas + Botellas del grupo + fallback legacy | sólo legacy de la fila | D1: los de W en las dos |
| | Parámetros | + `estado`, `incluir_no_operativas` | — | A conserva su contrato (sin params nuevos) |
| | Validación | ninguna | `terms ≤ 20`, `limit 1..500` | D2: la de A también en W |
| `GET /export/cameras` | `format` | cualquier valor ≠ xlsx → CSV | Enum estricto → 422 con `XLSX`/`pdf` | W conserva el modo laxo (lo usa el SPA) |
| | CSV vacío | B5 | salto de línea real | Fix B5 en core |
| | Sin pandas | CSV sin aviso | CSV + `X-Export-Warning` | **D4**: el header en las dos |

Hoy W ya delega smart-search (`camaras_consulta.buscar_camaras_por_terminos`) y export (`camaras_exportacion`)
en core; A tiene ~180 y ~150 líneas duplicadas inline de esas mismas dos rutas.

### Baneos y aviso

| Ruta | Diferencia | W | A | Recomendación |
|---|---|---|---|---|
| `ban/create`, `ban/lift` | Autor | usuario de la sesión | `usuario_ejecutor` del body (o "sistema") | Cada app conserva el suyo |
| | Largo de campos | sin `max_length` → falla en el flush, 200 `success:false` "Error inesperado" | `max_length` → 422 | **D2**: los límites de A en las dos |
| `ban/active` | Claves | + `camaras_baneadas_count`, `total_camaras_baneadas` | sin ellas | **D5**: forma de W (superset) en las dos; `duracion_horas` del modelo, redondeada a 1 decimal |
| `ban/{id}` | — | no existe (el SPA lo llamaba y caía al catch-all; P10 borra la llamada) | existe | Queda sólo en A |
| `notify/email` | SMTP sin configurar | 500 | 200 `success:false` | **D6**: comportamiento de A en las dos (el SPA trata igual los dos casos) |
| | Incidentes inexistentes | manda el mail sin adjuntos | 200 `success:false` | D6 |
| | Adjunto TXT con varios incidentes | uno solo en total (`break`) | uno por incidente | D6 |
| | SMTP | en threadpool | B3 | Fix B3 |
| `notify/email/config` | Error | 200 `configured:false` | 500 | W en las dos |
| `notify/download-eml` | Entrada | JSON | `Form` | Cada app conserva su contrato (P10 arregla el SPA) |
| | Persistencia | ninguna | guarda `email_subject`/`email_body` en el incidente | Sólo A (alimenta su `GET /ban/{id}`) |
| | Plantilla por defecto | HTML de 39 líneas | dos párrafos | **D7**: un solo armador en core con la plantilla de W |
| | Destinatarios | valida `@`, 400 si quedan vacíos | sin validar | D7: la de W |
| | TXT elegido | primera ruta con contenido | prioriza `ruta_protegida_id` | D7: la de A |
| | Columnas XLS | ID, Nombre, Fontine_ID, Dirección, Estado, Ticket | ID, Nombre, Dirección, Estado, Servicios, Lat, Long | **D8**: unión de las dos |
| | Nombre del archivo | saneado | B8 | D7: el de W |
| | `X-Unsent: 1` | no | no | **D9**: agregarlo (Outlook abre el `.eml` como borrador, que es el propósito declarado) |

### Tracking, rutas y empalmes (`web/app/routers/servicios.py` vs A)

| Ruta | Diferencia | W | A | Recomendación |
|---|---|---|---|---|
| `upload_tracking` | Tope | 5 MB → 413 | sin tope | Fix B10: 5 MB en las dos |
| | Respuesta | sin `camaras_nuevas` | `camaras_nuevas=0` | Cada app conserva su forma |
| `trackings/analyze` | Entrada | sólo `file` | `file` o `content`+`filename` | Cada app conserva su contrato |
| | Claves | + `suggested_action`, `hash_match`, `empalmes_nuevos`, `terminal_*` | + `cantidad_pelos`, `alias_id` | Un solo serializador en core (unión); cada app filtra con su `response_model` |
| `trackings/resolve` | CONFIRM_UPGRADE | `execute_upgrade`: cambia ids y hash; no reprocesa empalmes ni terminales. B1 y B2 | `resolve_tracking_file` con `old_service_id`: reprocesa empalmes, cámaras, tránsitos y terminales | **D10**: la de A en las dos y retirar `execute_upgrade` (arregla B1 y B2) |
| | `SKIP` | no-op 200 | no existe | Se acepta en las dos |
| | `new_ruta_tipo` inválido | cae en silencio a ALTERNATIVA | 400 | **D11**: 400 en las dos |
| `servicios/{id}/rutas` | Búsqueda | `servicio_id` OR `numero_primer_servicio` OR `numero_linea` | `servicio_id` exacto | **D12**: criterio de W en las dos, con orden determinista |
| `tracking/{ruta_id}/download` | — | textos de 404 | textos de 404 | Idéntico salvo mensajes |
| `DELETE servicios/{id}/empalmes` | Respuesta | sin `empalmes_rutas_eliminados` | con esa clave | Agregarla en W (no rompe a nadie) |

## Decisiones del usuario (2026-10-27)

- **Arquitectura**: los dos consumen `core/services` (servicios sync con `Session`; W directo, A con
  `asyncio.to_thread`). El panel no proxea estas rutas a la API.
- **Copias de la API**: se conservan (mismos paths, parámetros y forma de respuesta) como adaptadores de core.
- **D1-D12**: se aplican las recomendaciones de la tabla.
- **Rol**: crear y levantar baneos queda abierto a cualquier usuario logueado **a propósito** (decisión del
  usuario, no es un hueco). P12 tampoco cambia el rol de `DELETE servicios/{id}/empalmes`.
- **Otros hallazgos fuera de alcance**: `GET /api/infra/rutas/{id}/download` (sólo W, `servicios.py:543-612`)
  une con `"\\n"` literal y lee `empalme.descripcion`/`empalme.nombre`, que no existen (500 en el fallback);
  `submitBan`/`confirmLiftBan` del SPA muestran éxito ante un 200 `success:false` (para P10).
