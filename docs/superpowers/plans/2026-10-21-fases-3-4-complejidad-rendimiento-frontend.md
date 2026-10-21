# Nombre de archivo: 2026-10-21-fases-3-4-complejidad-rendimiento-frontend.md
# Ubicación de archivo: docs/superpowers/plans/2026-10-21-fases-3-4-complejidad-rendimiento-frontend.md
# Descripción: Plan de implementación de las Fases 3 y 4 del relevamiento técnico: gate, complejidad, restos de código, rendimiento medido de Cámaras y type-check del frontend

# Fases 3 y 4: complejidad, rendimiento medido y frontend

> **Para agentes:** SUB-SKILL REQUERIDA: usar superpowers:subagent-driven-development (recomendado) o superpowers:executing-plans para implementar tarea por tarea. Los pasos usan checkbox (`- [ ]`).

**Objetivo:**
- Cerrar el hueco del gate de `ready`.
- Bajar a menos de 20 la complejidad de las 4 funciones de producción más usadas que hoy la superan.
- Limpiar los restos de código detectados.
- Acelerar con medición la smart search y la exportación de Cámaras.
- Dejar el frontend con un type-check en verde que el gate pueda correr.

En ningún caso cambia el comportamiento observable.

**Arquitectura:** cada refactor sigue el mismo patrón probado en la Fase 2: primero tests de caracterización, que pasan sobre el código actual, después la extracción, y los mismos tests en verde. El rendimiento se mide antes y después, y los resultados se verifican con `scripts/linea_base_busqueda_camaras.py` contra la base de dev.

**Stack:** Python 3.11, FastAPI, SQLAlchemy 2, pytest, ruff; Vue 3, TypeScript, `vue-tsc`.

**Spec:** relevamiento técnico del 2026-10-20 (claude.ai/code/artifact/e0da6f4c-3f37-430c-921a-0b14be712475), "Fases propuestas": Fase 3, complejidad y manejo de errores; Fase 4, rendimiento medido y frontend. Más los pendientes registrados en `docs/PR/2026-10-21.md`, (a) a (c), y las decisiones del usuario: conservar todas las rutas y no cambiar comportamiento.

## Restricciones globales

- **Mismo comportamiento.** Ninguna ruta se borra, se renombra ni cambia su respuesta (cuerpo, status, headers). Tampoco cambian los textos de log usados por alertas (`action=...`).
- **Queda fuera, a propósito:**
  - Reemplazar `except Exception` por errores tipados: cambiaría qué se responde ante fallas.
  - Cambiar `_require_auth()` por `Depends`: altera el orden auth/validación (401 frente a 422) y el OpenAPI.
  - Ambas cosas sólo con decisión explícita del usuario.
- **Refactor con red.** Antes de extraer, tests de caracterización que pasan sobre el código de BASE. Se demuestra corriéndolos en un `git worktree add --detach` del BASE, o dejando constancia de que se escribieron y pasaron antes del cambio. Después de extraer, los mismos tests sin modificar.
- **Base de datos:** sólo la de dev (`127.0.0.1:5433`, `focas_dev`); nunca la 5432. Sólo lectura, salvo los tests con `requiere_postgres_real` que ya escriben y limpian.
- **Complejidad:** las funciones nuevas, menos de 20 (C901). Una función refactorizada pierde su `# noqa: C901`.
- **Archivos nuevos** con el encabezado de 3 líneas; nombres, comentarios y logs en español.
- **Coordinación:** lease `refactor:web-app-main` del controlador durante las tareas que tocan `web/app/`. Cada tarea termina con `ready` + `integrate`. Hay otra sesión trabajando en paralelo en tracking (`claude-trackvig-*`): `sync` antes de cada `ready`.

## Review Focus

1. **Ramas no ejercitadas por los tests de caracterización.** Al extraer una función con 25 ramas, el error típico es invertir una condición en una rama sin test. Cada tarea lista las ramas del original y marca cuáles quedan cubiertas.
2. **Eager loading que cambia el orden o duplica filas** (Tasks 8 y 9). Un `joinedload` sobre colecciones puede duplicar o reordenar resultados. Se usa `selectinload`, y la línea base lo verifica.
3. **Logging movido de lugar** (Task 2). Llamar a `setup_logging` antes de importar los routers no debe configurar handlers dos veces ni duplicar líneas en `web.log`.
4. **Type-check que el gate no puede correr.** Los worktrees no tienen `node_modules`. El gate saltea el paso con un motivo explícito, nunca falla por entorno ni pasa en silencio.
5. **Parches de tests apuntando al módulo equivocado** después de extraer: se aplica la lección de la Fase 1, se parchea donde se lee.

---

### Task 1: Gate — tests focales de routers vía `web.app.main`

**Archivos:** Modificar `scripts/agentes/calidad.py` y `tests/test_agentes_calidad.py`.

**Interfaces:** `tests_focales(ruta, archivos)` conserva la firma. Si algún archivo cambiado está bajo `web/app/routers/` o es `web/app/comun.py`, suma los tests que importan `web.app.main` o `app.main` (patrones `from web.app.main import`, `from web.app import main`, `import web.app.main`, `from app.main import`, `web_main`).

- [ ] **Paso 1:** test nuevo `test_tests_focales_de_un_router_suman_los_que_importan_main`. En el repo de prueba del fixture se agregan `web/app/routers/x.py` y un `tests/test_usa_main.py` con `from web.app.main import app`. Cambiar el router selecciona `test_usa_main.py`. Debe FALLAR con el código actual.
- [ ] **Paso 2:** implementar y ver el test en verde, junto con todo `tests/test_agentes_calidad.py` y `tests/test_agent_worktree.py`.
- [ ] **Paso 3:** commit `fix(agentes): el gate suma los tests que llegan a un router vía web.app.main`. Después `ready` + `integrate`.

### Task 2: Restos de código y orden de logging

**Archivos:** `core/docx_utils/text_replace.py:57`, `core/services/infra_service.py:526,547`, `core/sla/legacy_report.py:497,588,648`, `web/app/main.py`.

- [ ] **Paso 1:** las 5 asignaciones con `# noqa: F841`. Diagnóstico del controlador, para aplicar tal cual:
  - `text_replace.py:57`, `mapping`: variable muerta. Se borra la línea.
  - `infra_service.py:526/547`, `ruta_mismo_camino`: resto de la detección automática de NEW_STRAND, deshabilitada a propósito (ver el comentario en la línea ~591). Se borran la declaración y la asignación. El `if self._routes_have_same_path(...)` también, sólo si la función no tiene efectos (verificar). Si los tiene, se deja la llamada sin asignar.
  - `legacy_report.py:497` y `648`, `columns["numero_linea"]`: la lectura valida que la columna exista (KeyError). Se conserva como sentencia sin asignar, con un comentario `# valida que exista la columna`.
  - `legacy_report.py:588`, `texto_completo`: variable muerta. Se borra.
  - Los tests existentes de SLA, tracking y docx en verde (grep de los módulos).
- [ ] **Paso 2:** en `web/app/main.py`, llamar a `setup_logging(...)` antes del primer `from .routers import ...`. Hoy los routers se importan antes, y sus warnings de import van a stderr y no a `web.log`. Test: después de importar `web.app.main`, el logger `"web"` tiene exactamente los mismos handlers que antes, sin duplicados (Review Focus 3). Contrato de rutas en verde.
- [ ] **Paso 3:** commit `refactor: restos de asignaciones sin uso y logging antes de importar routers`. Después `ready` + `integrate`.

### Task 3: `_buscar_camara_intento` (Slack, complejidad 23)

**Archivos:** `modules/slack_baneo_notifier/camara_search.py:461` y un test nuevo, `tests/test_slack_camara_search_intento.py`.

- [ ] **Paso 1:** caracterización. Una tabla de casos de entrada → resultado esperado que recorra cada rama de la función (listarlas en el reporte). Los casos se derivan del código actual y de los ejemplos reales de `tests/test_slack_ingreso_listener.py` y `tests/test_busqueda_camaras_sin_match.py`. En verde sobre BASE.
- [ ] **Paso 2:** extraer en funciones de menos de 20 y quitar el `noqa`. Los mismos tests, más `tests/test_slack_*.py` y `tests/test_busqueda_camaras_sin_match.py`, en verde.
- [ ] **Paso 3:** commit `refactor(slack): _buscar_camara_intento en pasos chicos`. Después `ready` + `integrate`.

### Task 4: `get_ruta_tracking` (complejidad 26)

**Archivos:** `web/app/routers/servicios.py:363` y un test nuevo, `tests/test_web_ruta_tracking.py`.

- [ ] **Paso 1:** caracterización. Tests con `requiere_postgres_real` contra dev, siguiendo el patrón de `tests/soporte_postgres_real.py`, que llaman a `GET /api/infra/rutas/{ruta_id}/tracking` con auth parcheada en `web.app.routers.servicios`. Cubren al menos: una ruta con empalmes, una ruta sin empalmes, un id inexistente (404), y el resto de las ramas del original que se puedan cubrir con datos reales (listarlas). Se compara la respuesta completa contra un snapshot tomado en BASE dentro del mismo test (se graba con el código BASE en el worktree detached y se commitea en `tests/fixtures/`), o contra aserciones explícitas por campo si el snapshot no es estable.
- [ ] **Paso 2:** extraer la lógica a funciones de menos de 20 (en el router o en `core/services/` si ya existe un servicio de tracking natural, como `core/services/cromo/tracking_service.py`; decidir leyendo). Quitar el `noqa`.
- [ ] **Paso 3:** tests en verde, contrato de rutas y `tests/test_web_*` del dominio servicios. Commit `refactor(web): get_ruta_tracking en pasos chicos`. Después `ready` + `integrate`.

### Task 5: `generar_informe_sla_web` (complejidad 24)

**Archivos:** `web/app/routers/informes.py:168` y `tests/test_web_sla_flow.py`, ampliado.

- [ ] **Paso 1:** listar las ramas del original y agregar a `tests/test_web_sla_flow.py` los casos de las ramas que hoy no cubre: validaciones de entrada, modo Excel frente a modo DB, PDF on/off y errores. En verde sobre BASE.
- [ ] **Paso 2:** extraer y quitar el `noqa`. Tests de informes y SLA en verde, sin archivos nuevos en `web/data/` (el hook de conftest lo controla).
- [ ] **Paso 3:** commit `refactor(web): generar_informe_sla_web en pasos chicos`. Después `ready` + `integrate`.

### Task 6: `_evaluar_regla` del árbitro de Cromo (complejidad 21)

**Archivos:** `core/services/cromo/arbitro/motor.py:212` y `tests/test_cromo_arbitro_motor.py`, ampliado.

- [ ] **Paso 1:** ramas del original contra los tests actuales del árbitro (`tests/test_cromo_arbitro_*.py`). Agregar los casos que faltan. En verde sobre BASE.
- [ ] **Paso 2:** extraer y quitar el `noqa`. Tests del árbitro en verde (los `*_real_db.py` con Postgres de dev).
- [ ] **Paso 3:** commit `refactor(cromo): _evaluar_regla en pasos chicos`. Después `ready` + `integrate`.

### Task 7: Justificar los `noqa: C901` que quedan

**Archivos:** las 6 funciones restantes y `AGENTS.md`.

- [ ] **Paso 1:** reemplazar `# noqa: C901` por `# noqa: C901 - <motivo>` en:
  - `export_cameras` y `ingest_servicios` (API interna; se conservan por decisión del usuario).
  - `advanced_search_camaras_web` (variante conservada).
  - `mount_fo_monitor_routes` (sus rutas anidadas suman complejidad; FO Monitor está en stand-by en prod).
  - `comando_doctor` y `main` de `agent_lock` (CLIs de tooling con tests propios).
- [ ] **Paso 2:** en `AGENTS.md`, sección Build y Test, una línea: "Las excepciones a C901 llevan motivo; `except Exception` → errores tipados y `_require_auth` → `Depends` quedan fuera hasta decisión explícita (cambian respuestas)".
- [ ] **Paso 3:** commit `docs: motivos de las excepciones de complejidad`. Después `ready` + `integrate`.

### Task 8: Medición de la smart search y la exportación (línea base de tiempos y queries)

**Archivos:** `scripts/linea_base_busqueda_camaras.py`.

**Interfaces:** subcomando nuevo `medir --salida DIR [--solo smart|export]`. Corre las mismas consultas, y por cada una registra el tiempo de pared y la cantidad de sentencias SQL ejecutadas (con un listener `before_cursor_execute` sobre `db.session.engine`). Escribe `DIR/tiempos.json` e imprime un resumen: total, mediana y peor caso por grupo.

- [ ] **Paso 1:** implementar `medir` y correrlo sobre el código actual (es la referencia de la Task 9). Guardar el resumen en el reporte.
- [ ] **Paso 2:** para la consulta smart más lenta, `EXPLAIN (ANALYZE, BUFFERS)` de las 3 sentencias que más se repiten (sólo SELECT, contra dev). Anotar en el reporte dónde se va el tiempo: N+1 de empalmes, rutas o servicios; cables; botellas.
- [ ] **Paso 3:** commit `test(camaras): medición de tiempos y queries de smart search y exportación`. Después `ready` + `integrate`.

### Task 9: Smart search y exportación sin N+1

**Archivos:** `core/services/camaras_consulta.py`, `core/services/camaras_exportacion.py`.

- [ ] **Paso 1:** con el diagnóstico de la Task 8, agregar `selectinload` (nunca `joinedload` sobre colecciones; Review Focus 2) a las relaciones que se recorren por cámara: empalmes → rutas → servicio, cables, botellas, o lo que diga la medición. Lo mismo en `filas_exportacion`, y la consulta de servicios por cámara si aplica.
- [ ] **Paso 2:** verificación de resultados. Comparación completa (smart y export) contra una línea base fresca del BASE de la tarea, siguiendo el procedimiento de la docstring del script. Esperado: 72 de 72 idénticas.
- [ ] **Paso 3:** `medir` otra vez. En el reporte, tabla antes/después por grupo (sentencias y tiempo). Si el tiempo no mejora al menos un 30 % en la smart search con términos, reportarlo como DONE_WITH_CONCERNS con el diagnóstico, en vez de forzar cambios.
- [ ] **Paso 4:** commit `perf(camaras): smart search y exportación sin N+1`. Después `ready` + `integrate`.

### Task 10: Type-check del frontend

**Archivos:** `web/frontend/package.json`, los archivos `.ts`/`.vue` con errores, `scripts/agentes/calidad.py` y `tests/test_agentes_calidad.py`.

- [ ] **Paso 1:** en el worktree, `npm ci` dentro de `web/frontend` (su `node_modules` queda local al worktree e ignorado). Agregar el script `"type-check": "vue-tsc --noEmit -p tsconfig.json"`. Correrlo y anotar los errores reales. Hoy en el control hay 31, y 4 son "Cannot find module" de dependencias declaradas: probablemente `node_modules` desactualizado y no un error de código.
- [ ] **Paso 2:** corregir los errores restantes **sólo con cambios de tipos** (anotaciones, imports de tipos, `GeoJSON` vía `@types/geojson` si ya es dependencia transitiva, o `import type`). Sin cambiar lógica ni dependencias de runtime. Si un error exige un cambio de runtime, se deja con `// @ts-expect-error <motivo>` y se reporta.
- [ ] **Paso 3:** gate. Si cambian `.vue` o `.ts` bajo `web/frontend/src`, `ejecutar_gate` agrega el paso `type-check` (`npm run type-check` en `web/frontend`). Si no hay `web/frontend/node_modules`, el paso queda salteado con el motivo `sin node_modules (correr npm ci)` (Review Focus 4). Tests en `tests/test_agentes_calidad.py` para los 3 casos: sin cambios de frontend, con cambios y node_modules, y con cambios sin node_modules.
- [ ] **Paso 4:** `npm run build` en verde, porque el build no puede romperse. Commit `chore(frontend): type-check en verde y en el gate`. Después `ready` + `integrate`.

### Task 11: Cierre de las Fases 3 y 4

- [ ] **Paso 1:** suite completa una vez, más `ruff check .`, más `npm run type-check`.
- [ ] **Paso 2:** PR diario (`docs/PR/<fecha>.md`): qué se hizo, mediciones antes/después, `noqa` restantes con motivo y lo que quedó fuera y por qué. Actualizar `AGENTS.md` si corresponde (el script de type-check y el paso nuevo del gate). Commit `docs: cierre de las Fases 3 y 4`. Después `ready` + `integrate`.

## Fuera de alcance

- `except Exception` → errores tipados y `_require_auth` → `Depends`: requieren decisión del usuario porque cambian respuestas.
- Las 6 funciones con `noqa` justificado (Task 7).
- Tests unitarios del frontend (vitest): agregar un framework de tests es una decisión aparte.
- Activar `pg_stat_statements`: requiere reiniciar Postgres. Se mide con `EXPLAIN ANALYZE` y el contador de sentencias.
