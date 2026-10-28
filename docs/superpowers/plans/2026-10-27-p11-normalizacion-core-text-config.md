# P11 — Normalización a `core/text/` + configuración de rutas — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** que `core/` deje de importar del worker de Slack (`modules/slack_baneo_notifier/`) moviendo la normalización de nombres, el parseo de mensajes y la búsqueda en cascada a `core/`, sin cambiar un solo byte de salida; y unificar el default de `UPLOADS_DIR`/`REPORTS_DIR`/`TEMPLATES_DIR`.

**Architecture:** `camara_search.py` (933 líneas) mezcla tres capas que se separan: (1) normalización pura → `core/text/normalizacion.py`; (2) parseo del mensaje del Workflow de Slack → `core/text/mensaje_ingreso.py`; (3) cascada de búsqueda con DB → `core/services/camara_busqueda_nombre.py`. Los módulos de `modules/slack_baneo_notifier/` quedan como *shims* que re-exportan (incluidos los alias privados `_normalizar`, etc.), así listener, scripts y tests que importan de ahí no cambian. Un golden test sobre ~21 k nombres reales de `focas_dev` se genera ANTES del movimiento y debe seguir verde después.

**Tech Stack:** Python 3.13 (`.venv`), SQLAlchemy sync, pytest con `LLM_PROVIDER=heuristic`, PostgreSQL `focas_dev` (sólo `SELECT`).

**Spec:** `~/prompts-auditoria-2026-10-24/P11_normalizacion_config.md` (Partes A y B; la Parte C es sólo análisis y se entrega aparte).

## Global Constraints

- La lógica de matching y sus umbrales **se mueve, no se cambia** (regex, tablas `_ABREVIATURAS`/`_SINONIMOS`, `_UMBRAL_CORROBORACION = 0.8`, `_TOKENS_GENERICOS`, orden de la cascada).
- Golden test verde antes y después: salidas byte a byte iguales.
- Invariante final: `grep -rn "modules.slack_baneo_notifier" core/` → 0 (incluidos comentarios/docstrings que citan la ruta vieja: se actualizan a la nueva).
- No tocar `web/app/routers/` (P12). No tocar `core/services/cromo/ingesta.py` (P21).
- Archivos nuevos con encabezado de 3 líneas (Nombre de archivo / Ubicación / Descripción).
- DB: sólo `SELECT` contra `focas_dev`; prod no se lee ni se toca.
- Unificar reimplementaciones de "sin acentos + minúsculas" **sólo** si el golden da idéntico; si no, se dejan y se reporta.
- Suites de aceptación: `tests/test_slack*.py tests/test_cromo_* tests/test_camara* tests/test_ingreso* tests/test_fo_monitor*` en verde.

## Decisiones del usuario (2026-10-27/28)

| # | Decisión | Resuelto |
|---|---|---|
| D1+D4 | Corpus del golden | Nombres reales de `focas_dev` + mensajes sintéticos del Workflow + **483 textos reales de prod** (`ingresos_sin_match.texto_mensaje`/`texto_original` + `ingresos_correcciones.comando_crudo`, SELECT read-only autorizado por el usuario). Los IDs de Slack `<@U…>` van reemplazados por IDs ficticios determinísticos `U0FAKE0000…`. Fixture **commiteada**. El export anonimizado ya está en `/tmp/claude-1001/-home-support-focal-01-LAS-FOCAS/2ea4ed76-7491-4f81-a47a-806953887021/scratchpad/corpus/prod_mensajes_anon.json` (lista JSON de strings); el ejecutor NO vuelve a leer prod |
| D2 | Default único de rutas | `<repo>/data/uploads`, `<repo>/data/reports`, `<repo>/Templates` (en contenedor = `/app/data/...`, `/app/Templates`). Cambia sólo `core/sla` fuera de Docker (`<repo>/tmp` → `<repo>/data/uploads`, `<repo>/Reports` → `<repo>/data/reports`) |
| D3 | `correccion_ingreso.py` y `slack_user_resolver.py` | **Moverlos** a `core/` con shim (sin cambios de firma) |
| Ejecución | — | Subagent-driven |

## Review Focus

- Un import que hoy pasa por el shim pero cuyo *patch* en tests apunta al módulo viejo (`camara_search._buscar_ilike_lista`, `camara_search.func`): parchear el shim no afecta a la cascada movida → el test pasa “en verde” sin probar nada o pega a la DB. Task 3 reapunta los 20 patches y agrega un test que falla si el shim redefine en vez de re-exportar.
- `_normalizar` importa `unidecode` de forma perezosa con *fallback*: si el módulo nuevo lo importa arriba, un entorno sin `unidecode` cambia de “sin transliterar” a `ImportError`. Se conserva el import perezoso (golden lo cubre sólo con `unidecode` instalado; Task 2 agrega el caso sin él).
- Identidad de clases de error: `except AmbiguousSearchError` en el listener (importado del shim) debe capturar la que lanza la cascada en `core`. Task 3: test `shim.AmbiguousSearchError is core.AmbiguousSearchError`.
- `core/mcp/registry.py` lee `UPLOADS_DIR`/`REPORTS_DIR` en cada llamada (los tests hacen `monkeypatch.setenv` en caliente): centralizar como constante de import rompería eso. Task 6 expone funciones que leen el env al llamarse.
- Código de prod que corre en un contenedor sin `/app/data` montado (`api`): el default nuevo no debe crear directorios al importar. Task 6: las funciones no hacen `mkdir`.

---

### Task 1: Corpus real + golden snapshot (antes de mover nada)

**Files:**
- Create: `scripts/golden_normalizacion.py`
- Create: `tests/fixtures/normalizacion/corpus.json.gz`, `tests/fixtures/normalizacion/golden.json`
- Create: `tests/test_normalizacion_golden.py`

**Interfaces:**
- Produces: `FUNCIONES_GOLDEN: dict[str, Callable[[str], object]]` en `tests/test_normalizacion_golden.py`, con las claves fijas `limpiar_puntuacion, normalizar, expandir_abreviaturas, aplicar_sinonimos, expandir_abreviaturas_y_sinonimos, normalizar_candidato, limpiar_ruido_operativo, preparar_nombre_busqueda, quitar_botella_uno, detectar_multi_bot, separar_prefijo_empalme, pocos_tokens_significativos, re_bot_sufijo_search, extraer_nombre_camara, extraer_tipo_movimiento, extraer_slack_user_id_autorizacion, quitar_formato_slack`. Hoy apuntan a `modules.slack_baneo_notifier.*`; las Tasks 2-4 sólo cambian el import.

- [ ] **Step 1:** `scripts/golden_normalizacion.py exportar` hace `SELECT DISTINCT` de `app.camaras.nombre`, `app.cromo_botellas.nombre`, `app.camara_alias.alias_nombre` (vía `docker exec lasfocasdev-postgres psql`, sin imprimir credenciales), agrega por cada nombre real 3 mensajes sintéticos (`"*Nombre: Nodo/Camara/botella*\n{n}\n*Ingreso o Egreso*\nIngreso"`, `"Cámara: {n}"`, y el de salto accidental `"*Nombre: Nodo/Camara/botella*\nme:\n{n}\n*Otro*"`), suma a `mensajes` (y a `nombres`, para las funciones de nombre) los 483 textos reales anonimizados de `prod_mensajes_anon.json` (ver D1+D4; el script toma la ruta por `--prod-mensajes` y no consulta prod), y casos frontera fijos (vacío, sólo espacios, `"Bot 30 de Septiembre"`, `"Empalme 10245762: Cra 25 de Mayo 302"`, `"*negrita*"`, emojis, `º`, `°`, `ß`). Ordena y guarda `corpus.json.gz` = `{"nombres": [...], "mensajes": [...]}`.
- [ ] **Step 2:** `scripts/golden_normalizacion.py snapshot` aplica cada función de `FUNCIONES_GOLDEN` (las de nombre sobre `nombres`, las `extraer_*` sobre `mensajes`), serializa cada salida con `repr()` y guarda en `golden.json` `{funcion: [sha256 de cada bloque de 512 entradas]}` + total por función.
- [ ] **Step 3:** `test_golden_normalizacion[<funcion>]` (parametrizado) recalcula y compara hash por bloque; si falla, el mensaje dice el bloque y las primeras 3 entradas con su salida actual.
- [ ] **Step 4:** Además, en el scratchpad (NO se commitea): `cascada_antes.json` = resultado de `buscar_camara(n, session)` sobre una muestra fija (semilla 11) de 2 000 nombres + variantes (`bot2` pegado, sin acentos, con `" - CUADRILLA X"`, sin número) → `(camara.id | None, nombre_norm)` o `(tipo de excepción, cantidad, candidatos)`. Contra `focas_dev`, sólo lectura.
- [ ] **Step 5:** Run `LLM_PROVIDER=heuristic pytest tests/test_normalizacion_golden.py -q` → PASS (snapshot = estado actual).
- [ ] **Step 6:** Commit `test(normalizacion): golden de normalización sobre corpus real de focas_dev (P11)`.

### Task 2: `core/text/normalizacion.py` y `core/text/mensaje_ingreso.py`

**Files:**
- Create: `core/text/__init__.py`, `core/text/normalizacion.py`, `core/text/mensaje_ingreso.py`
- Modify: `modules/slack_baneo_notifier/camara_search.py` (borra las definiciones movidas, re-exporta), `modules/slack_baneo_notifier/cable_info.py` (`quitar_formato_slack` re-exportada)
- Modify: `core/services/localidades_catalogo.py`, `camara_sugerencias.py`, `camara_hierarchy_service.py`, `nodos_catalogo.py`, `cromo/direccion_comparacion.py`, `fo_monitor/alcance.py` (sólo sus imports de normalización)
- Test: `tests/test_normalizacion_golden.py` (reapuntar imports), `tests/test_core_text.py`

**Interfaces:**
- Produces `core.text.normalizacion`: `ABREVIATURAS`, `SINONIMOS`, `RE_BOT_SUFIJO`, `RE_BOT_PEGADO`, `RE_NUMERO_BOTELLA`, `limpiar_puntuacion(str)->str`, `normalizar(str)->str`, `expandir_abreviaturas(str)->str`, `aplicar_sinonimos(str)->str`, `expandir_abreviaturas_y_sinonimos(str)->str`, `normalizar_candidato(str)->str`, `limpiar_ruido_operativo(str)->str`, `preparar_nombre_busqueda(str)->str`, `quitar_botella_uno(str)->str`, `detectar_multi_bot(str)->list[str]|None`, `separar_prefijo_empalme(str)->tuple[int|None,str]`, `tokens_significativos(str)->list[str]`, `pocos_tokens_significativos(str)->bool`.
- Produces `core.text.mensaje_ingreso`: `extraer_nombre_camara(str)->str`, `extraer_tipo_movimiento(str)->str|None`, `extraer_slack_user_id_autorizacion(str)->str|None`, `quitar_formato_slack(str)->str`.
- El shim conserva cada nombre viejo, privado incluido: `_normalizar = normalizar`, `_limpiar_puntuacion = limpiar_puntuacion`, `_expandir_abreviaturas`, `_aplicar_sinonimos`, `_pocos_tokens_significativos`, `_tokens_significativos`, `_RE_BOT_PEGADO`, `_ABREVIATURAS`, `_SINONIMOS`, y `__all__` sin cambios.

- [ ] **Step 1:** `tests/test_core_text.py`: `test_shim_reexporta_mismos_objetos` (para cada nombre del `__all__` viejo que pertenece a esta capa, `getattr(camara_search, n) is getattr(core.text.normalizacion|mensaje_ingreso, publico)`), `test_normalizar_sin_unidecode` (con `monkeypatch.setitem(sys.modules, "unidecode", None)`: `normalizar("Cámara  X") == "cámara x"`). Corre → FAIL (no existe `core.text`).
- [ ] **Step 2:** Mover el código tal cual (comentarios incluidos, actualizando las rutas citadas). Import de `unidecode` sigue perezoso dentro de `normalizar`. `limpiar_puntuacion`… quedan con los mismos cuerpos.
- [ ] **Step 3:** Reapuntar los imports de los 6 módulos de `core/` listados a `core.text.normalizacion` con nombres públicos; reapuntar `FUNCIONES_GOLDEN` a `core.text.*`.
- [ ] **Step 4:** Run `LLM_PROVIDER=heuristic pytest tests/test_normalizacion_golden.py tests/test_core_text.py tests/test_slack*.py tests/test_camara* -q` → PASS, golden idéntico.
- [ ] **Step 5:** Commit `refactor(core): normalización de nombres y parseo del Workflow a core/text (P11)`.

### Task 3: Cascada de búsqueda a `core/services/camara_busqueda_nombre.py`

**Files:**
- Create: `core/services/camara_busqueda_nombre.py`
- Modify: `modules/slack_baneo_notifier/camara_search.py` (queda sólo shim), `core/services/cromo/camara_botella_busqueda.py`, `camara_ingest_service.py`, `infra_service.py`, `ingreso_reproceso_service.py`, `ingreso_correccion_service.py` (imports de cascada/errores)
- Modify tests: `tests/test_slack_ingreso_listener.py`, `tests/test_cromo_camara_botella_busqueda.py` (patch targets)
- Test: `tests/test_core_text.py`

**Interfaces:**
- Consumes: `core.text.normalizacion` (Task 2).
- Produces `core.services.camara_busqueda_nombre`: `AmbiguousSearchError`, `NumeroNoCoincideError`, `buscar_camara(nombre_raw, session, *, desempatar=True) -> tuple[Camara|None, str]`, `botella_cromo_por_n_id`, `resto_corrobora_botella`, `camara_por_prefijo_empalme`, `recorte_pierde_la_botella`, `tiene_gemela_critica`, y los filtros con nombre público `filtrar_por_numeros`, `filtrar_bots_secundarios`, `filtrar_numero_de_botella`. Privados que los tests parchean, sin renombrar: `_buscar_ilike_lista`, `_buscar_tokens_lista`, `func` (import de módulo), `_buscar_ilike`, `_buscar_tokens`, `_mejor_candidato`, `_buscar_camara_intento`.

- [ ] **Step 1:** En `tests/test_core_text.py`: `test_errores_son_la_misma_clase` (`camara_search.AmbiguousSearchError is camara_busqueda_nombre.AmbiguousSearchError`, ídem `NumeroNoCoincideError`) y `test_shim_no_define_funciones` (ningún `inspect.isfunction`/`isclass` del shim tiene `__module__ == "modules.slack_baneo_notifier.camara_search"`). FAIL.
- [ ] **Step 2:** Mover la cascada sin cambios; renombrar los 3 filtros a públicos (shim: `_filtrar_* = filtrar_*`).
- [ ] **Step 3:** Reemplazar los 20 targets `"modules.slack_baneo_notifier.camara_search.{_buscar_ilike_lista,_buscar_tokens_lista,func}"` por `"core.services.camara_busqueda_nombre.…"`.
- [ ] **Step 4:** Reapuntar imports de los 5 servicios de `core/` listados.
- [ ] **Step 5:** Run suites de aceptación completas (Global Constraints) + golden → PASS.
- [ ] **Step 6:** Rerun del script del Task 1 Step 4 → `cascada_despues.json`; `diff` con `cascada_antes.json` → idéntico. Si difiere: detener y revisar, nunca ajustar el snapshot.
- [ ] **Step 7:** Commit `refactor(core): búsqueda de cámara por nombre a core/services/camara_busqueda_nombre (P11)`.

### Task 4: Comandos de corrección y resolución de usuario de Slack

**Files:**
- Create: `core/services/ingreso_correccion_comandos.py` (contenido de `correccion_ingreso.py`), `core/services/slack_usuarios.py` (contenido de `slack_user_resolver.py`)
- Modify: `modules/slack_baneo_notifier/correccion_ingreso.py`, `slack_user_resolver.py` → shims; `core/services/ingreso_correccion_service.py`, `ingreso_reproceso_service.py` → imports nuevos
- Test: `tests/test_core_text.py`

**Interfaces:**
- Consumes: `core.text.mensaje_ingreso.quitar_formato_slack`, `core.text.normalizacion.limpiar_ruido_operativo`.
- Produces: mismos nombres públicos que los módulos originales (`extraer_comando_forzar_ingreso`, `construir_respuesta_*`, `ComandoForzarIngreso`, …, `resolver_nombre_tecnico(client, slack_user_id) -> str | None`). El logger de `slack_usuarios` conserva el nombre `"slack_baneo_worker.slack_user_resolver"`.

- [ ] **Step 1:** Tests de identidad shim ↔ core para ambos módulos (mismo patrón que Task 3 Step 1). FAIL.
- [ ] **Step 2:** Mover sin cambios de cuerpo; shims re-exportan `__all__` (y `_normalizar_texto`, `parsear_momento_ar`, `extraer_momento_solo` si están referenciados desde fuera: verificar con grep).
- [ ] **Step 3:** Run `LLM_PROVIDER=heuristic pytest tests/test_slack_correccion_ingreso.py tests/test_slack_user_resolver.py tests/test_ingreso* tests/test_core_text.py -q` → PASS.
- [ ] **Step 4:** Commit `refactor(core): comandos de corrección de ingreso y resolución de usuario Slack a core/services (P11)`.

### Task 5: Invariante y reimplementaciones

**Files:**
- Test: `tests/test_core_text.py`
- Modify (sólo si el golden da idéntico): `core/sla_consumo/clasificador.py`, `core/parsers/reclamos_excel.py`, `modules/informes_repetitividad/processor.py`, `core/services/cromo/pelo_servicios.py`, `core/services/cromo/servicio_posicion_vigente.py`

- [ ] **Step 1:** `test_core_no_importa_el_worker_de_slack`: recorre `core/**/*.py` y falla si algún archivo contiene `modules.slack_baneo_notifier` o `modules/slack_baneo_notifier`. Corre → si falla, actualizar las citas de docstrings/comentarios a la ruta nueva → PASS.
- [ ] **Step 2:** En el scratchpad, comparar sobre `corpus.json.gz` cada reimplementación contra su equivalente con `core.text.normalizacion.normalizar` (ajustando sólo el caso: `.upper()` para las de Cromo; `_clean_key` de repetitividad además quita espacios/`_`, así que no es equivalente por diseño). Registrar cantidad de diferencias y 5 ejemplos por función.
- [ ] **Step 3:** Unificar sólo las de 0 diferencias (importando de `core.text`); dejar las demás con un comentario de una línea que cite el motivo medido. Las copias de `pelo_servicios`/`servicio_posicion_vigente` respetan su comentario original si da diferencia.
- [ ] **Step 4:** Run suites de aceptación + `tests/test_sla*` `tests/test_repetitividad*` `tests/test_reclamos*` → PASS. Commit `refactor(core): invariante sin imports del worker de Slack + reimplementaciones medidas (P11)`.

### Task 6: Rutas de datos centralizadas (Parte B)

**Files:**
- Modify: `core/config.py`, `core/sla/config.py`, `modules/informes_repetitividad/config.py`, `modules/informes_sla/config.py`, `core/mcp/registry.py`
- Test: `tests/test_core_config_rutas.py`

**Interfaces:**
- Produces en `core/config.py`: `PROJECT_ROOT: Path` (`parents[1]` de `core/config.py`), `uploads_dir() -> Path` (env `UPLOADS_DIR`, default `PROJECT_ROOT / "data" / "uploads"`), `reports_dir() -> Path` (env `REPORTS_DIR`, default `PROJECT_ROOT / "data" / "reports"`), `templates_dir() -> Path` (env `TEMPLATES_DIR`, default `PROJECT_ROOT / "Templates"`), `MESES_ES: tuple[str, ...]`. Ninguna hace `mkdir`.

- [ ] **Step 1:** Tests: `test_defaults_relativos_al_repo` (sin env → los tres defaults de arriba), `test_env_manda` (con `monkeypatch.setenv` → el valor del env, leído en la llamada), `test_configs_de_informes_coinciden` (`core.sla.config.UPLOADS_DIR == informes_repetitividad.config.UPLOADS_DIR == informes_sla.config.UPLOADS_DIR`, ídem `REPORTS_DIR`, `TEMPLATES_DIR`, en un subproceso sin esas variables), `test_no_crea_directorios`. FAIL.
- [ ] **Step 2:** Implementar en `core/config.py`; los tres `config.py` toman sus constantes de import con `uploads_dir()`/`reports_dir()`/`templates_dir()` y `MESES_ES` (como `list(MESES_ES)` donde hoy es lista). `core/mcp/registry.py` reemplaza sus 4 `os.getenv("…", "/app/data/…")` por las funciones.
- [ ] **Step 3:** Verificar en contenedor sin rebuild: `docker exec lasfocasdev-web python -c` con el árbol del worktree montado en `/tmp` (PYTHONPATH) → imprime `/app/data/uploads /app/data/reports /app/Templates`, igual que hoy.
- [ ] **Step 4:** Run `LLM_PROVIDER=heuristic pytest tests/test_core_config_rutas.py tests/test_sla* tests/test_reports* tests/test_mcp* tests/test_repetitividad* -q` → PASS. Commit `refactor(config): default único de UPLOADS_DIR/REPORTS_DIR/TEMPLATES_DIR en core/config (P11)`.

### Task 7: Documentación y entrega

**Files:**
- Modify: `config/repository-map.json` (+ regenerar `docs/REPOSITORY_MAP.md`), `docs/bot.md` / `docs/infra.md` donde citen `camara_search` como dueño de la normalización, `scripts/arnes_busqueda_camaras.py` (docstring), `docs/PR/2026-10-27.md` (o la fecha del día)
- Create: sección del reporte con el mapa “de dónde → a dónde”, el resultado del golden y de la cascada, las reimplementaciones medidas y la Parte C (análisis SLA)

- [ ] **Step 1:** Actualizar mapa y docs; `python scripts/audit_agentic_environment.py` → OK.
- [ ] **Step 2:** Suite completa `LLM_PROVIDER=heuristic pytest -q -x --ignore=tests/*_real_db.py` → 0 fallas nuevas (comparar contra `dev` si hay fallas preexistentes). Disco ≥ 3 GB antes.
- [ ] **Step 3:** PR diario (`generar-pr-diario`), commit y push a la rama efímera. Integración sólo con `/cierre-sesion`.

## Notas para el ejecutor

- `NLP_INTENT_URL` (parte B del prompt): el hallazgo de `bot_telegram/handlers/intent.py` ya no aplica (P19 retiró el bot); `web/app/main.py:43` y `web/app/routers/chat.py:50` ya leen el env con el mismo default. Se reporta, no se toca (routers = P12/P17).
- `web/app/comun.py:36-42` calcula `UPLOADS_DIR`/`REPORTS_DIR` por ruta de archivo (= `/app/data/...` en contenedor). Fuera de alcance de este plan; se reporta como candidato para P12.
- `modules/informes_sla` quedó sin consumidores de producción tras P19 (sólo sus 2 tests): su retiro lo decide el usuario con el análisis de la Parte C.
