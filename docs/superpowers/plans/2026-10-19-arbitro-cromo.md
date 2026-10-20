# Nombre de archivo: 2026-10-19-arbitro-cromo.md
# Ubicación de archivo: docs/superpowers/plans/2026-10-19-arbitro-cromo.md
# Descripción: Plan de implementación del árbitro de Cromo (propuestas con confianza, modo sombra, evidencia del Registrador)

# Árbitro de Cromo — Plan de implementación

> **Para agentes:** SUB-SKILL REQUERIDA: usar superpowers:subagent-driven-development (recomendado) o superpowers:executing-plans para implementar tarea por tarea. Los pasos usan checkbox (`- [ ]`).

**Objetivo:** un árbitro que cruza hallazgos de los mecanismos existentes y produce propuestas puntuadas por confianza. En modo sombra sólo propone. En AUTO aplica, dentro de un umbral y un presupuesto, acciones baratas de revertir. Se alimenta de la ingesta, de las consultas en vivo que ya hace el Registrador o el web, y de las acciones del viewer.

**Arquitectura:** paquete `core/services/cromo/arbitro/`, con funciones puras de puntaje y reglas que leen sólo la base y nunca llaman a Cromo.
- Las propuestas persisten en `app.cromo_propuesta`. La configuración por regla va en `app.cromo_regla_correccion`. La evidencia de caminos en vivo va en `app.cromo_evidencia_camino`.
- Los disparadores encolan un job `arbitro_evaluar` en la cola Redis existente (`admin:recompute:jobs`). Lo consume `botellas_recalculo_worker`.
- El viewer de Inconsistencias suma las pestañas "Propuestas" y "Reglas".

**Stack:** Python 3 async, SQLAlchemy 2 (AsyncSession + `run_sync`), PostgreSQL, Alembic, Redis, FastAPI (web/app/main.py), Vue 3 + TypeScript + Vite, pytest.

**Spec:** `docs/superpowers/specs/2026-10-19-arbitro-cromo-design.md`

## Restricciones globales

- **Archivos:**
  - Todo archivo nuevo empieza con el encabezado de 3 líneas del repo: `# Nombre de archivo:`, `# Ubicación de archivo:`, `# Descripción:` (`//` en TS, `<!-- -->` en Vue).
  - Identificadores, comentarios, logs y textos de UI van en español.
- **Esquema:**
  - Vocabularios cerrados como `Text` + `CHECK`, nunca ENUM de Postgres.
  - Sin FK dura hacia objetos de Cromo (`*_n_id`). Sólo hay FK hacia maestros propios: `app.servicios.id`, `app.cromo_regla_correccion.codigo`, `app.cromo_propuesta.id`.
- **Lecturas:**
  - El árbitro **nunca** llama a Cromo; sólo lee la base.
  - Los matches de servicio se leen **sólo** desde `app.v_cromo_servicio_match_vigente`. El guard `tests/test_cromo_cuarentena_lectores.py` tiene que seguir en verde.
- **SQL:**
  - En `text()` con psycopg3, un bind con cast lleva espacio: `:ids ::bigint[]`, nunca `:ids::bigint[]`.
  - Los JSONB nuevos van con `JSONB(none_as_null=True)`.
- **Transacciones:**
  - `motor.evaluar`, `acciones.aplicar`/`revertir` y las operaciones manuales **no hacen commit**; lo hace el llamador (worker o endpoint).
  - Excepción: `registrar_evidencia` usa un savepoint propio más commit, como `auditoria_huerfanos.auditar_sin_romper`.
- **Encolado:** best-effort, nunca lanza, siempre **después** del commit.
- **Logs:** formato `action=arbitro_cromo evento=<x> clave=valor`.
- **Valores fijos:**
  - Usuario técnico: `USUARIO_ARBITRO = "arbitro-cromo"`.
  - Umbral default 90, presupuesto default 50 y TTL de evidencia de 30 días.
  - Para sugerir AUTO: precisión ≥ 0.95 con N ≥ 30.
- **Tests:**
  - Correr con `LLM_PROVIDER=heuristic` y el venv activo (`source .venv/bin/activate`).
  - Los tests contra Postgres real usan `requiere_postgres_real` (`tests/soporte_postgres_real.py`) e ids sintéticos `999_920_xxx`.
- **Entorno:**
  - Worktree `/home/support-focal-01/LAS-FOCAS-agentes/claude-cromo-arbitro-cromo`, rama `feat/claude-cromo-arbitro-cromo`. Sólo dev; nada en prod.
  - Docker compose siempre con `--env-file`.

## Foco de revisión

1. **Ráfaga de jobs:** el mismo servicio consultado 10 veces da una sola propuesta abierta (índice único parcial más upsert). Test en Task 11.
2. **Evidencia que cambia entre consultas:** hoy ODF A, mañana ODF B. La evidencia se actualiza por `(servicio_id, pelo_n_id)` y la propuesta abierta toma los parámetros y el hash nuevos. Test en Task 8 y Task 11.
3. **Operador que asocia a mano después de una propuesta AUTO:** una PROPUESTA pasa a OBSOLETA. Revertir una EN_OBSERVACION borra sólo la fila AUTO propia, nunca la MANUAL. Test en Task 10 y Task 11.
4. **Botella vacía que gana cables entre que se propone y se aplica:** `aplicar` revalida y lanza `AccionNoAplicable`, y la propuesta sigue PROPUESTA. Test en Task 10.
5. **Evidencia vieja (más de 30 días):** no cuenta como camino en vivo. Test en Task 8.

---

## Task 1: Consolidar protege el nombre corregido del destino

**Archivos:**
- Modificar: `core/services/cromo/consolidacion_service.py:211-213`
- Test: `tests/test_cromo_consolidacion_service.py`

**Interfaces:** ninguna nueva.

- [ ] **Paso 1: test que falla.** En `tests/test_cromo_consolidacion_service.py`, junto a `test_consolidar_actualiza_nombre_destino_si_viene_no_vacio` (línea 203), con el mismo `_build_session`:
  - `test_consolidar_con_nombre_marca_nombre_editado_manual`: después de `consolidar_grupo_botellas(..., nombre_destino="  Nombre Nuevo  ")` se cumple `destino.nombre == "Nombre Nuevo"` y `destino.nombre_editado_manual is True`.
  - `test_consolidar_sin_nombre_no_marca_nombre_editado_manual`: con `nombre_destino="   "`, `destino.nombre_editado_manual` sigue `False`.
- [ ] **Paso 2:** `pytest tests/test_cromo_consolidacion_service.py -q -k nombre_editado`. Esperado: FAIL en el primero.
- [ ] **Paso 3:** dentro del `if nombre_limpio:`, agregar `destino.nombre_editado_manual = True`, igual que `separacion_service.py:101-102`.
- [ ] **Paso 4:** `pytest tests/test_cromo_consolidacion_service.py -q`. Esperado: PASS completo.
- [ ] **Paso 5:** commit `fix(cromo): consolidar marca nombre_editado_manual para que la ingesta no pise el nombre corregido`.

## Task 2: Migración y modelos del árbitro

**Archivos:**
- Crear: `db/alembic/versions/20261020_01_cromo_arbitro.py` (`revision="20261020_01"`, `down_revision="20261017_04"`)
- Modificar: `db/models/cromo.py`: modelos nuevos `CromoReglaCorreccion`, `CromoPropuesta`, `CromoEvidenciaCamino`, y columnas `origen` y `propuesta_id` en `CromoServicioOdfOverride` (`:477`)
- Test: `tests/test_cromo_arbitro_migracion_real_db.py`

**Interfaces que produce:**
- **Tabla `app.cromo_regla_correccion`:**
  - `codigo text PK`;
  - `modo text NOT NULL DEFAULT 'SOMBRA'`, CHECK `IN ('APAGADA','SOMBRA','AUTO')`;
  - `umbral smallint NOT NULL DEFAULT 90`, CHECK `0..100`;
  - `presupuesto_por_corrida integer NOT NULL DEFAULT 50`, CHECK `>= 0`;
  - `descripcion text`, `actualizado_por varchar(128)`, `actualizado_en timestamptz DEFAULT now()`.
  - Seed idempotente (`ON CONFLICT DO NOTHING`) con `ODF_POR_CAMINO`, `CONTRADICCION_SERVICIO`, `GEMELO_VACIO`, `GEMELO_OPERATIVO` y `ODF_GEMELA_ISLA`, en modo SOMBRA y umbral 90, cada una con su descripción en español.
- **Tabla `app.cromo_propuesta`:**
  - `id bigserial PK`;
  - `regla text NOT NULL`, FK a `cromo_regla_correccion.codigo`;
  - `objeto_tipo text NOT NULL`, CHECK `IN ('SERVICIO','BOTELLA','ODF','CABLE')`, y `objeto_id bigint NOT NULL`;
  - `accion text NOT NULL`, CHECK `IN ('ASOCIAR_ODF','FUSIONAR_GEMELO','INFORMAR')`;
  - `parametros jsonb NOT NULL DEFAULT '{}'`;
  - `confianza smallint NOT NULL`, CHECK `0..100`;
  - `senales jsonb NOT NULL DEFAULT '[]'`;
  - `evidencia_hash varchar(64) NOT NULL`;
  - `estado text NOT NULL`, CHECK `IN ('PROPUESTA','EN_OBSERVACION','APLICADA','RECHAZADA','REVERTIDA','OBSOLETA')`;
  - `modo_al_evaluar text NOT NULL`, CHECK como `modo`;
  - `disparo text NOT NULL`, CHECK `IN ('INGESTA','REGISTRADOR','VIEWER','NORMALIZADOR')`;
  - `reversion jsonb`, `nota text`;
  - `creada_en`, `actualizada_en timestamptz NOT NULL DEFAULT now()`;
  - `decidida_por varchar(128)`, `decidida_en timestamptz`, `aplicada_en timestamptz`.
  - Índice único parcial `ux_cromo_propuesta_abierta (regla, objeto_tipo, objeto_id) WHERE estado IN ('PROPUESTA','EN_OBSERVACION')`, más un índice `(estado, regla)`.
- **Tabla `app.cromo_evidencia_camino`:**
  - `servicio_id integer NOT NULL`, FK a `app.servicios.id` con `ON DELETE CASCADE`;
  - `pelo_n_id bigint NOT NULL`; PK `(servicio_id, pelo_n_id)`;
  - `completo boolean NOT NULL`;
  - `extremos jsonb NOT NULL DEFAULT '[]'` (lista de `asdict(ExtremoCamino)`);
  - `pelos_camino bigint[]`;
  - `fuente text NOT NULL`, CHECK `IN ('SLACK','WEB','AUDITORIA_GLOBAL')`;
  - `generado_at timestamptz NOT NULL DEFAULT now()`.
- **Tabla `app.cromo_servicio_odf_override`:**
  - Columna `origen text NOT NULL DEFAULT 'MANUAL'`, CHECK `IN ('MANUAL','AUTO')`.
  - Columna `propuesta_id bigint NULL`, FK a `cromo_propuesta.id` con `ON DELETE SET NULL`.
  - El CHECK de `categoria_causa` se recrea agregando `'EVIDENCIA_CAMINO'`. Copiar la lista vigente de `20260908_01_cromo_servicio_odf_override.py:102` o de la migración posterior que lo haya cambiado; verificar con `grep -rn categoria_causa db/alembic/versions`.
- **Tabla `app.cromo_arbitro_evaluacion`** (pedido del usuario el 2026-10-19: el análisis retroactivo se lanza y se sigue desde la UI):
  - `id bigserial PK`;
  - `disparo text NOT NULL`, mismo CHECK que en `cromo_propuesta`;
  - `alcance jsonb NOT NULL`;
  - `reglas text[]` (NULL = todas las activas);
  - `estado text NOT NULL`, CHECK `IN ('EN_COLA','EN_CURSO','OK','OMITIDA','FALLIDA')`;
  - `resumen jsonb` (un `ResumenEvaluacion.a_dict()`), `error text`;
  - `solicitada_por varchar(128)`;
  - `encolada_en timestamptz NOT NULL DEFAULT now()`, `iniciada_en timestamptz`, `terminada_en timestamptz`.
  - Índice `(encolada_en DESC)`.
  - Test adicional en el Paso 1: `test_evaluacion_checks`, donde `estado='X'` da `IntegrityError`.
- **Desvío deliberado de la spec:** no hay columna `truncado`. Un camino truncado se registra con `completo=false` (Task 6) y la regla sólo cuenta los `completo` como camino en vivo.
- `downgrade()` revierte todo en orden inverso. El CHECK original se restaura después de borrar las filas `EVIDENCIA_CAMINO`, porque son datos del árbitro.

- [ ] **Paso 1: tests contra DB real que fallan.** Con la fixture `entorno` de `tests/test_cromo_inconsistencias_real_db.py:140-160`:
  - `test_regla_seed_en_sombra`: las 5 reglas existen, con `modo='SOMBRA'` y `umbral=90`.
  - `test_propuesta_abierta_unica`: un segundo INSERT abierto con la misma `(regla, objeto_tipo, objeto_id)` da `IntegrityError`. Si el primero está `RECHAZADA`, el segundo entra.
  - `test_checks_propuesta`: `estado='X'`, `accion='X'` y `confianza=101` dan `IntegrityError`.
  - `test_override_origen_default_manual_y_categoria_evidencia`: un INSERT sin `origen` guarda `'MANUAL'`; `categoria_causa='EVIDENCIA_CAMINO'` es aceptada.
  - `test_evidencia_cascade_servicio`: borrar el servicio sintético borra su evidencia.
- [ ] **Paso 2:** `python scripts/agent_lock.py acquire "db:migrations" --agent claude-cromo --reason "migración árbitro"`. Después `pytest tests/test_cromo_arbitro_migracion_real_db.py -q`. Esperado: FAIL o SKIP por tablas inexistentes.
- [ ] **Paso 3:** escribir la migración y los modelos. Los modelos siguen el estilo de `CromoServicioOdfOverride`, con docstring que explique "sin FK dura a Cromo".
- [ ] **Paso 4:** aplicar en dev y validar.
  - `alembic -c db/alembic.ini upgrade head`, luego `downgrade -1`, luego `upgrade head`, contra la DB dev (ver skill `alembic-migrations` para el comando dentro del contenedor).
  - `pytest tests/test_cromo_arbitro_migracion_real_db.py tests/test_cromo_servicio_odf_override_service.py -q`. Esperado: PASS.
- [ ] **Paso 5:** commit `feat(db): tablas del árbitro de Cromo y origen AUTO en override de ODF`. Liberar el lease.

## Task 3: Núcleo puro — señales, puntaje, alcance y contrato de regla

**Archivos:**
- Crear: `core/services/cromo/arbitro/__init__.py` (vacío con encabezado)
- Crear: `core/services/cromo/arbitro/senales.py`
- Test: `tests/test_cromo_arbitro_senales.py`

**Interfaces que produce** (todas en `arbitro/senales.py`):
- **Constantes:**
  - `USUARIO_ARBITRO = "arbitro-cromo"`.
  - `MODOS = ("APAGADA","SOMBRA","AUTO")`, `ESTADOS_ABIERTOS = ("PROPUESTA","EN_OBSERVACION")`.
  - `ACCIONES = ("ASOCIAR_ODF","FUSIONAR_GEMELO","INFORMAR")`, `DISPAROS = ("INGESTA","REGISTRADOR","VIEWER","NORMALIZADOR")`.
  - `OBJETO_SERVICIO="SERVICIO"`, `OBJETO_BOTELLA="BOTELLA"`, `OBJETO_ODF="ODF"`.
- `@dataclass(frozen=True, slots=True) class Senal`: `codigo: str`, `peso: int`, `detalle: Mapping[str, Any] = field(default_factory=dict)`, `veto: bool = False`.
- `@dataclass(frozen=True, slots=True) class Alcance`: `tipo: str` (`"TODO" | "SERVICIOS" | "BOTELLAS" | "ODFS"`) e `ids: tuple[int, ...] = ()`.
  - `def cubre(self, objeto_tipo: str, objeto_id: int) -> bool`.
  - `def a_dict(self) -> dict`.
  - `@classmethod desde_dict(cls, d) -> "Alcance"`: lanza `ValueError` si el tipo es inválido o los ids no son enteros.
- `@dataclass(frozen=True, slots=True) class Evaluacion`: `regla: str`, `objeto_tipo: str`, `objeto_id: int`, `accion: str`, `parametros: Mapping[str, Any]`, `senales: tuple[Senal, ...]`, `tope: int = 100`.
- `def puntaje(senales: Sequence[Senal], tope: int = 100) -> int`: con cualquier veto da 0; si no, `max(0, min(tope, 100, sum(pesos)))`.
- `def evidencia_hash(ev: Evaluacion) -> str`: sha256 hex de `json.dumps({regla, objeto_tipo, objeto_id, accion, parametros, senales:[(codigo,peso,detalle)…ordenadas por codigo]}, sort_keys=True, default=str)`.
- `class Regla(Protocol)`: `codigo: str` y `async def evaluar(self, sesion: AsyncSession, alcance: Alcance, *, propios: frozenset[int], contexto: dict[str, Any]) -> list[Evaluacion]`.
  - `propios` son los `objeto_id` que esta regla tiene EN_OBSERVACION. La regla **debe** volver a evaluarlos ignorando el efecto de su propia acción.
  - `contexto` es un caché compartido entre reglas dentro de una misma evaluación.

- [ ] **Paso 1: tests que fallan.**
  - `test_puntaje_suma_y_recorta`: pesos `[45,25,10,15,5]` dan 100; `[45,25,10,15,5,20]` también da 100.
  - `test_puntaje_respeta_tope`: `[45,10,10]` con `tope=60` da 60.
  - `test_puntaje_veto_da_cero`: `[45, Senal("X", 0, veto=True)]` da 0.
  - `test_puntaje_negativo_no_baja_de_cero`: `[10,-30]` da 0.
  - `test_hash_estable_ante_orden_de_senales`, y `test_hash_cambia_con_parametros`: ODF 1 contra ODF 2.
  - `test_alcance_cubre`: `TODO` cubre todo; `SERVICIOS (5,)` cubre `("SERVICIO",5)` y no cubre `("BOTELLA",5)`.
  - `test_alcance_desde_dict_invalido`: `{"tipo":"X"}` lanza `ValueError`.
- [ ] **Paso 2:** `pytest tests/test_cromo_arbitro_senales.py -q`. Esperado: FAIL (módulo inexistente).
- [ ] **Paso 3:** implementar.
- [ ] **Paso 4:** mismo comando. Esperado: PASS.
- [ ] **Paso 5:** commit `feat(cromo): núcleo de señales y puntaje del árbitro`.

## Task 4: `crear_override` acepta `origen`, `propuesta_id` y `confirmar`

**Archivos:**
- Modificar: `core/services/cromo/servicio_odf_override_service.py:51-106`
- Test: `tests/test_cromo_servicio_odf_override_service.py`

**Interfaces que produce:** la firma pasa a `crear_override(sesion, *, servicio_id, odf_n_id, pelo_n_id=None, categoria_causa, subcategoria=None, usuario, notas=None, senal_direccion=None, origen: str = "MANUAL", propuesta_id: Optional[int] = None, confirmar: bool = True) -> CromoServicioOdfOverride`.
- Con `confirmar=False` hace `flush()` en vez de `commit()` + `refresh()`, y el `id` queda disponible.
- `override_vigente_de_servicio` no cambia.

- [ ] **Paso 1: tests que fallan.**
  - `test_crear_override_auto_sin_commit`: con `confirmar=False` y `origen="AUTO"`, la sesión fake recibe `flush` y no `commit`; la fila tiene `origen == "AUTO"` y `propuesta_id == 7`.
  - `test_crear_override_default_manual_con_commit`: el comportamiento actual sigue igual.
- [ ] **Paso 2:** `pytest tests/test_cromo_servicio_odf_override_service.py -q`. Esperado: FAIL.
- [ ] **Paso 3:** implementar y agregar `origen` y `propuesta_id` al constructor.
- [ ] **Paso 4:** mismo comando. Esperado: PASS.
- [ ] **Paso 5:** commit `feat(cromo): crear_override admite origen AUTO y transacción del llamador`.

## Task 5: `ExtremoCamino` lleva at62 y pelo conectado del conector

**Archivos:**
- Modificar: `core/services/cromo/tracking_service.py`: `ExtremoCamino` (`:69-90`), `_extremo_de_nodo` (`:191-201`) y `ResumenCamino._desde_json` (`:144-167`)
- Test: `tests/test_cromo_tracking_service.py` (o el archivo de tests de `tracking_service` existente; ubicarlo con `grep -ln "ResumenCamino" tests/`)

**Interfaces que produce:** `ExtremoCamino.servicio_at62: Optional[str] = None` y `ExtremoCamino.pelo_conectado: Optional[int] = None`, copiados de `NodoCamino.servicio_at62` y `NodoCamino.pelo_conectado` (`camino_optico_service.py:194,205`).

- [ ] **Paso 1: tests que fallan.**
  - `test_extremo_de_nodo_copia_at62_y_pelo_conectado`: un `NodoCamino` de conector con `servicio_at62="106180"` y `pelo_conectado=77` produce un extremo con esos valores.
  - `test_desde_json_cache_viejo_sin_campos_nuevos`: un dict sin esas claves reconstruye el extremo con `None`, sin error.
  - `test_round_trip_json_con_campos_nuevos`: `a_json` y luego `desde_json` conservan `pelo_conectado` como `int`.
- [ ] **Paso 2:** `pytest <archivo> -q -k "at62_y_pelo or cache_viejo or round_trip_json"`. Esperado: FAIL.
- [ ] **Paso 3:** implementar. Agregar `"pelo_conectado"` al loop de casteo a `int` en `_desde_json`.
- [ ] **Paso 4:** `pytest tests/ -q -k "tracking or camino"`. Esperado: PASS, sin regresiones.
- [ ] **Paso 5:** commit `feat(cromo): extremos del tracking guardan at62 y pelo conectado del conector`.

## Task 6: Evidencia de caminos y cola del árbitro

**Archivos:**
- Crear: `core/services/cromo/arbitro/evidencia.py`
- Crear: `core/services/cromo/arbitro/cola.py`
- Modificar: `core/services/cromo/tracking_service.py`: `trackings_del_servicio` (`:611`) gana el kwarg `fuente_evidencia: str = "WEB"`. El enganche va después del bloque de auditoría (`:690-702`).
- Modificar: `modules/slack_baneo_notifier/tracking_servicio.py:185` (pasa `fuente_evidencia="SLACK"`) y `core/services/cromo/auditoria_huerfanos_global.py:218` (pasa `"AUDITORIA_GLOBAL"`).
- Modificar: `web/app/main.py`. En `GET …/camino-optico/tracking.txt` (`:8789`), registrar sólo si `not tracking.desde_cache`. En `GET /api/admin/infra/servicios-odf/{id}/camino-optico` (`:9806`), registrar cuando `camino.estado == "OK"`.
- Test: `tests/test_cromo_arbitro_evidencia.py`; real DB en `tests/test_cromo_arbitro_evidencia_real_db.py`.

**Interfaces que produce:**
- `@dataclass(frozen=True, slots=True) class EvidenciaEntrada`: `pelo_n_id: int`, `resumen: ResumenCamino`, `pelos_camino: frozenset[int]`.
- `def entradas_de_trackings(trackings: Sequence[TrackingGenerado]) -> list[EvidenciaEntrada]`: omite los trackings sin `extremos`.
- `def entrada_de_camino(camino: CaminoOptico) -> Optional[EvidenciaEntrada]`: usa `resumen_del_camino` y `pelos_del_camino`. Si `camino.estado != "OK"` devuelve `None`.
- `def camino_truncado(camino: CaminoOptico) -> bool`: detecta la advertencia de lado truncado que emite `camino_optico_service.py:1471-1473`. Leer el texto exacto ahí y reusar la constante si existe.
- `async def registrar_evidencia(sesion: AsyncSession, servicio_id: int, entradas: Sequence[EvidenciaEntrada], *, completo: bool, fuente: str) -> int`:
  - Hace upsert por `(servicio_id, pelo_n_id)`, que pisa `completo`, `extremos`, `pelos_camino`, `fuente` y `generado_at=now()`.
  - Trabaja en `begin_nested()` y luego `commit()`. Nunca lanza: ante un error loguea `evento=evidencia_fallida` y devuelve 0.
- `async def registrar_y_encolar(sesion, servicio_id, entradas, *, completo, fuente) -> None`: llama a `registrar_evidencia` y, si escribió más de 0 filas, a `encolar_evaluacion(Alcance("SERVICIOS", (servicio_id,)), "REGISTRADOR", motivo=f"evidencia:{fuente}")`.
- `cola.py`:
  - `JOB_KIND_ARBITRO = "arbitro_evaluar"`.
  - `async def encolar_evaluacion(alcance: Alcance, disparo: str, motivo: str = "", *, evaluacion_id: Optional[int] = None, reglas: Optional[Sequence[str]] = None) -> None` hace `rpush` a `botella_recompute_queue.QUEUE_KEY` de `{"kind","alcance":alcance.a_dict(),"disparo","motivo","evaluacion_id","reglas"}`. Usa `get_redis()` y es best-effort como `encolar_recalculo_duplicados_botellas`.
  - `evaluacion_id` lo pasa sólo el análisis retroactivo lanzado desde la UI (Task 13), que ya creó la fila `EN_COLA`. Los disparadores automáticos no lo pasan.

- [ ] **Paso 1: tests que fallan.**
  - `test_entradas_de_trackings_omite_sin_extremos`.
  - `test_encolar_evaluacion_payload`: Redis fake; verifica `kind`, `alcance={"tipo":"SERVICIOS","ids":[5]}` y `disparo`.
  - `test_encolar_evaluacion_redis_caido_no_lanza`.
  - `test_trackings_del_servicio_registra_evidencia`: monkeypatch de `registrar_y_encolar` y `trackings_por_camino`. Lo llama con `completo` igual a `resuelto_entero` y `fuente="SLACK"` cuando se pasa así.
  - Real DB:
    - `test_registrar_evidencia_upsert_pisa_lo_viejo`: dos registros con ODF distinta dejan una sola fila con la segunda.
    - `test_registrar_evidencia_error_no_lanza`: `servicio_id` inexistente rompe la FK, devuelve 0 y la sesión sigue usable.
- [ ] **Paso 2:** `pytest tests/test_cromo_arbitro_evidencia.py tests/test_cromo_arbitro_evidencia_real_db.py -q`. Esperado: FAIL.
- [ ] **Paso 3:** implementar y enganchar los cuatro puntos de entrada. Los dos del web van en `try` propio; no deben cambiar la respuesta HTTP.
- [ ] **Paso 4:** mismo comando, más `pytest tests/test_web_cromo_camino_optico*.py tests/test_slack*track*.py tests/test_cromo_auditoria_huerfanos*.py -q`. Esperado: PASS.
- [ ] **Paso 5:** commit `feat(cromo): las consultas en vivo dejan evidencia de camino y encolan al árbitro`.

## Task 7: El worker despacha `arbitro_evaluar` con payload

**Archivos:**
- Modificar: `modules/botellas_recalculo_worker/worker.py:78-103`
- Crear: `core/services/cromo/arbitro/aviso.py`
- Test: `tests/test_botellas_recalculo_worker.py`

**Interfaces que consume:** `motor.evaluar` y `ResumenEvaluacion` (Task 11). En esta tarea `_evaluar_arbitro` importa `motor` de forma diferida; los tests lo mockean.

**Interfaces que produce:**
- `DISPATCH: dict[str, Callable[[dict], Awaitable[None]]]`. El handler existente queda envuelto como `lambda payload: _recalcular_botellas_duplicados()`.
- `async def _evaluar_arbitro(payload: dict) -> None`:
  - Valida `Alcance.desde_dict(payload["alcance"])` y que `disparo` esté en `DISPAROS`; si no, loguea `evento=job_invalido` y retorna.
  - **Registro de la corrida:** con `evaluacion_id`, usa esa fila de `cromo_arbitro_evaluacion`. Sin él, crea una con `estado='EN_CURSO'` y `solicitada_por=USUARIO_ARBITRO`.
  - La marca `EN_CURSO` con `iniciada_en` y hace commit.
  - Abre `AsyncSessionLocal()`, llama a `evaluar(sesion, alcance, disparo, codigos=payload.get("reglas"))` y hace `commit()`.
  - Cierra la fila según el resultado y hace commit:
    - `OK` con `resumen` y `terminada_en`;
    - `OMITIDA` si `resumen.omitida`;
    - `FALLIDA` con `error` si hubo excepción. En ese caso hace rollback de la evaluación antes de cerrar la fila en una transacción nueva.
  - Al final llama a `avisar_evaluacion(resumen, evaluacion_id)`.
- `aviso.py`: `async def avisar_evaluacion(resumen: "ResumenEvaluacion", evaluacion_id: Optional[int]) -> None`. Nunca lanza.
  - Siempre publica por WS en `ADMIN_NOTIFICATIONS_CHANNEL` con `{"type":"arbitro_cromo_evaluado", "evaluacion_id", "nuevas", "aplicadas_auto", "revertidas", "presupuesto_excedido"}`.
  - Al pasar a `EN_CURSO` publica además `{"type":"arbitro_cromo_en_curso","evaluacion_id"}`.
  - Manda texto a Slack sólo si `aplicadas_auto`, `revertidas` o `presupuesto_excedido` son no vacíos, y con la config de la fila "Cromo Inconsistencias".
  - Reusa `inconsistencias_reporte._leer_config_slack` y `_enviar_slack_sync`. Verificar sus firmas en `inconsistencias_reporte.py:244-360` antes de usarlas.

- [ ] **Paso 1: tests que fallan.**
  - `test_dispatch_arbitro_llama_evaluar`: con `evaluar` mockeado, verifica el alcance y el disparo recibidos y el commit.
  - `test_dispatch_arbitro_payload_invalido_no_llama`: `alcance={"tipo":"X"}`.
  - `test_dispatch_arbitro_cierra_evaluacion_ok`: la fila `EN_COLA` termina `OK` con `resumen`.
  - `test_dispatch_arbitro_excepcion_marca_fallida`: la fila termina `FALLIDA` con `error`.
  - `test_dispatch_arbitro_sin_evaluacion_id_crea_fila`.
  - Para estos tres tests, sesión fake o `requiere_postgres_real` según convenga.
  - `test_dispatch_botellas_duplicados_sigue_funcionando`.
  - `test_avisar_evaluacion_sin_cambios_no_va_a_slack`.
- [ ] **Paso 2:** `pytest tests/test_botellas_recalculo_worker.py -q`. Esperado: FAIL.
- [ ] **Paso 3:** implementar.
- [ ] **Paso 4:** mismo comando. Esperado: PASS.
- [ ] **Paso 5:** commit `feat(worker): job arbitro_evaluar en el worker de recálculo`.

## Task 8: Reglas `ODF_POR_CAMINO` y `CONTRADICCION_SERVICIO`

**Archivos:**
- Crear: `core/services/cromo/arbitro/reglas/__init__.py`, con `REGLAS: tuple[Regla, ...]`. Se completa en la Task 9.
- Crear: `core/services/cromo/arbitro/reglas/odf_por_camino.py`
- Test: `tests/test_cromo_arbitro_regla_odf.py`; real DB en `tests/test_cromo_arbitro_regla_odf_real_db.py`.

**Interfaces que consume:**
- De `servicios_sin_odf.py`: `_SUBQUERY_ANTI_AMBIGUEDAD` (`:344`), `_SQL_NO_TIENE_ODF_RESUELTA` (`:377`) y `sugerencia_odf_para_servicio` (`:822`).
- `EvidenciaCamino`, que lee filas de `cromo_evidencia_camino`.

**Interfaces que produce:**
- **Constantes:** `REGLA_ODF = "ODF_POR_CAMINO"`, `REGLA_CONTRADICCION = "CONTRADICCION_SERVICIO"`, `EVIDENCIA_TTL_DIAS = 30`, `TOPE_SOLO_LOCAL = 60`.
- **Pesos:** `CAMINO_VIVO_COMPLETO=45`, `AT62_COINCIDE=25`, `CONECTOR_LIBRE=10`, `HERMANOS_COINCIDEN=15`, `EXTREMOS_COHERENTES=5`, `FUSIONES_LOCALES=45`.
- **Vetos:** `ODF_SIN_FILA` y `CONECTOR_OTRO_SERVICIO`.
- `@dataclass(frozen=True, slots=True) class ServicioCandidato`: `id: int` e `identidades: frozenset[str]` (`servicio_id`, `numero_primer_servicio` y `alias_ids`).
- `@dataclass(frozen=True, slots=True) class ConectorVisto`: `conector_n_id: Optional[int]`, `odf_n_id: int`, `odf_tiene_fila: bool`, `servicio_at62: Optional[str]`, `pelo_conectado: Optional[int]`, `servicio_resuelto: Optional[str]` y `en_vivo: bool`.
- `def puntuar_servicio(servicio: ServicioCandidato, conectores: Sequence[ConectorVisto], odf_hermanos: Optional[int]) -> list[Evaluacion]`. Función pura:
  - **Sin conectores:** devuelve `[]`.
  - **Contradicción:** cada conector cuyo `servicio_resuelto` no es vacío y no está en `identidades` produce una `Evaluacion(REGLA_CONTRADICCION, "SERVICIO", id, "INFORMAR", {"conector_n_id","odf_n_id","servicio_conector"}, (Senal("CONECTOR_OTRO_SERVICIO",0),))`.
  - **ODF objetivo:** se toma entre los conectores sin contradicción. Primero el que tiene `servicio_at62` en `identidades`; si no hay, el de menor `odf_n_id`.
  - **Más de 2 ODF distintas entre los válidos:** no se emite `ASOCIAR_ODF`.
  - **Evaluación `ASOCIAR_ODF`:**
    - `parametros={"odf_n_id", "pelo_n_id": pelo_conectado, "odfs_extremo": sorted}`.
    - Señales según la tabla de la spec. Vetos: `ODF_SIN_FILA` si la ODF objetivo no tiene fila, y `CONECTOR_OTRO_SERVICIO` si hay contradicción sobre esa misma ODF.
    - `tope=TOPE_SOLO_LOCAL` si ningún conector es `en_vivo`.
- `class ReglaOdfPorCamino` y `class ReglaContradiccionServicio`: implementan `Regla`. Las dos comparten la carga vía `contexto["odf_por_camino"]`.
  - `async def _cargar(sesion, alcance, propios) -> dict[int, tuple[ServicioCandidato, list[ConectorVisto], Optional[int]]]`.
  - **Universo:** el mismo filtro que `_PLANTILLA_LISTADO`. Se excluyen sólo los servicios con override `origen='MANUAL'`; los `propios` se incluyen aunque tengan override AUTO.
  - **Filtro por alcance:** para `SERVICIOS`, `s.id = ANY(:ids ::int[])`.
  - **Conectores en vivo:** de `cromo_evidencia_camino` con `completo` y `generado_at >= now() - interval '30 days'`. De cada extremo con `tipo` conector y `odf_id`:
    - `conector_n_id = id_cromo`;
    - `odf_tiene_fila` mirando `cromo_odfs`, con `odf_id` resuelto también como `version_id`;
    - `servicio_resuelto` desde `cromo_odf_conectores.n_id = conector_n_id`.
  - **Conectores locales:** sólo si `alcance.tipo == "TODO"`. BFS en Python por `cromo_fusiones` vigentes desde las semillas, que son pelos vigentes de `v_cromo_servicio_match_vigente` con `m.servicio_id`, hasta `cromo_odf_conectores.pelo_n_id` vigente. Se marcan `en_vivo=False`. El BFS se corta en 20.000 pelos visitados por servicio y el grafo se carga una sola vez por `contexto`, igual que la medición del 2026-10-19.
  - **Hermanos:** `odf_hermanos = (await sugerencia_odf_para_servicio(sesion, id)).odf_n_id` o `None`. Sólo se calcula si hay conectores, para no pagar 2.467 consultas.

- [ ] **Paso 1: tests puros que fallan.**
  - `test_vivo_completo_con_at62_libre_y_hermanos_da_100`.
  - `test_vivo_sin_at62_ni_hermanos_da_60`: 45+10+5 si hay 2 ODF coherentes; si no, 55.
  - `test_solo_local_topa_en_60`.
  - `test_conector_con_otro_servicio_veta_y_emite_contradiccion`.
  - `test_mas_de_dos_odf_no_propone`.
  - `test_odf_sin_fila_veta`.
  - `test_elige_odf_cuyo_at62_coincide`.
- [ ] **Paso 2: tests contra DB real que fallan.**
  - `test_evidencia_vencida_no_cuenta`: evidencia con `generado_at` de hace 31 días no aporta conectores `en_vivo`.
  - `test_override_manual_saca_del_universo`.
  - `test_override_auto_propio_sigue_en_universo`: con `propios={sid}`.
  - `test_evidencia_actualizada_cambia_parametros`: ODF A y después ODF B; la evaluación trae B.
- [ ] **Paso 3:** `pytest tests/test_cromo_arbitro_regla_odf*.py -q`. Esperado: FAIL.
- [ ] **Paso 4:** implementar. Las lecturas de matches van sólo por la vista.
- [ ] **Paso 5:** `pytest tests/test_cromo_arbitro_regla_odf*.py tests/test_cromo_cuarentena_lectores.py -q`. Esperado: PASS.
- [ ] **Paso 6:** commit `feat(cromo): reglas ODF_POR_CAMINO y CONTRADICCION_SERVICIO del árbitro`.

## Task 9: Reglas de gemelos (`GEMELO_VACIO`, `GEMELO_OPERATIVO`, `ODF_GEMELA_ISLA`)

**Archivos:**
- Crear: `core/services/cromo/arbitro/reglas/gemelos.py`
- Modificar: `core/services/cromo/arbitro/reglas/__init__.py` (registrar las 5 reglas)
- Test: `tests/test_cromo_arbitro_regla_gemelos.py`; real DB en `tests/test_cromo_arbitro_regla_gemelos_real_db.py`.

**Interfaces que consume:**
- `normalizar_para_agrupar_extendido` (`core/services/camara_hierarchy_service.py:96`).
- `tiene_cables_asociados_batch_sync` (`core/services/cromo/verificador.py:802`), vía `await sesion.run_sync(...)`.

**Interfaces que produce:**
- **Constantes:** `REGLA_GEMELO_VACIO`, `REGLA_GEMELO_OPERATIVO`, `REGLA_ODF_GEMELA_ISLA`.
- **Pesos:** `MISMA_LOCALIDAD=20`, `CERCA_50M=30`, `CERCA_300M=10`, `VACIA_SIN_FUSIONES=30`, `MISMA_CAMARA=15`, `COMPARTEN_CABLES=40`, `CABLES_DISJUNTOS=-30`.
- **Vetos:** `LEJOS_300M`, `SEPARADA_MANUAL` y `ALIAS_PREVIO`.
- `@dataclass(frozen=True, slots=True) class MiembroGemelo`: `n_id: int`, `nombre: str`, `localidad: Optional[str]`, `lat: Optional[float]`, `lon: Optional[float]`, `camara_id: Optional[int]`, `con_cables: bool`, `con_fusiones: bool`, `es_isla: bool`, `separada_manualmente: bool`, `alias_previo: bool` y `cables: frozenset[int]`.
- `def distancia_m(a: MiembroGemelo, b: MiembroGemelo) -> Optional[float]`: haversine; `None` si falta alguna coordenada.
- `def senales_de_cercania(a, b) -> list[Senal]`: localidad igual sin distinguir mayúsculas, que no sea nula; distancia en franjas; `MISMA_CAMARA` si los dos `camara_id` son iguales y no nulos.
- `def puntuar_grupo_botellas(miembros: Sequence[MiembroGemelo]) -> list[Evaluacion]`. Función pura:
  - **Operativa:** `con_cables`. **Vacía:** sin cables y sin fusiones.
  - **Exactamente 1 operativa:** cada vacía produce `Evaluacion(REGLA_GEMELO_VACIO, "BOTELLA", vacia.n_id, "FUSIONAR_GEMELO", {"origen": vacia.n_id, "destino": op.n_id}, señales)`.
    - Señales: `VACIA_SIN_FUSIONES` más las de cercanía.
    - Vetos: `SEPARADA_MANUAL` en cualquiera de los dos y `ALIAS_PREVIO` en la vacía o en el destino.
  - **Islas con exactamente 1 operativa no-isla:** cada miembro con `es_isla` produce lo mismo, pero con `accion="INFORMAR"`.
  - **2 o más operativas:** una `Evaluacion(REGLA_GEMELO_OPERATIVO, "BOTELLA", min(n_id operativas), "INFORMAR", {"miembros": sorted}, señales)`.
    - Señales: `COMPARTEN_CABLES` si hay intersección de `cables` entre algún par, si no `CABLES_DISJUNTOS`, más las de cercanía del primer par.
- `def puntuar_odf_isla(isla: MiembroGemelo, gemela: MiembroGemelo) -> Evaluacion`: `REGLA_ODF_GEMELA_ISLA`, objeto `"ODF"`, `"INFORMAR"`, señales de cercanía.
- **Clases `ReglaGemeloVacio`, `ReglaGemeloOperativo` y `ReglaOdfGemelaIsla`:** comparten la carga vía `contexto["gemelos"]`.
  - **Botellas:** `cromo_botellas` vigentes agrupadas por clave extendida no vacía, con 2 o más miembros, más los `propios` aunque estén `vigente=false`.
  - **`alias_previo`:** ignora los alias con `creado_por = USUARIO_ARBITRO` cuyo origen esté en `propios`.
  - **`es_isla`:** caso `ELEMENTO_ISLA` en estado PENDIENTE o CUARENTENA.
  - **`cables`:** n_id de los cables vigentes que tienen a la botella como extremo.
  - **ODF:** casos `ELEMENTO_ISLA` con clase 69 u 86, contra `cromo_odfs` vigentes con `lower(trim(nombre))` igual y otro `n_id`. Verificar si `cromo_odfs` tiene `localidad`, `latitud` y `longitud`; si falta alguna, la señal no se emite.
  - **Alcance:** `BOTELLAS` filtra los grupos que contienen algún id; `ODFS` filtra las islas; `SERVICIOS` devuelve `[]`.

- [ ] **Paso 1: tests puros que fallan.**
  - `test_vacia_con_operativa_cerca_misma_localidad_y_camara_da_95`: 30+20+30+15.
  - `test_vacia_lejos_300m_veta`.
  - `test_separada_manual_veta`.
  - `test_isla_con_operativa_informa_no_fusiona`.
  - `test_dos_operativas_comparten_cables_informa_operativo`.
  - `test_dos_operativas_disjuntas_resta`.
  - `test_sin_coordenadas_no_emite_distancia`.
  - `test_odf_isla_con_gemela_informa`.
- [ ] **Paso 2: tests contra DB real que fallan.**
  - `test_carga_agrupa_por_nombre_extendido_sin_camara`: dos botellas sin `camara_id`, una con cable y otra vacía, dan 1 `GEMELO_VACIO`.
  - `test_propia_fusionada_se_reevalua`: vacía con `vigente=false` y alias del árbitro, dentro de `propios`, sigue saliendo y sin veto `ALIAS_PREVIO`.
- [ ] **Paso 3:** `pytest tests/test_cromo_arbitro_regla_gemelos*.py -q`. Esperado: FAIL.
- [ ] **Paso 4:** implementar.
- [ ] **Paso 5:** mismo comando. Esperado: PASS.
- [ ] **Paso 6:** commit `feat(cromo): reglas de gemelos de botellas y ODF del árbitro`.

## Task 10: Acciones aplicables y reversibles

**Archivos:**
- Crear: `core/services/cromo/arbitro/acciones.py`
- Test: `tests/test_cromo_arbitro_acciones_real_db.py`

**Interfaces que consume:** `crear_override(..., origen="AUTO", propuesta_id=..., confirmar=False)` (Task 4) y `consolidar_grupo_botellas` (`consolidacion_service.py:68`, sync, vía `sesion.run_sync`).

**Interfaces que produce:**
- `class AccionNoAplicable(Exception)`.
- `async def aplicar(sesion: AsyncSession, propuesta: CromoPropuesta) -> dict`: devuelve el dict de reversión y no hace commit.
  - **`ASOCIAR_ODF`:** `crear_override(servicio_id=objeto_id, odf_n_id=parametros["odf_n_id"], pelo_n_id=parametros.get("pelo_n_id"), categoria_causa="EVIDENCIA_CAMINO", usuario=USUARIO_ARBITRO, origen="AUTO", propuesta_id=propuesta.id, confirmar=False, notas=f"Árbitro propuesta {id}")`. Devuelve `{"override_id": id}`.
    - Si el servicio ya tiene un override `MANUAL` posterior, lanza `AccionNoAplicable("override_manual")`.
  - **`FUSIONAR_GEMELO`:** revalida que el origen siga vigente, sin cables ni fusiones, y que el destino siga vigente con cables. Si no se cumple, lanza `AccionNoAplicable("gemelo_cambio")`.
    - Llama a `consolidar_grupo_botellas(s, ids_origen_cromo=[origen], id_destino_cromo=destino, usuario=USUARIO_ARBITRO, motivo=f"arbitro propuesta {id}")`. Devuelve `{"alias_origen": origen}`.
  - **`INFORMAR`:** lanza `AccionNoAplicable("solo_informativa")`.
- `async def revertir(sesion, propuesta) -> None`. No hace commit.
  - **`ASOCIAR_ODF`:** `DELETE` del override con `id = reversion.override_id AND origen = 'AUTO'`.
  - **`FUSIONAR_GEMELO`:** borra el alias con `id_cromo_origen = origen AND accion = 'fusionar' AND creado_por = USUARIO_ARBITRO` y pone `vigente = true` en la botella origen.

- [ ] **Paso 1: tests contra DB real que fallan.**
  - `test_asociar_odf_crea_override_auto_y_sale_de_sin_odf`: con `listar_servicios_sin_odf(..., q=servicio_id sintético)`, el total pasa de 1 a 0.
  - `test_revertir_asociar_borra_solo_la_fila_auto`: con un override MANUAL previo, la fila MANUAL queda.
  - `test_asociar_con_override_manual_posterior_no_aplica`.
  - `test_fusionar_gemelo_y_revertir_restituye_vigente_y_quita_alias`.
  - `test_fusionar_gemelo_que_gano_cables_no_aplica`.
  - `test_informar_no_aplica`.
- [ ] **Paso 2:** `pytest tests/test_cromo_arbitro_acciones_real_db.py -q`. Esperado: FAIL.
- [ ] **Paso 3:** implementar.
- [ ] **Paso 4:** mismo comando. Esperado: PASS.
- [ ] **Paso 5:** commit `feat(cromo): acciones reversibles del árbitro`.

## Task 11: Motor de evaluación y operaciones manuales

**Archivos:**
- Crear: `core/services/cromo/arbitro/motor.py`
- Test: `tests/test_cromo_arbitro_motor.py` (con reglas fake) y `tests/test_cromo_arbitro_motor_real_db.py`

**Interfaces que consume:** `REGLAS`, `puntaje`, `evidencia_hash`, `aplicar`/`revertir` e `ingesta_en_curso` (`inconsistencias_cromo.py:1446`).

**Interfaces que produce:**
- `@dataclass class ResumenEvaluacion`: `nuevas: int = 0`, `actualizadas: int = 0`, `obsoletas: int = 0`, `aplicadas_auto: list[int]`, `confirmadas: list[int]`, `revertidas: list[int]`, `presupuesto_excedido: list[str]` y `omitida: Optional[str] = None`.
- `ResumenEvaluacion.a_dict() -> dict`, con una entrada `por_regla: dict[str, dict]` de contadores por código. La UI la usa para mostrar el resultado de cada corrida.
- `async def evaluar(sesion, alcance: Alcance, disparo: str, *, reglas: Optional[Sequence[Regla]] = None, codigos: Optional[Sequence[str]] = None) -> ResumenEvaluacion`. No hace commit. `codigos` limita la corrida a esas reglas: lo usa el análisis retroactivo por regla desde la UI. El algoritmo:
  1. Si `await ingesta_en_curso(sesion)` devuelve algo, sale con `omitida="ingesta_en_curso"`. Si `pg_try_advisory_xact_lock(LOCK_ARBITRO)` da false, sale con `omitida="otra_evaluacion"`. `LOCK_ARBITRO` es una constante int propia, distinta de los locks de `inconsistencias_cromo.py`.
  2. Carga la config de reglas. Las reglas `APAGADA` se saltean.
  3. Por regla: `propios` son los `objeto_id` en `EN_OBSERVACION` de esa regla. Corre `evaluaciones = await regla.evaluar(sesion, alcance, propios=…, contexto=ctx)`.
  4. Por cada evaluación, con la fila abierta (`FOR UPDATE`):
     - **Hay fila `PROPUESTA`:** actualiza `parametros`, `senales`, `confianza`, `evidencia_hash`, `disparo` y `actualizada_en`.
     - **Hay fila `EN_OBSERVACION` y `disparo == "INGESTA"`:** si `confianza >= umbral`, pasa a `APLICADA` (va a `confirmadas`); si no, `revertir` y pasa a `REVERTIDA` (va a `revertidas`).
     - **No hay fila abierta:** si la última `RECHAZADA` para ese objeto tiene el mismo `evidencia_hash`, se saltea. Si no, inserta `PROPUESTA` con `modo_al_evaluar` igual al modo de la regla (va a `nuevas`).
  5. **Obsoletas:** las filas abiertas de esa regla que `alcance.cubre()` y no salieron en la evaluación.
     - Una `PROPUESTA` pasa a `OBSOLETA`.
     - Una `EN_OBSERVACION`, si `disparo == "INGESTA"`, se revierte y pasa a `REVERTIDA`.
  6. **Aplicación AUTO:** si la regla está en `AUTO`, se toman las `PROPUESTA` con `confianza >= umbral` y `accion != "INFORMAR"`.
     - Si son más que `presupuesto_por_corrida`, se agrega el código a `presupuesto_excedido` y no se aplica ninguna.
     - Si no, cada una corre en `begin_nested()`: `reversion = await aplicar(...)` y pasa a `EN_OBSERVACION`, con `aplicada_en=now()` y `decidida_por=USUARIO_ARBITRO`.
     - Con `AccionNoAplicable(m)` queda `PROPUESTA` y `nota=m`.
  7. Log `evento=evaluacion` con el resumen.
- `async def aplicar_manual(sesion, ids: Sequence[int], usuario: str) -> dict`: devuelve `{"aplicados":[ids], "rechazados":[{"id","motivo"}]}`.
  - Sólo actúa sobre `PROPUESTA`.
  - `INFORMAR` pasa a `APLICADA` sin acción. El resto llama a `aplicar` y pasa a `APLICADA`, sin observación; queda registrado en `decidida_por` y `decidida_en`.
- `async def rechazar(sesion, ids, usuario) -> dict`: de `PROPUESTA` a `RECHAZADA`.
- `async def revertir_manual(sesion, ids, usuario) -> dict`: de `EN_OBSERVACION` o `APLICADA`, con acción distinta de `INFORMAR`, llama a `revertir` y pasa a `REVERTIDA`.
- `async def listar_propuestas(sesion, *, regla=None, estado=None, limit=50, offset=0) -> dict`: devuelve `{"items":[{id, regla, objeto_tipo, objeto_id, accion, parametros, confianza, senales, estado, disparo, modo_al_evaluar, nota, creada_en, actualizada_en, decidida_por}], "total"}`, ordenado por `confianza DESC, id DESC`.
- `async def precision_por_regla(sesion) -> list[dict]`: devuelve `{codigo, descripcion, modo, umbral, presupuesto_por_corrida, aceptadas, rechazadas, decididas, precision, sugerir_auto}`.
  - **Aceptadas:** `APLICADA` con `decidida_por <> USUARIO_ARBITRO`.
  - **Rechazadas:** `RECHAZADA`, más `REVERTIDA` con `decidida_por <> USUARIO_ARBITRO`.
  - `precision` es `None` si no hay decididas. `sugerir_auto` vale `decididas >= 30 and precision >= 0.95`.
- `async def actualizar_regla(sesion, codigo, *, modo, umbral, presupuesto_por_corrida, usuario) -> None`: lanza `ValueError` ante valores inválidos o un código inexistente.

- [ ] **Paso 1: tests que fallan.** Primero con reglas fake y una sesión real con savepoint:
  - `test_rafaga_misma_evaluacion_una_sola_propuesta`: `evaluar` dos veces da 1 fila; la segunda corrida suma a `actualizadas`.
  - `test_sombra_nunca_aplica`: con confianza 100 y modo SOMBRA, `cromo_servicio_odf_override` no cambia.
  - `test_auto_sobre_umbral_aplica_y_queda_en_observacion`.
  - `test_auto_bajo_umbral_no_aplica`.
  - `test_presupuesto_excedido_no_aplica_ninguna`: presupuesto 1 con 2 candidatas.
  - `test_rechazada_mismo_hash_no_se_repropone` y `test_rechazada_hash_distinto_se_repropone`.
  - `test_observacion_confirmada_en_ingesta` y `test_observacion_contradicha_en_ingesta_se_revierte`: confianza bajo umbral o evaluación ausente.
  - `test_observacion_no_se_decide_fuera_de_ingesta`: con disparo REGISTRADOR sigue EN_OBSERVACION.
  - `test_obsoleta_solo_dentro_del_alcance`.
  - `test_ingesta_en_curso_omite`.
  - `test_aplicar_manual_informar_marca_aplicada`, `test_rechazar_solo_propuesta` y `test_precision_y_sugerir_auto`: 30 aceptadas y 1 rechazada dan precisión ≈ 0.968 y `True`.
- [ ] **Paso 2:** `pytest tests/test_cromo_arbitro_motor*.py -q`. Esperado: FAIL.
- [ ] **Paso 3:** implementar.
- [ ] **Paso 4:** `pytest tests/test_cromo_arbitro_*.py tests/test_botellas_recalculo_worker.py tests/test_cromo_cuarentena_lectores.py -q`. Esperado: PASS.
- [ ] **Paso 5:** commit `feat(cromo): motor del árbitro con modo sombra, presupuesto y observación`.

## Task 12: Disparadores (ingesta y acciones del viewer)

**Archivos:**
- Modificar: `core/services/cromo/ingesta.py:2433-2452`. Después de `detectar_post_ingesta`, si el modo está en `MODOS_POST_INGESTA`, llamar a `await encolar_evaluacion(Alcance("TODO"), "INGESTA", motivo=f"corrida:{corrida_id}")`, dentro del mismo `try` best-effort.
- Modificar: `web/app/main.py`. Encolar después del commit en cada endpoint:

  | Endpoint | Alcance |
  |---|---|
  | consolidar (`:7559`) | `BOTELLAS` con destino y orígenes |
  | apropiar (`:7384`) | `BOTELLAS` |
  | eliminar-grupo (`:7785`) | `BOTELLAS` |
  | eliminar botella (`:7721`) | `BOTELLAS` |
  | separar-padre (`:10170`) | `BOTELLAS` con `n_id` |
  | asociar ODF (`:7051`) | `SERVICIOS` |
  | odf-confirmadas (`:9576`) | `SERVICIOS` |
  | desconfirmar (`:9602`) | `SERVICIOS` |
  | inconsistencias estado (`:9444`) | `TODO` |

  Siempre con disparo `VIEWER`.
- Test: `tests/test_cromo_ingesta*.py` (el test del paso post-ingesta existente) y `tests/test_web_arbitro_disparadores.py`.

- [ ] **Paso 1: tests que fallan.**
  - `test_post_ingesta_encola_arbitro`: con `encolar_evaluacion` mockeado, una corrida COMPLETA OK lo llama con `Alcance("TODO")` y `"INGESTA"`; una SOLO_CABLES no lo llama.
  - En `tests/test_web_arbitro_disparadores.py`, para consolidar, asociar ODF y estado de inconsistencias, con el patrón de `tests/test_web_cromo_inconsistencias.py:120-191`: la respuesta 200 llama a `encolar_evaluacion` con el alcance esperado, y una respuesta de error no lo llama.
- [ ] **Paso 2:** `pytest tests/test_web_arbitro_disparadores.py -q -k post_ingesta`, más el test de ingesta. Esperado: FAIL.
- [ ] **Paso 3:** implementar.
- [ ] **Paso 4:** mismo comando, más `pytest tests/test_web_*.py tests/test_cromo_ingesta*.py -q`. Esperado: PASS (los tests de shell SPA pueden fallar por falta de `dist`, ver el aviso del worktree).
- [ ] **Paso 5:** commit `feat(cromo): ingesta y viewer disparan al árbitro`.

## Task 13: Endpoints web del árbitro

**Archivos:**
- Modificar: `web/app/main.py`. Agregar un bloque nuevo después de `:9530`, con modelos Pydantic junto a `:9278`.
- Test: `tests/test_web_arbitro_cromo.py`

**Interfaces que produce:** todos con `_require_admin`; los POST además con `_validar_csrf(request, body.csrf_token, scope, user)` y commit en el endpoint.

| Método y ruta | Cuerpo / parámetros | Llama a | Respuesta | Scope CSRF |
|---|---|---|---|---|
| `GET /api/admin/infra/arbitro-cromo/propuestas` | `regla`, `estado`, `limit` (≤200) y `offset` | `listar_propuestas` | — | — |
| `POST /api/admin/infra/arbitro-cromo/propuestas/aplicar` | `{ids: list[int] (1..500), csrf_token}` | `aplicar_manual` | — | `arbitro_cromo_propuestas` |
| `POST …/propuestas/rechazar` | igual | `rechazar` | — | `arbitro_cromo_propuestas` |
| `POST …/propuestas/revertir` | igual | `revertir_manual` | — | `arbitro_cromo_propuestas` |
| `GET /api/admin/infra/arbitro-cromo/reglas` | — | `precision_por_regla` | — | — |
| `POST /api/admin/infra/arbitro-cromo/reglas` | `{codigo, modo, umbral, presupuesto_por_corrida, csrf_token}` | `actualizar_regla` | 422 ante `ValueError` | `arbitro_cromo_reglas` |
| `POST /api/admin/infra/arbitro-cromo/normalizar` (análisis retroactivo) | `{reglas: Optional[list[str]], csrf_token}` | ver abajo | `202 {"evaluacion_id": id}` | `arbitro_cromo_normalizar` |
| `GET /api/admin/infra/arbitro-cromo/evaluaciones` | `limit` (≤50) | `listar_evaluaciones(sesion, limit)` en `motor.py` | `{"items":[{id, disparo, alcance, reglas, estado, resumen, error, solicitada_por, encolada_en, iniciada_en, terminada_en}], "en_curso": Optional[id]}` | — |

**`POST …/normalizar`:**
- Responde 409 si ya hay una evaluación `EN_COLA` o `EN_CURSO` de disparo `NORMALIZADOR`.
- Responde 422 si algún código de `reglas` no existe.
- Si no, crea una fila en `cromo_arbitro_evaluacion` con `disparo='NORMALIZADOR'`, `alcance={"tipo":"TODO"}`, `reglas`, `estado='EN_COLA'` y `solicitada_por=user`. Hace commit y después `encolar_evaluacion(Alcance("TODO"), "NORMALIZADOR", motivo=f"manual:{user}", evaluacion_id=id, reglas=reglas)`.

Después de aplicar o revertir con éxito se encola `encolar_evaluacion` con el alcance de los objetos tocados y disparo `VIEWER`.

- [ ] **Paso 1: tests que fallan** (patrón `tests/test_web_cromo_inconsistencias.py`).
  - `test_propuestas_requiere_admin`: 403 sin admin.
  - `test_aplicar_sin_csrf_403`.
  - `test_aplicar_devuelve_aplicados_y_rechazados`.
  - `test_reglas_post_valor_invalido_422`.
  - `test_normalizar_crea_evaluacion_encola_y_202`.
  - `test_normalizar_con_otra_en_curso_409`.
  - `test_normalizar_regla_inexistente_422`.
  - `test_evaluaciones_devuelve_en_curso`.
- [ ] **Paso 2:** `pytest tests/test_web_arbitro_cromo.py -q`. Esperado: FAIL.
- [ ] **Paso 3:** implementar.
- [ ] **Paso 4:** mismo comando. Esperado: PASS.
- [ ] **Paso 5:** commit `feat(web): endpoints del árbitro de Cromo`.

## Task 14: Viewer — pestañas Propuestas y Reglas

**Archivos:**
- Crear: `web/frontend/src/api/arbitroCromo.ts`
- Crear: `web/frontend/src/admin/components/arbitro/PropuestasArbitroPanel.vue` y `ReglasArbitroPanel.vue`
- Modificar: `web/frontend/src/admin/views/AdminInconsistenciasCromoViewer.vue`. Agregar tabs: "Casos" (la vista actual), "Propuestas" y "Reglas". Reusar el refresco por WS (`:506-511`) también para `type === "arbitro_cromo_evaluado"`.

**Interfaces que produce** (en `arbitroCromo.ts`, sobre `requestJson` como en `inconsistenciasCromo.ts`):
- Tipos `PropuestaArbitro`, `SenalArbitro` y `ReglaArbitro`, con los campos de la Task 13.
- `listarPropuestas(params)`, `aplicarPropuestas(ids)`, `rechazarPropuestas(ids)`, `revertirPropuestas(ids)`, `listarReglas()`, `actualizarRegla(codigo, {modo, umbral, presupuesto_por_corrida})`, `ejecutarAnalisisRetroactivo(reglas?: string[])` y `listarEvaluaciones(limit)`. Los POST van con `csrf: true`.
- Tipo `EvaluacionArbitro`.
- Componente adicional: `web/frontend/src/admin/components/arbitro/AnalisisRetroactivoPanel.vue`.

**UI:**
- **Propuestas:**
  - Filtros por regla y por estado; el default es estado `PROPUESTA`.
  - Tabla con regla, objeto (con link a la vista existente del servicio o botella si la hay), acción, confianza (barra 0-100), señales (desplegable `codigo +peso`, con los vetos marcados), disparo y estado.
  - Selección múltiple y botones Aplicar, Rechazar y Revertir, cada uno con `window.confirm`; mostrar los `rechazados` con su motivo.
- **Panel "Análisis retroactivo"** (arriba de la tabla de Propuestas):
  - Selector de reglas (todas por defecto) y botón "Ejecutar análisis retroactivo" con `window.confirm`.
  - El botón se deshabilita mientras `en_curso` no es nulo, o se reciben los WS `arbitro_cromo_en_curso`/`arbitro_cromo_evaluado`, y muestra "En curso desde HH:MM".
  - Historial de las últimas 10 evaluaciones, de cualquier disparo: estado, disparo, quién la pidió, duración y resumen por regla (nuevas, aplicadas AUTO, obsoletas, revertidas, presupuesto excedido).
  - Al terminar, refresca la tabla de Propuestas filtrada por las reglas de esa corrida.
- **Reglas:**
  - Una fila por regla con selector de modo, inputs de umbral y presupuesto, y aceptadas/rechazadas/precisión.
  - Badge "Lista para AUTO" si `sugerir_auto`.
  - Confirmación explícita al pasar a AUTO.
- Colores sólo con los tokens de `tokens.css` (skill `nocturne-token-compliance`).

- [ ] **Paso 1:** correr la skill `frontend-spa-architecture`, que valida que no hace falta tocar el router: es la misma ruta `/admin/servicios/viewer/InconsistenciasCromo`, `router/index.ts:366`.
- [ ] **Paso 2:** implementar el cliente y los componentes.
- [ ] **Paso 3: verificación de build.**
  - Ejecutar `ln -s /home/support-focal-01/LAS-FOCAS/web/frontend/node_modules web/frontend/node_modules`, sin comitear el enlace.
  - Después `cd web/frontend && npx vite build --outDir /tmp/claude-1001/arbitro-build --emptyOutDir`. Esperado: build sin errores.
  - Después `grep -nE "#[0-9a-fA-F]{3,8}\b|rgba?\(" web/frontend/src/admin/components/arbitro/*.vue`. Esperado: sin resultados.
- [ ] **Paso 4:** commit `feat(web): pestañas Propuestas y Reglas del árbitro en el viewer de inconsistencias`.

## Task 15: Documentación y verificación E2E en dev

**Archivos:**
- Modificar:
  - `docs/modulo_ingesta_cromo.md`: sección "Árbitro de Cromo", con modos, reglas y pesos, disparadores, observación y presupuesto.
  - `docs/infra.md`: viewer.
  - `docs/db.md`: las 3 tablas nuevas y las columnas del override.
  - `docs/PR/2026-10-19.md`, o la fecha del día, vía `/generar-pr-diario`.

- [ ] **Paso 1:** rebuild de `web`, `slack_baneo_worker`, `botellas_recalculo_worker` y `cromo_worker` en dev, con la skill `docker-rebuild` y `--env-file`. Verificar que el código del contenedor sea el nuevo: `docker exec lasfocasdev-web grep -c arbitro /app/core/services/cromo/tracking_service.py`.
- [ ] **Paso 2: línea base.** `SELECT count(*) FROM app.cromo_servicio_odf_override;` y `SELECT count(*) FROM app.cromo_propuesta;`.
- [ ] **Paso 3:** `@Registrador track <uno de los 17 servicios de alta confianza>` en Slack dev. Para sacar la lista, correr la BFS de la regla en modo reporte: `docker exec -e PYTHONPATH=/app lasfocasdev-web python3 -c "..."`, llamando a `ReglaOdfPorCamino._cargar` con `Alcance("TODO")`.
  - Esperado: una fila en `cromo_evidencia_camino`, el job procesado en los logs de `botellas_recalculo_worker` (`evento=job_procesado kind=arbitro_evaluar`) y una propuesta `ODF_POR_CAMINO` en SOMBRA visible en el viewer.
  - El count de overrides no cambia.
- [ ] **Paso 4:** "Ejecutar análisis retroactivo" desde el viewer, con todas las reglas. Verificar en la UI que el botón queda deshabilitado mientras corre, que el historial muestra `EN_CURSO` y luego `OK` con su resumen por regla, y que un segundo click durante la corrida da 409. Contar por regla con `SELECT regla, accion, count(*) FROM app.cromo_propuesta WHERE estado='PROPUESTA' GROUP BY 1,2;` y comparar con la línea base de la spec: ≈17 `ODF_POR_CAMINO`, ≈31 `CONTRADICCION_SERVICIO`, ≈4 `GEMELO_VACIO`, ≈8 `ODF_GEMELA_ISLA` y ≈28 `GEMELO_OPERATIVO`. Las diferencias se explican en el PR diario.
- [ ] **Paso 5:** pasar `ODF_POR_CAMINO` a AUTO desde el panel de Reglas sólo para la verificación, repetir el track del servicio del Paso 3 y verificar:
  - el override con `origen='AUTO'`;
  - que el servicio no aparece en "Servicios sin ODF";
  - que `trackings_del_servicio` devuelve los mismos tramos y residuales que antes.

  Después revertir desde el viewer y volver la regla a SOMBRA.
- [ ] **Paso 6:** `pytest tests/test_cromo_arbitro_*.py tests/test_cromo_cuarentena_*.py tests/test_cromo_inconsistencias*.py tests/test_web_cromo_inconsistencias.py tests/test_web_arbitro_*.py tests/test_botellas_recalculo_worker.py tests/test_cromo_consolidacion_service.py -q`. Esperado: PASS.
- [ ] **Paso 7:** commit `docs(cromo): árbitro de Cromo, verificación en dev`. Push a la rama efímera con la skill `repo-updater`.
