# Plan — Módulo Admin "Clientes por categoría" (fuente de verdad C0–C6)

## Contexto

Un relevamiento encontró inconsistencias en la categoría de los servicios. Hoy la categoría vive sólo en `app.servicios.categoria` y la escriben varias fuentes sin precedencia:

- **Excel de Servicios SLA** (columna "Nivel Cliente"). Pisa cualquier valor manual.
- **Placeholders de Cromo/PROV** (`categoria=0`).
- **Cambios manuales por servicio.**

No existe tabla de clientes. El nombre es texto libre (`nombre_cliente`), con variantes del mismo cliente: Galicia "SA" / "S A U", ARSAT x2, Credicoop. Además, `categoria=6` mezcla el C6 real con "sin categorizar", porque desde la migración `20260814_01` es el default.

**Objetivo:** un módulo sólo Admin con los clientes agrupados por categoría. Cada grupo es desplegable, está ordenado alfabéticamente y admite edición individual, masiva y por lista adjunta. Ese listado pasa a ser la fuente de verdad principal; las ingestas existentes se conservan como fuentes secundarias.

**Decisiones del usuario (2026-10-14)**

1. `6` = sólo C6 real. "Sin categorizar" pasa a `NULL`.
2. C6: la **Lista** es la fuente principal y la **ingesta SLA** la secundaria. Si la SLA marca C6 a un cliente que no está en la Lista, entra como "C6 · SLA". Lo que defina un admin siempre gana.
3. C5…C0 se autocompletan: gana la categoría con más servicios. C0 se ignora si hay alguna categoría real; si hay empate, gana la más alta.
4. El servicio hereda la categoría del cliente, salvo **excepción por servicio** marcada por un admin. La herencia no pisa las excepciones.
5. Enfoque 1: tabla de clientes + alias, con la categoría materializada en `servicios.categoria` para que los lectores actuales no cambien.
6. Regularización retroactiva: los servicios de clientes C6 pasan a `6`, incluidos sus placeholders C0.
7. Lista C6 inicial: las 50 que pegó el usuario + `BANCO DE LA CIUDAD DE BUENOS AIRES` + `BANCO MACRO SA` = **52**.
8. **Despliegue: todo `dev` junto a PROD**, incluido el informe "SLA consumido" pendiente (38 commits). Antes se corrige su migración.

## Global Constraints

- Idioma: código, docstrings, comentarios, mensajes y docs en español (convención del repo). Encabezado de 3 líneas `# Nombre de archivo / # Ubicación de archivo / # Descripción` en cada archivo nuevo (ver AGENTS.md).
- Semántica de categoría: `servicios.categoria` NULL = sin categorizar; 0..6 válidos; 6 = sólo C6 real. Nunca volver a usar 6 como default.
- Precedencia de categoría de un cliente: `LISTA`/`MANUAL` (definido por admin) > `SLA` (moda de `categoria_sla` 1..6, empate → más alta) > `AUTO` (0 si sólo hay placeholders C0) > NULL.
- Un servicio con `categoria_excepcion = true` nunca es pisado por la propagación.
- Toda la lógica de sync es set-based (SQL), no fila por fila (prod: ~30k servicios, ~5k clientes).
- Tests: pytest con `LLM_PROVIDER=heuristic`, venv `.venv` (enlazado en el worktree). Tests real-db usan `tests/soporte_postgres_real.py::requiere_postgres_real` contra dev (puerto 5433, `POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5433 POSTGRES_DB=focas_dev POSTGRES_USER=FOCALBOT POSTGRES_PASSWORD="$(cat .secrets/Dev_db_password_v1.txt)"`), con datos sintéticos que se borran al final.
- Prohibido tocar la DB de prod, hacer push, o correr `alembic upgrade` contra prod. Contra dev sólo lo indicado en la tarea.
- Frontend: sólo tokens de `web/frontend/src/assets/styles/tokens.css` (skill nocturne-token-compliance); nada de hex/rgba literales.
- Commits en la rama del worktree, mensajes estilo `feat(clientes): ...` en español, terminados con `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Flujo de trabajo

- Worktree propio: `python scripts/agent_worktree.py start --agent claude-api --type feat --task clientes-categoria`. Todo se edita, testea y commitea ahí.
- Lease `db:migrations` durante la migración.
- Ejecución por SDD (`superpowers:subagent-driven-development`), con TDD en el backend.
- Cierre con `/cierre-sesion`, que integra a `dev`.

## Task 1: Fix previo de la migración SLA consumido

`db/alembic/versions/20261005_02_sla_consumo_historico.py:54`: el `UPDATE app.reclamos SET horas_netas = horas_netas / 60.0` corre antes del `alter_column` a `Numeric(12,4)` (`:104`) y redondea a 2 decimales.

- **Fix:** mover el `UPDATE` después del `alter_column`, conservando el guard de "tabla no vacía".
- **Por qué no rompe dev:** dev ya está en esa revisión y el cambio no lo afecta. Prod (`20260930_01`) la va a correr por primera vez.
- **Test:** el existente de la migración, o uno nuevo que verifique el orden.

## Task 2: Migración 20261014_01_clientes_categoria y modelos

Se encadena sobre `20261005_02`. Sigue el patrón de enums de `20260814_02_servicios_origen_datos.py`.

**Enum nuevo** `app.cliente_origen_categoria`: `LISTA | MANUAL | SLA | AUTO`. Un `NULL` en `categoria` con `AUTO` equivale a "sin datos".

**Tabla `app.clientes`**

| Columna | Tipo / detalle |
|---|---|
| `id` | serial PK |
| `nombre` | varchar(255) |
| `clave` | varchar(255) UNIQUE |
| `categoria` | smallint NULL, CHECK 0–6 |
| `origen_categoria` | enum NOT NULL default `AUTO` |
| `a_revisar` | bool default false |
| `creado_en`, `actualizado_en` | timestamptz |
| `actualizado_por` | varchar(120) NULL |

**Tabla `app.clientes_alias`**

| Columna | Tipo / detalle |
|---|---|
| `id` | serial PK |
| `clave` | varchar(255) UNIQUE |
| `nombre_original` | varchar(255) |
| `cliente_id` | FK `ON DELETE CASCADE`, con índice |
| `origen` | varchar(10): `AUTO` / `MANUAL` |

**Cambios en `app.servicios`**
- `categoria_sla smallint NULL` (CHECK 0–6).
- `categoria_excepcion bool NOT NULL DEFAULT false`.
- `categoria`: se quitan `NOT NULL` y `DEFAULT 6`. El CHECK `ck_servicios_categoria_valida` sigue valiendo, porque Postgres deja pasar NULL.

**Backfill estructural**
- `categoria_sla = categoria` donde `nombre_cliente IS NOT NULL AND categoria BETWEEN 1 AND 6`. Hoy ese valor sólo puede venir de la planilla, porque PROV no escribe categoría.
- `categoria = NULL` donde `categoria = 6 AND nombre_cliente IS NULL`: era el default.

**`downgrade()`:** NULL→6, restaura `NOT NULL`/`DEFAULT 6`, borra columnas, tablas y enum. **No va carga de clientes en la migración**; esa la hace el script de la Tarea 3.

**Modelos** en `db/models/infra.py`:
- `Cliente`, `ClienteAlias`, `ClienteOrigenCategoria` (junto a `ServicioOrigenDatos`, `:58`).
- Columnas nuevas en `Servicio` (`:381`); `categoria` pasa a `nullable=True` sin `server_default`.

## Task 3: Servicio de dominio core/services/clientes_categoria_service.py

Lógica sync, con `Session`, llamable desde rutas vía `asyncio.to_thread` + `SessionLocal`. Mismo patrón que `api/app/routes/servicios.py:877-888`.

**`normalizar_clave_cliente(nombre) -> str | None`**
- Reutiliza `_clean_key` de `core/parsers/servicios_excel.py:102`, promovida a pública como `limpiar_clave`. Hace unidecode, minúsculas y no-alfanumérico→espacio.
- Después pasa a mayúsculas y quita sufijos societarios al final: `S A U`, `SAU`, `S A`, `SA`, `S R L`, `SRL`, `SAIC`, `INC`, `LTDO`/`LTDA`, `SOCIEDAD ANONIMA`, `COOPERATIVO LTDO`…
- Casos a testear con datos reales:
  - Galicia "SA" y "S A U" dan la misma clave.
  - ARSAT "(ARSAT)" vs "SOCIEDAD ANONIMA ARSAT" **no** colapsan solos → alias manual. Medir colisiones contra dev antes de cerrar la lista de sufijos.

**`sincronizar_categorias(session, claves: set[str] | None = None) -> ResumenSync`**

Set-based SQL, no fila por fila. Hay ~5k clientes y ~30k servicios en prod.

1. **Registrar clientes y alias.** Para cada `nombre_cliente` distinto de `servicios` (opcionalmente filtrado por `claves`): si la clave no existe como alias, se crea un `Cliente` (`AUTO`) más un alias `AUTO`.
2. **Recalcular la categoría automática** de los clientes con `origen_categoria IN ('SLA','AUTO')`:
   - Moda de `categoria_sla` en 1–6 entre sus servicios; si hay empate, la más alta. `origen = SLA` si la moda vino de datos SLA.
   - Si no hay `categoria_sla` pero hay servicios con `categoria=0`, queda `0` (`AUTO`).
   - Si no, `NULL`.
   - `a_revisar = true` si hay más de una categoría SLA distinta en 1–6.
   - Los clientes `LISTA`/`MANUAL` no se recalculan.
3. **Propagar:** `UPDATE servicios s SET categoria = c.categoria FROM clientes_alias a JOIN clientes c … WHERE a.clave = clave(s.nombre_cliente) AND NOT s.categoria_excepcion AND s.categoria IS DISTINCT FROM c.categoria`.
   - La clave se calcula en Python por nombre distinto: se arma una tabla temporal `(nombre_cliente, clave)` y se hace el `UPDATE … FROM` con ella. Así se evita duplicar la normalización en SQL.

Devuelve conteos: clientes creados, recalculados, servicios actualizados.

**Operaciones del módulo** (cada una termina en `sincronizar_categorias(claves afectadas)`):
- `listar_clientes_por_categoria()`: los grupos C6…C0 + Sin categorizar, con nombre, origen, `a_revisar`, cantidad de servicios, cantidad de excepciones y alias.
- `cambiar_categoria(ids, categoria | None, usuario)`: `origen = MANUAL`. "Volver a automático" pasa `origen = AUTO` y se recalcula.
- `previsualizar_lista(nombres, categoria, modo)` y `aplicar_lista(...)`:
  - Para cada nombre, resuelve la clave: alias existente → cliente; si no, "nuevo cliente".
  - Si no hay match exacto, agrega sugerencias por similitud (`difflib.get_close_matches` sobre las claves) para que el admin vincule el nombre como alias.
  - `modo="agregar"` sólo asigna `categoria` + `origen=LISTA`.
  - `modo="reemplazar"` además devuelve a `AUTO` a los clientes `LISTA` de esa categoría que no vengan en la lista.
  - La previsualización devuelve el diff (sube / baja / sin cambio / nuevo / sugerencias) y **no escribe**.
- `fusionar_clientes(destino_id, origen_ids)`: mueve los alias al destino y borra los clientes origen. Si el destino no es `LISTA`/`MANUAL`, recalcula.
- `agregar_alias(cliente_id, nombre)` / `quitar_alias(alias_id)`: no se puede quitar el último alias que coincide con su nombre canónico.

**Excepción por servicio** (`core/services/servicios_categoria_service.py`):
- `actualizar_categoria_masiva` (`:72`) y el `PATCH` individual (`api/app/routes/servicios.py:910`) ponen `categoria_excepcion = True`.
- Endpoint nuevo `PATCH /servicios/{id}/categoria/heredar`: quita la excepción y re-sincroniza ese cliente.
- `validar_categoria` acepta `None` sólo donde corresponde ("sin categorizar").

## Task 4: Script de regularización scripts/clientes_categoria_regularizar.py

Se corre una vez por entorno, primero con `--dry-run`. El dry-run usa una transacción externa con rollback, mismo patrón que `scripts/ingresos_reprocesar_sin_match.py::ejecutar`.

1. `sincronizar_categorias()` global: crea los clientes, la categoría automática y `a_revisar`.
2. Carga la **Lista C6 (52)** desde `scripts/data/clientes_c6_inicial.txt` con `aplicar_lista(..., categoria=6, modo="agregar")`.
   - Reporta los nombres sin match exacto: MEPADIP no está en la planilla SLA, y hay que confirmar si está en `servicios`.
   - Los alias conocidos se cargan en el mismo archivo con la forma `canónico | variante`: ARSAT, Credicoop, Galicia.
3. Propagación final, que es la regularización retroactiva. Los placeholders C0 de clientes C6 (Telecom, Galicia, Alterplan…) pasan a 6.
4. Imprime un JSON de resumen: antes/después por categoría, clientes `a_revisar` y nombres sin match.

**Contenido exacto de `scripts/data/clientes_c6_inicial.txt` (52 nombres, uno por línea; además agregar en líneas `canónico | variante` los alias conocidos: `BANCO DE GALICIA Y BUENOS AIRES S A U | BANCO DE GALICIA Y BUENOS AIRES SA`, `EMPRESA ARGENTINA DE SOLUCIONES SATELITALES SOCIEDAD ANONIMA ARSAT | EMPRESA ARGENTINA DE SOLUCIONES SATELITALES (ARSAT)`, `BANCO CREDICOOP COOPERATIVO LTDO | BANCO CREDICOOP`):**

```text
Alterplan Solutions SRL
ORANGE BUSINESS SERVICES ARGENTINA SA (EX EQUANT ARGENTINA SA)
INDUSTRIAL AND COMMERCIAL BANK OF CHINA (ARGENTINA) SA
Telecom Argentina SA
CIRION TECHNOLOGIES ARGENTINA SA
BANCO DE GALICIA Y BUENOS AIRES S A U
SERVICIO ELECTRONICO DE PAGO S.A. (PAGO FACIL)
DIRECTV ARGENTINA SRL
EMPRESA ARGENTINA DE SOLUCIONES SATELITALES SOCIEDAD ANONIMA ARSAT
DEFENSORIA GENERAL DE LA NACION
COPPEL SA
TEXPERT SA
Verizon Argentina SRL
Banco Supervielle SA
BANCO DE LA PROVINCIA DE BUENOS AIRES
BANCO SANTANDER ARGENTINA SOCIEDAD ANONIMA
SILICA NETWORKS ARGENTINA SA
Edge Argentina SRL
CAJA DE SEGUROS SA
BANCO CREDICOOP COOPERATIVO LTDO
Banco de la Nacion Argentina
BANCO HIPOTECARIO SA
GIGARED SA
SIDERCA SAIC
Banco Comafi SA
CORREO OFICIAL DE LA REPUBLICA ARGENTINA SA
GLOBENET CABOS SUBMARINOS ARGENTINA SRL
ESPN SUR SRL
Cepas Argentinas SA
MOLINOS RIO DE LA PLATA SA
IMAGEN SATELITAL SA
La Iglesia Universal del Reino de Dios
TELEVISION FEDERAL S A
TELEPIU SA
ANTEL TELECOMUNICACIONES ARGENTINA SA
The Walt Disney Company Argentina SA
GRUPO PROVINCIA SA
RED LINK SA
Aldea Solutions INC
Grupo Solunet SRL
TELEARTE SA - RADIO Y TV
BANCO DE SAN JUAN SA
QUALIA COMPAÑIA DE SEGUROS SA
IFX NETWORKS ARGENTINA SRL
TELCOM VENTURES DE ARGENTINA SA
ADMINISTRADORA SAN JUAN S.A,
BANCO DE SANTA CRUZ S.A.
NETLATIN S.R.L.
MEPADIP S.A.
NUEVO BANCO DE SANTA FE S.A.
BANCO DE LA CIUDAD DE BUENOS AIRES
BANCO MACRO SA
```

## Task 5: Integración con ingestas (fuentes secundarias)

**Excel SLA** (`api/app/routes/servicios.py`)
- `:347-361`: escribe `row["categoria_sla"]` con el "Nivel Cliente" válido. El fallback `else 6` (`:348`) pasa a `None`.
- `row["categoria"]`: si el servicio existe y tiene excepción, conserva la actual; si no, queda provisional, porque la sync la reescribe según el cliente.
- Agregar `categoria_sla` a `set_map` (`:493-508`) y a `changed_where` (`:510-523`).
- Después del `commit` (`:603`): `await asyncio.to_thread(sync)` restringido a las claves del archivo.

**PROV**
- `/prov/refrescar` (`servicios.py:835`): sync de la clave del servicio después del commit.
- `modules/slack_baneo_notifier/refresco_prov.py:247`: lo mismo.
- `scripts/servicios_backfill_prov.py` y `scripts/servicios_alta_prov_desde_cromo.py`: una sync global al final.

**Cromo placeholders** (`core/services/cromo/ingesta.py:1655`, `scripts/cromo_backfill_placeholders_servicios.py`): siguen insertando `0` sin nombre. Sin cambio: heredan cuando PROV completa el nombre.

**Resiliencia:** si la sync falla, la ingesta no se cae. Se loguea `action=clientes_sync_error`, el admin tiene un botón "Re-sincronizar" en el módulo y la sync idempotente lo corrige.

## Task 6: API interna + proxy web + nullabilidad backend

**API interna:** `api/app/routes/clientes.py`, nuevo `APIRouter(prefix="/clientes")` registrado como `servicios`. Endpoints:
- `GET /clientes/por-categoria`
- `PATCH /clientes/categoria` (ids + categoria | null | "auto")
- `POST /clientes/lista/previsualizar` (multipart xlsx/csv/txt **o** JSON `{nombres[]}`)
- `POST /clientes/lista/aplicar`
- `POST /clientes/fusionar`
- `POST /clientes/{id}/alias`
- `DELETE /clientes/alias/{id}`
- `POST /clientes/sincronizar`

**Proxy web** (`web/app/main.py`): `/api/admin/clientes/*` con `_require_admin(request)` (`:731`) + CSRF (patrón `:9671-9676`). Para el upload se usa el patrón `UploadFile` + `csrf_token: Form` (`:5128`). Límite de 5 MB y extensiones `.xlsx/.csv/.txt`.

**Lectura de archivos de lista:** se reusa la lectura de `ingest_servicios` (`servicios.py:247-258`). La columna de nombre se detecta por encabezado: "Cliente", "Nombre Cliente" o la primera columna. En `.txt`, un nombre por línea.

**Nullabilidad**
- `ServicioItemResponse.categoria: int | None` (`servicios.py:86`).
- Filtro `/servicios/search` (`:660-666`): acepta el token `sin` → `IS NULL`.
- Slack `cable_info.py:258` no cambia: `C6` ahora significa C6 real, que es lo buscado.

## Task 7: Frontend Admin Clientes por categoría + Sin categorizar en Servicios

**Rutas y navegación**
- Ruta `servicios/clientes-categoria` (`admin-clientes-categoria`, `meta.requiresAdmin`) en `web/frontend/src/router/index.ts`, con lazy import arriba (`:37-48`) y antes del catch-all (`:348`).
- Tarjeta nueva en `admin/views/AdminServicios.vue:28` (`ServiceCard`).

**Cliente API:** `admin/api/clientesCategoria.ts` con `requestJson` / `getCsrfToken` / XHR upload (patrón `api/servicios.ts:180-225`).

**Vista `admin/views/AdminClientesCategoria.vue`**
- `AdminPageHeader`.
- Buscador por nombre o alias.
- Resumen con el conteo por grupo.
- Un `AccordionItem` (`components/infra/AccordionItem.vue`) por grupo, C6→C0 y después "Sin categorizar". Slot `#meta` con la cantidad. C6 abierto por defecto.
- Filas ordenadas alfabéticamente (`localeCompare('es')`) con:
  - checkbox (patrón `Set` de `BaneosActivosPanel.vue:153,222-239`)
  - nombre
  - badge de origen (Lista/Manual/SLA/Auto)
  - badge "A revisar"
  - cantidad de servicios / excepciones
  - alias, desplegables con `<details>`
  - `<select>` de categoría con opción "Automático"
- Barra masiva (`role="toolbar"`, patrón `:105-123`): cambiar categoría, volver a automático, fusionar.

**Componentes nuevos** en `admin/components/clientes/`:
- `ClientesListaModal.vue`: adjuntar archivo o pegar texto, elegir categoría y modo (agregar/reemplazar), **previsualizar el diff** y confirmar sobre `ModalConfirmarAccionMasiva.vue`. Las sugerencias por similitud se vinculan como alias con un clic.
- `ClienteAliasModal.vue`
- `ClientesFusionarModal.vue`

**"Sin categorizar"** en Servicios
- `api/servicios.ts`: `categoria: number | null` (`:55`); `categoriaLabel(null)` devuelve "Sin categorizar".
- Chip "Sin cat." en `ServiciosView.vue:297`.
- Opción null en `ServicioDetalleView.vue:31-38`.
- Badge "Excepción" con acción "Heredar del cliente" en el detalle.
- `ServiciosCambioCategoriaModal.vue` avisa que el cambio crea una excepción.

**Estilo:** sólo tokens de `assets/styles/tokens.css`; verificar con la skill `nocturne-token-compliance` (grep de hex y rgba en la vista y sus imports).

## Task 8: Documentación

- `docs/db.md`: tablas y migración.
- `docs/decisiones.md`: entrada 2026-10-14 con las 8 decisiones.
- `docs/clientes_categoria.md`: reglas de precedencia, normalización y regularización.
- `docs/PR/2026-10-14.md`.
- Memoria del proyecto.

## Despliegue (lo ejecuta el controlador, no es Task)

**DEV** (`lasfocasdev-*`, puerto DB 5433)
1. `alembic upgrade head` contra dev (guardrail host/dev de `docs/cierres/2026-10-05.md`).
2. Rebuild + recreate de `api`, `web` y el worker Slack, con `--env-file` (ver la skill `docker-rebuild`).
3. `docker exec lasfocasdev-api python scripts/clientes_categoria_regularizar.py --dry-run`, revisar el JSON, y después correrlo sin `--dry-run`.
4. Verificación E2E (ver abajo).
5. `/cierre-sesion` integra a `dev`.

**PROD** según `docs/despliegue_produccion.md`. Lleva **todo dev** (SLA consumido + Clientes). **Requiere salir de Auto Mode**: el clasificador bloquea escrituras en la DB de prod y el push a `main`.
1. Relevamiento: `select * from alembic_version`. Se espera `20260930_01`.
2. Build de imágenes (`deploy/compose.yml --env-file .env`).
3. Backup: `pg_dump -F c` de `lasfocas-postgres`.
4. Merge `dev`→`main` (commit-tree, `:62-67`).
5. Ventana: stop de los servicios de la app → `alembic upgrade head`. Aplica `20261005_01/02` (ya con el fix /60) y `20261014_01` → `up -d --force-recreate`.
6. `docker exec -it lasfocas-api python scripts/clientes_categoria_regularizar.py --dry-run`; revisar con el usuario los sin match y los `a_revisar` contra los datos de prod (~29.5k servicios); después correrlo real.
7. Smoke: módulo cargado, conteo C6 coherente, una ingesta SLA de prueba no pisa la Lista.
8. **Rollback:** `alembic downgrade 20260930_01` + restore del backup.

## Verificación

**Tests unitarios** (`pytest`, `LLM_PROVIDER=heuristic`)
- `normalizar_clave_cliente` con las variantes reales.
- Regla de moda: empate → la más alta, C0 ignorado, `a_revisar`.
- Precedencia LISTA/MANUAL > SLA > AUTO.
- Excepción no pisada.
- `previsualizar_lista` no escribe; modo `reemplazar`.
- Fusión de clientes.
- Rutas con `_FakeAsyncSession` / `@patch(SessionLocal)` (patrón `tests/test_servicios_categoria_routes.py`).
- Ingesta Excel: escribe `categoria_sla`, no pisa la Lista y no usa el fallback 6.

**Test real-db** (`tests/test_clientes_categoria_real_db.py`, `requiere_postgres_real`)
- Servicios sintéticos `99996xx`.
- Sync completa, propagación y downgrade/upgrade de la migración en dev.

**Suite completa** sin regresiones, sobre todo `test_servicios_*`, `test_cromo_verificador`, `test_slack_cable_info` y `test_servicios_excel_parser`.

**Frontend:** `npx vue-tsc --noEmit` + `vite build` + grep de tokens.

**E2E dev**
- Contra los contenedores **recreados**: verificar la imagen antes, ver [[feedback_sdd_verificar_imagen_contenedor_antes_de_e2e]].
- Por la API interna (`curl localhost:8011`) y por el proxy (`localhost:8090`) con un usuario admin temporal, borrado al final.
- Flujo: listar → subir la lista C6 (preview + aplicar) → cambiar un cliente → excepción en un servicio → reingestar `docs/Doc Privada/Servicios_ Nuevo SLA.xlsx` y comprobar que la Lista y la excepción se conservan.
- SQL de control: ningún servicio de un cliente C6 queda ≠6 salvo excepciones, y no hay `categoria=6` sin cliente C6.
