# Nombre de archivo: infra.md
# Ubicación de archivo: docs/infra.md
# Descripción: Documentación del módulo Infraestructura FO para la SPA Vue 3 y la API asociada

# Infraestructura FO — LAS-FOCAS

## Resumen

El módulo **Infraestructura FO** permite la gestión de cámaras de fibra óptica, trackings de servicio y el **Protocolo de Protección** (baneo de cámaras). Vive en la SPA Vue 3 del panel web y consume endpoints JSON del backend.

## Funcionalidades principales

### Búsqueda de cámaras
- **Smart Search**: búsqueda libre por servicio, dirección, cámara, cable
- **Filtros rápidos**: por estado (Libre, Ocupada, Baneada, Detectada, Tracking)
- **Upload de tracking**: carga archivos `.txt` de tracking para asociar cámaras a servicios
- El grid sólo devuelve **Cámaras raíz** (`camara_padre_id IS NULL`, ver "Jerarquía Cámara → Botellas"
  más abajo) — las Botellas viven dentro del detalle de su Cámara, no como tarjetas propias en el
  dashboard.

### Jerarquía Cámara → Botellas

Muchas filas de `app.camaras` no son cámaras físicas distintas sino **Botellas** (cajas de empalme)
dentro de la MISMA cámara física, distinguidas sólo por un sufijo textual en el nombre — ej.
"Cra 14 de Julio 240 CF" y "Cra 14 de Julio 240 Bot 2 CF" son la misma cámara con 2 botellas. Desde
2026-08-10 esa jerarquía es explícita vía `Camara.camara_padre_id` (FK auto-referencial, exactamente
2 niveles — una Cámara tiene `camara_padre_id IS NULL`, una Botella lo tiene seteado apuntando a su
Cámara).

> **Nota de naming**: el módulo Cromo (`app.cromo_botellas`, ~11.100 filas) también usa el término
> "Botella" para un concepto de dominio totalmente distinto y sin ninguna relación con
> `app.camaras`/`camara_padre_id`. Son dos homónimos de dos dominios separados — no confundir al leer
> código o datos de ambos módulos. Ver `docs/modulo_ingesta_cromo.md`.

**Detección de agrupación**: `modules/slack_baneo_notifier/camara_search.py::RE_BOT_SUFIJO`
(`\bbot\.?\s*[1-9](?!\d)`, case-insensitive) detecta el sufijo "Bot N"; usa una clase de un solo dígito
a propósito para no confundir un nombre de calle como "Bot 30 de Septiembre..." con un índice de
botella. `core/services/camara_hierarchy_service.py::extraer_base()` remueve sólo el token "Bot N" del
nombre (preservando el resto, ej. el sufijo "CF" final) para obtener el nombre base con el que agrupar.

**Alta en vivo**: `core/services/camara_hierarchy_service.py::resolver_o_crear_padre()` se invoca desde
los 6 caminos de alta/promoción de `Camara` (tracking `.txt`, import Excel, sync Google Sheets, alta
Slack, y los dos endpoints admin `admin_dar_de_alta_camara`/`admin_aprobar_camara` en `web/app/main.py`)
— si el nombre nuevo matchea `RE_BOT_SUFIJO`, reusa la Cámara padre `INFERIDO` existente para esa base
o crea una nueva, y vincula la fila nueva como Botella.

**Backfill histórico** (`scripts/camara_backfill_padre_botella.py`, corrido una vez contra dev el
2026-08-10): agrupa TODAS las filas raíz existentes por nombre base normalizado; para cada grupo con
algún sufijo "Bot N" crea SIEMPRE una Cámara padre nueva (`origen_datos=INFERIDO`) y vincula como
Botellas tanto las filas con sufijo como la variante "pelada" (sin sufijo) — **nunca promueve una fila
existente a padre**, para no heredar por accidente un `origen_datos`/historial que no corresponde.
El estado de la Cámara padre nueva se calcula como el más restrictivo del grupo
(`BANEADA > OCUPADA/DETECTADA > LIBRE`; `PENDIENTE_REVISION` queda excluido de este cálculo — es un
estado administrativo, no de severidad física, y grupos con algún miembro en `PENDIENTE_REVISION` se
saltan por completo en la escalada). Resultado real en dev: 1645→1931 filas, 286 Cámaras padre creadas,
424 Botellas vinculadas, 188 grupos escalados de estado, 9 grupos saltados por `PENDIENTE_REVISION`.

**Cascada de baneo (bidireccional y completa)**: banear o desbanear CUALQUIER miembro de un grupo
(Cámara o Botella) afecta a TODO el grupo — Cámara padre + todas las Botellas hermanas.
`core/services/camara_estado_service.py::aplicar_estado_a_grupo()` es el único punto del código que
debe escribir `Camara.estado` directamente; `create_ban`/`lift_ban`
(`core/services/protection_service.py`) y `override_camara_estado_manual` (import Excel masivo + modal
admin de un click) lo usan en vez de asignar `camara.estado = X` a mano. Sin esto, banear una Botella
por Excel o por el modal admin dejaba a su Cámara padre mostrándose libre — el hueco de seguridad de
campo real que motivó este diseño.

**Limitación conocida — duplicados sin sufijo "Bot N"**: el backfill y `resolver_o_crear_padre` sólo
agrupan por el patrón "Bot N". Direcciones duplicadas con una plantilla de nombre distinta (ej.
"Cámara 14 de Julio 240", origen `SHEET`, sin ningún sufijo ni palabra en común con "Cra 14 de Julio
240 CF" más allá de la dirección) NO se detectan ni se fusionan — quedan como una segunda Cámara raíz
independiente, visible como una tarjeta separada en el dashboard. Confirmado en dev: id=1638 "Cámara 14
de Julio 240" (BANEADA, origen SHEET) coexiste con el grupo real id=2663/753/1065. Fusionar estos casos
requiere reasignar FKs de `empalmes`/`cables`/`ingresos`/`camara_alias` de forma potencialmente
destructiva — queda fuera de alcance de este backfill, es trabajo de un ticket separado con su propio
plan de validación.

**Escritura de `Ingreso` sobre el grupo**: fuera de alcance — la tabla `app.ingresos` no tiene ningún
camino de escritura real hoy (0 filas, 0 endpoints), por lo que no hay nada que propagar todavía. Ver
"Registros" más abajo, pestaña Ingresos placeholder.

**Endpoint**: `GET /api/infra/camaras/{camara_id}/botellas` — devuelve las Botellas de una Cámara,
unificando legado (self-FK de esta sección, lista vacía si `camara_id` es en sí una Botella) y Cromo
(`CromoBotella.camara_id`, desde 2026-08-11, ver sección "Cámara padre para Botellas Cromo" más abajo).
Consumido por `ModalBotellas.vue` desde una 4ª tarjeta "Botellas" en `CamaraDetailView.vue`.

### Submódulo Botellas (listado unificado, 2026-08-10; Cámara padre + estado para Cromo desde 2026-08-11)

Vista independiente en el sidebar (`Infraestructura FO → Botellas`, ruta `/infra/Botellas`) que lista
**dos fuentes de datos**, ambas llamadas históricamente "Botella":

1. **`app.cromo_botellas`** (mirror de sólo lectura de Cromo Red, ~11.100 filas vigentes) — siempre
   ordenadas primero. Verificado contra datos reales que Cromo tampoco distingue Cámara/Poste/Botella
   como entidades separadas — `app.cromo_clases` sólo tiene la entidad `BOTELLA` (clases
   68/121/122/123/124/125) para las tres cosas a la vez, diferenciadas sólo por texto libre en `nombre`
   (ej. "Poste Marcos Paz 2111" y "Cra. Pumacahua 48" conviven en la misma clase 68).
   Desde 2026-08-11 (ver sección "Cámara padre para Botellas Cromo" más abajo) **sí tiene** `camara_id`
   y `estado` propios, poblados por `scripts/cromo_backfill_camara_padre.py` — una fila sin backfillear
   expone `estado='NO_OPERATIVA'` (default seguro, nunca ausencia de dato).
2. **`app.camaras` con `camara_padre_id` seteado** (Botellas "legado" de la jerarquía Cámara→Botella de
   Infra/Baneos, ~424 filas) — con estado operativo real, ordenadas después de Cromo.

Filtro **"Mostrar No operativas"** (checkbox, oculto por defecto): tanto este listado unificado
(`incluir_no_operativas` en `GET /api/infra/botellas/buscar`) como el dashboard principal de Cámaras
(`InfraTab.vue`, `incluir_no_operativas` en `POST /api/infra/smart-search`) ocultan por defecto las
filas con `estado='NO_OPERATIVA'` de ambos orígenes — infraestructura sintetizada por nombre sin
ninguna señal operativa real detrás, que de otro modo contamina la vista con "fantasmas". El toggle
revela esas filas sin necesidad de tocar el selector de estado existente (son ortogonales, se
combinan). El detalle de una Cámara puntual (`GET /api/infra/camaras/{id}/botellas`) **nunca** aplica
este filtro — mostrar menos botellas de las que un grupo realmente tiene sería el mismo riesgo de
seguridad de campo que motivó todo este diseño.

Se combinan en **una sola query SQL `UNION ALL`** (`core/services/botellas_unificadas_service.py::buscar_botellas_unificadas`,
mismo patrón de `core/services/cromo/inventario.py::buscar_cables`: CTE reusado por COUNT y SELECT,
`CAST(:param AS tipo)` explícito) en vez de dos queries por engine (una async contra Cromo, una sync
contra Infra) combinadas con aritmética de paginación en Python — evita mezclar sesiones sync+async en
el mismo handler y evita lógica de "ventaneo" nueva. Endpoint: `GET /api/infra/botellas/buscar` (ver
más abajo). Frontend: `BotellasInventarioView.vue`, mismo patrón de scroll infinito + toggle
tarjeta/lista que `ServiciosView.vue` (`IntersectionObserver`, debounce 320ms, `localStorage` para el
modo de vista) — no el patrón de páginas numeradas de `InventarioCablesCromoView.vue`.

**Identidad NO unificada, a propósito**: un `n_id` de Cromo y un `Camara.id` legado son espacios de ID
independientes que pueden coincidir en valor sin ser la misma fila (ej. ambos pueden ser `753`). El
frontend nunca usa `id` solo como clave — siempre el compuesto `${origen}:${id}` (dedup, `:key` de Vue,
y el query param `?origen=` de la ruta de detalle). Un mismo sitio físico con fila en ambas fuentes
sigue apareciendo dos veces en la lista, por diseño explícito del usuario ("sin eliminarlas").

**Click-through sin UI de detalle nueva**: la ruta `/infra/Camaras/Botellas/ID:id(\d+)?origen=` (mismo
patrón de "ID" pegado al param que `/infra/cromo/cables/ID:nId(\d+)`) es un **shim de redirección**
(`BotellaDetalleUnificadaView.vue`) que reenvía a la vista real según origen: `?origen=legado` →
`/infra/Camaras/{id}` (reusa `CamaraDetailView.vue` tal cual, una Botella legado ya es una `Camara`
más); cualquier otro valor (incluido Cromo) → `/infra/cromo/verificador?tipo=botella&n_id={id}` (reusa
`VerificadorCromoView.vue` tal cual). No se construyó una segunda UI de detalle para datos que ya se
muestran correctamente en otro lado.

**Fuera de alcance, aún vigente**: fusión/deduplicación real de identidad entre ambas fuentes (un mismo
sitio físico con fila en Cromo y en legado sigue apareciendo dos veces, por diseño explícito).

### Cámara padre para Botellas Cromo (2026-08-11)

La resolución de "Cámara/Poste padre" para Botellas Cromo, diferida en el pase del 2026-08-10 (el
usuario había planteado primero ingerir cámaras/postes como objetos propios desde Cromo), se retomó
directamente sobre `cromo_botellas.nombre` por decisión explícita del usuario — **Cromo pasa a ser la
fuente de verdad** para esta jerarquía; el alta manual/por tracking de `app.camaras` queda como
legado en desuso a futuro (no se tocó ningún flujo en vivo en este pase, ver `docs/db.md`).

- **`CromoBotella` (`db/models/cromo.py`)** gana `camara_id` (FK a `app.camaras.id`, `ON DELETE SET
  NULL`) y `estado` (reusa el enum Postgres `camara_estado`, `NOT NULL DEFAULT 'NO_OPERATIVA'`, `CHECK`
  sólo admite `LIBRE/OCUPADA/BANEADA/NO_OPERATIVA` — Cromo no tiene equivalente de
  `DETECTADA`/`PENDIENTE_REVISION`, workflows exclusivos del legado). Migración `20260811_01`.
- Nuevos valores de enum: `CamaraEstado.NO_OPERATIVA` (default seguro, fail-closed, para entidades sin
  ninguna señal operativa real) y `CamaraOrigenDatos.INFERIDO_CROMO` (Cámara padre sintetizada por
  *este* backfill — distinto de `INFERIDO`, que es del backfill legado Bot-N).
- **Regex combinado** (`core/services/cromo/camara_padre_service.py::extraer_base_cromo`): intenta
  primero el sufijo real "Bot N" (mismo `RE_BOT_SUFIJO` que ya usa el legado — confirmado con el
  ejemplo real n_id 6638808 "Cra Plaza de los Ingleses CF" + variantes "Bot 2/3/4") y, si no matchea,
  un prefijo "Botella N &lt;nombre&gt;" (pedido explícito; sólo visto hasta ahora en texto libre de Slack,
  instrumentado con logging para confirmar/descartar su uso real en Cromo).
- **Política de estado**: una Cámara padre *nueva* nace siempre en `NO_OPERATIVA` (nunca `LIBRE` —
  `cromo_botellas` no aporta ninguna señal operativa real, así que asumir disponibilidad sería el mismo
  riesgo de seguridad de campo ya rechazado en 2026-08-10). Si el nombre coincide con una `Camara`
  legado ya existente, se reutiliza esa fila y se hereda su estado real (no es inferencia — es un dato
  que ya existe y tiene auditoría en `app.camaras_estado_auditoria`), mapeado al vocabulario de 4
  valores de Cromo (`DETECTADA→OCUPADA`, `PENDIENTE_REVISION→NO_OPERATIVA`).
- **Script**: `scripts/cromo_backfill_camara_padre.py` (`--dry-run` soportado). Corrida real contra
  `lasfocasdev-postgres` (2026-08-11): 11.100 Botellas vigentes, 1.588 matchearon el regex, 1.172
  Cámaras padre nuevas creadas (`NO_OPERATIVA`), 416 vinculaciones reutilizaron 258 Cámaras legado
  reales (heredando `OCUPADA`/`LIBRE`/`BANEADA` según corresponda), 125 grupos escalados de estado, 1
  grupo con `PENDIENTE_REVISION` saltado a propósito.
- **Hallazgo de performance real** (no teórico): la primera implementación reutilizaba
  `resolver_o_crear_padre_desde_base` (la misma función del legado) llamándola una vez por cada
  Botella candidata — esa función re-consulta TODAS las Cámaras raíz en cada llamada, aceptable para
  1 llamada aislada por evento en vivo pero no para 1.588 llamadas en un loop batch (más de 25 minutos
  sin terminar, 78% CPU sostenido dentro de `lasfocasdev-api`, abortado manualmente). El script quedó
  con su propia resolución en memoria (una única carga de raíces con `selectinload` + diccionarios),
  corriendo en ~90 segundos contra los mismos datos. La función compartida del legado no se tocó — sigue
  siendo correcta para sus llamadores en vivo.
- **Limitación conocida, no resuelta en este pase**: `CromoBotella.estado` es una foto fijada en el
  momento del backfill (o su próxima corrida) — `aplicar_estado_a_grupo` sigue escribiendo sólo
  `Camara.estado` (único punto de escritura, no se tocó), así que un cambio de estado real posterior
  sobre la Cámara padre (ej. un baneo nuevo) no se propaga automáticamente a las `CromoBotella` ya
  vinculadas hasta la siguiente corrida manual del script (mitigado en parte por el endpoint de
  cambio de estado masivo del 2026-08-12, ver más abajo, para correcciones puntuales).

### Fallback de nombre exacto + bug real de idempotencia corregido (2026-08-12)

Extiende el backfill del 2026-08-11: de las 9.512 Botellas Cromo que quedaban huérfanas (86% del
total), la muestra real mostraba que casi ninguna era "sin información" — eran direcciones válidas
sin el patrón "Bot N"/"Botella N" (ej. real "Av Rivadavia 6041"). Se agregó un tercer paso a
`extraer_base_cromo`: si ni el sufijo ni el prefijo matchean, usa el **nombre exacto de la Botella**
(recortado de espacios) como nombre de su propia Cámara padre — política de estado sin cambios
(nace `NO_OPERATIVA`, fail-closed, igual que los dos caminos de regex). Sólo una Botella con
`nombre` vacío/`NULL` sigue sin resolución automática.

- **Bug real de idempotencia encontrado en `--dry-run` antes de aplicar (nunca tocó datos reales)**:
  la clasificación de una Cámara raíz como "padre ya establecido" vs. "pelada absorbible" (tanto en
  `resolver_o_crear_padre_desde_base` como en la resolución en memoria propia del script) sólo miraba
  `Camara.botellas` (self-FK legado) — una Cámara padre creada por el backfill de Cromo tiene CERO
  Botellas legado (sus hijas son `CromoBotella`, tabla distinta), así que en **cualquier corrida
  posterior** del backfill (o cualquier llamada en vivo con el mismo nombre normalizado, ej. el
  listener de Slack) se la trataba como "pelada" y se la absorbía como Botella de un padre nuevo
  duplicado — dejando su `camara_id` de Cromo apuntando a una fila que dejó de ser raíz. El `--dry-run`
  de esta corrida detectó **~400 vinculaciones que habrían quedado inválidas** de no corregirse antes
  de aplicar. Corregido con `core/services/camara_hierarchy_service.py::ids_camaras_con_cromo_hijos`
  (set de IDs con `CromoBotella.camara_id` propio, consultado una vez y usado en ambos chequeos) —
  fix compartido entre el backfill y la función en vivo, así que también protege contra el mismo
  problema en el listener de Slack y en `camara_backfill_padre_botella.py` a futuro.
- **Corrida real contra `lasfocasdev-postgres` (post-fix)**: 9.512 candidatas, **9.512 resueltas por
  el fallback** (8.598 Cámaras padre nuevas, 914 reutilizando Cámaras existentes — incluidas las 1.172
  creadas por la corrida del 2026-08-11, ahora protegidas), 933 grupos escalados de estado. **Botellas
  Cromo huérfanas: 9.512 → 0.** Auditoría de invariante (`camara_id` siempre apunta a una raíz):
  0 violaciones post-commit.
- **Endpoint de cambio de estado masivo**: `PUT /api/infra/botellas/estado` (admin, CSRF) — recibe una
  lista de items `{origen, id}` (misma clave compuesta del inventario unificado, nunca un id numérico
  solo) + un `estado` de los 4 vigentes. Origen `legado` cascada por grupo completo vía
  `aplicar_estado_a_grupo` (dedupeado por raíz de grupo); origen `cromo` hace un `UPDATE` masivo
  directo sobre `CromoBotella.estado` (foto propia, no cascada — ver limitación arriba). Ver
  `core/services/botellas_estado_masivo_service.py`.
- **Frontend (`BotellasInventarioView.vue`)**: la vista lista gana un checkbox de selección por fila
  (`@click.stop` para no disparar la navegación al detalle de la fila) y una barra de acciones masivas
  con selector de estado — **"No operativa" es la primera opción** (la más relevante para marcar
  infraestructura fantasma detectada manualmente), seguida de Libre/Ocupada/Baneada.

### Estados operables: retiro de DETECTADA y del pseudo-estado "Tracking" (2026-08-11)

Decisión explícita del usuario: el estado operable de Cámara/Botella se redujo a **4 valores** —
`LIBRE`, `OCUPADA`, `BANEADA`, `NO_OPERATIVA`. `DETECTADA` (y el filtro client-side "Tracking" del
dashboard, basado en `rutas.length > 0`) quedaron retirados:

- `DETECTADA`/`PENDIENTE_REVISION` **siguen existiendo en el enum de Postgres** (no se puede remover
  un valor de enum sin recrear el tipo) — sólo dejaron de ser **seteables**: `estados_disponibles`
  (`GET /api/infra/camaras/{id}/estado`) y la validación de `POST /api/infra/camaras/{id}/estado`
  ahora sólo aceptan los 4 valores vigentes.
- `core/services/camara_estado_service.py::_estado_sugerido` y
  `core/services/protection_service.py::_determinar_estado_restauracion` dejaron de preservar
  `DETECTADA` — cualquier cómputo de estado sugerido/restauración cae al mismo cálculo
  BANEADA/OCUPADA/LIBRE que el resto de los casos.
- `scripts/retirar_estado_detectada.py` (nuevo, `--dry-run` soportado): migra retroactivamente toda
  fila `estado=DETECTADA` a su estado real, vía `aplicar_estado_a_grupo` (cascada de grupo completa).
  Corrida real contra `lasfocasdev-postgres` (2026-08-11): **1.053 filas migradas, 100% a `LIBRE`**
  (0 incidentes de baneo activos y 0 ingresos activos en todo el sistema en ese momento). **Hallazgo
  real durante la corrida**: 6 filas no fueron alcanzadas por la cascada de grupo porque estaban en
  una **cadena de más de 2 niveles** (`camara_padre_id` apuntando a otra fila que a su vez es Botella
  de una tercera — ej. reales ids 163→2552→2553), violando la invariante "exactamente 2 niveles" que
  toda la jerarquía Cámara/Botella asume. El script tiene una Fase 2 que corrige esas filas
  directamente (sin cascada de grupo, que no puede alcanzarlas) — la cadena rota en sí **no se
  corrigió**, queda como el mismo tipo de anomalía de datos ya documentada para duplicados de Cámara
  sin sufijo Bot-N (ver más abajo).
- `InfraTab.vue`: el chip "TRACKING" se quitó de `legendItems`/`legendCounts`; el filtro rápido de
  estado ahora sólo ofrece Libre/Ocupada/Baneada/No operativa.

### Cámaras duplicadas — Unificación manual (2026-08-11)

Limitación conocida desde el 2026-08-10 (duplicados de Cámara sin sufijo "Bot N", que
`resolver_o_crear_padre_desde_base` no agrupa por no compartir ningún token normalizado — ej. real
"Cámara 14 de Julio 240" vs "Cra 14 de Julio 240 CF") — confirmada a mayor escala: **47 grupos de
duplicados reales, 99 Cámaras raíz involucradas** de un total de 2.554. Resuelto con un flujo manual
de unificación, no automático (un humano decide qué dos Cámaras son en verdad el mismo sitio físico).

- **Estrategia deliberada**: en vez de un hard delete o un flag "archivada" nuevo, la Cámara
  secundaria queda **re-parentada como Botella de la principal** (mismo `camara_padre_id` self-FK de
  la jerarquía Bot-N) — conserva el 100% de su auditoría/historial (`CamaraEstadoAuditoria` nunca se
  toca), desaparece sola del dashboard de raíces, y sus rutas/servicios/empalmes propios se agregan
  automáticamente al ver el detalle de la principal vía la misma lógica de "grupo" que ya usa toda la
  jerarquía Cámara/Botella. Lo único que SÍ hay que mover explícitamente: las Botellas propias de la
  secundaria (se aplanan directo a la principal, para no crear una cadena de 3 niveles) y las
  `CromoBotella` vinculadas a la secundaria (la agregación de Botellas Cromo no es recursiva por
  grupo — se reasignan directo). Ver `core/services/camara_merge_service.py`.
- El nombre de la secundaria queda como alias de la principal (`CamaraAlias`, si difiere y no existe
  ya). El estado final del grupo completo es el más restrictivo (`estado_mas_restrictivo`), mismo
  criterio que la cascada de baneo.
- **Endpoint**: `POST /api/infra/camaras/merge` (admin, CSRF). **Búsqueda liviana**:
  `GET /api/infra/camaras/buscar?q=...` (sólo `id/nombre/direccion/estado/botellas_count`, sin el
  N+1 de rutas/servicios/cables de `smart-search` — pensada para selectores/autocomplete, no para el
  dashboard). **Frontend**: botón "Unificar Cámara" en el header del detalle (`CamaraDetailView.vue`,
  sólo admin, sólo si la Cámara no es ella misma una Botella) → `ModalUnificarCamara.vue` (buscar
  duplicada → confirmar).
- **Hallazgo real de routing durante la verificación**: `GET /api/infra/camaras/buscar` chocaba con
  `GET /api/infra/camaras/{camara_id}` (registrada antes en `web/app/main.py`) — FastAPI matchea por
  orden de registro, así que "buscar" se interpretaba como `camara_id: int` y devolvía 422. Corregido
  registrando `/camaras/buscar` ANTES de la ruta con parámetro.

### Botellas Cromo huérfanas — resolución manual (2026-08-11; automatizado casi al 100% desde 2026-08-12)

**Estado 2026-08-11**: el backfill automático (`scripts/cromo_backfill_camara_padre.py`) sólo
vinculaba el 14% de las Botellas Cromo vigentes (1.588/11.100) — el resto, 9.512 filas, quedaban
"huérfanas" (`camara_id IS NULL`). Verificado contra una muestra real: **no eran nombres sin
información** — eran direcciones válidas con ruido de formato que el regex de sufijo/prefijo no
cubría (paréntesis "(a instalar)", sufijo de localidad tras guión, abreviatura "Tza" no reconocida,
puntuación interna en "C.F").

**Actualizado 2026-08-12**: el fallback de nombre exacto (ver sección más arriba) resolvió las
9.512 restantes — hoy **0 Botellas Cromo vigentes quedan huérfanas**. El flujo manual descripto
abajo sigue existiendo (endpoints, componentes, todo vigente) para el único caso que el fallback no
puede resolver — `nombre` vacío/`NULL` — y para reasociar a mano si el resultado automático de una
Botella puntual fuera incorrecto.

- **Backend**: `core/services/cromo/orfanas_service.py` — `buscar_huerfanas` (lectura async, paginada,
  `ILIKE` sobre nombre/calle/localidad) y `asociar_huerfanas` (síncrona, toca `CromoBotella` y
  `Camara` en la misma sesión — mismo patrón que el script de backfill). Asociar a una Cámara
  existente hereda su estado real; crear una nueva la deja en `NO_OPERATIVA` (mismo criterio
  fail-closed del backfill automático).
- **Endpoints**: `GET /api/infra/cromo-botellas/huerfanas`, `POST /api/infra/cromo-botellas/asociar`
  (body `{n_ids, camara_id?, nombre_nueva_camara?}` — exactamente uno de los dos últimos), y
  `GET /api/infra/cromo-botellas/{n_id}/estado-asociacion` (chequeo liviano de una sola fila).
- **Frontend — masivo**: `BotellasInventarioView.vue` gana el toggle "Sólo huérfanas (sin Cámara
  asociada)", que cambia la fuente de datos al endpoint de huérfanas y habilita checkboxes de
  selección múltiple + una barra de acción masiva ("Asociar a Cámara").
- **Frontend — individual**: `BotellaDetalleUnificadaView.vue` (antes un shim de redirección puro)
  ahora chequea primero si la Botella Cromo está huérfana; si lo está, muestra un panel de resolución
  en vez de redirigir directo al Verificador.
- Ambos flujos comparten el mismo componente `ModalAsociarHuerfanas.vue` (buscar Cámara existente o
  escribir el nombre de una nueva), recibiendo 1 o N `n_ids` según el caso.

### Ingresos sin match — reemplaza el auto-registro `PENDIENTE_REVISION` (2026-08-11)

Decisión explícita del usuario: **el ingreso de un técnico nunca se rechaza**, y si no matchea contra
el inventario ya no se auto-registra una `Camara` nueva en `PENDIENTE_REVISION` — ese flujo quedaba
sin sentido con Cromo como fuente de verdad ("si no se encuentra una cámara es porque el técnico la
escribió mal o no matchea por diferencias de escritura", no porque falte darla de alta). En su lugar,
se registra el caso en `app.ingresos_sin_match` — información de sólo lectura para revisión manual y
mejora del regex de búsqueda, sin crear ninguna entidad de infraestructura.

- **Alcance**: los dos flujos que auto-registraban una Cámara al no encontrar match — el bot de Slack
  (`modules/slack_baneo_notifier/listener.py::_construir_respuesta_camara`) y la carga de tracking
  (`web/app/main.py::upload_tracking_web`). El técnico de Slack recibe un mensaje que aclara que
  puede ser un error de formato/tipeo y que **puede continuar con el ingreso igual** — nunca lee como
  un rechazo. El tracking simplemente deja `Empalme.camara_id = NULL` para esa ubicación (columna ya
  nullable) en vez de crear una Cámara `DETECTADA`/`TRACKING`.
- **No se toca** el panel admin "Cámaras Pendientes de Revisión" (`GET/POST /api/admin/infra/camaras/pendientes*`)
  — sigue disponible para gestionar las 34 filas legado ya existentes al 2026-08-11, simplemente deja
  de recibir filas nuevas.
- **Endpoints nuevos**: `GET /api/admin/infra/ingresos-sin-match` (filtro opcional `revisado`),
  `POST /api/admin/infra/ingresos-sin-match/{id}/marcar-revisado`. **Frontend**: nueva sección
  acordeón "Ingresos sin match" en `AdminBaneos.vue`, mismo patrón visual que "Cámaras Pendientes".
- **Fuera de alcance, encontrado pero no corregido**: `core/services/infra_service.py::_get_or_create_camara`
  (líneas ~260-310, usado por el flujo "Tracking V2"/`TrackingResolutionService`) tiene el mismo
  patrón de auto-creación `DETECTADA`/`TRACKING` — no fue parte del alcance confirmado para este pase
  (que cubrió específicamente el bot de Slack y `upload_tracking_web`), queda como hallazgo para una
  iteración futura.

### Vista principal y detalle dedicado
- **Tarjeta principal resumida**: cada cámara muestra solo nombre canon, ID numérico interno y estado.
- **Vista dedicada por cámara**: `GET /infra/Camaras/:id` dentro de la SPA Vue 3.
- **Dashboard de detalle**: tarjetas clickeables para alias, registros y servicios asociados.
- **Edición de estado reubicada**: el botón `Editar estado` sale de la tarjeta principal y vive en el header del detalle.

### Detalle operativo por cámara
La vista dedicada realiza carga paralela contra endpoints same-origin del servicio `web`:

- `GET /api/infra/camaras/{id}`
- `GET /api/infra/camaras/{id}/aliases`
- `GET /api/infra/camaras/{id}/registros`
- `GET/POST /api/infra/camaras/{id}/estado` para edición admin con CSRF

En esta iteración, **Registros** muestra solo la lógica operativa ya existente:

- pestaña **Ingresos** estructurada sobre un arreglo reactivo vacío, lista para futura hidratación desde backend
- pestaña **Baneos** con historial ordenado por fecha de inicio descendente y accordions retraídos por defecto
- auditoría manual de cambios de estado (`app.camaras_estado_auditoria`) como trazabilidad complementaria dentro de la pestaña de baneos

La tarjeta **Servicios Asociados** muestra la lista de IDs de servicio asociados ordenada de mayor a menor. Cada ID abre un segundo `dialog` modal superpuesto con el tracking detallado del servicio, reutilizando `TrackingDetail.vue` y la descarga del TXT actual.

Para el detalle fino de la UX web y del apilado de modales, la referencia principal queda en `docs/web.md`.

### Contratos y seguridad

- La vista usa contratos JSON del backend y no duplica lógica de negocio en el frontend.
- Las ediciones de estado requieren sesión válida y CSRF.
- Los listados se renderizan desde datos tipados; no se debe introducir DOM directo ni plantillas legacy.

### Protocolo de Protección (Baneo)
Sistema para proteger cámaras durante afectaciones de servicio, impidiendo trabajos en ellas hasta resolución.

#### Flujo de baneo
1. Click en **🚨 Protocolo Protección**
2. Wizard guiado: ticket, servicio afectado, servicio protegido, motivo
3. Confirmación y ejecución del baneo
4. Las cámaras cambian a estado `BANEADA`

#### Gestión de baneos activos
- **Badge indicador**: muestra cantidad de baneos activos en el header
- **Indicador de cámaras**: total de cámaras restringidas en el header
- **Modal de baneos activos**: click en el badge abre el modal con todos los baneos

### Notificaciones de baneo (Dar Aviso)

> **Cambio importante (2026-04-17)**: El botón "Dar Aviso" fue movido del header principal al modal de baneos activos.

#### Flujo anterior (deprecado)
El botón global "Dar Aviso" solo permitía notificar el primer baneo activo, causando que al tener múltiples baneos, solo se pudiera enviar aviso de uno.

#### Flujo actual
1. Click en el badge **🔒 N ACTIVOS** para abrir el modal
2. Cada baneo tiene su propio botón **📧 Dar Aviso**
3. Click en el botón abre el editor de correo con datos específicos de ese baneo
4. Enviar correo o descargar como EML

**Beneficios:**
- Independencia de avisos: cada baneo se notifica individualmente
- No hay mezcla de datos entre baneos
- El usuario puede enviar avisos de múltiples baneos consecutivamente

### Indicador global de cámaras afectadas

En el header de Infraestructura FO se muestra un indicador con el total de cámaras baneadas sumando todos los protocolos activos:

```
📷 29 cámaras restringidas
```

Este indicador:
- Aparece solo cuando hay baneos activos
- Suma las cámaras de todos los baneos
- Se actualiza al crear/levantar baneos

## Componentes UI

### Header principal
```
[🔒 2 ACTIVOS] [📷 29 cámaras restringidas] [🚨 PROTOCOLO PROTECCIÓN] [🔌 FO INFRA]
```

### Modal de baneos activos
```
┌─────────────────────────────────────────────┐
│ 🔒 Baneos Activos                        ✕  │
├─────────────────────────────────────────────┤
│ Cámaras protegidas por el Protocolo...      │
│                                             │
│ ┌─────────────────────────────────────────┐ │
│ │ MKT-1253765              ⏱️ 3.87h       │ │
│ │ Afectado: 52547 → Protegido: 52547      │ │
│ │ 📅 10/3/2026, 11:06:15                  │ │
│ │ [📧 Dar Aviso] [🔓 Levantar Baneo]      │ │
│ └─────────────────────────────────────────┘ │
│                                             │
│ ┌─────────────────────────────────────────┐ │
│ │ MKT-1241208              ⏱️ 3.88h       │ │
│ │ Afectado: 93152 → Protegido: 93155      │ │
│ │ 📅 10/3/2026, 11:05:04                  │ │
│ │ Corte de FO                             │ │
│ │ [📧 Dar Aviso] [🔓 Levantar Baneo]      │ │
│ └─────────────────────────────────────────┘ │
│                                             │
│ ☐ Enviar aviso por correo al desbanear     │
│                                  [Cerrar]   │
└─────────────────────────────────────────────┘
```

## API Endpoints

### GET /api/infra/camaras/{camara_id}
Obtiene el resumen operativo base de una cámara para la vista dedicada. Incluye nombre, ID, estado, editabilidad y servicios/rutas asociados.

### GET /api/infra/rutas/{ruta_id}/tracking
Obtiene la secuencia de tracking de una ruta FO (`punta_a`, `tracking[]`, `punta_b`) para el modal de servicios de la vista dedicada.

### GET /api/infra/tracking/{ruta_id}/download
Descarga el TXT actual de una ruta. La vista dedicada lo usa desde la tarjeta **Servicios Asociados** para mantener paridad con el flujo productivo.

### GET /api/infra/camaras/{camara_id}/aliases
Obtiene los alias conocidos de una cámara desde `app.camara_alias`.

### GET /api/infra/camaras/{camara_id}/registros
Obtiene registros operativos parciales: auditoría manual de estado, baneos relacionados y placeholders de ingresos/egresos.

### GET /api/infra/camaras/{camara_id}/botellas
Obtiene las Botellas de una Cámara, unificando ambos orígenes: legado (self-FK, jerarquía Cámara/Botella de esta sección) + Cromo (`CromoBotella.camara_id`, vigentes). Cada ítem lleva `origen: "legado"|"cromo"`. Nunca aplica el filtro de "No operativa" — es un drill-down sobre un grupo ya identificado. Lista de legado vacía si `camara_id` es en sí una Botella legado.

### GET /api/infra/botellas/buscar
Listado unificado de Botellas Cromo + legado (ver sección "Submódulo Botellas" más arriba). Query params: `q` (`ILIKE` sobre nombre, +calle/localidad para Cromo), `limit` (default 30, clamp 1-100), `offset`, `incluir_no_operativas` (bool, default `false` — oculta `estado='NO_OPERATIVA'` de ambos orígenes). Respuesta: `{total, limit, offset, incluir_no_operativas, botellas: [{origen: "cromo"|"legado", id, nombre, estado}]}` — `estado` real para ambos orígenes desde 2026-08-11 (antes, siempre `null` para `origen="cromo"`).

### PUT /api/infra/botellas/estado
Cambia el estado de un lote de Botellas de origen mixto (admin, CSRF). Body: `{items: [{origen: "cromo"|"legado", id}], estado, motivo?, csrf_token}` — `estado` uno de `LIBRE/OCUPADA/BANEADA/NO_OPERATIVA`. Legado cascada por grupo completo (`aplicar_estado_a_grupo`, dedupeado por raíz); Cromo actualiza `CromoBotella.estado` directo (foto propia, sin cascada). Respuesta: `{ok, estado_nuevo, legado_actualizadas, cromo_actualizadas, no_encontrados: [{origen, id}]}`. Ver sección "Fallback de nombre exacto + bug real de idempotencia corregido (2026-08-12)" más arriba y `core/services/botellas_estado_masivo_service.py`.

### GET /api/infra/camaras/buscar
Búsqueda liviana de Cámaras raíz por nombre (`ILIKE`), para selectores/autocomplete (unificación, asociación de huérfanas) — no para el dashboard. Query params: `q`, `limit` (default 10, clamp 1-50), `excluir_id`. Respuesta: `{camaras: [{id, nombre, direccion, estado, botellas_count}]}`. Registrada antes de `GET /api/infra/camaras/{camara_id}` en el código — ver nota de routing en "Cámaras duplicadas" más arriba.

### POST /api/infra/camaras/merge
Unifica dos Cámaras raíz duplicadas (admin, CSRF). Body: `{camara_principal_id, camara_secundaria_id, csrf_token}`. La secundaria pasa a ser Botella de la principal — ver sección "Cámaras duplicadas — Unificación manual" más arriba.

### GET /api/infra/cromo-botellas/huerfanas
Botellas Cromo vigentes sin `camara_id` (no matchearon el backfill automático). Query params: `q`, `limit` (default 30, clamp 1-100), `offset`. Respuesta: `{total, limit, offset, botellas: [{n_id, nombre, calle, localidad}]}`.

### GET /api/infra/cromo-botellas/{n_id}/estado-asociacion
Chequeo liviano de una Botella Cromo puntual — `{n_id, nombre, huerfana: bool}`. Usado por `BotellaDetalleUnificadaView.vue` antes de decidir si redirige o muestra el panel de resolución.

### POST /api/infra/cromo-botellas/asociar
Asocia una o más Botellas Cromo huérfanas a una Cámara existente o nueva. Body: `{n_ids, camara_id?, nombre_nueva_camara?, csrf_token}` — exactamente uno de `camara_id`/`nombre_nueva_camara`. Ver sección "Botellas Cromo huérfanas — resolución manual" más arriba.

### GET /api/admin/infra/ingresos-sin-match
Lista casos de ingreso (Slack o tracking) sin match contra el inventario — reemplaza el auto-registro `PENDIENTE_REVISION` (ver sección homónima más arriba). Query param opcional `revisado` (bool).

### POST /api/admin/infra/ingresos-sin-match/{caso_id}/marcar-revisado
Marca un caso como revisado — no muta ningún dato de infraestructura, sólo el flag de triage.

### GET /api/infra/ban/active
Lista todos los incidentes de baneo activos con conteo de cámaras.

**Response:**
```json
{
  "status": "ok",
  "total": 2,
  "incidentes": [
    {
      "id": 42,
      "ticket_asociado": "MKT-1253765",
      "servicio_afectado_id": "52547",
      "servicio_protegido_id": "52547",
      "ruta_protegida_id": 15,
      "usuario_ejecutor": "operador1",
      "motivo": "Afectación de servicio",
      "fecha_inicio": "2026-03-10T11:06:15+00:00",
      "activo": true,
      "duracion_horas": 3.87,
      "camaras_count": 29
    }
  ]
}
```

### GET /api/infra/ban/{incidente_id}
Obtiene detalle de un incidente específico para componer el correo.

### POST /api/infra/ban/create
Crea un nuevo baneo (Protocolo de Protección).

### POST /api/infra/ban/lift
Levanta un baneo y restaura el estado de las cámaras.

### POST /api/infra/notify/email
Envía notificación por correo de un baneo específico.

### POST /api/infra/notify/download-eml
Genera archivo EML para descargar y abrir en Outlook.

## Archivos relacionados

- `web/frontend/src/views/tabs/InfraTab.vue` - Tab principal de Infraestructura FO (dashboard, sólo Cámaras raíz)
- `web/frontend/src/views/CamaraDetailView.vue` - Vista dedicada por cámara (Alias, Registros, Servicios, Botellas)
- `web/frontend/src/components/infra/` - Modales aislados de alias, servicios, registros, botellas y edición de estado
- `web/frontend/src/router/index.ts` - Ruta SPA `/infra/Camaras/:id` (una Botella es una Camara más — reusa la misma ruta/vista)
- `web/app/main.py` - Endpoints web same-origin para listado y detalle; único consumidor real del frontend hoy
- `api/app/routes/infra.py` - Router montado en el servicio `api` (puerto 8011 dev / 8001 prod) con endpoints de cámaras/búsqueda equivalentes; **sin consumidor real en el frontend actual** (la SPA usa exclusivamente los endpoints same-origin de `web/app/main.py`) — deuda técnica preexistente, no se tocó en esta iteración
- `core/services/camara_estado_service.py` - Contexto/auditoría de estado, `miembros_del_grupo()`, `aplicar_estado_a_grupo()` (único punto que escribe `Camara.estado`), `obtener_ultima_transicion_a_baneada()`
- `core/services/camara_hierarchy_service.py` - Detección de sufijo "Bot N", extracción de nombre base, `resolver_o_crear_padre()` (alta en vivo), `estado_mas_restrictivo()`
- `core/services/protection_service.py` - Lógica de negocio del Protocolo de Protección (`create_ban`/`lift_ban`), con cascada de grupo completa
- `scripts/camara_backfill_padre_botella.py` - Backfill histórico de la jerarquía (idempotente, soporta `--dry-run`)
- `db/models/infra.py` - Modelos de cámaras (incl. `camara_padre_id`/`botellas`/`es_botella`), alias, auditoría e incidentes
- `db/alembic/versions/20260810_01_camara_padre_botella.py` - Migración: columna `camara_padre_id`, índice, `CHECK` anti-autoreferencia, valor `INFERIDO` en `camara_origen_datos`
- `core/services/botellas_unificadas_service.py` - Listado unificado Botellas Cromo + legado (`buscar_botellas_unificadas`, query `UNION ALL`)
- `web/frontend/src/views/BotellasInventarioView.vue` - Submódulo "Botellas" del sidebar (scroll infinito + toggle tarjeta/lista, patrón `ServiciosView.vue`)
- `web/frontend/src/views/BotellaDetalleUnificadaView.vue` - Shim de redirección por origen en `/infra/Camaras/Botellas/ID:id`
- `web/frontend/src/components/infra/BotellaCard.vue` - Tarjeta mínima (origen, ID, nombre, estado) del submódulo Botellas
- `web/frontend/src/api/botellas.ts` - Cliente frontend del listado unificado

## Historial de cambios

### 2026-08-12 - Fallback de nombre exacto, fix de idempotencia real, cambio de estado masivo

- **Agregado**: fallback de nombre exacto en `extraer_base_cromo` (3er paso, tras sufijo/prefijo) —
  resuelve el 100% de las Botellas Cromo con `nombre` no vacío. Botellas Cromo huérfanas: **9.512 →
  0** tras la corrida real.
- **Corregido — bug real de idempotencia** (detectado en `--dry-run` antes de aplicar, nunca tocó
  datos reales): una Cámara padre de Cromo (cero Botellas legado) se clasificaba como "pelada" en
  cualquier corrida posterior del backfill o llamada en vivo con el mismo nombre, y se absorbía como
  Botella de un padre duplicado — rompiendo el invariante "`camara_id` siempre apunta a una raíz"
  (~400 vinculaciones habrían quedado inválidas). Corregido con
  `core/services/camara_hierarchy_service.py::ids_camaras_con_cromo_hijos`, compartido entre el
  backfill y `resolver_o_crear_padre_desde_base` (protege también al listener de Slack y a
  `camara_backfill_padre_botella.py`).
- **Agregado**: `PUT /api/infra/botellas/estado` — cambio de estado masivo sobre Botellas de origen
  mixto (`core/services/botellas_estado_masivo_service.py`).
- **Agregado**: en `BotellasInventarioView.vue`, checkbox de selección por fila en la vista lista
  (con `@click.stop` para no colisionar con la navegación al detalle) y barra de acciones masivas con
  selector de estado ("No operativa" primero).
- Ver sección "Fallback de nombre exacto + bug real de idempotencia corregido (2026-08-12)" más
  arriba para el detalle completo.

### 2026-08-11 (cont.) - Retiro de DETECTADA, unificación de Cámaras, huérfanas Cromo, ingresos sin match

- **Retirado**: `CamaraEstado.DETECTADA` y el pseudo-estado "Tracking" del dashboard — estado
  operable reducido a LIBRE/OCUPADA/BANEADA/NO_OPERATIVA. `scripts/retirar_estado_detectada.py`
  migró 1.053 filas reales a `LIBRE` (0 incidentes/ingresos activos en el sistema); encontró y
  corrigió 6 filas en una cadena de más de 2 niveles (hallazgo de integridad de datos preexistente,
  no corregido en sí). Ver sección "Estados operables" más arriba.
- **Agregado**: unificación de Cámaras duplicadas (`POST /api/infra/camaras/merge`,
  `core/services/camara_merge_service.py`, `ModalUnificarCamara.vue`) — la secundaria pasa a ser
  Botella de la principal, conserva auditoría completa. 47 grupos de duplicados reales confirmados.
- **Agregado**: resolución manual de Botellas Cromo huérfanas (`core/services/cromo/orfanas_service.py`,
  3 endpoints nuevos, `ModalAsociarHuerfanas.vue`, toggle en `BotellasInventarioView.vue`, panel en
  `BotellaDetalleUnificadaView.vue`) — 9.512/11.100 Botellas Cromo vigentes son huérfanas hoy.
- **Reemplazado**: el auto-registro `PENDIENTE_REVISION` en ingresos sin match (bot de Slack +
  `upload_tracking_web`) por `app.ingresos_sin_match` (migración `20260811_02`) — el ingreso nunca
  se rechaza, sólo se registra el caso para revisión manual/mejora del regex. Panel admin
  "Cámaras Pendientes de Revisión" sigue disponible para las 34 filas legado, sin recibir nuevas.
- **Hallazgo real de routing**: `GET /api/infra/camaras/buscar` chocaba con
  `GET /api/infra/camaras/{camara_id}` por orden de registro de FastAPI — corregido reordenando.
- **Fuera de alcance, encontrado**: `core/services/infra_service.py::_get_or_create_camara`
  (flujo "Tracking V2") tiene el mismo patrón de auto-creación DETECTADA/TRACKING, no confirmado en
  el alcance de este pase.

### 2026-08-11 - Cámara padre + estado real para Botellas Cromo, filtro "No operativa"

- **Agregado**: `CromoBotella.camara_id`/`estado` (migración `20260811_01`), valores de enum
  `CamaraEstado.NO_OPERATIVA`/`CamaraOrigenDatos.INFERIDO_CROMO`, `core/services/cromo/camara_padre_service.py`
  (regex combinado sufijo+prefijo), `scripts/cromo_backfill_camara_padre.py`. Detalle completo en la
  sección "Cámara padre para Botellas Cromo" más arriba — retoma y resuelve lo que el pase del
  2026-08-10 había diferido explícitamente.
- **Agregado**: filtro "Mostrar No operativas" (oculto por defecto) en `InfraTab.vue` y
  `BotellasInventarioView.vue`, parámetro `incluir_no_operativas` en `smart-search` y
  `botellas/buscar`.
- **Corregido**: `buscar_botellas_unificadas` dejó de exponer `estado=NULL` fijo para Cromo — lee la
  columna real. `BotellaCard.vue`/`BotellasInventarioView.vue` dejaron de decidir "Sin estado
  operativo" mirando el origen; ahora miran si `estado` es `null` (compatible con filas pre y post
  backfill sin flag nuevo).
- **Corrida real contra `lasfocasdev-postgres`**: 1.588/11.100 Botellas vigentes vinculadas, 1.172
  Cámaras padre nuevas, 416 vinculaciones reusando 258 Cámaras legado reales, 125 grupos escalados de
  estado.
- **Hallazgo de performance real durante la verificación**: la implementación inicial reutilizaba la
  función de resolución del backfill legado (O(n) por llamada, pensada para 1 evento en vivo) en un
  loop de 1.588 iteraciones — no terminaba en 25+ minutos, 78% CPU sostenido en `lasfocasdev-api`.
  Corregido con resolución en memoria propia del script (~90s). Ver sección técnica arriba.
- **Fuera de alcance, documentado explícitamente**: deprecar el alta manual (`modules/slack_baneo_notifier/listener.py`)
  y por tracking (`POST /api/infra/upload_tracking`, sin consumidor Vue encontrado) de Cámaras legado —
  dirección estratégica declarada por el usuario, no un entregable de este pase. Propagación en vivo de
  cambios de estado de una Cámara padre hacia sus `CromoBotella` ya vinculadas (hoy es una foto fijada
  al momento del backfill, no hay push automático).

### 2026-08-10 - Submódulo Botellas: listado unificado Cromo + legado

- **Agregado**: submódulo "Botellas" en el sidebar (`Infraestructura FO → Botellas`, ruta `/infra/Botellas`) — lista `app.cromo_botellas` (siempre primero, sin estado operativo) y `app.camaras` con `camara_padre_id` seteado (legado, con estado real), sin fusionar ni eliminar duplicados entre fuentes, sólo diferenciadas con un badge de origen.
- **Agregado**: `core/services/botellas_unificadas_service.py::buscar_botellas_unificadas` — una sola query SQL `UNION ALL` (COUNT + SELECT, mismo patrón que `buscar_cables`) en vez de combinar dos engines (async Cromo + sync Infra) con aritmética de paginación en Python.
- **Agregado**: endpoint `GET /api/infra/botellas/buscar` (ver "API Endpoints" más arriba).
- **Agregado**: ruta `/infra/Camaras/Botellas/ID:id(\d+)?origen=` — shim de redirección (`BotellaDetalleUnificadaView.vue`), sin UI de detalle nueva: reenvía a `/infra/Camaras/{id}` (legado) o al verificador Cromo existente (`?tipo=botella&n_id=`).
- **Hallazgo real, confirmado contra `lasfocasdev-postgres`**: Cromo no distingue Cámara/Poste/Botella como entidades separadas (una sola entidad `BOTELLA` en `app.cromo_clases` cubre las clases 68/121/122/123/124/125) y sí tiene el mismo patrón de sufijo "Bot N" que `app.camaras` (ejemplo real: n_id 6638808 "Cra Plaza de los Ingleses CF" + 3 variantes "Bot 2/3/4") — pero resolver esa jerarquía sobre `cromo_botellas` queda deliberadamente fuera de este pase (decisión del usuario: primero ingesta de cámaras/postes propios desde Cromo, después script de vinculación).
- **Explícitamente fuera de alcance**: tarjeta "Cámara Padre" para Botellas Cromo, inferencia de estado operativo Cromo por coincidencia de nombre (riesgo de mostrar un estado de seguridad incorrecto), fusión/deduplicación real de identidad entre ambas fuentes.
- **Verificado end-to-end** contra `lasfocasdev-postgres`/`lasfocasdev-web` real (usuario QA temporal): `total=11524` sin filtro (11100 Cromo vigentes + 424 legado, exacto); orden "Cromo siempre primero" confirmado con `limit=5` sin filtro (las 5 primeras filas son Cromo); búsquedas reales ("Plaza de los Ingleses", "14 de Julio 240") devuelven los ejemplos esperados con `estado` correcto por origen.

### 2026-05-13 - Refactor de tarjetas FO y vista dedicada por cámara
- **Corregido**: la grilla principal vuelve a mostrar el `id` numérico real de cámara en lugar de depender de `fontine_id`.
- **Modificado**: las tarjetas principales se simplifican a `Nombre canon + ID + Estado`, removiendo detalle operativo inline.
- **Agregado**: ruta SPA `/infra/Camaras/:id` con vista dedicada `CamaraDetailView.vue`.
- **Agregado**: endpoints web same-origin `GET /api/infra/camaras/{id}`, `GET /api/infra/camaras/{id}/aliases` y `GET /api/infra/camaras/{id}/registros`.
- **Agregado**: modales aislados para alias conocidos, servicios asociados, registros y edición manual de estado.
- **Recuperado**: la tarjeta `Servicios Asociados` vuelve a exponer la secuencia de tracking productiva con tabs por ruta y descarga del TXT actual.
- **Corregido**: el modal `Editar estado` de la vista dedicada vuelve a usar el estilo dark coherente con el dashboard.
- **Diseño**: la tarjeta `Registros` se divide en tabs `Ingresos/Baneos`; los baneos usan accordions ordenados por fecha y los ingresos quedan maquetados hasta contar con backend dedicado.

### 2026-04-17 - Refactor de avisos individuales y conteo de cámaras
- **Eliminado**: Botón global "Dar Aviso" del header principal
- **Agregado**: Botón "Dar Aviso" individual en cada fila del modal de baneos
- **Agregado**: Indicador global de cámaras restringidas en el header
- **Modificado**: Endpoint `/api/infra/ban/active` ahora incluye `camaras_count`
- **Beneficio**: Soporte correcto para múltiples baneos activos simultáneos

### 2026-04-17 - Worker de notificaciones Slack para baneos
- **Agregado**: Nuevo contenedor `slack_baneo_worker` que envía periódicamente un reporte de cámaras baneadas a canales de Slack
- **Agregado**: Tabla `app.config_servicios` para configuración dinámica del worker (intervalo, canales, estado)
- **Agregado**: Panel admin en `/admin/Servicios/Baneos` para gestionar la configuración y verificar el health del worker
- **Componentes**: `modules/slack_baneo_notifier/` (worker + notifier), `deploy/docker/slack_baneo_worker.Dockerfile`
- **Tecnología**: APScheduler para periodicidad, `slack_sdk` para envío, health check HTTP embebido (puerto 8095)
- **Característica**: Reconfiguración dinámica sin reinicio — el worker relee la config de la DB en cada ejecución y reprograma el scheduler si el intervalo cambió
- **Logs**: Se centralizan en `Logs/slack_baneo_worker.log` vía `LOGS_DIR=/app/Logs` y además permanecen accesibles por `docker compose logs`

### 2026-04-20 - Normalización manual de estados de cámaras
- **Agregado**: Servicio `core/services/camara_estado_service.py` para calcular estado sugerido, detectar inconsistencias y auditar overrides manuales
- **Agregado**: Tabla `app.camaras_estado_auditoria` + migración `20260420_01_camaras_estado_auditoria.py`
- **Agregado**: Endpoints web `GET/POST /api/infra/camaras/{id}/estado` con restricción a `admin` y validación CSRF
- **Agregado**: Modal de edición de estado en tarjetas de Infra/Cámaras con motivo obligatorio e incidentes activos relacionados
- **Modificado**: `GET /api/infra/ban/active` ahora expone `camaras_baneadas_count` y `total_camaras_baneadas`
- **Beneficio**: permite corregir discrepancias operativas sin perder trazabilidad y elimina falsos positivos en el conteo visual de cámaras baneadas

### 2026-04-21 - Hot reload del worker Slack y correcciones UX del editor de cámaras
- **Modificado**: `slack_baneo_worker` expone `POST /reload` para releer `app.config_servicios` y reprogramar el scheduler sin esperar la próxima ejecución.
- **Modificado**: el panel admin de baneos acepta IDs de canal Slack (ej: `C08UB8ML3LP`) además de nombres con `#`.
- **Corregido**: el editor de estado de cámaras usa endpoints same-origin del servicio `web` en lugar de `API_BASE`, eliminando `404` al abrir el modal cuando el frontend apunta a `:8001`.
- **Corregido**: las tarjetas muestran `Editar estado` a usuarios `admin` aunque un payload legacy no incluya `editable`, manteniendo la autorización real en backend.

### 2026-04-24 - Listener de ingresos técnicos via Slack Socket Mode
- **Agregado**: `modules/slack_baneo_notifier/camara_search.py` — búsqueda fuzzy de cámaras: normalización unidecode, expansión de abreviaturas (cra, av, clle, pje, bv, dr), cascada ILIKE → tokens AND → retry sin números.
- **Agregado**: `modules/slack_baneo_notifier/listener.py` — `IngresoListener` (slack_bolt Socket Mode) que escucha mensajes con `Cámara: <nombre>` en un canal configurado y responde en hilo con estado de baneo (libre / baneada con #incidente / no encontrada).
- **Modificado**: `worker.py` — arranca `IngresoListener` como daemon thread si `SLACK_APP_TOKEN` está disponible; expone `listener_activo: bool` en `/health`.
- **Dependencias**: `slack_bolt>=1.22,<2` y `unidecode>=1.3.8` añadidos a `modules/slack_baneo_notifier/requirements.txt`; `slack_bolt>=1.22,<2` añadido a `requirements-dev.txt` para resolución local.
- **Variable de entorno nueva**: `SLACK_APP_TOKEN` (xapp-...) en `deploy/env.sample` — ya estaba declarado; no requiere cambio de compose.
- **Sin migración**: el listener usa `app.config_servicios` con una nueva fila `slack_ingreso_listener` creada en primer arranque; sin cambios de esquema.
- **Panel admin**: nueva card "🎧 Monitor de Ingresos" en `/admin/Servicios/Baneos` (toggle activo + canal ID + guardar).
- **Tests**: `tests/test_slack_ingreso_listener.py` — 15/15 pasan.

### 2026-04-27 - Correcciones `unaccent` y zona horaria GMT-3
- **Corregido**: error `function unaccent(text) does not exist` al buscar cámaras desde el listener. Causa: extensión `unaccent` no instalada en PostgreSQL. Solución: migración `20260427_01_unaccent_extension.py` + `CREATE EXTENSION IF NOT EXISTS unaccent;` en `db/init.sql` para nuevos entornos.
- **Corregido**: logs del worker mostraban hora UTC en lugar de GMT-3. Solución tripartita:
  1. `core/logging.py` — nuevo `_ArgTzFormatter` con `converter()` basado en `zoneinfo.ZoneInfo(APP_TIMEZONE)`.
  2. `deploy/compose.yml` — variables `TZ=America/Argentina/Buenos_Aires` y `APP_TIMEZONE=America/Argentina/Buenos_Aires` en el servicio `slack_baneo_worker`.
  3. `deploy/docker/slack_baneo_worker.Dockerfile` — instalación de `tzdata` + `ENV TZ=America/Argentina/Buenos_Aires`.
- **Corregido**: `BlockingScheduler()` instanciado sin `timezone`, lo que podía causar offsetting incorrecto en el scheduler. Ahora: `BlockingScheduler(timezone=TZ_ARG)` donde `TZ_ARG = ZoneInfo("America/Argentina/Buenos_Aires")`.
- **Resultado verificado en logs**: `Next wakeup is due at 2026-04-28 07:00:00-03:00` — offset explícito `-03:00`; timestamps de inicio del worker en hora local Argentina.

### 2026-04-28 - Entorno de Desarrollo (Dev) aislado
- **Agregado**: `deploy/docker-compose.dev.yml` — stack Docker Compose paralelo con nombre de proyecto `lasfocasdev`, puertos alternativos y red propia `lasfocas_dev_net`.
- **Agregado**: `deploy/env.dev.sample` — plantilla de variables para entorno dev; DB apunta a `focas_dev`, LLM en modo `heuristic`, web en `localhost:8090`.
- **Agregado**: `scripts/start_dev.sh` — script bash con flags `--clone-db`, `--no-build`, `--down`; incluye espera de Postgres, migraciones Alembic y healthchecks.
- **Sin impacto en producción**: el stack prod (`compose.yml`, `.env`) no fue modificado.

### 2026-04-29 - Imagen base focas-base:latest con multi-stage build
- **Agregado**: `common-requirements.txt` — 22 paquetes Python comunes a todos los servicios (FastAPI, SQLAlchemy, pandas, etc.).
- **Agregado**: `deploy/docker/base.Dockerfile` — patrón multi-stage: stage `builder` compila wheels con `build-essential/gcc/libpq-dev`; stage `runtime` instala solo los wheels pre-compilados sin herramientas de compilación.
- **Agregado**: `scripts/build_base.sh` — construye `focas-base:latest` con detección de cambios vía hash SHA-256 de `common-requirements.txt` para evitar rebuilds innecesarios.
- **Modificado**: `api/Dockerfile`, `web/Dockerfile`, `deploy/docker/bot.Dockerfile`, `deploy/docker/nlp_intent.Dockerfile`, `deploy/docker/slack_baneo_worker.Dockerfile`, `deploy/docker/repetitividad_worker.Dockerfile` — reemplazado `FROM python:3.11-slim*` por `FROM focas-base:latest`.
- **Modificado**: `api/requirements.txt`, `web/requirements.txt`, `bot_telegram/requirements.txt`, `nlp_intent/requirements.txt`, `modules/slack_baneo_notifier/requirements.txt` — eliminados los 22 paquetes comunes (ya en la imagen base).
- **Actualizado**: `Start` y `scripts/start_dev.sh` — llaman a `build_base.sh` automáticamente antes de levantar el stack.
- **Excluido**: `office_service/Dockerfile` queda sin cambios (usa fastapi 0.111.1/pydantic 2.8.2/uvicorn 0.30.1 + LibreOffice, incompatible con la base común).
- **Armonización de versiones**: `SQLAlchemy` 2.0.32→2.0.36, `psycopg[binary]` 3.1.19→3.2.1 en `requirements.txt` raíz y `slack_baneo_notifier/requirements.txt`.

### 2026-08-10 - Jerarquía Cámara → Botellas y fix de restauración de baneo

- **Agregado**: `Camara.camara_padre_id` (FK auto-referencial, 2 niveles) + relaciones `camara_padre`/`botellas`/propiedad `es_botella`. Migración `20260810_01_camara_padre_botella.py` (agrega también `INFERIDO` a `camara_origen_datos`).
- **Agregado**: `core/services/camara_hierarchy_service.py` — detección de sufijo "Bot N" (reusa/promueve `RE_BOT_SUFIJO` de `camara_search.py`), extracción de nombre base, `resolver_o_crear_padre()` conectado a los 6 caminos reales de alta/promoción de `Camara`.
- **Agregado**: `core/services/camara_estado_service.py::aplicar_estado_a_grupo()` — único punto de escritura de `Camara.estado`, con cascada bidireccional completa al grupo (Cámara + todas sus Botellas). `create_ban`/`lift_ban` y `override_camara_estado_manual` reescritos para usarlo.
- **Agregado**: `scripts/camara_backfill_padre_botella.py` — backfill histórico, corrido contra dev: 1645→1931 filas, 286 Cámaras padre creadas, 424 Botellas vinculadas, 188 grupos escalados de estado, 9 grupos con `PENDIENTE_REVISION` saltados intencionalmente.
- **Agregado**: endpoint `GET /api/infra/camaras/{id}/botellas`; `_serialize_camara_response` expone `es_botella`/`botellas_count`; el dashboard (`smart-search`) sólo devuelve Cámaras raíz.
- **Agregado**: frontend — `ModalBotellas.vue` (tarjetas independientes por Botella) y 4ª tarjeta "Botellas" en `CamaraDetailView.vue`; `InfraTab.vue` muestra conteo de botellas junto al de servicios y usa `fontine_id` como label si existe (fallback al ID interno).
- **Corregido (bug real encontrado durante la verificación, no sólo en dry-run)**: `_determinar_estado_restauracion` en `protection_service.py::lift_ban` sólo sabía restaurar a `LIBRE`/`OCUPADA` — nunca a `DETECTADA`, y no distinguía una Cámara/Botella con un baneo INDEPENDIENTE de este incidente (override manual o heredado del backfill, sin `IncidenteBaneo` que lo respalde) de una recién baneada por el incidente que se está levantando. El bug ya existía antes de esta iteración (un `lift_ban` de una sola cámara sin agrupar habría tenido el mismo problema), pero la cascada de grupo multiplicó el radio de impacto de 1 cámara a todo el grupo por cada `lift_ban`. Se detectó en una verificación real contra dev (grupo de prueba arrastró 8 cámaras de otros 2 grupos reales a `LIBRE` perdiendo su `DETECTADA`/`BANEADA` real) y se revirtió manualmente antes de aplicar el fix. **Fix**: nueva consulta `camara_estado_service.obtener_ultima_transicion_a_baneada()` sobre `app.camaras_estado_auditoria`; si la última transición a `BANEADA` es anterior al inicio del incidente que se levanta, la cámara se mantiene `BANEADA` (baneo independiente); si el estado previo a esa transición era `DETECTADA`, se preserva. Tests de regresión en `tests/test_protection_service.py`.
- **Limitación conocida documentada**: direcciones duplicadas con una plantilla de nombre distinta a "Bot N" (ej. "Cámara 14 de Julio 240" vs "Cra 14 de Julio 240 CF") no se detectan ni fusionan — ver sección "Jerarquía Cámara → Botellas" más arriba.
- **Fuera de alcance**: escritura de `Ingreso` sobre el grupo (la tabla no tiene ningún camino de escritura real hoy), fusión de duplicados sin patrón "Bot N", unificación de las 3 implementaciones divergentes de conteo de servicios, limpieza de `api/app/routes/infra.py` (huérfano, sin consumidor real).

### 2026-05-12 - Restauración de avisos Slack en Protocolo de Protección
- **Corregido**: los baneos ejecutados desde el panel Vue 3 entran por `web/app/main.py`; esa ruta persistía el incidente pero no disparaba el aviso inmediato a Slack ni el reporte actualizado.
- **Corregido**: `POST /api/infra/ban/create` y `POST /api/infra/ban/lift` del servicio `web` ahora reutilizan `modules.slack_baneo_notifier.eventos` igual que `api`, manteniendo el aviso puntual y el reenvío del reporte de cámaras baneadas.
- **Agregado**: `slack_sdk==3.33.5` en `web/requirements.txt`, porque el contenedor `web` no incluía la dependencia necesaria para ejecutar ese flujo.
- **UX**: el modal del wizard de Protocolo de Protección se cierra automáticamente tras un alta exitosa y reinicia su estado interno.

---

## Entorno de Desarrollo (Dev)

Stack Docker Compose independiente (`lasfocasdev`) que corre en paralelo al productivo sin interferencia.

### Puertos

| Servicio             | Producción                    | Dev                     |
|----------------------|-------------------------------|-------------------------|
| PostgreSQL           | `127.0.0.1:5432`              | `127.0.0.1:5433`        |
| API (docs: `/docs`)  | `:8001`                       | `:8011`                 |
| Web (panel)          | `172.18.208.162:8080`         | `127.0.0.1:8090`        |
| pgAdmin (profile)    | `127.0.0.1:5050`              | `127.0.0.1:5051`        |
| NLP / Office / Slack | interno (sin exposición)      | interno (sin exposición) |

El panel dev está vinculado a `127.0.0.1:8090`. Para acceso desde una máquina remota usar SSH tunneling:

### Secretos dev adicionales

- `api_key_v1` (dev: `.secrets/Dev_api_key_v1.txt`; prod: `.secrets/api_key_v1.txt`): API key interna para proteger rutas sensibles del servicio `api`.
- `web_secret_key_v1` (dev: `.secrets/Dev_web_secret_key_v1.txt`; prod: `.secrets/web_secret_key_v1.txt`): firma de cookie de sesión del panel web.
- `cromo_password_v1` (dev: `.secrets/Dev_cromo_password_v1.txt`; **sólo dev por ahora**, no provisionado en
  `deploy/compose.yml`/prod): contraseña de la cuenta de sólo lectura contra Cromo Red
  (`core/services/cromo/config.py`). `scripts/setup_local_secrets.sh` la deja vacía por defecto (igual que
  los tokens opcionales) — sin ella, la ingesta Cromo falla con un `CromoConfigError` claro en vez de
  bloquear el resto del servicio `web`. El resto de la config (`CROMO_BASE_URL`, `CROMO_USER`, etc., no
  sensible) viaja por `.env.dev`, igual que `POSTGRES_*`.
- `scripts/setup_local_secrets.sh` genera los archivos `Dev_*.txt` de forma idempotente para dev/CI; en producción, `deploy/compose.yml` usa el mismo mecanismo de Docker Compose Secrets pero con archivos sin prefijo (ver `docs/Seguridad.md`).

```bash
ssh -L 8090:localhost:8090 usuario@172.18.208.162
```

### Inicio rápido

```bash
# Primera vez: crear .env.dev desde la plantilla
cp deploy/env.dev.sample .env.dev
# Editar valores no sensibles y placeholders de compatibilidad
nano .env.dev

# Crear Docker Secrets locales de desarrollo
./scripts/setup_local_secrets.sh

# Levantar stack dev (build + migraciones + healthchecks)
./scripts/start_dev.sh

# Levantar con clonado de base de datos de prod → dev
./scripts/start_dev.sh --clone-db

# Levantar sin rebuild (iteración rápida)
./scripts/start_dev.sh --no-build
```

### Detener el stack dev

```bash
docker compose -f deploy/docker-compose.dev.yml down
```

### Variables de entorno

`deploy/env.dev.sample` → copiar a `.env.dev` en la raíz. Diferencias clave respecto a `.env`:

En dev, las credenciales reales se leen primero desde Docker Secrets montados en
`/run/secrets/*`, cuyos archivos fuente en `.secrets/` usan el prefijo `Dev_`
(ej. `Dev_db_password_v1.txt`). En producción se usa el mismo mecanismo con
archivos sin prefijo (ej. `.secrets/db_password_v1.txt`), ya implementado en
`deploy/compose.yml`. Si falta un archivo, el código cae a `.env`/`.env.dev`
para mantener compatibilidad durante la transición. Si se cambia
`db_password_v1.txt` (o `Dev_db_password_v1.txt`) sobre un volumen PostgreSQL
ya inicializado, el valor debe coincidir exactamente con la contraseña vigente
del rol — cambiarlo sin actualizar el rol o recrear el volumen rompe la
autenticación (ver `docs/Seguridad.md`).

| Variable              | Producción                       | Dev                          |
|-----------------------|----------------------------------|------------------------------|
| `POSTGRES_DB`         | `FOCALDB`                        | `focas_dev`                  |
| `API_BASE`            | `http://172.18.208.162:8080`     | `http://localhost:8090`      |
| `WEB_INFERRED_ORIGIN` | `http://172.18.208.162:8080`     | `http://localhost:8090`      |
| `SLACK_BOT_TOKEN`     | token de app Slack prod          | token de app Slack dev       |
| `SLACK_APP_TOKEN`     | token de app Slack prod          | token de app Slack dev       |
| `LLM_PROVIDER`        | `openai`                         | `heuristic` (sin costo/API)  |
| `LOG_LEVEL`           | `INFO`                           | `DEBUG`                      |

### Clonar DB de producción a dev

```bash
./scripts/start_dev.sh --clone-db
```

Requisito: el contenedor `lasfocas-postgres` (prod) debe estar corriendo. El script hace `pg_dump` del esquema prod y lo restaura en `focas_dev` con `--clean --if-exists`.

### Control del worker de baneos desde el panel admin

Desde 2026-08-11, `web` ya no monta `/var/run/docker.sock` — controla `slack_baneo_worker` a través de `docker-socket-proxy` (`tecnativa/docker-socket-proxy`, red dedicada `docker_proxy_net`/`docker_proxy_dev_net`, acotado a `containers.get`/`.start`/`.reload` sobre un único contenedor). Detalle completo, motivo y verificación en `docs/decisiones.md`, entrada 2026-08-11.

**Limitación conocida (preexistente, no relacionada al proxy):** en producción el panel busca el contenedor `lasfocas-slack-baneo-worker`; en dev el contenedor se llama `lasfocasdev-slack-baneo-worker`, por lo que el toggle del panel dev no controla el worker dev por nombre. El worker dev funciona correctamente de forma autónoma; solo el control desde la UI admin queda limitado en este entorno.

### Archivos relacionados

- `deploy/docker-compose.dev.yml` — Stack Docker Compose dev
- `deploy/env.dev.sample` — Plantilla de variables de entorno dev
- `.secrets/` — Secretos locales dev ignorados por Git
- `scripts/setup_local_secrets.sh` — Bootstrap idempotente de secretos dev/CI
- `scripts/check_no_plaintext_secrets.sh` — Control preventivo anti-secretos
- `scripts/start_dev.sh` — Script de inicio con healthchecks y clonado opcional de DB

### Purga local de secretos históricos

Antes de publicar una rama reescrita, coordinar ventana de trabajo, partir de un
árbol limpio y conservar un backup del repo. En esta VM `git filter-repo` debe
estar instalado previamente.

```bash
cat > /tmp/las-focas-replacements.txt <<'EOF'
<password_db_historico_prod>==>***REMOVED***
<password_db_historico_dev>==>***REMOVED***
<password_default_historico>==>***REMOVED***
<hash_bcrypt_admin_historico>==>***REMOVED***
EOF

git filter-repo --replace-text /tmp/las-focas-replacements.txt --force
git grep -n "<patron_historico_a_validar>" $(git rev-list --all)
```

Después de validar, publicar con `git push --force-with-lease origin dev` y
avisar al equipo que debe resincronizar sus clones.

---

## Imagen base Docker: `focas-base:latest`

Imagen multi-stage compartida por todos los servicios Python del proyecto (excepto `office_service`).

### Qué incluye

22 paquetes Python directos y todas sus dependencias transitivas, pre-compilados como wheels en el stage `builder` e instalados en el stage `runtime` sin herramientas de compilación:

| Grupo | Paquetes |
|-------|----------|
| FastAPI stack | `fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`, `httpx`, `orjson` |
| Web extras | `jinja2`, `itsdangerous`, `python-multipart`, `bcrypt` |
| DB / ORM | `SQLAlchemy`, `psycopg[binary]`, `alembic` |
| Data | `pandas`, `openpyxl`, `python-docx`, `Unidecode` |
| Geo / Maps | `matplotlib`, `Pillow`, `staticmap`, `contextily`, `pyproj` |

Además incluye en runtime: `curl`, `libpq5`, `libexpat1`, `tzdata`, `ca-certificates`.

### Patrón multi-stage

```
builder (python:3.11-slim-bookworm)
  └─ apt: build-essential gcc libpq-dev libffi-dev libssl-dev
  └─ pip wheel --wheel-dir /wheels -r common-requirements.txt
        ↓ wheels de todos los paquetes + transitive deps
runtime (python:3.11-slim-bookworm)  ← imagen final
  └─ apt: curl libpq5 libexpat1 tzdata ca-certificates
  └─ pip install --no-index --find-links=/wheels ...
  └─ rm -rf /wheels  ← limpia en el mismo layer
```

### Cuándo reconstruir

`build_base.sh` detecta automáticamente si `common-requirements.txt` cambió (hash SHA-256) y solo reconstruye cuando es necesario.

Casos que requieren rebuild manual:
- Se agrega o actualiza un paquete en `common-requirements.txt`
- Se cambia la versión base de Python

### Comandos

```bash
# Build automático (detecta cambios)
./scripts/build_base.sh

# Forzar rebuild aunque no haya cambios
./scripts/build_base.sh --force

# Build manual directo
docker build -t focas-base:latest -f deploy/docker/base.Dockerfile .
```

`Start` y `scripts/start_dev.sh` llaman a `build_base.sh` automáticamente antes de levantar el stack.

### Excepción: office_service

`office_service/Dockerfile` usa `fastapi==0.111.1`, `pydantic==2.8.2` y `uvicorn==0.30.1` (versiones distintas a las de `focas-base`) además de `python3-uno` y LibreOffice instalados desde apt. No hereda de `focas-base`.

### Archivos relacionados

- `common-requirements.txt` — 22 paquetes comunes (fuente de verdad de la imagen base)
- `deploy/docker/base.Dockerfile` — Dockerfile multi-stage
- `scripts/build_base.sh` — Script de build con detección de cambios
