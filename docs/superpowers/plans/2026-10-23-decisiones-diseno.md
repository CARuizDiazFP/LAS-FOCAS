# Nombre de archivo: 2026-10-23-decisiones-diseno.md
# Ubicación de archivo: docs/superpowers/plans/2026-10-23-decisiones-diseno.md
# Descripción: Plan de implementación de las decisiones de diseño post Fases 0-4: /reports con sesión (hotfix prod), orden explícito + smart search 6 s, Slack (sugerencias, reescritura, Fontaine ID), errores tipados y Depends

# Decisiones de diseño pendientes: plan de implementación (2026-10-23)

## Context

Al cerrar las Fases 0 a 4 del relevamiento quedaron decisiones de diseño para el usuario. Ya las tomó:

1. **Smart search a 6 s con orden explícito de las relaciones** (opción C).
2. **Código inalcanzable:**
   - Borrar el chequeo `missing_files` del informe SLA.
   - Reemplazar el "Intento 3" de Slack por un flujo útil: tolerar números mal escritos.
3. **Errores tipados** en lugar de `except Exception`, gradual y empezando por Cámaras. El manejador global mantiene el formato `{"error": "..."}`. Prioridad: no exponer el texto interno de la excepción. Alcance: SPA, FO Monitor y **también la API interna** (la API v1 no se toca).
4. **Autenticación con `Depends`** a nivel router, y reglas puntuales (sólo admin) en la firma del endpoint, de a un router.

**Hallazgo nuevo de la auditoría previa:** `app.mount("/reports", StaticFiles(...))` sirve los informes SLA y de repetitividad **sin sesión**. En dev, `GET /reports/sla/202610/InformeSLA_20261006_114649.docx` sin cookie dio `200` (1,8 MB). En prod hay 206 archivos, en `172.18.208.162:8080`, con nombres adivinables por fecha y hora. El usuario pidió **hotfix a prod apenas esté**.

El resto de la auditoría está bien: todos los demás endpoints de negocio verifican sesión (los de FO Monitor con `_auth`/`_admin`, los de clientes dentro de `_proxy_lista_clientes`). Los públicos son legítimos: health, session, login, logout, redirect `/reports/index` y el catch-all de la SPA.

## Decisiones del usuario para la búsqueda de Slack

- Si el número no coincide, el bot **avisa y pide reescribir la Cámara en el mismo hilo**. Si la reescriben bien, hace match. Si no, queda sin match (como hoy: `IngresoSinMatch`).
- El operador puede dar un **"Fontaine ID"**. El usuario aportó el ejemplo real `1228619` (captura de Slack: el operador valida con "ingreso ok, id: 1228619"). Verificado en dev y prod: es **`app.cromo_botellas.id_legacy`** de la Botella `n_id 10245762`, "Cra 25 de Mayo 302 CF" (`camara_id 33978`), justo la Cámara del mensaje.
  - Cobertura: 8.410 de 11.072 Botellas tienen `id_legacy` ("no todas las cámaras lo tienen"), y todas están vinculadas a una Cámara.
  - Hay 1 `id_legacy` duplicado.
  - El formato son 7 dígitos (11xxxxx-12xxxxx). El `n_id` de Cromo tiene 8.
- Un número en el hilo se prueba primero como Fontaine ID y, si no existe, como ID de empalme ("probar ambos").
- La captura muestra además que el técnico había escrito "Empalme 10245762: Cra 25 de Mayo 302", con el `n_id` de Cromo dentro del texto, y la búsqueda falló porque ese número entró como "número requerido" del nombre. La Task 7 lo resuelve también.

## Restricciones globales

- Trabajo en worktree propio por tarea, `ready` (gate) e `integrate` a dev por tarea; lease `refactor:web-app-main` sostenido por el controlador.
- Ninguna ruta se borra (decisión vigente). No cambian rutas, paths ni respuestas de éxito.
- Cambios de comportamiento **intencionales y aceptados**, a registrar en el PR diario:
  - El orden de rutas, empalmes, botellas y servicios pasa a ser por `id` (cambia el orden visible en ~145 Cámaras).
  - Los 500 dicen "Error interno (ref XXXX)" en lugar del texto de la excepción.
  - Sin sesión, la respuesta pasa a ser 401 aunque el body sea inválido (antes 422).
  - Los informes de `/reports` exigen sesión.
- Base de dev `127.0.0.1:5433`; **nunca 5432** salvo en el paso de despliegue autorizado.
- Ejecución con `superpowers:subagent-driven-development`, encabezados `### Task N:`, revisión por tarea y revisión final.

## Tareas

### Bloque A: seguridad de `/reports` (urgente)

### Task 1: `/reports` con sesión en dev + test de exposición.

- En `web/app/routers/informes.py`, reemplazar el mount `app.mount("/reports", StaticFiles(...))` de `web/app/main.py` por la ruta `GET /reports/{ruta:path}`, registrada **después** de `/reports/index`.
  - Exige sesión (`_require_auth`).
  - Resuelve la ruta dentro de `informes._mount_reports` con `Path.resolve()` y `is_relative_to`, para evitar path traversal: si sale del directorio, 404.
  - Devuelve `FileResponse` con `media_type` de `mimetypes.guess_type`.
  - Las URLs que arma `_report_href` no cambian.
- Regenerar `tests/fixtures/web_rutas_contrato.json`: sólo debe cambiar la entrada del mount por la ruta nueva.
- **Test de exposición** nuevo, `tests/test_web_exposicion_sin_sesion.py`. Recorre `app.routes`, y para cada ruta que no esté en la lista `PUBLICAS` (health, health/version, auth/session, auth/login, auth/logout, logout, reports/index, catch-all) hace un request sin cookie y espera 401 o 403 (nunca 2xx). Es la red de seguridad de las Tasks 9 a 16. Más tests puntuales de `/reports`: sin sesión 401; con sesión 200; `..%2F` y `../` dan 404.

### Task 2: hotfix a producción.

Sigue `docs/despliegue_produccion.md`, sección "Hotfix puntual a prod".
- Rama `fix/<agente>-hotfix-reports-sesion` desde `origin/main`. En prod el código no está partido: el cambio va en `web/app/main.py` de main (líneas ~236-238 y `reports_index_redirect` ~413).
- Imagen etiquetada `pre-hotfix-<fecha>` y `up` **desde el checkout de control**.
- Verificar con curl sin cookie (401) y con sesión (200), sobre un informe real.
- Merge del hotfix a `dev` (`git diff` contra dev: sólo lo esperado).
- **Requiere autorización explícita en el momento del push a `main`**: el modo automático lo bloquea, según la memoria.

### Bloque B: orden explícito + smart search a 6 s

### Task 3: orden explícito de relaciones + smart search a 6 s

- En `db/models/infra.py`, `order_by` explícito por `id` en:
  - `Camara.empalmes` (l.179), con `Empalme.id`;
  - `Camara.botellas` (l.190), con `Camara.id`;
  - `Empalme.servicios` (l.269), con `Servicio.id`;
  - `Empalme.rutas` (l.276), con `RutaServicio.id`;
  - `Servicio.empalmes` (l.470, deprecada), con `Empalme.id`.
- No hace falta migración, porque sólo cambia la lectura.
- Aplicar el patch del experimento de la Fase 4 (pegado en `docs/PR/2026-10-22.md`) en `core/services/camaras_consulta.py._CARGA_POR_LOTE`.
- Verificación con `scripts/linea_base_busqueda_camaras.py` contra una línea base fresca del commit anterior:
  - Comparar con las listas `rutas`/`servicios` ordenadas por id en ambos lados: idénticas, o sea que sólo cambió el orden.
  - Comprobación cámara por cámara (10.136): el orden nuevo está ordenado por id.
  - `medir`: smart con términos, unas 200 sentencias y ~6 s.
- Tests de consulta, exportación, detalle e infra en verde. Revisar los consumidores de esas relaciones fuera de Cámaras (tracking, export) para confirmar que no dependían del orden anterior.

### Bloque C: código inalcanzable y búsqueda de Slack

### Task 4: borrar la rama inalcanzable missing_files del informe SLA

borrar la rama `missing_files` de `generar_informe_sla_web` (`web/app/routers/informes.py`) y actualizar la línea de `AGENTS.md` que la menciona. Los tests de `tests/test_web_sla_generar_ramas.py` siguen en verde.

### Task 5: número que no coincide → sugerencias

(`modules/slack_baneo_notifier/camara_search.py`).
- Reemplazar `_intento_sin_numeros`, que es inalcanzable. Si el input **tiene** números y los intentos 1, 2 y 4 no encontraron nada:
  - buscar sin los números (con los mismos filtros de bot y botella);
  - si hay candidatos, lanzar `NumeroNoCoincideError(AmbiguousSearchError)` con hasta 3 nombres.
- **Nunca asigna automáticamente.**
- En `listener.py`, capturar `NumeroNoCoincideError` antes que `AmbiguousSearchError`. Registra el `IngresoSinMatch` como hoy, y el mensaje dice: "No encontré *X* con ese número. ¿Quisiste decir: • A • B? Escribí la cámara correcta en este hilo".
- El path de revalidación (`_procesar_revalidacion_ingreso`, ~l.659) la trata como ambigua: es subclase.
- Actualizar la docstring de `_buscar_camara_intento`.
- Tests:
  - `tests/test_slack_camara_search_intento.py`: casos de la tabla, con números que no coinciden, con y sin parecidas;
  - `tests/test_slack_ingreso_listener.py`: el mensaje y el `IngresoSinMatch`.

### Task 6: reescritura de la Cámara en el hilo

(`listener.py`, cadena de respuestas en hilo ~l.955-1005).
- Nuevo `_procesar_reescritura_camara`, evaluado **después** de empalme, revalidación y corrección, y sólo si:
  - hay un `IngresoSinMatch` pendiente en ese `thread_ts`;
  - el autor es una persona (`event["user"]`);
  - el texto no es un comando conocido;
  - el texto pasa la heurística de nombre: 2 o más tokens significativos o algún número. Si no la pasa, se ignora en silencio (charla del hilo).
- Llama a `buscar_camara_o_botella_cromo(texto)`:
  - si hay match, reutiliza el camino de la revalidación (`_registrar_movimiento_si_corresponde`, `caso.resuelto_via_revalidacion = True`) y responde la confirmación;
  - si no, responde "sigue sin match" y deja el caso como está.
- Sin migración: el texto corregido queda en el log `action=`.
- Tests en `tests/test_slack_ingreso_listener.py` (match, sin match, charla ignorada, sin caso pendiente).

### Task 7: identificación por Fontaine ID (`id_legacy`) y por `n_id` de Cromo.

- **Servicio** `core/services/cromo/camara_botella_busqueda.py`, función nueva `buscar_por_id_legacy(id_legacy: str, session) -> ResultadoBusqueda | None`, sobre `app.cromo_botellas.id_legacy`:
  - devuelve la Cámara vinculada (`camara_id`), con la misma forma de resultado que `buscar_camara_o_botella_cromo`;
  - si el `id_legacy` está duplicado (hay 1 caso), devuelve ambiguo y nunca elige.
  - Reutilizar, si existe, la búsqueda por `n_id` que ya usa el seguimiento de empalme.
- **Respuesta del operador en el hilo** (`listener.py`, `_procesar_seguimiento_empalme` ~l.509 y su regex `_RE_SEGUIMIENTO_EMPALME`):
  - Reconocer, además del número solo, las formas reales `id: 1228619`, `id 1228619` e `ingreso ok, id: 1228619`, sin distinguir mayúsculas.
  - Con el número extraído, probar primero el Fontaine ID (`id_legacy`) y, si no existe, el ID de empalme (comportamiento actual).
  - Si resuelve, cierra el `IngresoSinMatch` por el mismo camino que hoy y responde indicando por cuál de los dos IDs resolvió.
  - Mantener la prioridad de la cadena: la corrección con fecha pendiente va primero, como hoy.
- **Mensaje del técnico con "Empalme <n_id>"** (`camara_search.py`, preprocesamiento de `buscar_camara`): si el texto empieza con `Empalme <8 dígitos>[:-]`, resolver primero por `n_id` de Cromo. Si existe y está vinculado a una Cámara, es match directo. Si no, se quita ese prefijo y el número no cuenta como "número requerido", y la búsqueda por nombre sigue como hoy. Caso de test: la captura, "Empalme 10245762: Cra 25 de Mayo 302" → Cámara 33978.
- **Tests:**
  - servicio: id existente, inexistente, duplicado y sin cámara;
  - listener: número solo como Fontaine, como empalme y en ninguno; formato "ingreso ok, id: N"; prioridad intacta;
  - camara_search: prefijo "Empalme N" con N válido, inválido y ausente.
  - Con datos reales: `requiere_postgres_real` sobre el ejemplo 1228619 y n_id 10245762.

### Bloque D: errores tipados + `Depends`, de a un router

### Task 8: infraestructura común, sin migrar endpoints.

- `web/app/errores.py`:
  - base `ErrorDeDominio(Exception)` con `status_code` y `mensaje`;
  - subclases `NoEncontrado` (404), `DatoInvalido` (422) y `Conflicto` (409);
  - `error_interno(accion: str, exc: Exception, **contexto) -> JSONResponse`, que loguea con `logger.exception("action=%s_error ...")` (mismo texto `action=` que hoy) y responde 500 `{"error": "Error interno (ref <8 hex>)"}`, con la ref también en el log.
- Handlers en `web/app/main.py`:
  - `ErrorDeDominio` → `{"error": mensaje}` con su status;
  - `Exception` → `error_interno`.
- **`HTTPException` no se toca:** 401, 403 y 404 de FastAPI siguen igual.
- `web/app/dependencias.py`:
  - `UsuarioSesion(username, role)`;
  - `usuario_sesion(request)` y `usuario_admin(request)`, que reutilizan la lógica de `comun._require_auth`/`_require_admin`, única fuente;
  - fixture de tests `con_sesion(rol)` vía `app.dependency_overrides`.
- Lo mismo en la API interna: `api/app/errores.py` y sus handlers en `api/app/main.py` (la API ya protege con `Depends(require_api_key)` a nivel router).
- Tests de los handlers y de las dependencias.

**Patrón por router (Tasks 9 a 15):**
1. `APIRouter(dependencies=[Depends(usuario_sesion)])`, o `usuario_admin` si todo el router es admin.
2. En cada endpoint, `username, role = _require_auth(request)` pasa a ser un parámetro `usuario: UsuarioSesion = Depends(usuario_sesion)`. FastAPI cachea la dependencia por request, así que no se evalúa dos veces. Los admin puntuales usan `Depends(usuario_admin)` en la firma.
3. Cada `except Exception as exc: ...JSONResponse({"error": f"...{exc!s}"}, 500)` pasa a `return error_interno("<accion>", exc, ...)`, conservando claves extra del cuerpo si las había (`"success": False`). Donde el `try` puede atrapar un `HTTPException`, poner antes `except HTTPException: raise`. Los `except` específicos que ya devuelven 4xx con mensaje propio se conservan; los `ValueError` de validación pasan a `DatoInvalido` sólo si hoy responden 4xx.
4. Redirigir los tests que parchean `_require_*` a `dependency_overrides` o a login real.
5. Verificación:
   - test de exposición en verde, contrato de rutas sin regenerar y tests del dominio en verde;
   - `grep` sin `{exc!s}`/`str(exc)` en cuerpos de respuesta del router;
   - para Cámaras, además, `scripts/linea_base_busqueda_camaras.py comparar`: idéntico en éxito.

### Task 9: errores tipados + Depends en `web/app/routers/camaras.py` (36 `except Exception`)

Aplicar el "Patrón por router (Tasks 9 a 15)" de arriba a: `web/app/routers/camaras.py` (36 `except Exception`).

### Task 10: errores tipados + Depends en `web/app/routers/servicios.py` (31)

Aplicar el "Patrón por router (Tasks 9 a 15)" de arriba a: `web/app/routers/servicios.py` (31).

### Task 11: errores tipados + Depends en `web/app/routers/cromo.py` (20)

Aplicar el "Patrón por router (Tasks 9 a 15)" de arriba a: `web/app/routers/cromo.py` (20).

### Task 12: errores tipados + Depends en `web/app/routers/admin_datos.py` (18; casi todo admin)

Aplicar el "Patrón por router (Tasks 9 a 15)" de arriba a: `web/app/routers/admin_datos.py` (18; casi todo admin).

### Task 13: errores tipados + Depends en `web/app/routers/informes.py` + `chat.py` + `sesion.py` (21; en sesión sólo errores: sus rutas son públicas o ya validan)

Aplicar el "Patrón por router (Tasks 9 a 15)" de arriba a: `web/app/routers/informes.py` + `chat.py` + `sesion.py` (21; en sesión sólo errores: sus rutas son públicas o ya validan).

### Task 14: errores tipados + Depends en `web/fo_monitor_routes.py` (`_auth`/`_admin` → `Depends`; errores)

Aplicar el "Patrón por router (Tasks 9 a 15)" de arriba a: `web/fo_monitor_routes.py` (`_auth`/`_admin` → `Depends`; errores).

### Task 15: errores tipados + Depends en API interna: `api/app/routes/infra.py`, `servicios.py` y el resto de `api/app/routes/*.py` salvo `v1/`. Sólo errores: `Depends` ya existe

Aplicar el "Patrón por router (Tasks 9 a 15)" de arriba a: API interna: `api/app/routes/infra.py`, `servicios.py` y el resto de `api/app/routes/*.py` salvo `v1/`. Sólo errores: `Depends` ya existe.


### Task 16: cierre.

- Suite completa, ruff y type-check.
- Rebuild de dev (`docker compose ... --env-file .env.dev build` + `up -d --no-deps`, sin `start_dev.sh` mientras la base de dev tenga migraciones de otra sesión).
- Curl en dev:
  - un 500 forzado muestra la ref y no el texto interno;
  - un endpoint sin cookie da 401;
  - `/reports` con y sin sesión.
- PR diario con los cambios de comportamiento intencionales y el flujo nuevo de Slack: sugerencias por número, reescritura en el hilo, Fontaine ID (`id_legacy`) y "Empalme <n_id>".
- `AGENTS.md`: patrones nuevos (`errores.py`, `dependencias.py`, test de exposición).

## Archivos clave

- `web/app/main.py` (mount y handlers).
- `web/app/routers/*.py`, `web/fo_monitor_routes.py`.
- `web/app/comun.py` (`_require_auth`/`_require_admin`, que se reutilizan).
- `db/models/infra.py`, `core/services/camaras_consulta.py`.
- `modules/slack_baneo_notifier/camara_search.py`, `listener.py`.
- `api/app/main.py`, `api/app/routes/*.py`.
- Nuevos: `web/app/errores.py`, `web/app/dependencias.py`, `api/app/errores.py`, `tests/test_web_exposicion_sin_sesion.py`.

## Verificación end to end

1. Test de exposición: ninguna ruta no pública responde 2xx sin sesión, incluido `/reports`.
2. `tests/test_web_rutas_contrato.py`: sólo cambia la entrada de `/reports`, en la Task 1.
3. Línea base de Cámaras: éxito idéntico, salvo el orden por id de la Task 3, verificado normalizado.
4. Suite completa en verde (hoy 3.567 passed).
5. En dev reconstruido:
   - `curl` sin cookie a una ruta de negocio da 401;
   - `/reports/...` sin cookie da 401, y con sesión 200;
   - un 500 provocado devuelve `{"error": "Error interno (ref ...)"}` y la ref aparece en `Logs/web.log`.
6. Prod (Task 2): `/reports/...` sin cookie da 401 y con sesión 200; el resto de prod sin cambios.
