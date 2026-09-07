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
los 5 caminos de alta/promoción de `Camara` (tracking `.txt`, sync Google Sheets, alta Slack, y los dos
endpoints admin `admin_dar_de_alta_camara`/`admin_aprobar_camara` en `web/app/main.py`) — si el nombre
nuevo matchea `RE_BOT_SUFIJO`, reusa la Cámara padre `INFERIDO` existente para esa base o crea una
nueva, y vincula la fila nueva como Botella. La ingesta Excel de cámaras baneadas
(`core/services/camara_ingest_service.py`) dejó de ser un camino de alta — hoy sólo banea
Cámaras/Botellas ya existentes, nunca crea una `Camara` nueva ni pasa por `resolver_o_crear_padre()`
(ver sub-sección "Ingesta Excel de cámaras baneadas" más abajo).

**Normalización extendida en la resolución de padre (2026-08-14)**: `resolver_o_crear_padre_desde_base`
(núcleo compartido por los 5 caminos legado de arriba y por `resolver_o_crear_padre_cromo`) usa ahora
`normalizar_para_agrupar_extendido()` (abreviaturas + sinónimos, misma tabla que la detección de
duplicados de la sección "Dashboard Viewer" más abajo) para decidir si ya existe una Cámara padre —
antes usaba `normalizar_para_agrupar` (básica), que seguía generando duplicados nuevos con nombres que
sólo difieren en "CF"/abreviatura vial (ej. real "Bot Tza San Antonio 640" vs "Bot. Tza.San Antonio 640
CF"). Riesgo aceptado explícitamente por el usuario: más falsos positivos posibles si dos sitios reales
comparten abreviatura. Ver `docs/decisiones.md` 2026-08-14.

**Nota (2026-08-22):** `resolver_o_crear_padre_desde_base` no tiene llamador productivo desde `resolver_o_crear_padre_cromo` hoy — el mecanismo real de agrupamiento de Botellas Cromo es la resolución en memoria de `scripts/cromo_backfill_camara_padre.py`, que reimplementa la resolución por separado debido al incidente de performance de 2026-08-12 documentado en el propio script.

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

Nota (2026-08-14): la normalización extendida de arriba reduce la creación de **nuevos** duplicados de
este tipo hacia adelante, pero no fusiona retroactivamente los ya existentes (como el caso id=1638) —
eso sigue siendo responsabilidad del flujo manual de la sección "Dashboard Viewer de Cámaras" más abajo.

**Escritura de `Ingreso` sobre el grupo** (2026-08-31): ya existe camino de escritura real —
`IngresoListener._registrar_movimiento_si_corresponde` (`modules/slack_baneo_notifier/listener.py`)
llama a `registrar_movimiento_ingreso()` (`core/services/ingreso_service.py`) cada vez que un mensaje
de Slack trae el campo `*Ingreso o Egreso*` del Workflow y matchea una `Camara`/`CromoBotella` real.
Un "Ingreso" siempre crea fila nueva (`fecha_fin=NULL`); un "Egreso" cierra el `Ingreso` abierto más
reciente que matchee `tecnico_id`+`camara_id`+`cromo_botella_id` (NULL-safe) o, si no hay ninguno,
crea una fila huérfana con `fecha_inicio=NULL`. `Ingreso.camara_id` es siempre la cámara padre del
grupo; `Ingreso.cromo_botella_id` (columna nueva, migración `20260831_02`) guarda la botella Cromo
específica cuando aplica — por eso estas filas sí propagan correctamente sobre el grupo completo
(cámara + botellas hermanas), consistente con `tiene_ingreso_activo` de `camara_estado_service.py`.
Ver "Registros" más abajo, pestaña Ingresos ya poblada desde backend real (ya no placeholder).

**Actualización 2026-09-04:** `tiene_baneo_activo` (`get_camara_estado_contexto`) tenía un bug real —
sólo miraba `IncidenteBaneo` activo, nunca `Camara.estado == BANEADA` de ningún miembro del grupo. Un
baneo manual (override admin/import Excel, sin incidente de protección asociado) quedaba invisible
tanto para el badge "Contexto operativo" (`ModalRegistros.vue`) como para el chequeo de acceso del
listener de Slack de ingreso. Corregido: `tiene_baneo_activo` ahora también es `True` cuando cualquier
miembro de `miembros_del_grupo(camara)` tiene `estado == BANEADA`, incidente o no. `tiene_ingreso_activo`
ahora filtra explícitamente `Ingreso.tipo == 'INGRESO'` (columna nueva, migración `20260904_01`) para no
contar un `INTENTO_BLOQUEADO` (mismo `fecha_fin IS NULL`) como si alguien estuviera realmente adentro.

**Fix de revisión final (mismo día, 2026-09-04):** el fix de arriba (`tiene_baneo_activo` ahora
también `True` para un baneo manual) rompió silenciosamente a `core/services/baneos_grupos_service.py`
(panel admin "Baneos Activos" / `POST /api/admin/baneos/grupos/liberar`), escrito contra el
significado VIEJO de `tiene_baneo_activo` (sólo incidente). Se agregó un campo nuevo,
`tiene_incidente_activo` (`CamaraEstadoContexto`), que preserva ese significado viejo — `puede_liberar`
y el guard de `forzar` de `liberar_grupos_masivo` ahora usan `tiene_incidente_activo`, nunca el signal
amplio `tiene_baneo_activo`. Ver `docs/api.md` (`GET /api/admin/baneos/grupos`) para el detalle
completo y el porqué.

`GET /api/infra/camaras/{id}/registros` expone además `botella_label` por cada `Ingreso` — resuelve
"Botella 1" (convención ya usada por `camara_search.detectar_multi_bot`: la Cámara raíz misma, sin fila
propia en `CromoBotella`) cuando no se especificó botella, el nombre de la `CromoBotella` cuando sí hay
`cromo_botella_id`, o el nombre de la Botella legado (self-FK) cuando la fila de `Ingreso.camara_id`
apunta directo a una Botella sin `CromoBotella` asociada.

Consecuencia para el flujo admin de borrado: `_bloqueo_camara()` en
`core/services/camara_botella_delete_service.py` bloquea eliminar una `Camara` que tenga CUALQUIER fila
`Ingreso` asociada (abierta o ya cerrada, sin distinción) — y por ser `eliminar_camara` todo-o-nada,
ese único bloqueo aborta el borrado de todo el grupo (cámara + botellas hermanas), no sólo de la fila
con el Ingreso. Antes de esta rama `app.ingresos` estaba siempre vacía, así que este gate nunca se
disparaba en la práctica; ahora que hay escritura real, cualquier cámara/botella donde un técnico haya
reportado un ingreso queda permanentemente indeletable vía "eliminar grupo" del panel admin.

**Endpoint**: `GET /api/infra/camaras/{camara_id}/botellas` — devuelve las Botellas de una Cámara,
unificando legado (self-FK de esta sección, lista vacía si `camara_id` es en sí una Botella) y Cromo
(`CromoBotella.camara_id`, desde 2026-08-11, ver sección "Cámara padre para Botellas Cromo" más abajo).
Consumido por `ModalBotellas.vue` desde una 4ª tarjeta "Botellas" en `CamaraDetailView.vue`.

### Ingesta Excel de cámaras baneadas: deja de crear, matcher extendido, revisión manual (2026-08-24)

`/admin/ingesta/camaras` (`POST /api/admin/ingesta/camaras` → proxy a `POST /ingest/camaras`) creaba
antes una `Camara` nueva (`origen_datos=SHEET`) cuando un alias del Excel no matcheaba contra el
inventario — legacy de cuando ese inventario no estaba completo. Hoy Cromo Red es la fuente de verdad
del inventario de Cámaras/Botellas: un alias sin match es un problema de escritura/regex a corregir,
no una cámara faltante que haya que dar de alta.

- **Matcher nuevo**: `core/services/camara_ingest_service.py` resuelve ahora cada alias con
  `buscar_camara_o_botella_cromo` (`core/services/cromo/camara_botella_busqueda.py`) — la misma
  búsqueda extendida Camara+CromoBotella que ya usa `_resolve_camara_o_registrar_sin_match` de
  `infra_service.py` (ver sección "Ingresos sin match" más abajo) — en vez del match exacto por
  alias/nombre que usaba antes. Un nombre ambiguo (`AmbiguousSearchError`) se trata igual que "sin
  match": nunca se banea a ciegas entre candidatas.
- **Sin match → `IngresoSinMatch`**: se registra en `app.ingresos_sin_match` con
  `origen="excel_camaras"` (tercer valor de esa columna, junto a `"slack"`/`"tracking"`) — mismo
  mecanismo existente, no una tabla nueva.
- **Asociación manual**: `POST /api/admin/ingesta/camaras/asociar`
  (`core/services/camara_ingest_service.py::asociar_nombres_a_camara`) crea un `CamaraAlias` por cada
  nombre resuelto a mano hacia una Cámara/Botella existente y banea el grupo destino una sola vez — el
  efecto es que el mismo texto del Excel matchea automáticamente en la próxima corrida (el buzón se
  vacía con el uso). "Descartar" en el visor
  (`POST /api/admin/infra/ingresos-sin-match/marcar-revisado-masivo`) sólo oculta de la vista — la fila
  queda en la base para poder ajustar el regex/normalización de búsqueda a futuro.
- **Typeahead**: `GET /api/infra/camaras/buscar` ganó el parámetro `solo_raiz` (default `true`,
  preserva el comportamiento histórico) — `solo_raiz=false` incluye también Botellas hijas en los
  resultados, con `es_botella`/`camara_padre_id`/`camara_padre_nombre` en la respuesta, para el picker
  de asociación manual del Revisor Manual (`AdminIngestaCamaras.vue`).
- **Bug de cascada corregido** (afecta a toda la jerarquía, no sólo a esta ingesta):
  `override_camara_estado_manual` (`core/services/camara_estado_service.py`) comparaba antes el
  estado de la fila puntual en vez del grupo completo — si esa fila ya estaba en el estado destino
  pero el grupo había quedado mixto (ej. tras un `lift_ban` parcial), la cascada no corría y las
  hermanas quedaban desincronizadas. Corregido para comparar `miembros_del_grupo(camara)` completo.

**Reporte Excel de Slack agrupado**: `modules/slack_baneo_notifier/notifier.py::generar_excel_baneadas`
ahora agrupa por Cámara padre (una fila por grupo, no por Botella individual) usando el mismo
`listar_grupos_baneados` que alimenta el panel — evita que el reporte y el panel puedan divergir.
Columnas nuevas: `ID | Fontine ID | Cámara | Dirección | Botellas baneadas | Botellas | Latitud |
Longitud | Último Update` (antes: `ID | Fontine ID | Nombre | Dirección | Latitud | Longitud |
Último Update`, una fila por cada `Camara` con `estado=BANEADA` sin distinguir padre/hijas).

**Limitación conocida**: tanto el reporte como el panel de "Baneos Activos" listan raíces con
`estado=BANEADA` — una Botella baneada cuya Cámara padre NO está baneada (dato legacy, anterior a
este refactor — no debería poder ocurrir hacia adelante gracias a la cascada, pero puede existir en
filas ya escritas antes) queda invisible en ambas superficies. No se corrige en este plan (cambiar
la semántica de agrupación es una decisión de alcance separada); si aparecen casos así en
producción, es un candidato a ticket propio.

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
- **Limitación cerrada (2026-08-12)**: `CromoBotella.estado` era una foto fijada sólo al momento del
  backfill — `aplicar_estado_a_grupo` escribía sólo `Camara.estado`, así que un cambio de estado real
  posterior sobre la Cámara padre (ej. un baneo nuevo, o la corrección de un `DETECTADA` legado) no se
  propagaba a las `CromoBotella` ya vinculadas. Encontrado con impacto real (295 filas desincronizadas)
  y cerrado estructuralmente — ver sección "Propagación de estado a CromoBotella + resync real
  (2026-08-12)" más abajo.

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

### Cambio de política de estado, paginación real y navegación cruzada (2026-08-13)

**Reversión explícita del usuario** de la política fail-closed descripta arriba: toda Cámara padre
*nueva* sintetizada desde Cromo (por sufijo, prefijo, o el fallback de nombre exacto) nace ahora en
**`LIBRE`**, no `NO_OPERATIVA`. Aplica a los 3 caminos de alta (`core/services/cromo/camara_padre_service.py`,
`scripts/cromo_backfill_camara_padre.py`, `core/services/cromo/orfanas_service.py`) y al
`server_default` de `app.cromo_botellas.estado` (migración `20260813_01`, metadata-only, no reescribe
filas ya ingeridas). **Por qué es seguro pese al riesgo que motivó la política original**: una Cámara
recién creada no tiene todavía ningún empalme/ruta propio, así que estructuralmente no puede existir
un `IncidenteBaneo` activo real que la afecte en el momento del alta — no hay nada que "chequear". El
caso que sí importaba proteger (reutilizar una `Camara` legado ya existente, potencialmente `BANEADA`)
sigue intacto: ese camino nunca tocó el estado de una fila reusada, con o sin esta reversión. **No se
re-corrieron los backfills históricos** — las ~9.672 Cámaras padre ya creadas en `NO_OPERATIVA` (ver
arriba) no se tocaron retroactivamente; el cambio aplica sólo hacia adelante, a cualquier alta nueva.
Ver `docs/decisiones.md`.

> **Actualización 2026-08-14**: el backfill retroactivo que este párrafo decía explícitamente que NO
> se había corrido, se corrió — ver la sección "Fix de nombres residuales y backfill retroactivo de
> estado (2026-08-14)" más abajo. Las ~9.672 Cámaras mencionadas arriba ya no están en `NO_OPERATIVA`.

**Paginación real en el dashboard `/infra`**: hasta esta fecha, `InfraTab.vue` no cargaba nada al
montar — el usuario debía escribir un término o tocar un chip de estado para disparar la primera
consulta (guard explícito en `searchCamaras()`), y aun con resultados cargados no había forma de
pedir una página más allá de la primera tanda de 100. Ahora la vista carga sin filtros al montar
(mismo contrato `POST /api/infra/smart-search` con `terms: []`) y expone controles reales
"Anterior"/"Siguiente" sobre `offset`/`limit`/`total`. El toggle "Mostrar No operativas" (oculto por
defecto, decisión de UX previa) **no se tocó** — se decidió explícitamente mantenerlo así. Del lado
del backend, la rama sin términos de `smart_search_camaras_web` pasó de traer TODAS las cámaras raíz
a memoria y paginar en Python a un `LIMIT`/`OFFSET`/`COUNT` real en SQL; la rama con términos de
búsqueda libre sigue en memoria (necesita computar servicios/cables/rutas por cámara para matchear,
que no está en una columna filtrable en SQL sin un join mayor) — aceptable a la escala real medida
(~10.200 cámaras raíz en dev).

**UX del inventario de Botellas** (`/infra/Botellas`): la barra de acciones masivas de cambio de
estado (ver "Endpoint de cambio de estado masivo" arriba) se extrajo a un componente propio,
`components/infra/BotellasBulkActionsPanel.vue`, con posicionamiento `fixed` (panel flotante, visible
incluso con scroll, en vez de la barra inline dentro del toolbar). Además: la vista **grid**
(`BotellaCard.vue`) ganó su propio checkbox de selección — antes sólo la vista lista permitía
selección múltiple; el nombre de cada Botella en la vista lista pasó de texto plano a un link real
(`RouterLink`); y se corrigió un bug real en el modo "huérfanas" donde el botón "Asociar" (anidado
dentro del `<label>` que envuelve el checkbox de selección) también togglaba el checkbox por el
comportamiento nativo de `<label>` — corregido con `@click.stop` en el botón.

**Navegación cruzada Botella → Cámara padre**: `BotellaDetalleUnificadaView.vue` sigue siendo un shim
de redirección puro (nunca se renderiza visible, ver "Submódulo Botellas" más abajo) — el link
"Cámara padre" se agregó en los destinos reales a los que redirige, no en el shim: `CamaraDetailView.vue`
(Botella legado, `camara_padre_id`/`camara_padre_nombre` agregados a `_serialize_camara_response`) y
`VerificadorCromoView.vue` (Botella Cromo con `camara_id` resuelto, vía el mismo
`GET /api/infra/cromo-botellas/{n_id}/estado-asociacion` ya usado por el shim, extendido para
devolver `camara_id`/`camara_nombre` además de `huerfana`).

### Fix de nombres residuales y backfill retroactivo de estado (2026-08-14)

**Bug real reportado desde el dashboard `/infra`**: varias Cámaras padre de Cromo mostraban nombres
rotos con un punto residual al inicio (ej. `". Cra Marcos Sastre y Colectora Este"`,
`". Poste Est . Bs. As. C.F"`). **Causa raíz**: `RE_BOT_SUFIJO`
(`modules/slack_baneo_notifier/camara_search.py`) y `RE_BOTELLA_PREFIJO`
(`core/services/cromo/camara_padre_service.py`) consumían un punto ANTES del dígito de "Bot N"
("Bot. 2") pero ninguno consumía un punto DESPUÉS del dígito — cuando el nombre real de Cromo traía
el punto ahí (ej. `"Bot 2. Cra Marcos Sastre y Colectora Este"`), el match terminaba en el dígito y el
punto sobrevivía como residuo (ni el colapso de espacios ni el `.strip()` posterior lo tocan, no es
whitespace). Fix: `\.?` agregado después del lookahead `(?!\d)` en ambos regex — `extraer_base_cromo()`
llama internamente a `extraer_base()` (la función que usa `RE_BOT_SUFIJO`), así que corregir esa única
constante compartida arregla ambos caminos (legado Bot-N y Cromo) a la vez.

**Alcance real, verificado contra `lasfocasdev-postgres`**: sólo **7 de 9.770** Cámaras
`INFERIDO_CROMO` tenían el residuo real (ids 6557, 6561, 6564, 6813, 7361, 7466, 7683). El punto AL
FINAL de muchos nombres (ej. `"...C.F."`, 732 filas) es formato legítimo original de Cromo — no es el
bug, no se tocó. Corrección retroactiva vía `scripts/cromo_fix_nombre_camara_padre_residual.py`
(quirúrgica: recorta el residuo del valor ya guardado, no re-deriva desde la `CromoBotella` vinculada
— preserva intacto cualquier punto interno legítimo, ej. `"Poste Est ."` del id 6561). Resultado real:
7/7 nombres corregidos, 0 residuos restantes.

**Backfill retroactivo de estado** (pendiente explícito de la entrada 2026-08-13): las ~9.672 Cámaras
`INFERIDO_CROMO` que habían nacido `NO_OPERATIVA` bajo el default fail-closed ya revertido se
corrigieron a `LIBRE` vía `scripts/cromo_backfill_estado_no_operativa_retroactivo.py` — candidatas
filtradas por `origen_datos=INFERIDO_CROMO` + `estado=NO_OPERATIVA` + sin ninguna fila en
`camaras_estado_auditoria` (de las 98 Cámaras `INFERIDO_CROMO` con auditoría propia, el 100% fue
escrita por procesos automáticos — `cromo_backfill`/`retiro_detectada` —, cero por un humano). Aplicado
vía `aplicar_estado_a_grupo` (único punto de escritura sancionado, sincroniza `CromoBotella.estado` en
la misma transacción) — `--dry-run` cronometrado confirmó 9.672 filas en 35.6 segundos reales antes de
aplicar, sin el problema de performance que sí afectó a `resolver_o_crear_padre_desde_base` en el
backfill original del 2026-08-11. Resultado real: 0 `NO_OPERATIVA` restantes en `origen_datos=
INFERIDO_CROMO` (9.753 en `LIBRE`, 17 `BANEADA` sin tocar). Ver `docs/decisiones.md`.

### Propagación de estado a CromoBotella + resync real (2026-08-12)

Hallazgo real reportado desde el dashboard (captura del inventario de Botellas): muchas filas
mostraban `OCUPADA` sin ningún `Ingreso` activo detrás — verificado contra `lasfocasdev-postgres`:
**0 `Ingreso` activos en todo el sistema**, pero **295 `CromoBotella` mostraban un estado que ya no
coincidía con el de su propia Cámara padre** (291 en `OCUPADA`/4 en `BANEADA` con el padre ya en
`LIBRE`).

- **Causa raíz**: el 2026-08-11 a la mañana, el primer backfill de Cromo mapeó `DETECTADA→OCUPADA`
  al fijar el estado inicial de varias `CromoBotella` (padres legado reusados que en ese momento
  estaban en `DETECTADA`). Horas después, `scripts/retirar_estado_detectada.py` corrigió esos
  mismos padres a su estado real (`LIBRE`) — pero `aplicar_estado_a_grupo`, en ese momento, sólo
  escribía `Camara.estado`; nunca tocaba las `CromoBotella` ya vinculadas. La foto vieja quedó
  fijada para siempre, sin ningún evento que la refrescara.
- **Cierre estructural**: `core/services/camara_estado_service.py::aplicar_estado_a_grupo` (el único
  punto de escritura sancionado de `Camara.estado`, usado por el override manual, `create_ban`/
  `lift_ban` y el backfill) ahora también actualiza, en la misma transacción, las `CromoBotella`
  vinculadas a cualquier miembro del grupo efectivamente modificado — vía el mismo
  `MAPEO_ESTADO_CROMO` que ya usaba el backfill (movido a este módulo para que ambos lo compartan).
  Verificado real contra dev: banear una Cámara padre con Botellas Cromo propias sincroniza ambas
  tablas en la misma operación (probado con rollback, sin tocar datos reales).
- **Corrección retroactiva**: `scripts/resync_cromo_botella_estado.py` (nuevo, `--dry-run`
  soportado) — corrida única que resincroniza cualquier `CromoBotella` cuyo estado no coincida con
  el de su padre actual. Corrida real: **295 filas corregidas → 0 desincronizadas** (verificado
  contra las 11.100 `CromoBotella` vinculadas). No es un proceso recurrente: desde el cierre
  estructural, cualquier cambio de estado futuro ya se propaga solo.

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

### Cámaras duplicadas — Unificación manual: fusión real Cámara-a-Cámara (2026-08-11, rediseñado 2026-08-14)

Limitación conocida desde el 2026-08-10 (duplicados de Cámara sin sufijo "Bot N", que
`resolver_o_crear_padre_desde_base` no agrupa por no compartir ningún token normalizado — ej. real
"Cámara 14 de Julio 240" vs "Cra 14 de Julio 240 CF"). Un análisis manual puntual del 2026-08-11
había estimado **47 grupos de duplicados reales, 99 Cámaras raíz involucradas de un total de 2.554**
— cifra **obsoleta**: no fue producida por ningún script reusable (fue una revisión manual de esa
única sesión), y el universo de Cámaras raíz creció ~4x con los backfills de Cromo del
2026-08-11/12/14, hasta **10.212** raíces reales (verificado contra `lasfocasdev-postgres` el
2026-08-14). Resuelto con un flujo manual de unificación, no automático (un humano decide qué dos
Cámaras son en verdad el mismo sitio físico) — pero ya no depende de un análisis manual para
**encontrar** los candidatos: `/admin/servicios/viewer/Camaras` (`GET
/api/admin/infra/camaras/viewer/duplicados`, `core/services/camara_duplicados_service.py`) recalcula
los grupos en cada carga.

### Dashboard Viewer de Cámaras — listado dual + detección de duplicados en vivo (2026-08-14)

`/admin/servicios` → tarjeta "Viewer" → `/admin/servicios/viewer` (hub de dashboards de datos
operativos para mantenimiento, pensado para crecer con más módulos) → tarjeta "Cámaras" →
`/admin/servicios/viewer/Camaras`:

- **Listado general**: mismo estilo dual grid/lista con scroll infinito de `ServiciosView.vue`
  (`GET /api/admin/infra/camaras/viewer`, paginación real en SQL — `q`, `estado`, `limit<=100`,
  `offset` — sin el N+1 en memoria de `smart-search`).
- **Filtro "Sólo duplicadas"**: cambia el contenido a una tarjeta por cada grupo de 2+ Cámaras
  candidatas a duplicado (`GET /api/admin/infra/camaras/viewer/duplicados`,
  `core/services/camara_duplicados_service.py::detectar_grupos_duplicados`) — sin paginar, calculado
  sobre el universo completo de Cámaras raíz (~10.212 filas, O(n) en Python, sub-segundo, sin cache).
  Cada tarjeta muestra un badge "⚠ Estados distintos" si los miembros no coinciden en estado, y un
  botón "Fusionar" por miembro que abre `ModalUnificarCamara.vue` (reusado tal cual, con el nombre
  del otro miembro del grupo precargado como sugerencia de búsqueda vía el prop nuevo
  `sugerenciaInicial`). Tras un merge exitoso se recalculan tanto los grupos como el listado general.
- **Criterio de detección — "normalización extendida"** (decisión explícita del usuario, sin
  similitud difusa): `camara_hierarchy_service.normalizar_para_agrupar_extendido()` compone
  `normalizar_para_agrupar()` (sin modificarla) con `expandir_abreviaturas_y_sinonimos()` (pública, en
  `modules/slack_baneo_notifier/camara_search.py` — reusa `_ABREVIATURAS`/`_SINONIMOS`, las mismas
  tablas que ya usa `buscar_camara` para texto libre de técnicos, sin duplicarlas). Resuelve el caso
  documentado: "Cámara 14 de Julio 240" y "Cra 14 de Julio 240 CF" colapsan a la misma clave
  (`"cra 14 de julio 240"`) por la abreviatura `cf→""` y el sinónimo `camara→cra`. Excluye sufijo
  Bot-N (ya resuelto por la jerarquía Cámara/Botella). **Movida (2026-08-14) desde
  `camara_duplicados_service.py` (donde nació el mismo día como `normalizar_para_detectar_duplicados`)
  hacia `camara_hierarchy_service.py`** — ahora `resolver_o_crear_padre_desde_base()` también la usa
  para prevenir duplicados nuevos en el alta, no sólo para sugerir candidatas a revisión manual (ver
  sección "Jerarquía Cámara → Botellas" más arriba); moverla evita un ciclo de import, ya que
  `camara_duplicados_service.py` depende de `camara_hierarchy_service.py`, no al revés.
- **"Fusionar todas" (2026-08-14)**: botón nuevo por tarjeta de grupo que abre
  `ModalFusionarGrupo.vue` — sugiere como principal la Cámara con más `botellas_count + cables_count`
  del grupo (empate → id más bajo, el admin puede cambiar la elección) y fusiona todas las demás de un
  solo click vía `POST /api/infra/camaras/merge-grupo`
  (`core/services/camara_merge_service.py::fusionar_grupo_camaras`, loop de `unificar_camaras()` con
  `session.expire_all()` obligatorio entre cada llamada — sin esto, `Camara.estado` queda
  desincronizado en botellas absorbidas por fusiones intermedias del mismo grupo, hallazgo real de
  investigación).
- **"Fusión masiva" (2026-08-14)**: botón en el toolbar (visible con "Sólo duplicadas" activo) que
  fusiona TODOS los grupos detectados de un click, vía `POST /api/infra/camaras/merge-masivo` —
  `sugerir_principal()` (`camara_duplicados_service.py`) elige la principal de cada grupo con el
  mismo criterio de arriba, sin que el admin tenga que abrir cada grupo. Cada grupo corre en su
  propia transacción (`SessionLocal` independiente) — un grupo con error no revierte los ya
  fusionados, queda reportado en la respuesta. Confirmación previa vía
  `ModalConfirmarAccionMasiva.vue` (genérico, reusado también en el viewer de Botellas).

- **Estrategia vigente (2026-08-14)**: fusión real entre dos Cámaras, no entre Cámara y Botella. La
  principal hereda todo lo heredable de la secundaria y la secundaria se **elimina físicamente**
  (`session.delete`). Para que el hard delete no pierda nada por una cascada, `unificar_camaras()`
  reasigna explícitamente, con `session.flush()` antes del delete, las 7 FK reales hacia
  `app.camaras.id`: Botellas propias (self-FK `camara_padre_id`), `CromoBotella.camara_id`,
  `Cable.origen_camara_id`/`destino_camara_id`, `Empalme.camara_id` (crítico: `Camara.empalmes` tiene
  `cascade="all, delete-orphan"`), `Ingreso.camara_id` (mismo riesgo de cascada), `CamaraAlias.camara_id`
  (se migran los alias que la secundaria ya tenía, no sólo se crea uno con su nombre) y
  `CamaraEstadoAuditoria.camara_id` (tiene `ondelete="CASCADE"` en Postgres — sin reasignar, el DELETE
  hubiera borrado el historial completo de la secundaria). `CromoPelo`/`CromoFusion`/`CromoCable`/
  `CromoTubo` no tienen `camara_id` propio y viajan solos en cuanto se reasigna `CromoBotella.camara_id`.
  Ver `core/services/camara_merge_service.py` y la entrada de decisión 2026-08-14 en `docs/decisiones.md`
  (reemplaza el diseño anterior de reparentado-como-Botella del 2026-08-11).
- El nombre de la secundaria queda como alias de la principal sólo si se pide explícitamente
  (`guardar_alias: bool`, default `True`). El estado final es el más restrictivo entre el grupo de la
  principal (`miembros_del_grupo`, que ya no incluye a la secundaria) y el estado que tenía la
  secundaria antes de desaparecer (`estado_mas_restrictivo`, mismo criterio que la cascada de baneo).
  Se registra siempre un evento explícito en `CamaraEstadoAuditoria` de la principal ("Cámara 'X'
  (ID N) fusionada dentro de esta cámara"), incluso si el estado no cambió.
- **Endpoint**: `POST /api/infra/camaras/merge` (admin, CSRF) — body
  `{camara_principal_id, camara_secundaria_id, guardar_alias, csrf_token}`, devuelve contadores de
  todo lo migrado (`botellas_legado_migradas`, `botellas_cromo_migradas`, `cables_migrados`,
  `empalmes_migrados`, `ingresos_migrados`, `aliases_migrados`, `alias_creado`, `estado_final`).
  **Fusión de grupo**: `POST /api/infra/camaras/merge-grupo` — body `{camara_principal_id,
  camara_secundaria_ids: [...], guardar_alias, csrf_token}`, mismos contadores acumulados de las N
  fusiones. **Búsqueda liviana**: `GET /api/infra/camaras/buscar?q=...` (`id/nombre/direccion/estado/
  botellas_count/cables_count` — `botellas_count` suma botellas legado + Botellas Cromo propias desde
  2026-08-14, sin el N+1 de rutas/servicios de `smart-search` — pensada para selectores/autocomplete,
  no para el dashboard). **Frontend**: botón "Unificar Cámara" en el header del detalle
  (`CamaraDetailView.vue`, sólo admin, sólo si la Cámara no es ella misma una Botella) →
  `ModalUnificarCamara.vue` (buscar duplicada → resumen de impacto + checkbox de alias → confirmar).
- **Hallazgo real de routing durante la verificación (2026-08-11, sigue vigente)**:
  `GET /api/infra/camaras/buscar` chocaba con `GET /api/infra/camaras/{camara_id}` (registrada antes
  en `web/app/main.py`) — FastAPI matchea por orden de registro, así que "buscar" se interpretaba
  como `camara_id: int` y devolvía 422. Corregido registrando `/camaras/buscar` ANTES de la ruta con
  parámetro — cualquier ruta GET literal nueva bajo `/api/infra/camaras/` debe seguir este orden.

### Dashboard Viewer de Botellas — duplicados dentro de la misma Cámara padre y apropiación legado→Cromo (2026-08-14)

`/admin/servicios` → "Viewer" → tarjeta "Botellas" → `/admin/servicios/viewer/Botellas`: mismo estilo
dual grid/lista que el de Cámaras, pero el concepto de "duplicado" acá es distinto: no son dos
Cámaras raíz con nombre parecido, son dos hijas (Botella legado y/o `CromoBotella`) de la MISMA
Cámara padre que representan el mismo sitio físico — típicamente aparece después de fusionar dos
Cámaras raíz duplicadas (sección anterior), cuando ambas traían botellas que ahora conviven bajo el
mismo padre.

- **Listado general**: `GET /api/admin/infra/botellas/viewer`, delega en
  `core/services/botellas_unificadas_service.py::buscar_botellas_unificadas` (mismo servicio y
  patrón `AsyncSessionLocal` que ya usa `GET /api/infra/botellas/buscar`), con guarda admin
  adicional. Sin chips de estado individuales (el servicio subyacente sólo soporta el booleano
  `incluir_no_operativas`) — sólo el toggle "Mostrar no operativas" ya conocido de
  `BotellasInventarioView.vue`.
- **Filtro "Sólo duplicadas"**: `GET /api/admin/infra/botellas/viewer/duplicados`
  (`core/services/botella_duplicados_service.py::detectar_grupos_duplicados_botellas`) — agrupa las
  Botellas de ambos orígenes por Cámara padre común (`camara.botellas` self-FK + `CromoBotella.
  camara_id`, vigentes) y, dentro de cada padre, por nombre normalizado extendido (misma
  `normalizar_para_agrupar_extendido` de `camara_hierarchy_service.py`). Sólo 2 queries totales (con
  `joinedload` al padre), sin iterar las ~10.212 Cámaras raíz una por una. Cada tarjeta de grupo
  muestra la Cámara padre como encabezado (a diferencia de Cámaras, acá el agrupador natural es el
  padre, no el propio nombre) y un badge "⚠ Estados distintos"/"Revisión manual" según corresponda.
- **Política de resolución (2026-08-14, confirmada explícitamente por el usuario)**: "Cromo gana".
  Sólo el caso mixto de exactamente 1 legado + 1 Cromo dentro del mismo padre tiene botón "Apropiar"
  — la `CromoBotella` se conserva sin cambios, la Botella legado se elimina físicamente tras
  reasignar sus 7 tipos de FK reales (mismo mecanismo que `camara_merge_service.py`, adaptado) a la
  Cámara padre. Estado heredado vía `aplicar_estado_a_grupo` (ya sincroniza la `CromoBotella` del
  grupo). Evento explícito en `CamaraEstadoAuditoria` del padre. A diferencia de `unificar_camaras`,
  NO se crea un alias automático con el nombre de la legado — sólo se migran los que ya tenía. Ver
  `core/services/botella_merge_service.py`.
- **Endpoint**: `POST /api/infra/botellas/apropiar` (admin, CSRF) — body `{legado_id, cromo_n_id,
  csrf_token}`. Frontend: `AdminBotellasViewer.vue`, `ModalApropiarBotella.vue` (confirmación directa,
  sin paso de búsqueda — el par ya viene resuelto del grupo `resoluble`).
- **"Apropiación masiva" (2026-08-14)**: botón en el toolbar (con "Sólo duplicadas" activo) que
  apropia TODOS los grupos `resoluble` de un click, vía `POST /api/infra/botellas/apropiar-masivo` —
  `sugerir_apropiacion()` (`botella_duplicados_service.py`) resuelve el par legado/cromo de cada
  grupo. Grupos no resolubles se omiten (no tienen política automática). Mismo patrón de transacción
  por grupo que "Fusión masiva" de Cámaras — un grupo con error no revierte los ya apropiados.
- **Cierre del gap "Revisión manual" (2026-08-19)**: ver sección siguiente — legado↔legado,
  cromo↔cromo, y mixtos con 2+ legado, que hasta acá sólo se detectaban y mostraban sin acción, ahora
  tienen un botón "Consolidar".

### Consolidación manual de duplicados Cromo — cierra el gap "Revisión manual" (2026-08-19)

Cierra el gap consciente de la sección anterior. Política confirmada: Cromo siempre gana — si el
grupo a consolidar incluye una o más Botellas legado, sus datos se heredan a la `CromoBotella` elegida
como destino (reusando `apropiar_legado_a_cromo` tal cual). A diferencia de "Apropiar"/"Apropiación
masiva" (restringidos al par exacto 1 legado + 1 Cromo que el detector arma por nombre normalizado),
"Consolidar" opera sobre un **grupo libre**: el admin puede tipear a mano n_ids Cromo que el detector
nunca agrupó (el caso real que motivó `app.cromo_botella_alias` — botellas sin nombre no se agrupan
por normalización).

- **Señal "operativa" (tiene cables)**: `core/services/cromo/verificador.py::
  tiene_cables_asociados_batch_sync` — una sola query batcheada (`extremo_a_n_id`/`extremo_b_n_id`
  contra todos los n_ids de la página) para marcar qué miembro Cromo de un grupo tiene cables
  asociados, sin N+1. `GET /api/admin/infra/botellas/viewer/duplicados` ahora incluye
  `tiene_cables: boolean | null` por miembro (`null` para legado, esa señal no existe de ese lado).
  `POST /api/admin/infra/botellas/operatividad` (body `{n_ids}` → `{operativos}`) cubre el mismo
  chequeo para n_ids tipeados a mano, fuera de cualquier grupo detectado.
- **`POST /api/infra/botellas/consolidar`** (admin, CSRF) — body `{ids_origen_cromo, id_destino_cromo,
  ids_legado, nombre_destino, motivo, csrf_token}`. `core/services/cromo/consolidacion_service.py::
  consolidar_grupo_botellas`: crea/actualiza filas en `app.cromo_botella_alias`
  (`accion='fusionar'`) para cada origen, migra cada `id_legado` hacia el destino reusando
  `apropiar_legado_a_cromo` sin envolver su validación de mismo padre (si el admin combina un legado y
  un destino de otra Cámara padre, la función lo rechaza — mismo motivo por el que esa validación
  existe: evita reasignar Cables/Empalmes/Ingresos reales al sitio equivocado), y opcionalmente
  corrige `CromoBotella.nombre` si venía en blanco. Guardas explícitas: el destino no puede estar ya
  marcado como basura de otra fila de alias; repuntear un origen ya aliaseado se reporta
  (`alias_repuntados`), nunca es silencioso; cualquier alias que ya apuntaba a un origen que ahora
  desaparece se recablea directo al destino final (evita una cadena de 2 saltos —
  `resolver_referencia`, en la ingesta, nunca persigue cadenas).
  - **Fix real (2026-08-21)**: la fila `cromo_botella_alias` sólo la lee la ingesta FUTURA
    (`resolver_referencia`) — el `CromoBotella` origen, ya materializado de una corrida anterior,
    seguía `vigente=true` con el mismo nombre/`camara_id`, así que `detectar_grupos_duplicados_botellas`
    volvía a devolver el mismo grupo "duplicado" siempre, sin que ninguna corrida futura lo corrigiera
    (la ingesta sólo se abstiene de re-tocar un n_id aliaseado, nunca lo retira). Ahora
    `consolidar_grupo_botellas` también repuntea los `CromoCable.extremo_a/b_n_id`/
    `CromoFusion.botella_n_id` YA ingeridos que apuntaban al origen (el `resolver_referencia` de la
    ingesta nunca los toca retroactivamente) y marca el origen `vigente=False` — mismo flag que ya
    filtran `botella_duplicados_service`/`orfanas_service`/`botellas_unificadas_service`. Nuevos
    campos de respuesta: `cables_existentes_recableados`, `fusiones_existentes_recableadas`.
  - **`force_camera_association` (2026-08-24)**: bypasea el guard de "misma Cámara padre" descrito
    arriba — pero SÓLO ese, el que vive dentro de `apropiar_legado_a_cromo` y sólo se dispara cuando
    el body incluye `ids_legado`. **Hallazgo al auditar el código para este ticket, confirmado con el
    usuario y dejado deliberadamente sin resolver**: la consolidación Cromo↔Cromo pura
    (`ids_origen_cromo` sin ningún `id_legado`) nunca tuvo ningún guard de "misma Cámara padre", ni en
    este servicio ni en `ModalConsolidarBotellas.vue` — se puede fusionar cualquier n_id Cromo hacia
    cualquier destino sin ninguna advertencia. `force_camera_association` no toca ese camino. Cuando
    sí bypasea el guard (mismatch legado↔Cromo forzado), los datos reales del legado se migran igual
    que siempre a `legado.camara_padre_id` (nunca al `camara_id` previo de la Cromo — ver los puntos
    3-5 de `apropiar_legado_a_cromo` en la sección de abajo); para que el resultado sea coherente, la
    `CromoBotella` superviviente adopta esa misma Cámara padre
    (`ResultadoApropiacionBotella.camara_forzada`, propagado como
    `ResultadoConsolidacion.legados_con_camara_forzada` — nunca silencioso, mismo criterio que
    `alias_repuntados`).
- **Frontend**: `ModalConsolidarBotellas.vue` — botón "Consolidar" en cada tarjeta de grupo no
  `resoluble` (pre-completa destino/orígenes/legado desde el grupo), más botón de toolbar "Consolidar
  manualmente" (mismo modal, sin grupo — orígenes y destino 100% libres). Checkbox "Forzar asociación
  a la Cámara" junto a la selección de Botellas legado (2026-08-24) — envía
  `force_camera_association` en el payload.
- **Export de inconsistencias**: `GET /api/admin/infra/botellas/inconsistencias/exportar` (admin) —
  Excel (`pandas.ExcelWriter(engine="openpyxl")`, mismo patrón ya usado para el export de Cámaras) con
  columnas `ID Cromo | Nombre | Cámara Padre | Motivo`: huérfanas (`orfanas_service.buscar_huerfanas`)
  + un renglón por miembro de cada grupo `resoluble=False`. Para un miembro legado, `ID Cromo` queda
  vacío a propósito (no existe tal id en ese espacio) — su `Camara.id` se referencia dentro del propio
  `Motivo` en su lugar. Botón "Exportar inconsistencias" en el toolbar del viewer.

### Caché Redis + worker dedicado + WebSocket para el visor de duplicados (2026-08-21)

`detectar_grupos_duplicados_botellas` (2 queries `joinedload` sin paginar, agrupadas en Python) se
llama de forma síncrona en 3 endpoints; su costo escala con el tamaño total de `app.camaras`/
`app.cromo_botellas`, no con la cantidad de duplicados reales. Se agregó una caché Redis de lectura +
un worker dedicado que la recalcula en background + un canal WebSocket que avisa a cualquier panel
admin abierto cuando el recálculo termina — sin tocar la función de detección en sí. Detalle completo
(arquitectura, convenciones exactas, decisiones de infraestructura confirmadas y alcance YAGNI) en
`docs/superpowers/specs/2026-08-21-botellas-duplicados-redis-ws.md`; acá sólo el resumen operativo.

- **3 endpoints leen la caché antes de calcular** (`cache:botellas_duplicados:v1`, TTL 24h como red de
  seguridad — la invalidación real es explícita en cada mutación, ver abajo):
  `GET /api/admin/infra/botellas/viewer/duplicados` (el propio viewer), `GET
  /api/admin/infra/botellas/inconsistencias/exportar` (export), y `POST
  /api/infra/botellas/apropiar-masivo` (la necesita como insumo propio para decidir qué grupos son
  `resoluble`, no sólo para responder). Hit → se salta el cómputo completo. Miss (frío o Redis caído)
  → cómputo síncrono de siempre, sin cambios, más un `SET` oportunista del resultado.
- **8 endpoints mutadores invalidan la caché y encolan un recálculo** — cambian datos que afectan la
  agrupación (`vigente`, `camara_id`/`camara_padre_id`, `nombre`) pero ninguno recalculaba
  server-side antes de esto: `POST /api/infra/botellas/apropiar` (individual), `POST
  /api/infra/botellas/apropiar-masivo` (sólo si `grupos_apropiados > 0`), `POST
  /api/infra/botellas/consolidar`, `POST /api/infra/botellas/eliminar`, `POST
  /api/infra/botellas/eliminar-grupo` (2026-08-24, ver sección de eliminación más abajo), `POST
  /api/infra/botellas/{n_id}/repoblar-cables` (sólo si `resultado.corrida_id is not None` — hay un
  camino "nada pendiente" que no debe encolar nada), `POST
  /api/infra/botellas/{n_id}/separar-padre` y `PATCH /api/infra/botellas/{n_id}/nombre`. Los 8 llaman a
  `core.services.botella_recompute_queue.encolar_recalculo_duplicados_botellas(motivo)`, que borra la
  clave de caché (`DELETE`) y encola un job (`RPUSH admin:recompute:jobs {"kind":
  "botellas_duplicados", "motivo": ...}`) — siempre después de confirmar la mutación.
- **Worker dedicado** `modules/botellas_recalculo_worker/` (mismo layout que `modules/cromo_worker/`,
  imagen `focas-base` + Dockerfile propio, sin `BackgroundTasks`/Celery): un loop `BLPOP` sobre
  `admin:recompute:jobs` con un dispatch table (hoy un solo `kind` registrado,
  `botellas_duplicados`) que recalcula con la misma `detectar_grupos_duplicados_botellas` sin tocar,
  repuebla la caché y publica `{"type": "botellas_duplicados_recalculado", "at": "<iso8601 UTC>"}` en
  el canal Redis `admin-notifications`. `GET /health` (puerto interno `8097`) refleja la vida real del
  loop (`loop_muerto` si la tarea asyncio terminó), no un "ok" estático — y el healthcheck de Docker
  **mira el cuerpo de la respuesta**, no sólo el 200
  (`curl -fsS .../health | grep -qv loop_muerto`): con el `CMD curl` pelado anterior, un loop muerto
  seguía figurando `healthy`. El recálculo pesado corre en un hilo aparte (`asyncio.to_thread`)
  justamente para que ese `/health` siga contestando mientras el job trabaja: ejecutándolo directo en
  el event loop, el contenedor se marcaba `unhealthy` durante cada recálculo (~100s medidos, 3
  healthchecks vencidos seguidos). `detectar_grupos_duplicados_botellas` (compartida con `web`,
  ver más abajo) materializa además en lotes de 500 filas (`yield_per`, no `.all()`) con un
  `time.sleep(0)` entre lotes — sin esto, el hilo del `to_thread` retenía el GIL el tiempo
  suficiente para que `/health` (en el hilo principal) tardara hasta ~20s en responder durante un
  recompute real (2026-08-22). Verificado en vivo tras el fix: latencia máxima de `/health` durante
  un recompute completo, **0.40s** (`GET /health` sondeado cada ~0.3s, `jobs_procesados`
  incrementando durante la ventana medida) — ver `docs/decisiones.md`, entrada 2026-08-22 (cont. 2).
  Servicio `redis` (imagen
  fijada `redis:7.4-alpine`) y `botellas_recalculo_worker` agregados a `deploy/docker-compose.dev.yml`
  y `deploy/compose.yml` — en dev, buildeados, levantados y verificados `healthy` reales; en prod,
  código listo pero sin recrear contenedores (ver `docs/decisiones.md`, entrada 2026-08-21 (cont.)).
- **Canal WebSocket** `GET /ws/admin-notifications` (`web/admin_ws.py`) — a diferencia del WS de chat
  preexistente (`web/chat_ws.py`, 1 conexión ↔ 1 orchestrator), éste hace broadcast: un
  `ConnectionManager` registra todas las conexiones activas del panel admin y reenvía cada mensaje que
  llega por el canal pub/sub `admin-notifications` a todas. Exige sesión con `role == "admin"` (más
  estricto que el WS de chat) y valida `origin` igual que `chat_ws.py`; el proceso `web` se suscribe al
  canal en el arranque (`@app.on_event("startup")`). Frontend:
  `web/frontend/src/composables/useAdminNotifications.ts` (conecta al montar/desconecta al desmontar,
  reconexión con backoff exponencial + jitter, nunca reconecta si el cierre es código `4401` — sesión
  no admin). En `AdminBotellasViewer.vue`, los 3 handlers que antes bloqueaban en `Promise.all([
  reloadDuplicados(), reloadFromZero()])` (apropiar individual, apropiar masiva, consolidar) ahora sólo
  esperan `reloadFromZero()`; el evento WS dispara un `reloadDuplicados()` silencioso aparte. El botón
  "Actualizar" ya existente (`refrescar()`) sigue como fallback manual — no se agregó ninguno nuevo.
- **Redis nunca es una dependencia dura**: cada punto de fallo (lectura/escritura de caché, encolado,
  publish, subscribe) se atrapa y loguea — el sistema completo degrada al comportamiento síncrono de
  siempre, correcto, sólo sin la mejora de velocidad. Hay **dos** factories en
  `core/cache/redis_client.py`, y usar la equivocada rompe cosas sutiles:
  - `get_redis()` — singleton para comandos CORTOS Y ACOTADOS (`GET`/`SET`/`DEL`/`RPUSH`/`PUBLISH` y
    el `BLPOP` del worker). `socket_connect_timeout=2`, `socket_timeout=10` (subido desde `2` durante
    la implementación: tiene que superar con margen el `BLPOP_TIMEOUT_SECONDS=5` del worker, o cada
    ciclo `BLPOP` sin jobs tira un `TimeoutError` espurio tratado como "Redis caído").
  - `get_redis_pubsub_client()` — conexión DEDICADA para el subscriber de larga vida de
    `web/admin_ws.py`, con `socket_timeout=None` (bloquear indefinidamente en la lectura, que es lo
    que un subscriber debe hacer) + keepalive TCP. Sin esto, `PubSub.listen()` heredaba el
    `socket_timeout=10` del cliente compartido y **cada 10s de silencio genuino del canal** levantaba
    `TimeoutError` → desconexión → resuscripción: medido con `PUBSUB NUMSUB` contra el dev real, el
    canal quedaba **sin suscriptores 9 de cada 24 muestras (~1/3 del tiempo)**, y todo lo publicado
    en esas ventanas se perdía para siempre (pub/sub es fire-and-forget). Tras el fix, 46/46 muestras
    en 96s de idle dieron `1`, sin una sola caída a `0`. Los fallos REALES se siguen detectando
    igual: cuando el server cierra la conexión, el parser levanta
    `ConnectionError("Connection closed by server.")` y el mismo `except` de siempre reintenta con
    backoff (verificado deteniendo el contenedor `redis` en vivo).
- **Escotilla manual de refresco** (`?refrescar=true`): `GET
  /api/admin/infra/botellas/viewer/duplicados` acepta ese parámetro para **saltear la caché por
  completo** y forzar el cómputo, repoblando la caché con el resultado fresco. Lo usa el
  botón "Actualizar" del visor (`refrescar()` → `reloadDuplicados(true)`). El cómputo (acá y en los
  otros 2 call-sites directos de `detectar_grupos_duplicados_botellas` en `web/app/main.py` —
  `apropiar-masivo` y el export de inconsistencias, ambos en su propio cache-miss) corre vía
  `await asyncio.to_thread(...)`, no directo en el `async def` del endpoint (2026-08-22): antes del
  fix, cualquiera de los 3 bloqueaba el event loop entero de `web` durante todo el cómputo — medido
  en vivo, ~56-60s con **0 heartbeats** de una tarea `asyncio.sleep(0.2)` corriendo en paralelo.
  Con el fix, la misma tarea siguió latiendo cada 0.56-0.68s durante un cómputo real de ~72s — ver
  `docs/decisiones.md`, entrada 2026-08-22 (cont. 2). Existe porque hay
  escritores que tocan los mismos campos y **no** invalidan la caché — la ingesta Cromo
  (`modules/cromo_worker/`, su propio intervalo de 24h), los cambios de estado/baneo
  (`aplicar_estado_a_grupo`), merge/eliminar de Cámaras y `scripts/cromo_backfill_camara_padre.py`.
  Cablearles la invalidación a los cuatro es una decisión deliberadamente diferida (ver
  `docs/decisiones.md`, entrada 2026-08-21 (cont.)); el refetch automático por WebSocket NO fuerza,
  porque ahí el worker ya dejó la caché fresca.
- **Prod: falta generar el secret `redis_password_v1`**. `deploy/compose.yml` ya declara el secret y
  lo consume desde `web`/`redis`/`botellas_recalculo_worker`, pero `.secrets/redis_password_v1.txt`
  **no existe en el host de producción** — a propósito. Compose no degrada ante un secret file-based
  inexistente: **falla la creación del contenedor `web`**. Procedimiento completo (generación,
  verificación post-despliegue, rollback) en
  [docs/mantenimiento_redes_produccion.md](mantenimiento_redes_produccion.md), sección
  "Pre-requisito obligatorio: secret `redis_password_v1`".

### Eliminación de Cámaras/Botellas basura + exclusión automática en Cromo (2026-08-20)

El "Verificador Cromo"/"Validar datos DB Cromo" (2026-08-19) dejaron a la vista basura heredada de
backfills viejos: Botellas Cromo con nombre "0", sin cables asociados, cuya Cámara padre a veces
tampoco tiene nada más. Se agrega un borrado permanente admin-only, con política **bloquear, nunca
forzar** (confirmada explícitamente por el usuario): si el elemento — o cualquier hijo, en el caso de
una Cámara — tiene Cables/Empalmes/Ingresos (legado) o Cables/Fusiones (Cromo) reales asociados, la
eliminación se rechaza sin borrar nada. `eliminar_camara` es además **todo o nada**: si un solo hijo
bloquea, se aborta la operación completa antes de tocar la sesión.

- **`core/services/camara_botella_delete_service.py`** (nuevo) — dos funciones públicas que comparten
  los mismos helpers de chequeo (`_bloqueo_camara`, `_bloqueo_cromo_botella`) usados tanto para el
  borrado individual como para el cascada, evitando dos implementaciones divergentes del mismo
  criterio "¿esto está realmente vacío?":
  - `eliminar_botella(origen, id, usuario)` — Cromo: bloquea por `CromoCable.extremo_a/b_n_id`,
    `CromoFusion.botella_n_id`, o ser destino de otra fila de `cromo_botella_alias`; si está limpia,
    registra el `n_id` en `app.cromo_botella_alias` (`accion='ignorar'`, upsert-por-origen — mismo
    patrón que `consolidacion_service.py`) y borra. Legado: exige que sea una Botella
    (`camara_padre_id is not None`), bloquea por `Cable.origen/destino_camara_id`, `Empalme.camara_id`,
    `Ingreso.camara_id`. En ambos casos, tras `session.flush()` (obligatorio — con `autoflush=False` la
    comprobación de "padre vacío" todavía vería el hijo recién borrado), intenta `eliminar_camara()`
    sobre la Cámara padre; si esta levanta `EliminacionBloqueadaError` (el padre tiene otros datos), se
    atrapa en silencio — el padre sobrevive, no es un error.
  - `eliminar_camara(camara_id, usuario)` — rechaza si es en realidad una Botella
    (`camara_padre_id is not None`, mismo criterio que `unificar_camaras`). Reúne TODOS los hijos
    (self-FK `Camara.camara_padre_id` + `CromoBotella.camara_id`) y corre TODOS los chequeos de
    bloqueo antes de cualquier `session.delete`/`add` — todo-o-nada real. Si está limpia: alias +
    delete por cada `CromoBotella` hijo, delete por cada Cámara hijo self-FK, flush, delete de la raíz.
  - **Sin sobreviviente, sin auditoría persistente**: a diferencia de `unificar_camaras`/
    `apropiar_legado_a_cromo` (que siempre dejan un evento en `CamaraEstadoAuditoria` del
    sobreviviente), acá no hay sobreviviente — `CamaraEstadoAuditoria` de la fila borrada cascadea
    (`ondelete=CASCADE`) junto con ella. No queda rastro en base de datos de que existió, sólo el
    `logger.info(...)` del endpoint. Agregar una tabla de auditoría dedicada quedó fuera de alcance de
    este ticket.
- **Endpoints** (admin, CSRF, `web/app/main.py`):
  - `POST /api/infra/botellas/eliminar` — body `{origen, id, csrf_token}`. 400 con
    `{"error", "bloqueos": [{origen, id, nombre, razon}]}` si se rechaza; 200 con
    `{ok, origen, id, camara_padre_eliminada, alias_registrado}` si se borra.
  - `POST /api/infra/camaras/eliminar` — body `{camara_id, csrf_token}`. Mismo 400 con `bloqueos`; 200
    con `{ok, camara_id, botellas_legado_eliminadas, botellas_cromo_eliminadas, aliases_registrados}`.
- **Frontend**: botón "Eliminar Botella"/"Eliminar Cámara" gateado por `isAdmin` (mismo idiom
  `useSession` ya usado en el resto de la app — no hay export compartido, cada vista lo re-deriva) en
  `CamaraDetailView.vue` (`.camara-detail-hero__actions`, etiqueta condicional según
  `camara.es_botella`) y `VerificadorCromoView.vue` (junto a "Ver info en Cromo", sólo con
  `tipo === 'botella'`). Confirmación inline estilo `AdminBaneos.vue` (no un modal): "⚠️ ¿Eliminar
  permanentemente...? Esta acción no se puede deshacer." + "Sí, eliminar"/"Cancelar"; si el backend
  responde 400 con `bloqueos`, se listan con su `razon`. En `CamaraDetailView.vue`, al confirmar con
  éxito se redirige a `/infra` (la vista deja de tener sentido — el elemento que mostraba ya no
  existe); en `VerificadorCromoView.vue` se limpia el resultado local y se muestra un mensaje de éxito
  transitorio.

#### "Borrar y Excluir Cromo" — borrado forzado de grupo (2026-08-24)

El botón "Borrar y Excluir Cromo" del visor de duplicados (`/admin/servicios/viewer/Botellas`) cubre
el caso real que la política de arriba deja sin salida a propósito: un grupo completo de
`CromoBotella` conflictivas (residuo de un cambio de nombre en la ingesta) que SÍ tienen
`CromoCable`/`CromoFusion` reales — datos incorrectos, no datos que valga la pena preservar. Es
**deliberadamente el único camino de este módulo que ignora "bloquear, nunca forzar"**:
`eliminar_botella`/`eliminar_camara` no cambiaron, siguen bloqueando siempre para cualquier otro
llamador — no ganaron ningún flag de bypass.

- **`core/services/camara_botella_delete_service.py::eliminar_y_excluir_grupo_cromo(ids_cromo,
  usuario)`** (nueva, función separada) — de-dup de `ids_cromo`; borrado físico completo
  (`.delete(synchronize_session=False)`, bulk) de todos los `CromoCable`/`CromoFusion` cuyo extremo o
  `botella_n_id` esté en la lista, **sin excluir** los que tengan el otro extremo en una botella que
  se conserva (confirmado con el usuario: es limpieza de datos incorrectos, no una operación
  quirúrgica); registra cada n_id encontrado en `app.cromo_botella_alias`
  (`accion='ignorar'`, reusa `_registrar_alias_ignorar`) y lo borra. IDs pedidos que no existen se
  reportan en `no_encontradas` sin abortar el resto. No intenta limpiar la Cámara padre si queda
  vacía — no fue pedido, y mezclarlo con un borrado sin bloqueos daría una garantía distinta a la de
  `eliminar_botella`.
- **`POST /api/infra/botellas/eliminar-grupo`** (admin, CSRF) — body `{ids_cromo, csrf_token}`, 200
  con `{ok, botellas_eliminadas, cables_eliminados, fusiones_eliminadas, aliases_registrados,
  no_encontradas}`. Es el 8vo endpoint mutador que encola un recálculo de duplicados (ver sección de
  caché Redis más arriba).
- **Frontend**: `AdminBotellasViewer.vue` — botón "Borrar y Excluir Cromo" en el header de cada
  tarjeta de grupo (visible si el grupo tiene algún miembro Cromo, sin restringirlo a `!resoluble`),
  actúa sobre **todos** los miembros Cromo del grupo mostrado (no hay selección por subconjunto).
  Confirmación inline (mismo estilo que la eliminación individual) listando los n_id afectados antes
  de confirmar.

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
  **Tercer origen (2026-08-24)**: la ingesta Excel de cámaras baneadas
  (`core/services/camara_ingest_service.py`, `origen="excel_camaras"` — ver sección "Ingesta Excel de
  cámaras baneadas" más arriba) registra acá los alias que no matchearon contra el inventario. A
  diferencia de los otros 2 orígenes (que sólo admiten triage, "marcar revisado"), `excel_camaras` es
  el único de los 3 que hoy tiene además una acción de resolución real: la asociación manual
  (`POST /api/admin/ingesta/camaras/asociar`) que crea un `CamaraAlias` y banea la Cámara/Botella
  destino.
- **No se toca** el panel admin "Cámaras Pendientes de Revisión" (`GET/POST /api/admin/infra/camaras/pendientes*`)
  — sigue disponible para gestionar las 34 filas legado ya existentes al 2026-08-11, simplemente deja
  de recibir filas nuevas.
- **Endpoints nuevos**: `GET /api/admin/infra/ingresos-sin-match` (filtro opcional `revisado`),
  `POST /api/admin/infra/ingresos-sin-match/{id}/marcar-revisado`. **Frontend**: nueva sección
  acordeón "Ingresos sin match" en `AdminBaneos.vue`, mismo patrón visual que "Cámaras Pendientes".
- **Cerrado (Tarea 3 del refactor de baneos, 2026-08-23, commit `2c17296`)**: cuando se escribió esta
  sección (2026-08-11), `core/services/infra_service.py` tenía una función separada (entonces con el
  mismo patrón de auto-creación `DETECTADA`/`TRACKING`) usada por las acciones del flujo
  "analyze→modal→resolve" de `InfraService` (`_action_create_new`/`_action_merge_append`/
  `_action_replace`/`_action_branch`/`_action_confirm_upgrade`/`_action_add_strand`) — quedaba
  explícitamente fuera de alcance de este pase. Eso ya no es así: esa función es hoy
  `_resolve_camara_o_registrar_sin_match`, reescrita para usar `buscar_camara_o_botella_cromo`
  (búsqueda extendida Camara+CromoBotella, ver `docs/modulo_ingesta_cromo.md`) y registrar
  `IngresoSinMatch` (`origen="tracking"`) igual que el resto de los flujos de esta sección — **nunca
  crea una `Camara` nueva**. Unifica así las 3 superficies que antes podían auto-crear una cámara al
  no matchear: el bot de Slack, `upload_tracking_web`, y las acciones de `InfraService` recién
  listadas.

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

**Registros** muestra:

- pestaña **Ingresos** (desde 2026-08-31) poblada con los movimientos reales de `app.ingresos` del
  grupo cámara+botellas hermanas (`_serialize_camara_ingreso` en `web/app/main.py`, consumido por
  `ModalRegistros.vue` vía prop `ingresos`) — ver "Escritura de `Ingreso` sobre el grupo" más arriba
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

#### Dos dominios de baneo conviviendo (2026-08-24)

Hoy convive el **Protocolo de Protección** de arriba (`/api/infra/ban/*`, orientado a
`IncidenteBaneo`/`servicio_protegido_id`, wizard guiado desde el header) con el **panel de baneos
agrupados** nuevo (`/admin/Servicios/Baneos`, pestaña "Baneos Activos") — este último lista Cámaras
padre baneadas por CUALQUIER camino (Protocolo, ingesta Excel de cámaras, override manual) agrupadas
con sus Botellas hijas, y permite **liberar (desbanear) varios grupos de una** vía
`POST /api/admin/baneos/grupos/liberar`. "Liberar" respeta un guard: un grupo con un `IncidenteBaneo`
activo detrás se omite salvo que se pase `forzar=true` explícito — evita que el panel anule
silenciosamente una protección que el Protocolo todavía necesita. No hay ningún borrado físico de
Cámaras/Botellas en este flujo — "liberar" es únicamente un cambio de estado.

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
Obtiene registros operativos de la cámara: auditoría manual de estado, baneos relacionados e ingresos/egresos reales (`app.ingresos`, grupo cámara+botellas hermanas — ver detalle en `docs/api.md`).

### GET /api/infra/camaras/{camara_id}/botellas
Obtiene las Botellas de una Cámara, unificando ambos orígenes: legado (self-FK, jerarquía Cámara/Botella de esta sección) + Cromo (`CromoBotella.camara_id`, vigentes). Cada ítem lleva `origen: "legado"|"cromo"`. Nunca aplica el filtro de "No operativa" — es un drill-down sobre un grupo ya identificado. Lista de legado vacía si `camara_id` es en sí una Botella legado.

### GET /api/infra/botellas/buscar
Listado unificado de Botellas Cromo + legado (ver sección "Submódulo Botellas" más arriba). Query params: `q` (`ILIKE` sobre nombre, +calle/localidad para Cromo), `limit` (default 30, clamp 1-100), `offset`, `incluir_no_operativas` (bool, default `false` — oculta `estado='NO_OPERATIVA'` de ambos orígenes). Respuesta: `{total, limit, offset, incluir_no_operativas, botellas: [{origen: "cromo"|"legado", id, nombre, estado}]}` — `estado` real para ambos orígenes desde 2026-08-11 (antes, siempre `null` para `origen="cromo"`).

### PUT /api/infra/botellas/estado
Cambia el estado de un lote de Botellas de origen mixto (admin, CSRF). Body: `{items: [{origen: "cromo"|"legado", id}], estado, motivo?, csrf_token}` — `estado` uno de `LIBRE/OCUPADA/BANEADA/NO_OPERATIVA`. Legado cascada por grupo completo (`aplicar_estado_a_grupo`, dedupeado por raíz); Cromo actualiza `CromoBotella.estado` directo (foto propia, sin cascada). Respuesta: `{ok, estado_nuevo, legado_actualizadas, cromo_actualizadas, no_encontrados: [{origen, id}]}`. Ver sección "Fallback de nombre exacto + bug real de idempotencia corregido (2026-08-12)" más arriba y `core/services/botellas_estado_masivo_service.py`.

### GET /api/infra/camaras/buscar
Búsqueda liviana de Cámaras por nombre (`ILIKE`), para selectores/autocomplete (unificación, asociación de huérfanas, asociación manual de la ingesta Excel) — no para el dashboard. Query params: `q`, `limit` (default 10, clamp 1-50), `excluir_id`, `solo_raiz` (default `true`, preserva el comportamiento histórico de sólo Cámaras raíz; `false` incluye también Botellas legado — ver sección "Ingesta Excel de cámaras baneadas" más arriba). Respuesta: `{camaras: [{id, nombre, direccion, estado, botellas_count, cables_count, es_botella, camara_padre_id, camara_padre_nombre}]}` (`botellas_count` suma botellas legado + Cromo desde 2026-08-14; los 3 últimos campos sólo se pueblan — no-`null`/no-`false` — cuando `solo_raiz=false` y la fila es una Botella). Registrada antes de `GET /api/infra/camaras/{camara_id}` en el código — ver nota de routing en "Cámaras duplicadas" más arriba.

### POST /api/infra/camaras/merge
Fusiona dos Cámaras raíz duplicadas (admin, CSRF). Body: `{camara_principal_id, camara_secundaria_id, guardar_alias, csrf_token}`. La secundaria se elimina físicamente tras heredar todo lo heredable — ver sección "Cámaras duplicadas — Unificación manual" más arriba.

### POST /api/infra/camaras/merge-grupo
Fusiona TODAS las Cámaras de un grupo de duplicados dentro de una sola principal (admin, CSRF). Body: `{camara_principal_id, camara_secundaria_ids: [...], guardar_alias, csrf_token}`. Loop de `unificar_camaras()` con `session.expire_all()` entre cada llamada — ver sección "Dashboard Viewer de Cámaras" más arriba y `core/services/camara_merge_service.py::fusionar_grupo_camaras`.

### POST /api/infra/camaras/merge-masivo
Fusiona automáticamente TODOS los grupos de Cámaras duplicadas detectados en el momento de la ejecución (admin, CSRF). Body: `{guardar_alias, csrf_token}`. Cada grupo elige su principal vía `sugerir_principal()` y corre en su propia transacción — un grupo con error no revierte los ya fusionados. Respuesta: `{ok, total_grupos, grupos_fusionados, grupos_con_error, detalle: [...]}`. Ver sección "Dashboard Viewer de Cámaras" más arriba.

### GET /api/admin/infra/camaras/viewer
Listado paginado dual de Cámaras raíz para `/admin/servicios/viewer/Camaras` (admin). Query params: `q`, `estado`, `limit` (clamp 1-100), `offset`. Respuesta: `{total, limit, offset, camaras: [{id, nombre, estado, botellas_count, cables_count}]}`.

### GET /api/admin/infra/camaras/viewer/duplicados
Grupos de Cámaras raíz candidatas a duplicado por nombre normalizado extendido (admin, sin paginar) — ver `core/services/camara_duplicados_service.py`.

### GET /api/admin/infra/botellas/viewer
Listado paginado dual de Botellas (Cromo + legado) para `/admin/servicios/viewer/Botellas` (admin) — delega en `buscar_botellas_unificadas`, mismo shape que `GET /api/infra/botellas/buscar`.

### GET /api/admin/infra/botellas/viewer/duplicados
Grupos de Botellas candidatas a duplicado dentro de la misma Cámara padre (admin, sin paginar) — ver `core/services/botella_duplicados_service.py`. Cada grupo puede traer además `sugerencia_placeholders` (`{id_destino_cromo, ids_origen_cromo}`, o `null` si no aplica): se emite sólo cuando el grupo es 100% Cromo (ningún miembro legado) y exactamente uno de sus miembros tiene cables asociados — ese es el destino y el resto son placeholders vacíos "ID dual" (`sugerir_consolidacion_placeholders`, mismos ids que espera `POST /api/infra/botellas/consolidar`).

### POST /api/infra/botellas/apropiar
Apropia una Botella legado hacia su CromoBotella hermana (admin, CSRF). Body: `{legado_id, cromo_n_id, csrf_token}` — ver sección "Dashboard Viewer de Botellas" más arriba y `core/services/botella_merge_service.py`.

### POST /api/infra/botellas/apropiar-masivo
Apropia automáticamente TODOS los grupos `resoluble` detectados en el momento de la ejecución (admin, CSRF). Body: `{csrf_token}`. Grupos no resolubles se omiten. Cada grupo corre en su propia transacción. Respuesta: `{ok, total_grupos, grupos_resolubles, grupos_apropiados, grupos_con_error, detalle: [...]}`. Ver sección "Dashboard Viewer de Botellas" más arriba.

### POST /api/infra/botellas/consolidar
Consolida un grupo LIBRE de n_ids Cromo (no restringido a un grupo detectado por nombre) hacia un único destino, opcionalmente migrando una o más Botellas legado y corrigiendo el nombre del destino (admin, CSRF). Body: `{ids_origen_cromo, id_destino_cromo, ids_legado, nombre_destino, motivo, csrf_token}`. Ver sección "Consolidación manual de duplicados Cromo" más arriba y `core/services/cromo/consolidacion_service.py`.

### POST /api/admin/infra/botellas/operatividad
Cuáles de los n_ids Cromo dados tienen al menos un cable asociado — señal "operativa" para elegir un destino al consolidar IDs tipeados a mano (admin). Body: `{n_ids}`. Respuesta: `{operativos: [...]}`.

### GET /api/admin/infra/botellas/inconsistencias/exportar
Excel de inconsistencias sin resolver — huérfanas + miembros de grupos duplicados no `resoluble` (admin). Columnas: `ID Cromo | Nombre | Cámara Padre | Motivo`.

### POST /api/infra/botellas/eliminar
Elimina permanentemente una Botella (Cromo o legado) genuinamente vacía — rechaza con 400 y `{error, bloqueos}` si tiene Cables/Empalmes/Ingresos/Fusiones reales asociados (admin, CSRF). Body: `{origen, id, csrf_token}`. Si es Cromo y se borra, registra el `n_id` en `app.cromo_botella_alias` (`accion='ignorar'`) para que la ingesta no la resucite. Intenta además eliminar la Cámara padre si queda vacía. Respuesta: `{ok, origen, id, camara_padre_eliminada, alias_registrado}`. Ver sección "Eliminación de Cámaras/Botellas basura" más arriba y `core/services/camara_botella_delete_service.py`.

### GET /api/infra/cromo/botellas/{n_id}/cables-detectados
Verificador Cromo — "Cables detectados en Cromo": consulta la botella EN VIVO contra Cromo (siguiendo `hist[]`/`next_id` si el `n_id` quedó vacío por un caso de "ID dual") y compara sus cables contra `app.cromo_cables` local. Sólo lectura, nunca persiste — cualquier usuario autenticado, mismo criterio que el resto de `/api/infra/cromo/*`. Respuesta: `{botella_n_id, ids_cadena, cables: [{n_id, nombre, extremo_a_n_id, extremo_b_n_id, estado_local: "OK"|"FALTA"|"DESACTUALIZADO"}]}`. 404 si la botella no existe local o el n_id no existe en Cromo; 502 si Cromo no responde. Ver `docs/db.md`, sección "Repoblación de cables con historial 'ID dual'", y `core/services/cromo/repoblacion_service.py::detectar_cables_faltantes`.

### POST /api/infra/botellas/{n_id}/repoblar-cables
Verificador Cromo — "Repoblar Cables": toma los cables que el endpoint anterior detectó faltantes/desactualizados y los persiste en `app.cromo_cables`/`cromo_tubos`/`cromo_pelos` local, con el extremo correctamente anclado a esta Botella (admin, CSRF). Body: `{csrf_token}`. Nunca escribe hacia Cromo ni toca `CromoBotella`/`CromoFusion`. Si no hay nada pendiente, no crea una corrida (evita ensuciar el histórico admin con clicks repetidos). Respuesta: `{ok, corrida_id, botella_n_id, creados, actualizados, sin_cambios, errores, detalle: [{n_id, accion, detalle}]}`. Ver `core/services/cromo/repoblacion_service.py::repoblar_cables`.

### PATCH /api/infra/botellas/{n_id}/nombre
Verificador Cromo — corrección manual de un nombre de Botella Cromo duplicado/incorrecto (admin, CSRF). Body: `{nombre, csrf_token}`. Marca `cromo_botellas.nombre_editado_manual=True` para que ninguna corrida de ingesta futura la pise. Si la Botella **ya existe localmente**, es escritura local pura y no toca Cromo. Si **no existe** (caso "ID dual": Cromo la reportó bajo otro n_id en una corrida anterior), consulta Cromo **en vivo y de sólo lectura** (`core/services/cromo/botella_creacion_service.py::crear_o_actualizar_botella_desde_vivo`, sigue la cadena `hist[]`/`next_id`) para crear la fila antes de aplicar la corrección — nunca escribe hacia Cromo. Respuesta: `{ok, n_id, nombre}`, más `n_id_solicitado` cuando el n_id de la URL era un id de versión y la fila quedó bajo el n_id de linaje que reporta Cromo: **el `n_id` de la respuesta es siempre el real, puede diferir del de la URL** (anclar al de la URL plantaba una fila huérfana que la ingesta siguiente volvía a duplicar — hallazgo de la revisión final del 2026-08-22). Status codes: 400 si el nombre queda vacío tras `.strip()` o si la clase resuelta está excluida (no es una Botella); 404 si no existe ni local ni en Cromo; 409 si la cadena resuelve a un n_id que YA tiene fila local propia (respuesta con `n_id_correcto`, sin crear duplicado); 502 si Cromo no responde o no está configurado; 500 (logueado con traza) ante cualquier error inesperado del alta desde vivo.

### POST /api/infra/botellas/{n_id}/separar-padre
Separa una Botella Cromo agrupada erróneamente por nombre bajo una Cámara padre compartida: crea una Cámara nueva e independiente (`origen_datos=MANUAL`) y reasigna `camara_id` (admin, CSRF). Body: `{nombre, motivo, csrf_token}` — `nombre` siempre editable en el modal, se aplica también a `cromo_botellas.nombre` (`nombre_editado_manual=True`, mismo mecanismo que el endpoint de edición de nombre). Rechaza con 400 si el nombre, tras normalizar (`normalizar_para_agrupar_extendido`, mismo criterio que el detector de Cámaras duplicadas), colisiona con cualquier Cámara raíz existente — incluida la Cámara padre original si no se cambió el nombre. 404 si la Botella no existe. Nunca toca la Cámara padre anterior (ni la elimina ni la audita) — usar "Eliminar Cámara" por separado si corresponde. Respuesta: `{ok, botella_n_id, camara_anterior_id, camara_nueva_id, camara_nueva_nombre}`. Ver `docs/decisiones.md` y `core/services/cromo/separacion_service.py`.

### POST /api/infra/camaras/eliminar
Elimina permanentemente una Cámara raíz y sus Botellas — todo o nada: si la Cámara o cualquiera de sus Botellas tiene datos reales asociados, rechaza con 400 y `{error, bloqueos}` sin borrar nada (admin, CSRF). Body: `{camara_id, csrf_token}`. Cada Botella Cromo eliminada registra su `n_id` en `app.cromo_botella_alias` (`accion='ignorar'`). Respuesta: `{ok, camara_id, botellas_legado_eliminadas, botellas_cromo_eliminadas, aliases_registrados}`. Ver sección "Eliminación de Cámaras/Botellas basura" más arriba.

### GET /api/infra/cromo-botellas/huerfanas
Botellas Cromo vigentes sin `camara_id` (no matchearon el backfill automático). Query params: `q`, `limit` (default 30, clamp 1-100), `offset`. Respuesta: `{total, limit, offset, botellas: [{n_id, nombre, calle, localidad}]}`.

### GET /api/infra/cromo-botellas/{n_id}/estado-asociacion
Chequeo liviano de una Botella Cromo puntual — `{n_id, nombre, huerfana: bool}`. Usado por `BotellaDetalleUnificadaView.vue` antes de decidir si redirige o muestra el panel de resolución.

### POST /api/infra/cromo-botellas/asociar
Asocia una o más Botellas Cromo huérfanas a una Cámara existente o nueva. Body: `{n_ids, camara_id?, nombre_nueva_camara?, csrf_token}` — exactamente uno de `camara_id`/`nombre_nueva_camara`. Ver sección "Botellas Cromo huérfanas — resolución manual" más arriba.

### GET /api/admin/infra/ingresos-sin-match
Lista casos de ingreso (Slack, tracking o ingesta Excel de cámaras) sin match contra el inventario — reemplaza el auto-registro `PENDIENTE_REVISION` (ver sección homónima más arriba). Query params opcionales: `revisado` (bool), `origen` (coma-separado, ej. `?origen=excel_camaras` o `?origen=slack,tracking`; default sin filtrar).

### POST /api/admin/infra/ingresos-sin-match/{caso_id}/marcar-revisado
Marca un caso como revisado — no muta ningún dato de infraestructura, sólo el flag de triage.

### POST /api/admin/infra/ingresos-sin-match/marcar-revisado-masivo
Marca en lote varios casos como revisados — el "Descartar" del Revisor Manual de la ingesta Excel de cámaras. Sólo oculta de la vista, no muta ningún dato de infraestructura. Ver sección "Ingesta Excel de cámaras baneadas" más arriba y `docs/api.md`.

### POST /ingest/camaras
Endpoint interno (servicio `api`) de la ingesta masiva de cámaras desde Excel — nunca crea una `Camara` nueva. Ver sección "Ingesta Excel de cámaras baneadas" más arriba y `docs/api.md` para el contrato completo.

### POST /api/admin/ingesta/camaras/asociar
Resuelve a mano uno o más `IngresoSinMatch` de la ingesta Excel de cámaras hacia una Cámara/Botella existente (crea `CamaraAlias` + banea). Ver sección "Ingesta Excel de cámaras baneadas" más arriba y `docs/api.md`.

### GET /api/admin/baneos/grupos
Lista Cámaras padre baneadas (por cualquier camino) agrupadas con sus Botellas hijas, para el panel `/admin/Servicios/Baneos` → pestaña "Baneos Activos". Ver sección "Dos dominios de baneo conviviendo" más arriba y `docs/api.md`.

### POST /api/admin/baneos/grupos/liberar
Libera (desbanea) varios grupos de una — la única acción masiva de este panel, sin ningún borrado físico. Guard de `IncidenteBaneo` activo salvo `forzar=true`. Ver sección "Dos dominios de baneo conviviendo" más arriba y `docs/api.md`.

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

### 2026-08-24 - La ingesta Excel de cámaras deja de crear, panel de baneos agrupados con desbaneo masivo

- **Agregado**: la ingesta Excel de cámaras baneadas dejó de ser un camino de alta de `Camara` — ahora
  resuelve cada alias contra el inventario real (`buscar_camara_o_botella_cromo`, matcher extendido
  Camara+CromoBotella) y sólo banea lo que ya existe; un alias sin match se registra en
  `app.ingresos_sin_match` (`origen="excel_camaras"`, tercer valor de esa columna) para revisión
  manual, nunca crea una `Camara` nueva.
- **Agregado**: asociación manual (`POST /api/admin/ingesta/camaras/asociar`) que crea un `CamaraAlias`
  y banea el grupo destino — el "Revisor Manual" de `AdminIngestaCamaras.vue` permite seleccionar
  varios nombres sin match, descartarlos (`POST /api/admin/infra/ingresos-sin-match/marcar-revisado-masivo`)
  o asociarlos por typeahead (`GET /api/infra/camaras/buscar?solo_raiz=false`, que ahora también
  devuelve Botellas con `es_botella`/`camara_padre_id`/`camara_padre_nombre`).
- **Agregado**: panel de baneos agrupados (`/admin/Servicios/Baneos` → pestaña "Baneos Activos",
  `GET/POST /api/admin/baneos/grupos*`) que lista Cámaras padre baneadas con sus Botellas hijas y
  permite liberar (desbanear) varios grupos de una — con guard de `IncidenteBaneo` activo salvo
  `forzar=true`. Convive con el Protocolo de Protección existente, sin reemplazarlo. `AdminBaneos.vue`
  pasó a ser un contenedor de 3 tabs (Baneos Activos / Configuración / Revisión).
- **Corregido**: bug de cascada en `override_camara_estado_manual` — comparaba el estado de la fila
  puntual en vez del grupo completo, dejando hermanas desincronizadas cuando el grupo quedaba mixto
  (ej. tras un `lift_ban` parcial). Afecta a toda la jerarquía Cámara/Botella, no sólo a la ingesta.
- **Sin borrado físico**: "liberar" (panel de baneos) y el resto de este cambio son únicamente cambios
  de estado — ningún endpoint de eliminación de Cámaras/Botellas se agregó en este pase.

### 2026-08-12 - Fallback de nombre exacto, fix de idempotencia real, cambio de estado masivo, propagación de estado a CromoBotella

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
- **Corregido — bug real de propagación de estado** (reportado por el usuario desde el dashboard:
  Botellas mostrando `OCUPADA` sin ningún `Ingreso` activo real): 295 `CromoBotella` quedaron con un
  estado stale porque `aplicar_estado_a_grupo` nunca las tocaba tras el backfill inicial. Cerrado
  estructuralmente (`aplicar_estado_a_grupo` ahora sincroniza las `CromoBotella` vinculadas en cada
  cambio real de estado) + corrección retroactiva (`scripts/resync_cromo_botella_estado.py`, 295
  filas corregidas → 0 desincronizadas). Ver sección "Propagación de estado a CromoBotella + resync
  real (2026-08-12)" más arriba.
- Ver también sección "Fallback de nombre exacto + bug real de idempotencia corregido (2026-08-12)"
  más arriba para el detalle del resto de esta tanda.

### 2026-08-11 (cont.) - Retiro de DETECTADA, unificación de Cámaras, huérfanas Cromo, ingresos sin match

- **Retirado**: `CamaraEstado.DETECTADA` y el pseudo-estado "Tracking" del dashboard — estado
  operable reducido a LIBRE/OCUPADA/BANEADA/NO_OPERATIVA. `scripts/retirar_estado_detectada.py`
  migró 1.053 filas reales a `LIBRE` (0 incidentes/ingresos activos en el sistema); encontró y
  corrigió 6 filas en una cadena de más de 2 niveles (hallazgo de integridad de datos preexistente,
  no corregido en sí). Ver sección "Estados operables" más arriba.
- **Agregado**: unificación de Cámaras duplicadas (`POST /api/infra/camaras/merge`,
  `core/services/camara_merge_service.py`, `ModalUnificarCamara.vue`) — la secundaria pasa a ser
  Botella de la principal, conserva auditoría completa. 47 grupos de duplicados reales confirmados.
  **Diseño reemplazado el 2026-08-14** por hard delete real de la secundaria con reasignación
  explícita de 7 FKs — ver sección "Cámaras duplicadas — Unificación manual" más arriba.
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
