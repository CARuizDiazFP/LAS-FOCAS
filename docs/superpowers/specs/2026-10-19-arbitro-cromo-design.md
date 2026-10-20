# Nombre de archivo: 2026-10-19-arbitro-cromo-design.md
# Ubicación de archivo: docs/superpowers/specs/2026-10-19-arbitro-cromo-design.md
# Descripción: Diseño aprobado del árbitro de Cromo (cruce de mecanismos y autonormalización)

# Plan: Árbitro de Cromo — mecánicas que cruzan hallazgos y se auto-normalizan

## Contexto

Hoy hay unos 70 mecanismos que evitan que Cromo ensucie la base, y no se hablan entre sí:
- el detector de duplicados no sabe qué encontró el de islas;
- "Servicios sin ODF" no sabe qué encontró el tracking.

El usuario pidió:
1. Que el sistema **corrija solo cuando la confianza supere un umbral**; por debajo, que proponga o informe.
2. Que funcione **reactivo en las ingestas** y también como **normalizador** de lo ya acumulado.
3. Que **no se agreguen consultas a Cromo**: consultar caminos es costoso. Se reaprovecha lo que ya consultan por demanda el Registrador de Slack (`@Registrador track`) y el panel web.

Decisiones del usuario (2026-10-19):
- **Modo sombra primero.** Cada regla arranca registrando lo que *haría*; el operador acepta o rechaza, y con eso se mide la precisión. AUTO se habilita regla por regla.
- **ODF automática como asociación con `origen=AUTO`** en `cromo_servicio_odf_override`, y no como ODF confirmada. Así no cambia la clasificación de tramos (evita repetir el 102452, que pasó de 6 a 12).
- **Disparadores:** ingesta, consultas del Registrador o del web, y acciones del operador en el viewer.
- El bug del nombre en Consolidar entra como primer ítem de este plan.

Línea base medida en dev el 2026-10-19, con consultas de sólo lectura:

| Medición | Valor |
|---|---|
| Servicios sin ODF | 2.467 |
| …con algún pelo vigente etiquetado | 927 |
| …que llegan a un conector ODF por fusiones locales | 49 |
| …de esos, con conector libre y 1-2 ODF | 17 |
| …de esos, con un conector que dice otro servicio | 31 |
| …que no llegan a ODF con los datos locales | 860 (las cubre el tracking real) |
| Grupos de botellas duplicadas | 52 (hoy sólo 2 con sugerencia) |
| …con 2+ botellas Cromo con cables | 28 |
| Botellas vacías con una homónima operativa | 4 |
| ODF isla con una ODF homónima | 8 |

## Principios de diseño

- **El árbitro nunca llama a Cromo.** Decide sólo con evidencia ya persistida:
  - inventario ingerido;
  - confirmaciones en vivo del detector (`evidencia.confirmaciones`, TTL de 7 días);
  - la nueva evidencia de caminos que dejan las consultas del Registrador.
- **Confianza = suma de señales con peso, recortada a 0..100.** Cada regla tiene un umbral y un modo (`APAGADA` / `SOMBRA` / `AUTO`).
- **AUTO sólo para acciones baratas de revertir.** Cada aplicación guarda los datos necesarios para deshacerse.
- **Período de observación.** Lo aplicado en AUTO queda `EN_OBSERVACION` hasta la evaluación siguiente a una ingesta. Si esa evaluación lo contradice, se revierte solo.
- **Presupuesto por corrida y por regla**, con default 50. Si una regla lo supera, se aborta esa regla, no se aplica nada de ella y se avisa. Es el mismo criterio de las bajas (tope 300).
- **Las decisiones humanas mandan.** Una propuesta rechazada no se re-propone mientras la evidencia no cambie (se compara por hash de evidencia). Tampoco se tocan objetos con decisión manual: casos ACEPTADA/REPORTADA, MANUAL en matches, `separada_manualmente`.

## Fases

### Fase 0 — Bug del nombre en Consolidar
- `core/services/cromo/consolidacion_service.py:211-213`: agregar `destino.nombre_editado_manual = True`, como hace `separacion_service.py:101-102`.
- Test en `tests/test_cromo_consolidacion*.py`: el destino queda marcado y una ingesta ACTUALIZADA simulada no pisa el nombre (lógica de `ingesta.py:1418-1425`).

### Fase 1 — Modelo de datos y motor en modo sombra
**Migración** `db/alembic/versions/20261020_01_cromo_arbitro.py`, reversible y con lease `db:migrations`:
- **`app.cromo_regla_correccion`:** `codigo` (PK), `modo` (CHECK APAGADA/SOMBRA/AUTO), `umbral` smallint (CHECK 0-100), `presupuesto_por_corrida`, `descripcion`, `actualizado_por`, `actualizado_en`. Se siembran todas las reglas en `SOMBRA`, umbral 90.
- **`app.cromo_propuesta`:** columnas
  - `id`, `regla` (FK a la tabla anterior);
  - `objeto_tipo` (CHECK SERVICIO/BOTELLA/ODF/CABLE) y `objeto_id` bigint;
  - `accion` (CHECK ASOCIAR_ODF / FUSIONAR_GEMELO / INFORMAR);
  - `parametros` jsonb, `confianza` smallint, `senales` jsonb (lista `{codigo, peso, detalle}`), `evidencia_hash`;
  - `estado` (CHECK PROPUESTA / EN_OBSERVACION / APLICADA / RECHAZADA / REVERTIDA / OBSOLETA);
  - `modo_al_evaluar`, `disparo` (CHECK INGESTA / REGISTRADOR / VIEWER / NORMALIZADOR);
  - `reversion` jsonb;
  - `creada_en`, `decidida_por`, `decidida_en`, `aplicada_en`.
  - Índice único parcial `(regla, objeto_tipo, objeto_id) WHERE estado IN ('PROPUESTA','EN_OBSERVACION')`.
- **`app.cromo_evidencia_camino`**, con PK `(servicio_id, pelo_n_id)`, FK `servicio_id` a `servicios` con CASCADE y sin FK a Cromo, como es la convención. Columnas: `completo` bool, `truncado` bool, `extremos` jsonb (por lado: tipo, `odf_n_id`, `odf_clase`, `conector_numero`, `servicio_at62` del conector, `pelo_conectado`), `pelos_camino` bigint[], `fuente` (SLACK / WEB / AUDITORIA_GLOBAL), `generado_at`.
- **`cromo_servicio_odf_override`:** se agrega
  - `origen` (CHECK MANUAL/AUTO, default MANUAL), siguiendo el precedente de `cromo_servicio_pelo_excluido.origen`;
  - `propuesta_id`, FK a `cromo_propuesta` con SET NULL;
  - el valor `EVIDENCIA_CAMINO` al CHECK de `categoria_causa`.
- Modelos nuevos en `db/models/cromo.py`.

**Paquete nuevo** `core/services/cromo/arbitro/`:
- `senales.py`: dataclasses `Senal`, `Evaluacion` (regla, objeto, acción, parámetros, señales) y `puntaje()`. Funciones puras.
- `motor.py`: `evaluar(sesion, alcance, disparo)`. `alcance` puede ser todo, una lista de servicios o una lista de botellas/ODF.
  - Corre las reglas y hace upsert de propuestas.
  - Marca `OBSOLETA` lo abierto que ya no se detecta.
  - Si la regla está en AUTO y `confianza ≥ umbral` dentro del presupuesto, ejecuta la acción.
  - Toma `pg_advisory_xact_lock` propio y no corre si `ingesta_en_curso` (reusar `inconsistencias_cromo.py:1446`).
- `acciones.py`: envoltorios con reversión sobre los servicios existentes, todos con usuario `arbitro-cromo`.
  - Ojo: `crear_override` hace commit por dentro. Agregarle `confirmar=False`, como en `pelos_excluidos.excluir_pelos`.
  - Las acciones sync (consolidar) van por `asyncio.to_thread` con su propia `SessionLocal`.
- `aplicar_manual(ids, usuario)`, `rechazar(ids, usuario)` y `revertir(ids, usuario)` para el viewer.

**Viewer:** pestaña "Propuestas" en `AdminInconsistenciasCromoViewer.vue`.
- Columnas: regla, objeto, acción, confianza, señales (expandible), disparo y estado.
- Botones Aplicar, Rechazar y Revertir, con `window.confirm`.
- Panel "Reglas": modo y umbral por regla, más la precisión medida (aceptadas / decididas, con N).
- Endpoints en `web/app/main.py`, junto a `:9444`, siguiendo el patrón de `/estado` (`_require_admin` + `_validar_csrf` con scope propio + commit en el endpoint):
  - `GET /api/admin/infra/arbitro-cromo/propuestas`
  - `POST …/propuestas/{aplicar|rechazar|revertir}`
  - `GET/POST …/reglas`
  - `POST …/normalizar`
- Cliente nuevo `web/frontend/src/api/arbitroCromo.ts`.

### Fase 2 — Evidencia reactiva desde el Registrador y el web
- **`tracking_service.py`**
  - Extender `ExtremoCamino` y `ResumenCamino` (`:69-119`) con `servicio_at62` y `pelo_conectado` del conector, que ya vienen en `NodoCamino` y `OdfDelCamino`.
  - `a_json` debe ser retrocompatible con el caché viejo.
- **`arbitro/evidencia.py`:** `registrar_evidencia(sesion, servicio_id, trackings, fuente)` hace un upsert en `cromo_evidencia_camino`, dentro de un savepoint y sin lanzar nunca.
- **Enganche** en el mismo punto que la auditoría de huérfanos (`tracking_service.py:690-702`), que es por donde pasan el Slack track, `/caminos` y la auditoría global. Se suma:
  - `GET …/tracking.txt` (`main.py:8789`), sólo en caché miss;
  - el panel admin `/camino-optico` (`main.py:9806`, `resolver_camino_de_servicio`).
  - Sólo se registra un camino con `completo` y sin errores; si está truncado (`MAX_NODOS_POR_LADO`), se registra marcado.
- **Cola:** `arbitro/cola.py` expone `encolar_evaluacion(alcance, ids, disparo)`.
  - Hace `rpush` best-effort, después del commit, sobre `admin:recompute:jobs`.
  - Usa el `kind` nuevo `arbitro_evaluar` con payload.
  - En `modules/botellas_recalculo_worker/worker.py:78-103`, el `DISPATCH` pasa a recibir el payload.
  - La respuesta de Slack no espera: el `rpush` tarda milisegundos.

### Fase 3 — Reglas iniciales
| Código | Detecta | Señales (peso) | Acción | AUTO posible |
|---|---|---|---|---|
| `ODF_POR_CAMINO` | Servicio en el universo "sin ODF" (`servicios_sin_odf._PLANTILLA_LISTADO`) con evidencia de camino que termina en un conector ODF 69/86 con fila en `cromo_odfs` | camino en vivo completo (+45); at62 del conector = identidad del servicio (`IDENTIDADES_DEL_SERVICIO_SQL`) (+25); conector libre (+10); coincide con `sugerencia_odf_para_servicio` de hermanos (+15); ambos extremos en ODF distintas y coherentes (+5); sólo camino por fusiones locales, sin vivo (tope 60); conector con otro servicio (veto) | `ASOCIAR_ODF`: override `origen=AUTO`, `categoria_causa=EVIDENCIA_CAMINO` | Sí. Revertir = borrar la fila AUTO |
| `CONTRADICCION_SERVICIO` | El camino del servicio llega a un conector ODF cuyo `servicio_resuelto` es otro servicio (31 hoy) | — | `INFORMAR`, con ambos servicios y el conector en las señales; probable renumeración o alias sin unir | No |
| `GEMELO_VACIO` | Botellas Cromo homónimas (`normalizar_para_agrupar_extendido`, sin exigir Cámara padre): una sin cables ni fusiones (`tiene_cables_asociados_batch_sync`, o un caso `ELEMENTO_ISLA`) y exactamente una operativa. Generaliza `sugerir_consolidacion_placeholders` | misma localidad (+20); a menos de 50 m (+30), entre 50 y 300 m (+10), a más de 300 m (veto); vacía sin fusiones (+30); isla confirmada en vivo (+15); `separada_manualmente`, alias previo o destino ya aliaseado (veto) | `FUSIONAR_GEMELO` vía `consolidar_grupo_botellas` (alias `fusionar`, sin recablear nada, porque está vacía) | Sí. Revertir = borrar el alias y volver a `vigente=true` |
| `GEMELO_OPERATIVO` | Grupos con 2+ botellas Cromo con cables (28 hoy) | comparten cables o pelos (+40); distancia geo; cables disjuntos (−30) | `INFORMAR`, como propuesta de fusión para el operador | No en v1 (fusionar recablea: revertirlo es caro) |
| `ODF_GEMELA_ISLA` | ODF isla (`ELEMENTO_ISLA` clase 69/86) con una ODF homónima operativa (8 hoy) | igual que `GEMELO_VACIO` | `INFORMAR` (no existe un servicio de consolidación de ODF) | No en v1 |

Los pesos y umbrales son valores iniciales y se calibran en modo sombra. El ejemplo del usuario, botellas duplicadas donde una es isla, lo cubre `GEMELO_VACIO`. Hoy en dev da 0 casos de botellas isla y 4 de botellas vacías, más 8 de ODF.

### Fase 4 — Disparadores
1. **Post-ingesta:** al final de `detectar_post_ingesta` (`inconsistencias_cromo.py:1642`), `encolar_evaluacion("todo", disparo="INGESTA")`. Medido: el cruce completo tarda unos 90 s y no consulta Cromo.
2. **Registrador / web:** Fase 2, con alcance = el servicio consultado.
3. **Viewer:** después del commit de consolidar, eliminar, separar, confirmar o asociar ODF y cambio de estado de inconsistencia, encolar con alcance = objetos afectados. Va donde hoy se llama a `encolar_recalculo_duplicados_botellas`.
4. **Normalizador manual:** botón "Normalizar todo" en la pestaña Propuestas, que encola `todo` con disparo `NORMALIZADOR`.

### Fase 5 — Calibración, AUTO y observación
- La precisión por regla se calcula desde `cromo_propuesta`. El panel sugiere habilitar AUTO cuando la precisión es ≥ 95 % con N ≥ 30 decisiones; el cambio de modo es decisión del admin.
- **Observación:** la siguiente evaluación post-ingesta vuelve a puntuar lo `EN_OBSERVACION`.
  - Si la confianza sigue sobre el umbral, pasa a `APLICADA`.
  - Si cae o hay veto, se revierte y queda `REVERTIDA`.
- **Aviso:** se reusa `inconsistencias_reporte.avisar_casos_nuevos`, que publica por WS en `admin-notifications` y por Slack si está activo. Avisa de propuestas nuevas, aplicaciones AUTO, presupuestos excedidos y reversiones.

### Fuera de este plan (propuestas para una segunda etapa)
- Retiro de decisiones caducas: alias cuyo origen ya no existe, pelos excluidos que Cromo dejó de etiquetar.
- Alias transitivos (A→B→C).
- Verificación automática de REPORTADA.
- Huecos de permisos y CSRF del relevamiento: `asociar` huérfanas sin admin; `PENDIENTE_REVISION` sin CSRF.

## Archivos críticos
- Nuevos:
  - `core/services/cromo/arbitro/{__init__,senales,motor,acciones,evidencia,cola}.py`
  - `core/services/cromo/arbitro/reglas/*.py`
  - `db/alembic/versions/20261020_01_cromo_arbitro.py`
  - `web/frontend/src/api/arbitroCromo.ts`
- Modificados:
  - `consolidacion_service.py`
  - `tracking_service.py`
  - `servicio_odf_override_service.py` (`origen`, `propuesta_id`, `confirmar=False`)
  - `inconsistencias_cromo.py` (enganche post-ingesta)
  - `modules/botellas_recalculo_worker/worker.py`
  - `web/app/main.py`
  - `AdminInconsistenciasCromoViewer.vue`
  - `db/models/cromo.py`
- Docs: `docs/modulo_ingesta_cromo.md` (sección Árbitro), `docs/infra.md`, `docs/db.md`, PR diario.

## Ejecución
- Worktree propio: `agent_worktree.py start --agent claude-cromo --type feat --task arbitro-cromo`.
- Lease `db:migrations`.
- Skills: `alembic-migrations`, `pytest-focas`, `cromo-diagnostico-real` (validar `servicio_at62` / `pelo_conectado` en caminos reales antes de confiar en la regla), `frontend-spa-architecture`, `nocturne-token-compliance`.
- Subagent-driven-development por fase.
- Sólo dev. Prod requiere un aviso aparte y el orden de deploy del runbook: migración, luego `cromo_worker`, luego web y workers.

## Verificación
1. **Unit (sin DB):** cada regla como función pura sobre fakes, cubriendo:
   - el puntaje y los vetos;
   - el presupuesto excedido, que no aplica nada;
   - un rechazo con el mismo `evidencia_hash`, que no se re-propone;
   - la observación con reversión.

   Patrón de `tests/test_cromo_inconsistencias.py`.
2. **Real DB:** patrón de `tests/test_cromo_inconsistencias_real_db.py`, con savepoint e ids sintéticos `999_920_xxx`.
   - El override AUTO saca el servicio de "sin ODF" sin cambiar `clasificar_caminos`.
   - Revertir lo restituye.
   - `GEMELO_VACIO` crea el alias y lo revierte.
   - Los CHECK de la migración se cumplen, y el downgrade funciona.
3. **Guardias existentes en verde:** `tests/test_cromo_cuarentena_lectores.py` (el árbitro lee la vista, no la tabla), `test_cromo_cuarentena_real_db.py`, `test_cromo_inconsistencias*.py`, `test_web_cromo_inconsistencias.py`.
4. **E2E en dev:**
   - `@Registrador track` sobre uno de los 17 servicios de alta confianza. Esperado: fila en `cromo_evidencia_camino`, job en la cola y propuesta `SOMBRA` visible en el viewer, sin filas nuevas en `cromo_servicio_odf_override` (comparar el `count(*)` antes y después).
   - "Normalizar todo": comparar contra la línea base (≈17 `ODF_POR_CAMINO` con evidencia sólo local y tope de 60, ≈31 `CONTRADICCION_SERVICIO`, 4 `GEMELO_VACIO`, 8 `ODF_GEMELA_ISLA`, 28 `GEMELO_OPERATIVO`).
   - Pasar `ODF_POR_CAMINO` a AUTO, repetir el track y verificar el override AUTO, la salida del listado "sin ODF" y que el número de trackings y su clasificación no cambian.
