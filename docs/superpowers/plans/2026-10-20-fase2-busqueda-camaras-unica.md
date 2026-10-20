# Nombre de archivo: 2026-10-20-fase2-busqueda-camaras-unica.md
# Ubicación de archivo: docs/superpowers/plans/2026-10-20-fase2-busqueda-camaras-unica.md
# Descripción: Plan de implementación de la Fase 2 del relevamiento técnico: la búsqueda y exportación de Cámaras de la SPA pasan a core/; las demás variantes se conservan

# Fase 2: una sola búsqueda y exportación de Cámaras

> **Para agentes:** SUB-SKILL REQUERIDA: usar superpowers:subagent-driven-development (recomendado) o superpowers:executing-plans para implementar tarea por tarea. Los pasos usan checkbox (`- [ ]`).

**Objetivo:** la smart search y la exportación de Cámaras de la SPA pasan a `core/services/` en funciones chicas y testeadas, con resultados idénticos a los de hoy. Las otras seis variantes (simple y avanzada de la SPA; simple, avanzada, smart y exportación de la API interna) se conservan sin cambios.

**Arquitectura:**
- Lógica nueva en dos módulos, `core/services/camaras_consulta.py` (smart search) y `core/services/camaras_exportacion.py` (CSV/XLSX).
- Reciben una `Session` de SQLAlchemy sync y parámetros simples, sin `Request` ni `JSONResponse`.
- Los endpoints de `web/app/routers/camaras.py` quedan como capa fina: auth, llamada al servicio, armado de la respuesta HTTP y manejo de errores.
- Antes de tocar nada se graba una línea base de respuestas reales contra la base de dev. Después de cada tarea se compara contra ella.

**Stack:** FastAPI, SQLAlchemy 2 (sync `SessionLocal`), pandas/openpyxl, pytest.

**Spec:** relevamiento técnico del 2026-10-20 (claude.ai/code/artifact/e0da6f4c-3f37-430c-921a-0b14be712475), sección "Duplicación de lógica", y las decisiones del usuario del 2026-10-20: "manda la SPA; la API v1 no se toca" y, después, "conservá las rutas: el portal todavía tiene poco uso y podríamos borrar algo que, aunque no se use, sigue operativo". **No se borra ninguna ruta.**

## Restricciones globales

- **Mismos resultados.** Para la misma entrada, la smart search devuelve el mismo JSON: mismas claves, mismos `id` en el mismo orden, mismos `total`, `limit`, `offset`, `filters_applied` y `estado_filter`. La exportación devuelve el mismo CSV byte a byte (salvo el timestamp del nombre de archivo) y un XLSX con las mismas filas y columnas. Lo verifica la línea base de la Task 1.
- **No se toca:** `api/app/routes/v1/` (API v1 de otras áreas, OAuth2), el resto de `api/app/routes/infra.py` (tracking, ban, notify, sync, servicios), `GET /api/infra/camaras/buscar` (lo usan 3 modales del frontend) ni el frontend.
- **No se borra ni se cambia el comportamiento de ninguna ruta.** Las variantes duplicadas (`search_camaras_web`, `advanced_search_camaras_web` en la SPA; `search_camaras`, `advanced_search_camaras`, `smart_search_camaras`, `export_cameras` en la API interna) quedan como están: tienen poco uso pero siguen operativas.
- **Imports en `core/`:** absolutos (`from db.models.infra import ...`). `core/` nunca importa `web.*` ni `api.*`. En el router, `from core.services.camaras_consulta import ...`.
- **Encabezado** de 3 líneas en archivos nuevos. Nombres, comentarios y logs en español.
- **Complejidad:** ninguna función nueva supera C901 = 20. Las dos funciones de la SPA que se adelgazan pierden su `# noqa: C901`.
- **Coordinación:** lease `refactor:web-app-main` del agente durante toda la fase (el router de Cámaras es el hotspot). Cada tarea termina con `ready` + `integrate`.

## Review Focus

1. **Orden de los resultados.** La smart search filtra en Python sobre una query ordenada, y después pagina. Si el servicio cambia el orden de la query o pagina antes de filtrar, cambian los `id` de cada página sin que falle nada. Lo cubre la línea base, con consultas que usan `offset` mayor que cero.
2. **Términos vacíos, repetidos o con mayúsculas y espacios.** `"  ruta 5 "`, `""`, `["A","a"]`. El comportamiento actual (strip, minúsculas, AND) se conserva tal cual. Hay tests unitarios para cada caso.
3. **`incluir_no_operativas` cruzado con `estado = NO_OPERATIVA`.** La regla actual: el chip de estado NO_OPERATIVA trae esas cámaras aunque el toggle esté apagado. Hay tests unitarios del filtro y una consulta en la línea base.
4. **Exportación sin pandas.** Si `pandas` no está, el XLSX cae a CSV con un warning. Se conserva, con un test que simula el `ImportError`.
5. **Helpers movidos que usan otras rutas.** `_collect_camara_rutas_info` y `_collect_camara_servicios_ids` los usan también el detalle, los registros y `search_camaras_web`, que se conservan. Al moverlos a `core/`, todos sus lectores tienen que seguir funcionando, y lo mismo los parches de tests que los apunten.

---

### Task 1: Línea base de respuestas reales

**Archivos:**
- Crear: `scripts/linea_base_busqueda_camaras.py` (herramienta de verificación de esta fase; se commitea porque se reusa en las Tasks 2 a 4).

**Interfaces:**
- Produce el CLI `python scripts/linea_base_busqueda_camaras.py grabar --salida <dir>` / `comparar --salida <dir>`:
  - Arma un `TestClient` sobre `web.app.main.app` y parchea `web.app.routers.camaras._require_auth` para devolver `("linea-base", "admin")`.
  - Corre las consultas fijas de `CONSULTAS` (abajo) y guarda cada respuesta en `<dir>/<nombre>.json`. En la exportación guarda el cuerpo CSV, y el XLSX lo pasa por `pandas.read_excel` y lo guarda como JSON de filas.
  - `comparar` vuelve a correr todo y falla (exit 1) con un diff legible ante cualquier diferencia. Ignora sólo el timestamp del `Content-Disposition`.
- `CONSULTAS`: smart search con `terms` ∈ {`[]`, `["ruta"]`, `["RUTA ", " 5"]`, `["a","a"]`, `[""]`}. Cada uno con `estado` ∈ {`None`, `"LIBRE"`, `"NO_OPERATIVA"`}, `incluir_no_operativas` ∈ {`False`, `True`}, y `offset` 0 y 50 con `limit` 50. Exportación con `filter_status` ∈ {`ALL`, `LIBRE`, `BANEADA`}, `format` ∈ {`csv`, `xlsx`} y un `servicio_id` real tomado de la base (el primero con cámaras).
- Base: la de dev (`POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5433 POSTGRES_DB=focas_dev POSTGRES_USER=FOCALBOT POSTGRES_PASSWORD="$(cat .secrets/Dev_db_password_v1.txt)"`). Nunca la de producción (5432). El script aborta si `POSTGRES_PORT` no es 5433.

- [ ] **Paso 1:** escribir el script y correr `grabar --salida .superpowers/linea-base-fase2` (ruta ignorada por Git) sobre el código actual, sin cambios.
- [ ] **Paso 2:** correr `comparar` inmediatamente. Esperado: exit 0. Si da diferencias sin haber cambiado código, la base se movió entre corridas o hay no determinismo. Documentarlo y fijar el orden antes de seguir.
- [ ] **Paso 3:** commit `test(camaras): línea base de smart search y exportación contra la base de dev`.

### Task 2: Smart search a `core/services/camaras_consulta.py`

**Archivos:**
- Crear: `core/services/camaras_consulta.py`, `tests/test_camaras_consulta.py`
- Modificar: `web/app/routers/camaras.py` (`smart_search_camaras_web` queda fino)

**Interfaces:**
- Produce:
  - `@dataclass(frozen=True) class ResultadoSmartSearch` con `total: int`, `limit: int`, `offset: int`, `estado_filter: str | None`, `terminos_aplicados: int`, `camaras: list[Camara]`. Son las cámaras de la página, ya filtradas y en orden.
  - `buscar_camaras_por_terminos(session: Session, terminos: list[str], *, estado: str | None, incluir_no_operativas: bool, limit: int, offset: int) -> ResultadoSmartSearch`. Contiene la query, los filtros, el matching y la paginación, tal cual hoy. El `min(limit, 500)` y el `max(offset, 0)` también se mueven acá.
  - `termino_coincide(termino: str, camara, servicios_ids: list[str], cables_nombres: list[str]) -> bool`, pura.
  - `normalizar_terminos(terminos: list[str]) -> list[str]`, pura: el strip y el descarte de vacíos que hace hoy el endpoint, exactamente.
  - `_collect_camara_rutas_info` y `_collect_camara_servicios_ids` se mueven de `web/app/routers/camaras.py` a este módulo, sin cambios en el cuerpo, porque el servicio los necesita y `core` no puede importar `web`. El router los importa desde acá para los otros endpoints que ya los usan.
- El endpoint conserva `_require_auth`, la serialización con `_serialize_camara_response`, el log `action=smart_search...` con los mismos campos, el `JSONResponse` con las mismas claves y el `except` que responde 500.

- [ ] **Paso 1:** tests unitarios de `normalizar_terminos` y `termino_coincide`, con objetos falsos (`SimpleNamespace`) que cubran cada campo que se busca hoy: nombre, dirección, fontine_id, servicios, cables, estado y origen. Valores sacados del cuerpo actual de la función. Más los casos de la Review Focus 2.
- [ ] **Paso 2:** test del filtro de estado y no operativas (Review Focus 3). Usa una sesión falsa o, mejor, `requiere_postgres_real` contra dev, siguiendo el patrón de `tests/soporte_postgres_real.py`.
- [ ] **Paso 3:** mover la lógica. `ruff check --select C901` debe quedar sin `noqa` en `smart_search_camaras_web` y en las funciones nuevas.
- [ ] **Paso 4:** `python scripts/linea_base_busqueda_camaras.py comparar --salida .superpowers/linea-base-fase2`. Esperado: exit 0 en todas las consultas de smart search. Correr también `tests/test_web_rutas_contrato.py` (sin regenerar) y los tests que importan los helpers movidos.
- [ ] **Paso 5:** commit `refactor(camaras): smart search a core/services/camaras_consulta.py`. Después `ready` e `integrate`.

### Task 3: Exportación a `core/services/camaras_exportacion.py`

**Archivos:**
- Crear: `core/services/camaras_exportacion.py`, `tests/test_camaras_exportacion.py`
- Modificar: `web/app/routers/camaras.py` (`export_cameras_web` queda fino)

**Interfaces:**
- Produce:
  - `filas_exportacion(session: Session, *, filter_status: str | None, servicio_id: str | None) -> list[dict[str, object]]`. Devuelve las filas con las mismas claves y el mismo orden de columnas de hoy.
  - `a_csv(filas: list[dict]) -> bytes`, la serialización exacta del CSV actual (`csv.DictWriter`, encoding y BOM como hoy).
  - `a_xlsx(filas: list[dict]) -> bytes | None`. Devuelve `None` si `pandas` no está disponible, y el endpoint cae a CSV con el mismo `logger.warning("action=export_cameras warning=pandas_not_available fallback=csv")`.
- El endpoint conserva auth, nombre de archivo `camaras_<timestamp>.<ext>`, `media_type`, `Content-Disposition` y la respuesta de error actual.

- [ ] **Paso 1:** tests de `a_csv` (encabezados y orden, comillas, caracteres no ASCII), de `a_xlsx` (lectura de vuelta con pandas) y del fallback (monkeypatch del import de pandas: Review Focus 4).
- [ ] **Paso 2:** mover la lógica y quitar el `# noqa: C901` de `export_cameras_web`.
- [ ] **Paso 3:** `comparar` contra la línea base. Esperado: exit 0 en todas las consultas de exportación. Contrato de rutas en verde.
- [ ] **Paso 4:** commit `refactor(camaras): exportación a core/services/camaras_exportacion.py`. Después `ready` e `integrate`.

### Task 4: Documentar las variantes conservadas

**Archivos:**
- Modificar: `docs/PR/<fecha>.md`, `AGENTS.md` (una línea en Arquitectura).

- [ ] **Paso 1:** en `AGENTS.md`, indicar que la búsqueda y la exportación de Cámaras del panel viven en `core/services/camaras_consulta.py` y `core/services/camaras_exportacion.py`. Agregar que las variantes `search_camaras*` y `advanced_search_camaras*` de la SPA y de la API interna, y `smart_search_camaras` y `export_cameras` de la API interna, se conservan a propósito: tienen poco uso pero siguen operativas, así que no se borran sin decisión explícita del usuario.
- [ ] **Paso 2:** `comparar` contra la línea base, una última vez, y la suite completa.
- [ ] **Paso 3:** PR diario. Commit `docs(camaras): búsqueda y exportación de Cámaras en core/; variantes conservadas`. Después `ready` e `integrate`.

## Fuera de alcance

- Borrar o cambiar cualquier ruta (decisión del usuario: se conservan todas, incluidas las de `/api/infra/*` de la API interna).
- La búsqueda de Cámaras del listener de Slack (`modules/slack_baneo_notifier/camara_search.py`), que interpreta texto libre y tiene sus propias reglas.
- Optimizar el N+1 de la smart search (eso es de la Fase 4).
