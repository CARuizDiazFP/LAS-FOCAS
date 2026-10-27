# Nombre de archivo: 2026-10-27-p12-dedupe-web-api-core-services.md
# Ubicación de archivo: docs/superpowers/plans/2026-10-27-p12-dedupe-web-api-core-services.md
# Descripción: Plan de implementación de P12 (auditoría 2026-10-24): rutas duplicadas web/api → core/services

# P12 — Dedupe web/api → `core/services` — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** que las 16 rutas duplicadas entre `web/app/routers/{camaras,servicios}.py` y `api/app/routes/infra.py` (más `ingest_servicios`) consuman una sola implementación en `core/services/`, con los routers como adaptadores finos.

**Architecture:** la lógica va a servicios **sync** que reciben `Session`. El panel (rutas `def`) los llama directo; la API los llama con `await asyncio.to_thread(...)`, abriendo `SessionLocal()` adentro del thread y serializando **antes** de cerrar la sesión. Auth, parseo HTTP, `response_model` y formato de error (`{"error"}` en web, `{"detail"}` en api) se quedan en cada router.

**Tech Stack:** Python 3.13 (`.venv`), FastAPI 0.136.1, SQLAlchemy 2 (sync `Session`), pytest.

**Spec:** `docs/superpowers/specs/2026-10-27-p12-matriz-divergencias-web-api.md` (matriz, bugs B1-B11, decisiones D1-D12; leerla antes de cada tarea).

## Global Constraints

- Paths, parámetros, forma de respuesta y códigos HTTP **sin cambios**, salvo lo que fija una decisión D1-D12 o un bug B1-B11 de la spec (cada tarea dice cuál aplica).
- `api/app/routes/v1/` intacta. Frontend (`web/frontend/src`) intacto: es de P10.
- Nombres de los handlers web sin cambios (`tests/fixtures/web_rutas_contrato.json`, `tests/test_web_rutas_contrato.py`).
- Sin I/O bloqueante dentro de `async def`: toda llamada a core desde la API va por `asyncio.to_thread`.
- No se cambia el rol de ninguna ruta (crear/levantar baneos abierto a cualquier usuario logueado: decisión del usuario).
- `servicio_empalme_association` se sigue leyendo como fallback y se sigue limpiando: retirarla es P22.
- Archivos nuevos con el encabezado de 3 líneas (Nombre de archivo / Ubicación / Descripción). Comentarios y docstrings en español, densidad como el código vecino.
- Tests: `source .venv/bin/activate`, `LLM_PROVIDER=heuristic`. Los `*_real_db.py` corren contra `focas_dev`: `POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5433 POSTGRES_DB=focas_dev POSTGRES_USER=FOCALBOT POSTGRES_PASSWORD="$(cat .secrets/Dev_db_password_v1.txt)"`. Nunca contra prod.
- Disco: `df --output=avail -BM /` antes de cualquier corrida pesada; con menos de 3 GB, frenar.
- Ninguna función de más de ~150 líneas en los cuatro routers tocados.
- Commits en la rama efímera `refactor/claude-dedupe-dedupe-web-api-core-services`; con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Cámara vinculada sólo por la asociación legacy (sin rutas)**: tiene que seguir listando sus `servicios` en las dos apps (fallback de `_collect_camara_servicios_ids`). Test en Task 3.
2. **Objetos ORM leídos después de cerrar la sesión en el thread de la API** (`DetachedInstanceError` silencioso, como B7): toda serialización ocurre dentro del `with SessionLocal()`. Tests en Task 3 y Task 9 con relaciones lazy.
3. **Ticket ausente o con comillas/barras en el nombre del `.eml` y del XLS**: nombre saneado, nunca `None` ni una comilla en `Content-Disposition`. Test en Task 9.
4. **CONFIRM_UPGRADE con un `old_service_id` que no existe**: respuesta `success: false` con mensaje, nunca 500 ni texto de excepción. Test en Task 11.
5. **Términos sólo de espacios y `limit` en el borde (1 y 500)** en smart-search de la API con `solo_raiz=False`: mismo total que hoy. Test en Task 4.

---

### Task 1: Tests de contrato antes del refactor

**Files:**
- Create: `tests/test_contrato_infra_web_api.py` (sin DB: validaciones 422/400 que se resuelven antes de tocar la base)
- Create: `tests/test_contrato_infra_web_api_real_db.py` (contra `focas_dev`, sólo caminos que **no escriben**)

**Interfaces:**
- Produces: helpers `cliente_web(con_sesion, csrf_real)` y `cliente_api()` (headers `{"Authorization": "Bearer test-api-key"}`, como `tests/test_api_errores_rutas.py`) y `assert_forma(payload: dict, claves: dict[str, type | tuple[type, ...]])` que verifica el **conjunto exacto** de claves y sus tipos. Las tareas siguientes editan las aserciones de estos dos archivos cuando una decisión cambia el contrato, y sólo esas.

- [ ] **Step 1:** Escribir, para web y api, un test por ruta con las claves y tipos actuales (los que dan la matriz y el código hoy):
  - Lectura (real_db): `GET /api/infra/camaras?limit=5` (web: 21 claves por cámara; api: 9), `POST /api/infra/search` con `{"filters": [], "limit": 5}`, `POST /api/infra/smart-search` con `{"terms": [], "limit": 5}`, `GET /api/infra/export/cameras?format=csv` (status, `content-type`, `Content-Disposition` que matchea `camaras_\d{8}_\d{6}\.csv`), `GET /api/infra/ban/active`, `GET /api/infra/notify/email/config`, `GET /api/infra/servicios/{id}/rutas` con un `servicio_id` real de `focas_dev` elegido en un fixture que lo busca por SELECT, `GET /api/infra/tracking/{ruta_id}/download` con una ruta real que tenga `raw_file_content` y con `999999999` (404).
  - Sin escritura (real_db): `ban/create` con servicios inexistentes (`"ZZ-NO-EXISTE"`) → 200 `success: false`; `ban/lift` con `incidente_id=999999999` → 200 `success: false`; `notify/download-eml` con `incident_id=999999999` (web JSON, api Form) → 404; `DELETE /api/infra/servicios/ZZ-NO-EXISTE/empalmes` → 404; `trackings/resolve` con `action="NO_EXISTE"` → 400.
  - Sin DB: `search` con `field="x"` (api 422, web 200 vacío), `smart-search` con 21 términos (api 422, web 200), `export/cameras?format=XLSX` (api 422, web 200 xlsx), `upload_tracking` de 6 MB (web 413).
- [ ] **Step 2:** Correr los dos archivos sobre el código actual. Esperado: todo PASS (fija el estado de hoy). Comando: `LLM_PROVIDER=heuristic <vars real_db> pytest tests/test_contrato_infra_web_api.py tests/test_contrato_infra_web_api_real_db.py -q`.
- [ ] **Step 3:** Commit `test(infra): contrato web/api de las 16 rutas duplicadas antes del dedupe (P12)`.

### Task 2: Cliente httpx compartido del panel

**Files:**
- Create: `web/app/http_interno.py`
- Modify: `web/app/main.py` (lifespan), `web/app/routers/servicios.py` (8 proxies, `:675-2120`)
- Test: `tests/test_web_http_interno.py`

**Interfaces:**
- Produces: `cliente_api_interna() -> httpx.AsyncClient` (devuelve el cliente creado en el lifespan; si no hay lifespan activo, por ejemplo en `TestClient` sin context manager, crea uno perezoso y lo reusa), `async def abrir_cliente_api_interna() -> None`, `async def cerrar_cliente_api_interna() -> None`. Base URL `INTERNAL_API_BASE_URL` (de `web/app/comun.py`); el timeout se sigue pasando **por pedido** (`timeout=180.0` en ingest, `70.0` en prov/refrescar, `30.0` el resto). P17 lo usará en `admin_datos.py`: no tocar ese archivo.

- [ ] **Step 1:** Test: dos pedidos seguidos a `/api/servicios/search` (con `respx` o con un transport `httpx.MockTransport` inyectado vía monkeypatch de `cliente_api_interna`) usan **la misma** instancia; al salir del `with TestClient(app)`, el cliente queda cerrado (`is_closed`).
- [ ] **Step 2:** Correrlo: FAIL (no existe el módulo).
- [ ] **Step 3:** Implementar el módulo, registrar el lifespan en `FastAPI(...)` de `web/app/main.py` y reemplazar los 8 `async with httpx.AsyncClient(...)` de `servicios.py` por `cliente_api_interna().post/get/patch(..., timeout=...)`. `chat.py`, `cromo.py`, `admin_datos.py` y `classify_text` no se tocan.
- [ ] **Step 4:** `pytest tests/test_web_http_interno.py tests/test_web_servicios_errores_depends.py tests/test_web_uploads_limite.py -q`: PASS.
- [ ] **Step 5:** Commit `refactor(web): cliente httpx compartido para los proxies al API interno (P12)`.

### Task 3: Listado de cámaras y serialización comunes (D1, B9)

**Files:**
- Modify: `core/services/camaras_consulta.py`, `web/app/routers/camaras.py` (`GET /api/infra/camaras` `:177-286`, `_serialize_camara_response` `:65-127` y sus llamadores), `api/app/routes/infra.py` (`:191-316`)
- Test: `tests/test_camaras_consulta.py`, contrato de Task 1

**Interfaces:**
- Produces (en `core/services/camaras_consulta.py`):
  - `listar_camaras(session: Session, *, q: str | None, estado: str | None, limit: int) -> list[CamaraEncontrada]`: misma query y filtros que el panel hoy (Botellas y NO_OPERATIVA incluidas, `ORDER BY nombre`, `min(limit, LIMITE_MAXIMO)`); rutas con `_collect_camara_rutas_info(camara)` y servicios con `_collect_camara_servicios_ids` (ordenados); fallback por servicio con el `ILIKE` actual más `order_by(Servicio.servicio_id)` antes del `.first()`, recorriendo `servicio.rutas` con carga por lote.
  - `serializar_camara_basica(encontrada: CamaraEncontrada) -> dict[str, Any]`: las 9 claves de `CamaraResponse`.
  - `serializar_camara_panel(*, camara, rutas_info, servicios_ids, contexto, editable) -> dict[str, Any]`: es `_serialize_camara_response` movida tal cual (mismas 21 claves). En el router queda `from core.services.camaras_consulta import serializar_camara_panel as _serialize_camara_response` para no tocar sus otros llamadores.
- Cambio de contrato aceptado (D1): en el panel, `rutas[]` de `GET /camaras` pasa de 4 a 8 claves (las de smart-search); en la API, `servicios` sale de rutas (con fallback legacy) y no sólo de la asociación legacy.

- [ ] **Step 1:** Tests en `tests/test_camaras_consulta.py` con objetos `SimpleNamespace` como los existentes: `test_listar_camaras_servicios_ordenados` (dos rutas de servicios `"B"` y `"A"` → `["A", "B"]`), `test_listar_camaras_sin_rutas_usa_legacy` (Review Focus 1: cámara con un empalme cuyo `servicios=[Servicio("X")]` y sin rutas → `["X"]`), `test_serializar_camara_basica_claves` (exactamente las 9 claves).
- [ ] **Step 2:** Correrlos: FAIL.
- [ ] **Step 3:** Implementar las tres funciones. Web: el handler queda en `listar_camaras` + `get_camara_estado_contexto_batch` + `serializar_camara_panel`. API: `async def` → `await asyncio.to_thread(_run)`, donde `_run` abre `SessionLocal()`, llama `listar_camaras` y devuelve ya serializado con `serializar_camara_basica` (Review Focus 2); sin `Depends(get_async_db)`. **Adaptar** `test_infra_500_con_ref_sin_texto_interno_y_log_con_ref` en `tests/test_api_errores_rutas.py` para que rompa `infra.SessionLocal` en vez de `get_async_db` (misma aserción).
- [ ] **Step 4:** `pytest tests/test_camaras_consulta.py tests/test_api_errores_rutas.py tests/test_web_camaras_errores_depends.py tests/test_contrato_infra_web_api*.py -q` (con vars real_db): PASS; actualizar en el contrato sólo la forma de `rutas[]` del panel.
- [ ] **Step 5:** Commit `refactor(infra): listado de cámaras y serialización en core/services (P12)`.

### Task 4: smart-search de la API sobre core (D1, D2, D3)

**Files:**
- Modify: `core/services/camaras_consulta.py` (`_consulta_base`, `buscar_camaras_por_terminos`), `api/app/routes/infra.py` (`:595-772`, helpers `:416-446` que queden sin uso), `web/app/routers/camaras.py` (`SmartSearchRequestModel` `:1521-1527`)
- Test: `tests/test_camaras_consulta.py`, `tests/test_contrato_infra_web_api_real_db.py`

**Interfaces:**
- Consumes: `serializar_camara_basica` (Task 3).
- Produces: `buscar_camaras_por_terminos(..., solo_raiz: bool = True)`; con `solo_raiz=False` no filtra `camara_padre_id IS NULL`. La API llama con `estado=None, incluir_no_operativas=True, solo_raiz=False` (conserva su universo, D3) y responde con su `SearchResponse` (`filters_applied` = términos no vacíos, 9 claves por cámara).
- D2: el modelo del panel suma `terms: list[str] = Field(default_factory=list, max_length=20)`, `limit: int = Field(100, ge=1, le=500)`, `offset: int = Field(0, ge=0)` (los mismos límites que la API).

- [ ] **Step 1:** Tests: `test_buscar_solo_raiz_false_incluye_botellas` (unit) y, en real_db, Review Focus 5: para `terms=["  "]`, `terms=[]` y `limit` en 1 y 500, el `total` de la API después del cambio es igual al `total` de `SELECT count(*) FROM app.camaras` (sin términos efectivos matchea todo). Agregar al contrato: web con `limit=0` → 422.
- [ ] **Step 2:** Correr: FAIL.
- [ ] **Step 3:** Implementar el kwarg; reemplazar la ruta de la API por `to_thread` + `buscar_camaras_por_terminos` + `serializar_camara_basica`; borrar `_term_matches_camara` y los helpers de la API que queden sin uso (verificar con `grep -n` en `api/` y `tests/`).
- [ ] **Step 4:** Tests de Step 1 + `tests/test_camaras_consulta.py` + contrato: PASS.
- [ ] **Step 5:** Commit `refactor(infra): smart-search de la API sobre camaras_consulta (P12)`.

### Task 5: Búsqueda avanzada por filtros en core (D1, D2, B4)

**Files:**
- Create: `core/services/camaras_busqueda_avanzada.py`
- Modify: `web/app/routers/camaras.py` (`:1332-1518`), `api/app/routes/infra.py` (`:105-146`, `:324-587`), `tests/test_infra_search.py` (imports `:13-19`)
- Test: `tests/test_camaras_busqueda_avanzada.py`

**Interfaces:**
- Produces: `FilterField`, `FilterOperator` (Enums movidos tal cual de la API), `SearchFilter`, `SearchRequest` (modelos Pydantic de la API con `max_length=10`, `limit 1..500`, `offset >= 0`), `filtro_texto_coincide(value, operator: FilterOperator, db_value: str | None) -> bool`, `camara_coincide_filtro(camara, flt: SearchFilter, servicios_ids: list[str], cables_nombres: list[str]) -> bool`, `ResultadoBusqueda(total: int, camaras: list[CamaraEncontrada])` y `buscar_camaras_avanzada(session: Session, filtros: list[SearchFilter], *, limit: int, offset: int) -> ResultadoBusqueda` (carga con `_CARGA_POR_LOTE`, servicios de `_collect_camara_rutas_info` + `_collect_camara_servicios_ids`, prefiltro SQL de estado de la API).
- Los dos routers usan `SearchRequest` como modelo del body; web devuelve su JSON actual con 9 claves por cámara y la API su `SearchResponse`. D2: el panel pasa a responder 422 con field/operator inválido o más de 10 filtros.

- [ ] **Step 1:** Tests: los de `tests/test_infra_search.py` reapuntados al módulo nuevo; nuevo `test_status_eq_lista_vacia_no_rompe` (B4: `SearchFilter(field="status", operator="eq", value=[])` → sin excepción, 0 resultados); `test_filtro_servicio_usa_rutas` (D1). Contrato: web `field="x"` pasa de 200 a 422.
- [ ] **Step 2:** Correr: FAIL.
- [ ] **Step 3:** Implementar; los dos routers quedan en adaptadores (web `def`, api `to_thread`).
- [ ] **Step 4:** `pytest tests/test_camaras_busqueda_avanzada.py tests/test_infra_search.py tests/test_contrato_infra_web_api*.py -q`: PASS.
- [ ] **Step 5:** Commit `refactor(infra): búsqueda avanzada de cámaras en core/services (P12)`.

### Task 6: Exportación de cámaras (D4, B5)

**Files:**
- Modify: `core/services/camaras_exportacion.py`, `web/app/routers/camaras.py` (`:1278-1329`), `api/app/routes/infra.py` (`:2128-2279`), `tests/test_camaras_exportacion.py` (`:71-72`)

**Interfaces:**
- Produces: `nombre_archivo_exportacion(ext: str) -> str` (`camaras_<UTC %Y%m%d_%H%M%S>.<ext>`), `AVISO_SIN_XLSX = "XLSX no disponible, exportando como CSV"`. `a_csv([])` escribe `"Sin datos\n"` con salto de línea real (B5).
- La API conserva su Enum `ExportFormat` (422 con `XLSX`); el panel conserva el modo laxo. Las dos agregan `X-Export-Warning: AVISO_SIN_XLSX` cuando `a_xlsx` devuelve `None` (D4).

- [ ] **Step 1:** Tests: actualizar `tests/test_camaras_exportacion.py:71-72` a `b"\xef\xbb\xbfSin datos\n"`; nuevo test de router (web y api) con `a_xlsx` parcheado a `None` → `X-Export-Warning` presente y CSV.
- [ ] **Step 2:** Correr: FAIL.
- [ ] **Step 3:** Implementar; la API usa `filas_exportacion`/`a_csv`/`a_xlsx` dentro de su `to_thread` y responde `Response(content=bytes)`; se borran sus ~150 líneas inline.
- [ ] **Step 4:** `pytest tests/test_camaras_exportacion.py tests/test_contrato_infra_web_api*.py -q`: PASS.
- [ ] **Step 5:** Commit `refactor(infra): exportación de cámaras de la API sobre camaras_exportacion (P12)`.

### Task 7: Baneos — crear, levantar y activos (D2, D5)

**Files:**
- Create: `core/services/baneo_operaciones.py`
- Modify: `web/app/routers/camaras.py` (`:565-770`), `api/app/routes/infra.py` (`:1529-1729`)
- Test: `tests/test_baneo_operaciones.py`, `tests/test_web_baneos.py`

**Interfaces:**
- Produces:
  - Constantes `LARGO_TICKET = 64`, `LARGO_SERVICIO = 64`, `LARGO_USUARIO = 128`, `LARGO_MOTIVO = 512` (las de la API, alineadas con `db/models/infra.py:973-982`); los dos routers las usan en sus `Field(max_length=...)` (D2: el panel responde 422 en vez de 200 "Error inesperado").
  - `crear_baneo_y_notificar(session: Session, *, ticket_asociado: str | None, servicio_afectado_id: str, servicio_protegido_id: str, ruta_protegida_id: int | None, motivo: str | None, usuario_ejecutor: str | None) -> BanResult`: `create_ban`; si `success`, commit y aviso Slack con `notificar_evento_baneo(session, "create", datos, get_settings().slack.bot_token)` (import perezoso como hoy, `try/except` con `logger.warning`); si no, rollback.
  - `levantar_baneo_y_notificar(session: Session, incidente_id: int, *, usuario_ejecutor: str | None, motivo_cierre: str | None) -> LiftResult`: lo mismo con `lift_ban` y evento `"lift"`.
  - `listar_incidentes_activos(session: Session) -> dict[str, Any]`: forma del panel (`status`, `incidentes` con `camaras_count` y `camaras_baneadas_count`, `total`, `total_camaras_baneadas`), `duracion_horas = round(inc.duracion_horas, 1)` desde la propiedad del modelo, `None` si no hay `fecha_inicio` (D5).
- El autor sigue saliendo de la sesión en el panel y del body en la API. Los logs `action=create_ban user=…` quedan en el router del panel.

- [ ] **Step 1:** Tests con `_FakeSession` y `monkeypatch` sobre `core.services.baneo_operaciones.create_ban`/`lift_ban`/`notificar_evento_baneo`: commit + Slack si `success`; rollback y sin Slack si no; un error de Slack no cambia la respuesta. `test_listar_activos_redondea`. Contrato: `ban/active` de la API suma `camaras_baneadas_count` y `total_camaras_baneadas`; `ban/create` del panel con ticket de 65 caracteres → 422.
- [ ] **Step 2:** Correr: FAIL.
- [ ] **Step 3:** Implementar y adelgazar los seis handlers (web `def`, api `to_thread`). `GET /api/infra/ban/{incidente_id}` de la API no cambia.
- [ ] **Step 4:** `pytest tests/test_baneo_operaciones.py tests/test_web_baneos.py tests/test_api_errores_rutas.py tests/test_contrato_infra_web_api*.py -q`: PASS.
- [ ] **Step 5:** Commit `refactor(infra): crear, levantar y listar baneos en core/services (P12)`.

### Task 8: Aviso de baneo por email (D6, D8, B3, B6)

**Files:**
- Create: `core/services/baneo_aviso.py`
- Modify: `core/services/email_service.py` (`:120`), `web/app/routers/camaras.py` (`:853-1024`), `api/app/routes/infra.py` (`:1776-1953`, `:2006-2020`)
- Test: `tests/test_baneo_aviso.py`

**Interfaces:**
- Produces:
  - `COLUMNAS_XLS_BANEO = ["ID", "Nombre", "Fontine_ID", "Dirección", "Estado", "Ticket", "Servicios", "Latitud", "Longitud"]` (D8, unión), hoja `Baneos_Activos`.
  - `adjuntos_aviso_baneo(session: Session, incidente_ids: list[int], *, include_xls: bool, include_txt: bool) -> list[EmailAttachment] | None`: `None` si ningún id existe; un TXT **por incidente**, eligiendo primero `ruta_protegida_id` y si no la primera ruta con contenido (D6/D7); el XLS se arma dentro de la sesión.
  - `estado_config_email() -> dict[str, Any]`: la forma actual del panel (`configured`, y lo que hoy devuelve).
  - `enviar_aviso_baneo(session: Session, *, to: list[str], cc: list[str] | None, subject: str, body: str, incidente_ids: list[int], include_xls: bool, include_txt: bool) -> EmailNotifyResultado` con `EmailNotifyResultado(success: bool, message: str, error: str | None, recipients_count: int)`: SMTP sin configurar → `success=False` (D6, el panel deja de responder 500 y responde 200); sin incidentes → `success=False`, "No se encontraron incidentes con los IDs especificados".
- B6: en `EmailService.send_email` (y en el armador de Task 9) los adjuntos se crean con `MIMEApplication(datos, _subtype=...)` / `MIMEText` con el tipo correcto, sin `add_header("Content-Type")` duplicado.
- B3: la API llama `enviar_aviso_baneo` entera dentro de `asyncio.to_thread`.

- [ ] **Step 1:** Tests: `test_adjuntos_un_txt_por_incidente`, `test_adjuntos_prioriza_ruta_protegida`, `test_adjuntos_none_sin_incidentes`, `test_send_email_un_solo_content_type_por_adjunto` (parsear el mensaje armado con `email.message_from_bytes` y contar `Content-Type` por parte), `test_api_notify_email_no_bloquea_el_loop` (parchear `send_email` con un `time.sleep(0.3)` y verificar que una segunda corrutina avanza mientras tanto, como en `feedback_verificacion_heartbeat_event_loop`). Contrato: el panel con SMTP sin configurar pasa de 500 a 200 `success:false`; `test_notify_email_conserva_200_success_false_con_ref` sigue verde.
- [ ] **Step 2:** Correr: FAIL.
- [ ] **Step 3:** Implementar y adelgazar `notify/email` y `notify/email/config` en las dos apps. En `config`, un error interno responde en las dos 200 `{"configured": false, "error": "Error interno (ref …)"}` (la recomendación "W en las dos" de la matriz; la API deja de dar 500). Agregarlo al contrato de Task 1.
- [ ] **Step 4:** `pytest tests/test_baneo_aviso.py tests/test_api_errores_rutas.py tests/test_contrato_infra_web_api*.py -q`: PASS.
- [ ] **Step 5:** Commit `refactor(infra): aviso de baneo por email en core/services; SMTP fuera del event loop (P12)`.

### Task 9: `.eml` del aviso (D7, D8, D9, B6, B7, B8)

**Files:**
- Modify: `core/services/baneo_aviso.py`, `core/services/email_service.py` (retirar `generate_ban_eml` `:187-276` si no queda llamador), `web/app/routers/camaras.py` (`:1031-1271`), `api/app/routes/infra.py` (`:2023-2120`)
- Test: `tests/test_baneo_aviso.py`

**Interfaces:**
- Consumes: `adjuntos_aviso_baneo` (Task 8).
- Produces:
  - `PLANTILLA_AVISO_BANEO`: el `DEFAULT_EMAIL_TEMPLATE` del panel movido tal cual.
  - `parsear_destinatarios(raw: str | None) -> list[str]`: split por `[,;\s]+`, sólo los que tienen `@`.
  - `EmlBaneo(contenido: bytes, nombre_archivo: str, subject: str, html_body: str)` y `armar_eml_baneo(session: Session, incidente_id: int, *, destinatarios: list[str], subject: str | None, html_body: str | None, include_xls: bool = True, include_txt: bool = True) -> EmlBaneo | None` (`None` si el incidente no existe). Reemplazo de `{{…}}` en plantilla y cuerpo con valores escapados con `html.escape`; asunto por defecto `AVISO DE BANEO - Ticket {ticket or id}`; headers `Date`, `X-Mailer` y **`X-Unsent: 1`** (D9); nombre `notificacion_{ticket saneado o id}_{UTC %Y%m%d_%H%M%S}.eml` con la función de saneo del panel.
  - `guardar_plantilla_aviso(session: Session, incidente_id: int, subject: str, html_body: str) -> None`: lo que hoy hace la API (persistir `email_subject`/`email_body`); sólo la llama la API.
- Contratos que se conservan: el panel recibe JSON (`EmlDownloadRequestModel`) y responde 400 si no quedan destinatarios válidos; la API recibe `Form` y no exige destinatarios.

- [ ] **Step 1:** Tests (Review Focus 3): ticket `None` → nombre con el id; ticket `'A"B/C'` → nombre sin `"` ni `/`; el `.eml` tiene `X-Unsent: 1`, un solo `Content-Type` por parte y la columna "Servicios" del XLS con datos cuando la cámara tiene servicios (B7, con objetos cargados dentro de la sesión); `{{ticket}}` con `<script>` sale escapado.
- [ ] **Step 2:** Correr: FAIL.
- [ ] **Step 3:** Implementar y adelgazar los dos handlers; si `grep -rn generate_ban_eml` sólo encuentra su definición, borrarla.
- [ ] **Step 4:** `pytest tests/test_baneo_aviso.py tests/test_contrato_infra_web_api*.py -q`: PASS.
- [ ] **Step 5:** Commit `refactor(infra): un solo armador del .eml de aviso de baneo en core (P12)`.

### Task 10: Upload, análisis y descarga de tracking (B10)

**Files:**
- Create: `core/services/tracking_operaciones.py`
- Modify: `web/app/routers/servicios.py` (`:615-652`, `:2142-2360`), `api/app/routes/infra.py` (`:800-1221`, `:1956-2003`)
- Test: `tests/test_tracking_operaciones.py`

**Interfaces:**
- Produces:
  - `MAX_TRACKING_MB = 5`; `decodificar_tracking(contenido: bytes) -> str` (utf-8 y si falla latin-1).
  - `TrackingSinServicioId(ValueError)`, `TrackingSinUbicaciones(ValueError)`; `ResultadoUploadTracking(servicio_id: str, camaras_existentes: int, ubicaciones_sin_match: int, empalmes_registrados: int, ...)` con los campos que hoy devuelven los dos routers; `procesar_tracking_legacy(session: Session, raw_text: str, filename: str) -> ResultadoUploadTracking` (get-or-create del servicio de la API, que sólo pisa `nombre_archivo_origen` si cambió).
  - `serializar_analisis(result: AnalysisResult) -> dict[str, Any]`: unión de claves (las del panel + `cantidad_pelos` + `alias_id`); `upgrade_info` completo. El panel devuelve el dict; la API lo pasa por su `TrackingAnalyzeResponse` (las claves extra se descartan solas).
  - `TrackingOriginal(filename: str, contenido: str)` y `obtener_tracking_original(session: Session, ruta_id: int) -> TrackingOriginal | None`: devuelve `None` si la ruta no existe y lanza `TrackingOriginalNoDisponible(LookupError)` si existe pero no tiene `raw_file_content`. Las dos apps mapean ambos casos a 404 con sus textos actuales.
- B10: la API lee el upload con tope de `MAX_TRACKING_MB` (`await file.read(limite + 1)` → 413 `detail`) en `upload_tracking` y `analyze`. La entrada `content`+`filename` de analyze en la API se conserva. `download` de la API pasa de `AsyncSession` a `to_thread`.

- [ ] **Step 1:** Tests: `decodificar_tracking(b"\xe1")` → `"á"`; `procesar_tracking_legacy` sin servicio → `TrackingSinServicioId`; `serializar_analisis` tiene `suggested_action`, `cantidad_pelos` y `upgrade_info.terminal_a_odf`; API upload de 6 MB → 413. Contrato: `upload_tracking` y `analyze` en las dos apps.
- [ ] **Step 2:** Correr: FAIL.
- [ ] **Step 3:** Implementar y adelgazar los tres pares de handlers.
- [ ] **Step 4:** `pytest tests/test_tracking_operaciones.py tests/test_tracking_parser.py tests/test_web_uploads_limite.py tests/test_web_servicios_errores_depends.py tests/test_contrato_infra_web_api*.py -q`: PASS.
- [ ] **Step 5:** Commit `refactor(infra): upload, análisis y descarga de tracking en core/services (P12)`.

### Task 11: Resolución de tracking y CONFIRM_UPGRADE (D10, D11, B1, B2)

**Files:**
- Modify: `core/services/tracking_operaciones.py`, `core/services/infra_service.py` (borrar `execute_upgrade` `:714-832`), `web/app/routers/servicios.py` (`:2363-2489`), `api/app/routes/infra.py` (`:1224-1321`)
- Test: `tests/test_tracking_operaciones.py`, `tests/test_ruta_servicio.py`

**Interfaces:**
- Produces: `parsear_accion_resolve(valor: str) -> ResolveAction | None` (`None` = `SKIP`; inválida → `AccionResolveInvalida(ValueError)`), `parsear_ruta_tipo(valor: str | None) -> RutaTipo` (vacío → `ALTERNATIVA`; inválido → `RutaTipoInvalido(ValueError)` → 400 en las dos, D11), `serializar_resolucion(result: ResolveResult) -> dict[str, Any]`.
- D10: CONFIRM_UPGRADE en las dos apps es `resolve_tracking_file(..., ResolveAction.CONFIRM_UPGRADE, old_service_id=...)`; el panel deja de exigir `old_service_db_id` (lo acepta y lo ignora, el modelo no cambia). Arregla B1. `execute_upgrade` se borra (B2; `grep -rn execute_upgrade` debe quedar vacío).
- `SKIP` se acepta en las dos: 200 `{"success": true, "action": "SKIP", ...}` con la forma actual del panel.

- [ ] **Step 1:** Tests: panel CONFIRM_UPGRADE con sólo `old_service_id` llega a `resolve_tracking_file` (parcheado) y no da 400 (B1); Review Focus 4: `old_service_id="ZZ-NO-EXISTE"` contra `resolve_tracking` real (fixture de `tests/test_ruta_servicio.py`) → `success: False` con mensaje y sin texto de excepción; `new_ruta_tipo="x"` → 400 en el panel; `SKIP` en la API → 200. Contrato: actualizar `resolve` acción inválida (sigue 400).
- [ ] **Step 2:** Correr: FAIL.
- [ ] **Step 3:** Implementar, adelgazar y borrar `execute_upgrade`.
- [ ] **Step 4:** `pytest tests/test_tracking_operaciones.py tests/test_ruta_servicio.py tests/test_contrato_infra_web_api*.py -q`: PASS.
- [ ] **Step 5:** Commit `fix(infra): CONFIRM_UPGRADE del panel usa el resolve común y deja de dar 400 (P12)`.

### Task 12: Rutas de un servicio y limpieza de empalmes (D12)

**Files:**
- Modify: `core/services/tracking_operaciones.py`, `web/app/routers/servicios.py` (`:44-119`, `:2492-2550`), `api/app/routes/infra.py` (`:1324-1379`, `:1451-1521`)
- Test: `tests/test_tracking_operaciones.py`

**Interfaces:**
- Produces:
  - `buscar_servicio_por_identificador(session: Session, identificador: str) -> Servicio | None`: `servicio_id` OR `numero_primer_servicio` OR `numero_linea` (criterio del panel) con `order_by(Servicio.id)` antes del `.first()` (D12, también en la API).
  - `obtener_rutas_de_servicio(session: Session, identificador: str) -> dict[str, Any] | None`: la forma actual (las mismas claves en las dos apps), con `selectinload(RutaServicio.empalmes)`.
  - `limpiar_empalmes_de_servicio(session: Session, servicio_id: str) -> dict[str, Any] | None`: hace commit; devuelve la forma de la API (con `empalmes_rutas_eliminados`); `None` si el servicio no existe. El panel suma esa clave y conserva su `message`.

- [ ] **Step 1:** Tests: `test_buscar_servicio_por_numero_linea`, `test_buscar_servicio_orden_determinista` (dos candidatos → el de menor `id`). Contrato: `DELETE` del panel con la clave nueva; `rutas` de la API acepta un `numero_primer_servicio`.
- [ ] **Step 2:** Correr: FAIL.
- [ ] **Step 3:** Implementar y adelgazar los cuatro handlers (`rutas` y `DELETE` de la API pasan de `AsyncSession` a `to_thread`).
- [ ] **Step 4:** `pytest tests/test_tracking_operaciones.py tests/test_web_servicios_errores_depends.py tests/test_contrato_infra_web_api*.py -q`: PASS.
- [ ] **Step 5:** Commit `refactor(infra): rutas de servicio y limpieza de empalmes en core/services (P12)`.

### Task 13: Ingesta de servicios de la API en core (B11)

**Files:**
- Create: `core/services/servicios_ingesta_service.py`
- Modify: `api/app/routes/servicios.py` (`:249-650`), `tests/test_servicios_ingest_routes.py` (`:782`, `:806`)

**Interfaces:**
- Produces: `ResultadoIngesta`, dataclass con exactamente los campos que hoy arma `IngestServiciosResponse` en `api/app/routes/servicios.py:641-650` (mismos nombres y tipos), más lo que necesite `sincronizar_clientes_post_ingesta`; `FormatoNoSoportado(ValueError)` (→ 415) y `ArchivoIlegible(ValueError)` (→ 400); `ingerir_servicios(session: Session, filename: str, content: bytes) -> ResultadoIngesta`, partido en `leer_y_parsear`, `armar_filas`, `consolidar_filas`, `planear_fusiones`, `upsert_servicios` y `aplicar_fusiones` (bloques 2-11 del informe de la spec), con commit al final y rollback ante excepción. El SQL y el orden del DML se mueven **sin cambios**.
- El router conserva los 400 de archivo vacío y sin nombre, el 415 y la llamada async a `sincronizar_clientes_post_ingesta`; todo lo demás va en `await asyncio.to_thread(_run)` con `SessionLocal()`.

- [ ] **Step 1:** Reapuntar los `monkeypatch.setattr(servicios_routes, "es_verificable_por_tipo_y_estado" | "sincronizar_clientes_post_ingesta", ...)` al módulo donde quede cada nombre; agregar `test_ingesta_no_bloquea_el_loop` (mismo patrón que Task 8).
- [ ] **Step 2:** Correr `tests/test_servicios_ingest_routes.py` (real_db) sobre el código actual con el test nuevo: FAIL sólo el de bloqueo.
- [ ] **Step 3:** Mover la lógica.
- [ ] **Step 4:** `pytest tests/test_servicios_ingest_routes.py tests/test_servicios_excel_parser.py tests/test_servicios_consolidacion_service.py tests/test_web_uploads_limite.py -q` (con vars real_db): PASS, y el test de carrera `:760-785` sigue verde.
- [ ] **Step 5:** Commit `refactor(servicios): ingesta de servicios en core/services, fuera del event loop (P12)`.

### Task 14: Cierre — verificación, docs y checklist

**Files:**
- Modify: `docs/api.md` (rutas de infra: notas de comportamiento D2-D12), `docs/infra.md` (si cita los handlers movidos), `docs/web.md` (docstring "proxy al API interno" de `GET /camaras`), `docs/PR/2026-10-27.md` (sección P12, unión si ya existe)

- [ ] **Step 1:** Largo de funciones: un `python - <<'EOF'` con `ast` que liste las funciones de más de 150 líneas en los cuatro routers. Esperado: ninguna. Medir líneas antes (`2762`, `2550`, `2279`, `1033`) y después con `wc -l`.
- [ ] **Step 2:** `LLM_PROVIDER=heuristic pytest tests/test_api_*.py tests/test_web_*.py -q` y la suite completa sin DB: 0 fallas nuevas respecto de `dev`; los `*_real_db.py` tocados, con vars real_db: PASS.
- [ ] **Step 3:** E2E sin sesión contra el web de este worktree con `uvicorn --port $WEB_PORT` (puertos de `.env.dev` del worktree; `docker compose` compartido no se toca): `curl` de las rutas de lectura → 401 sin sesión, y de la API con la key de dev → 200.
- [ ] **Step 4:** Docs y PR diario: matriz enlazada, líneas antes/después, bugs B1-B11, decisiones D1-D12, backlog (`GET /api/infra/rutas/{id}/download` roto; avisos para P10: `submitBan`/`confirmLiftBan` con `success:false`) y checklist del usuario:
  - Logueado en el panel: baneo de 3 pasos y levantarlo (Slack llega), baneos activos, aviso por email, descargar `.eml` (requiere P10 integrado), búsqueda smart con chip y toggle, exportar csv/xlsx, subir/analizar/resolver tracking incluido **CONFIRM_UPGRADE**, rutas de un servicio, limpiar empalmes.
  - Por la API con su cliente: `GET /api/infra/camaras`, `smart-search`, `search`, `export/cameras`, `ban/active`, `notify/download-eml` (Form) y `servicios/ingest`.
- [ ] **Step 5:** Commit `docs(p12): PR diario, docs de infra/api y checklist de pruebas (P12)` y push a la rama efímera.
