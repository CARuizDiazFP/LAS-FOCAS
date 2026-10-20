# Nombre de archivo: 2026-10-20-fase1-partir-web-main.md
# Ubicación de archivo: docs/superpowers/plans/2026-10-20-fase1-partir-web-main.md
# Descripción: Plan de implementación de la Fase 1 del relevamiento técnico: partir web/app/main.py en routers por dominio sin cambiar comportamiento

# Fase 1 — Partir `web/app/main.py` en routers por dominio

> **Para agentes:** SUB-SKILL REQUERIDA: usar superpowers:subagent-driven-development (recomendado) o superpowers:executing-plans para implementar tarea por tarea. Los pasos usan checkbox (`- [ ]`).

**Objetivo:** que `web/app/main.py` (11.514 líneas, 172 rutas `@app.*`) quede como ensamblador de la app. Las rutas pasan a `web/app/routers/<dominio>.py` sin cambiar ningún path, método, respuesta ni orden de resolución.

**Arquitectura:**
- Cada dominio es un módulo con `router = APIRouter()`. `main.py` lo incluye con `app.include_router(...)`.
- Los helpers que usan dos o más dominios van a `web/app/comun.py`. Los que usa un solo dominio se mudan con él.
- Un test de contrato congela qué endpoint resuelve cada ruta *antes* de mover nada. Cada mudanza tiene que dejarlo idéntico.
- Un dominio por rama efímera, integrado a `dev` el mismo día.

**Stack:** FastAPI/Starlette, pytest, `scripts/agent_worktree.py` (gate de calidad de la Fase 0).

**Spec:** relevamiento técnico del 2026-10-20 (claude.ai/code/artifact/e0da6f4c-3f37-430c-921a-0b14be712475), secciones "Hotspots", "Duplicación de lógica" y "Fases propuestas" (Fase 1 y su gate).

## Restricciones globales

- **Mover, no reescribir.** El cuerpo de cada función se copia tal cual. Sólo cambian el decorador (`@app.` → `@router.`) y los imports. Los arreglos de lógica, renombres y desduplicaciones son de la Fase 2/3 y quedan prohibidos acá.
- **Imports relativos dentro de `web/app/`** (`from .comun import ...`, `from .routers import camaras`). En el contenedor el paquete se llama `app` (`COPY web/app /app/app`, `CMD uvicorn app.main:app`) y en los tests `web.app`; sólo los imports relativos funcionan en los dos. Ningún módulo de `routers/` importa `main`.
- **Archivos nuevos** con el encabezado de 3 líneas del repo (`# Nombre de archivo:`, `# Ubicación de archivo:`, `# Descripción:`). Nombres, comentarios y logs en español.
- **El catch-all SPA `/{path:path}` queda en `main.py` y registrado último.** Todos los `include_router` van antes que él.
- **Coordinación:** `web/app/main.py` recibió 101 commits en 6 meses. Antes de cada dominio:
  `python scripts/agent_lock.py acquire "refactor:web-app-main" --agent <id> --reason "Fase 1: mudar <dominio>"`.
  Liberarlo al integrar. Mientras otra sesión lo sostenga, no se empieza otro dominio.
- **Cierre de cada dominio:** `sync` → `ready` (gate) → `integrate` en el día. Nunca acumular dos dominios sin integrar.

## Review Focus

1. **Precedencia de rutas.** Una ruta literal (`/api/infra/camaras/export`) movida detrás de una paramétrica (`/api/infra/camaras/{camara_id}`) deja de responder sin error de import. Lo cubre el contrato de la Tarea 1: cada muestra tiene que resolver al mismo endpoint.
2. **Monkeypatch a `web_main.<nombre>`.** 25 nombres se parchean sobre `web.app.main`: `_obtener_servicio_categorizado` (14), `encolar_recalculo_duplicados_botellas` (11), `leer_cache_duplicados` (9), `REPORT_SERVICE_CONFIG` (7)… Cuando la función que los usa se muda, el parche sobre `main` deja de tener efecto y el test puede pasar en falso o llamar al servicio real. Cada tarea de dominio redirige esos parches (paso "Redirigir parches").
3. **Imports en el contenedor.** `from web.app.comun import` funciona en tests y rompe en la imagen (no existe el paquete `web.app`). Lo cubre la Tarea 10, que importa `app.main` dentro de la imagen construida.
4. **Estado global compartido** (`REPORT_HISTORY`, `INTENT_COUNTER`, caches). Si dos módulos crean su propia instancia, la métrica o el historial se parte en dos. Regla: se define una vez en `comun.py` y se importa; nunca se re-crea.
5. **Artefactos de tests en el árbol.** `tests/test_web_sla_flow.py` y `tests/test_web_sla_consumo.py` escriben en `web/data/reports/` y traban `agent_worktree.py cleanup`. Lo cubre la Tarea 2.

---

### Tarea 1: Contrato de rutas de la SPA

**Archivos:**
- Crear: `tests/test_web_rutas_contrato.py`
- Crear: `tests/fixtures/web_rutas_contrato.json` (generado y commiteado)

**Interfaces:**
- Produce:
  - `muestra_de_ruta(plantilla: str) -> str` reemplaza los parámetros: `{x}` → `muestra`, `{x:int}` → `1`, `{x:float}` → `1.5`, `{x:path}` → `muestra/sub`.
  - `resolver(app, tipo: str, metodo: str, path: str) -> str | None` recorre `app.router.routes` en orden y devuelve `endpoint.__name__` del primer `Match.FULL`, armando un `scope` mínimo (`type` = `http`/`websocket`, `method`, `path`). Los `Mount` (`/reports`) devuelven `"mount:<name>"`.
  - `contrato_actual(app) -> list[dict]` arma entradas `{"tipo", "metodo", "plantilla", "muestra", "endpoint"}` ordenadas por `(plantilla, metodo)`: una por método de cada `APIRoute` y una por cada `WebSocketRoute`.

- [ ] **Paso 1:** escribir `test_contrato_de_rutas_no_cambia`. Carga el JSON y lo compara con `contrato_actual(app)`. Ante una diferencia, el mensaje lista sólo las entradas distintas (agregadas, quitadas, endpoint cambiado). Si `REGENERAR_CONTRATO_RUTAS=1`, escribe el JSON y hace `pytest.skip`.
- [ ] **Paso 2:** escribir `test_muestra_de_ruta`, con los cuatro casos de convertidor más una plantilla sin parámetros, y `test_resolver_detecta_sombra`: una app de juguete con `/x/{id}` registrada antes que `/x/export` resuelve `GET /x/export` a la paramétrica.
- [ ] **Paso 3:** `REGENERAR_CONTRATO_RUTAS=1 pytest tests/test_web_rutas_contrato.py`, y después sin la variable. Esperado: PASS. El JSON tiene unas 180 entradas.
- [ ] **Paso 4:** verificar que el contrato muerde. Mover a mano `@app.get("/health/version")` debajo del catch-all `/{path:path}`. El test tiene que FALLAR con `GET /health/version` resolviendo al endpoint del catch-all. Si pasa, el resolver no respeta el orden: corregirlo. Revertir el experimento.
- [ ] **Paso 5:** commit `test(web): contrato de resolución de rutas de la SPA`.

### Tarea 2: Los tests no escriben en `web/data/reports/`

**Archivos:**
- Modificar: `tests/conftest.py`, `tests/test_web_sla_flow.py`, `tests/test_web_sla_consumo.py`

**Interfaces:**
- Produce: hooks `pytest_sessionstart` / `pytest_sessionfinish` en `tests/conftest.py`. El primero toma un snapshot de los archivos bajo `web/data/reports/`. El segundo, si aparecieron archivos nuevos, los lista en el reporte y fuerza `session.exitstatus = 1`.

- [ ] **Paso 1:** implementar los hooks y correr `pytest tests/test_web_sla_flow.py tests/test_web_sla_consumo.py`. Esperado: FALLA, listando `InformeSLA_*.docx` y `a.xlsx`/`a_ejecutivo.docx`…
- [ ] **Paso 2:** en esos tests, `monkeypatch.setattr(web_main, "REPORTS_DIR", tmp_path / "reports")` junto al `setenv("REPORTS_DIR", ...)` que ya existe. El env no alcanza porque la constante se calcula al importar. Si la ruta de consumo usa otra constante, parchear esa: buscar `reports_dir=` en `web/app/main.py`.
- [ ] **Paso 3:** correr de nuevo los dos archivos. Esperado: PASS, sin archivos nuevos. Correr además la suite de `tests/test_web_*.py` para descartar otros escritores.
- [ ] **Paso 4:** commit `test(web): los tests de SLA ya no dejan informes en web/data/reports`.

**Cierre de las Tareas 1 y 2:** una rama (`refactor/<id>-contrato-rutas`), `ready`, `integrate`.

### Tarea 3: `web/app/comun.py` con lo compartido

**Archivos:**
- Crear: `web/app/comun.py`, `web/app/routers/__init__.py` (vacío, con encabezado)
- Modificar: `web/app/main.py`, y los tests cuyos parches apunten a nombres movidos

**Interfaces:**
- Produce en `web/app/comun.py`, con el cuerpo tal cual hoy:
  - Auth: `_require_auth(request) -> tuple[str, str]`, `_require_admin(request) -> str`, `_validar_csrf`, `get_current_user`.
  - Configuración: `DB_DSN`, `INTERNAL_API_BASE_URL`, `_internal_api_auth_headers`, `_env_int`.
  - Rutas de datos: `BASE_DIR`, `DATA_DIR`, `UPLOADS_DIR`, `REPORTS_DIR`. `SPA_INDEX` y `DIST_DIR` quedan en `main.py` con el catch-all.
  - Estado: `REPORT_HISTORY`.
- `main.py` los importa con `from .comun import ...`, así que el resto de `main.py` no cambia.

- [ ] **Paso 1:** mover esas definiciones a `comun.py`. `BASE_DIR` pasa a `Path(__file__).resolve().parents[1]`, el mismo valor porque el archivo está en el mismo directorio.
- [ ] **Paso 2 — Redirigir parches:** `grep -rnE 'setattr\((web_main|main)[^,]*, *"(get_current_user|_require_auth|_require_admin|_validar_csrf|DB_DSN|INTERNAL_API_BASE_URL|REPORTS_DIR|UPLOADS_DIR|REPORT_HISTORY)"' tests`. Cada parche se apunta a `web.app.comun`. En la Tarea 2 los de `REPORTS_DIR` se apuntaron a `web_main`: ahora van a `comun`.
- [ ] **Paso 3:** `pytest -q tests/test_web_rutas_contrato.py tests/test_web_*.py`. Esperado: PASS, contrato idéntico.
- [ ] **Paso 4:** commit `refactor(web): helpers compartidos de main.py a web/app/comun.py`; luego `ready` e `integrate`.

### Tareas 4–9: un dominio por tarea (mismo procedimiento)

**Procedimiento común** (cada tarea en su propia rama, con el lease `refactor:web-app-main`):

- [ ] **Paso 1:** crear `web/app/routers/<modulo>.py` con `router = APIRouter()`. Mover, en el orden en que aparecen en `main.py`, todas las rutas cuyos paths empiezan con los prefijos de la tabla. Mover también los helpers privados, modelos Pydantic y constantes que **sólo** usan esas rutas (`grep -n '\b<nombre>\b' web/app/main.py`). Si un helper lo usa además otro dominio todavía no mudado, va a `comun.py`.
- [ ] **Paso 2:** en `main.py`, `from .routers import <modulo>` y `app.include_router(<modulo>.router)` en el bloque de includes, inmediatamente antes del catch-all.
- [ ] **Paso 3 — Redirigir parches:** para cada nombre movido, `grep -rnE 'setattr\((web_main|main)[^,]*, *"<nombre>"' tests` y apuntar al módulo nuevo (`web.app.routers.<modulo>`). Los parches sobre módulos de terceros (`web_main.psycopg`, `web_main.httpx`, `web_main.asyncio`) siguen funcionando, porque parchean el módulo compartido: no se tocan.
- [ ] **Paso 4:** `pytest -q tests/test_web_rutas_contrato.py`. Si falla por endpoint cambiado, es precedencia: reordenar las rutas **dentro** del router o mover el `include_router`, nunca cambiar un path. Después, el gate: `python scripts/agent_worktree.py ready --agent <id>`. Corre los tests focales que importan `app.main`/`web.app.main`, unos 50 archivos.
- [ ] **Paso 5:** `ruff check web/app` sin avisos. Las rutas con `# noqa: C901` mantienen la marca.
- [ ] **Paso 6:** commit `refactor(web): rutas de <dominio> a web/app/routers/<modulo>.py`, `integrate` y liberar el lease.

| Tarea | Módulo | Prefijos de path | Rutas aprox. |
| --- | --- | --- | ---: |
| 4 | `sesion.py` | `/health`, `/api/auth`, `/logout`, `/api/admin/me`, `/api/users`, `/api/admin/users` | 9 |
| 5 | `informes.py` | `/reports/index`, `/api/reports`, `/api/flows`, `/api/tools` | 9 |
| 6 | `chat.py` | `/api/chat`, `/mcp/invoke` | 6 |
| 7 | `admin_datos.py` | `/api/admin/ingesta`, `/api/admin/clientes`, `/api/admin/servicios` | 26 |
| 8 | `servicios.py` | `/api/servicios`, `/api/infra/servicios`, `/api/admin/infra/servicios-odf`, `/api/infra/rutas`, `/api/infra/tracking`, `/api/infra/trackings`, `/api/infra/upload_tracking` | 32 |
| 9a | `cromo.py` | `/api/infra/cromo`, `/api/infra/cromo-botellas`, `/api/infra/botellas`, `/api/admin/infra/botellas`, `/api/admin/infra/huerfanos`, `/api/admin/infra/inconsistencias-cromo`, `/api/admin/infra/arbitro-cromo` | 55 |
| 9b | `camaras.py` | `/api/infra/camaras`, `/api/admin/infra/camaras`, `/api/infra/ban`, `/api/admin/baneos`, `/api/infra/notify`, `/api/infra/export`, `/api/infra/search`, `/api/infra/smart-search`, `/api/infra/ingresos`, `/api/admin/infra/ingresos-sin-match` | 34 |

El orden va de menor a mayor riesgo. Cromo y Cámaras van al final porque son los dominios con más rutas paramétricas y más helpers compartidos. Al empezar cada uno, contar con `grep -cE '^@app\.' web/app/main.py` y anotar en el commit cuántas rutas quedan.

### Tarea 10: `main.py` como ensamblador y verificación en la imagen

**Archivos:**
- Modificar: `web/app/main.py`, `config/repository-map.json` (y regenerar `docs/REPOSITORY_MAP.md`), `AGENTS.md` (sección Arquitectura: dónde viven las rutas de la SPA)

- [ ] **Paso 1:** `grep -cE '^@app\.' web/app/main.py` debe dar 1, el catch-all. En `main.py` sólo quedan la creación de la app, middlewares, mounts, `mount_*` de websockets y FO Monitor, los `include_router` y el catch-all. Lo que quede suelto se muda a `comun.py` o al router que lo usa.
- [ ] **Paso 2:** `pytest -q tests/test_web_rutas_contrato.py tests/test_web_*.py` en verde, y la suite completa una vez (`pytest -q tests nlp_intent/tests`).
- [ ] **Paso 3 — imagen:** construir sólo la imagen web de dev (`docker compose -f deploy/compose.yml --env-file .env.dev build web`, ver memoria `--env-file obligatorio`). Correr `docker run --rm <imagen> python -c "import app.main, app.routers.camaras"`. Esperado: exit 0. Es la única verificación de que los imports relativos funcionan con el paquete `app` del contenedor.
- [ ] **Paso 4:** actualizar el mapa del repo y `AGENTS.md`. Commit `refactor(web): main.py queda como ensamblador de la app`, `ready`, `integrate`. Actualizar la sección "Fases" del relevamiento: Fase 1 cumplida y `main.py` con N líneas.

## Fuera de alcance

Unificar la búsqueda y la exportación de Cámaras entre `api/` y `web/` (Fase 2). Bajar complejidad, `except Exception` y `_require_auth` → `Depends` (Fase 3). Desplegar a producción: se hace con el runbook habitual cuando el usuario lo pida.
