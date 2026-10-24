# Nombre de archivo: 2026-10-23-correccion-ingresos-portal.md
# Ubicación de archivo: docs/superpowers/plans/2026-10-23-correccion-ingresos-portal.md
# Descripción: Plan para mover y anular ingresos desde el portal (admin), con baja lógica y auditoría

# Corrección de ingresos desde el portal (admin)

## Context

Un ingreso puede quedar registrado en la Cámara equivocada: por un Fontaine ID mal tipeado, una reescritura en el hilo o un
"Forzar ingreso" con la cámara errónea. Hoy no hay forma de corregirlo (`listener.py:~749`). Decisiones del usuario
(2026-10-23):

- **Dos operaciones:** *mover* el ingreso a otra Cámara (el ingreso existió, pero quedó en la cámara equivocada) y *anular*
  (el ingreso nunca ocurrió).
- **Sólo desde el portal y sólo para admin.** Slack no cambia, y en los hilos el bot nunca deriva a terceros ("avisá a un
  administrador").

El relevamiento de lectores y escritores está en la conversación de la sesión 2026-10-23. Lo esencial:

- No hay SQL crudo sobre `app.ingresos` (todo pasa por el ORM) y la API v1 no lee ingresos.
- "Ingreso activo" = `tipo == INGRESO AND fecha_fin IS NULL`. `docs/db.md:416` exige filtrar por `tipo`, y la anulación agrega
  una condición más.
- Registrar o cerrar un ingreso nunca escribe `Camara.estado`: OCUPADA es un valor *sugerido* que se calcula en vivo.
- La auditoría existente, `app.ingresos_correcciones`, es append-only (trigger `BEFORE UPDATE OR DELETE`). `comando` es
  String(32) y `origen` admite `web` con `actor_web_usuario`.

## Decisiones de diseño (tomadas por el controlador; las confirman las revisiones)

1. **Baja lógica** con columnas nullable en `app.ingresos`: `anulado_at` (timestamptz), `anulado_por` (String(128)) y
   `anulado_motivo` (Text). La condición única vive en un helper del modelo, por ejemplo `Ingreso.vigente()` →
   `Ingreso.anulado_at.is_(None)`, para no repetirla a mano.
2. **Auditoría de mover:** agregar a `app.ingresos_correcciones` las columnas nullable `camara_id_anterior` (FK a camaras, SET
   NULL) y `cromo_botella_id_anterior` (BigInteger, sin FK; es histórico). Usar `ADD COLUMN`, que no dispara el trigger.
   `comando` toma los valores nuevos `MOVER_INGRESO` y `ANULAR_INGRESO`; `origen='web'`.
3. **Mover:**
   - Cambia `camara_id`.
   - `cromo_botella_id` pasa a `NULL` salvo que el admin elija una `CromoBotella` vigente del destino; el backend valida
     `CromoBotella.camara_id == destino.id`.
   - No se puede mover un ingreso anulado ni a la misma cámara con la misma botella.
   - Un ingreso abierto se mueve abierto.
   - Las intervenciones de FO Monitor vinculadas que sigan abiertas actualizan `camara_id` y `botella_objetivo_n_id`; las
     cerradas no se tocan.
4. **Anular:**
   - Motivo obligatorio (3 a 500 caracteres); un ingreso ya anulado no se vuelve a anular.
   - El `IngresoSinMatch` que lo había resuelto **no** se reabre: si fue un error total, no hay nada que reabrir. Se documenta.
   - Las intervenciones de FO Monitor vinculadas y todavía abiertas pasan a `CANCELADA`, un estado que ya existe en
     `db/models/fo_monitor.py:44`.
5. **`Camara.estado` persistido no se toca**, igual que al registrar. El estado derivado (`tiene_ingreso_activo`,
   `estado_sugerido`, `inconsistente`) se corrige solo gracias al filtro.
6. **Listados:** excluyen los anulados para todos. Un admin puede pedirlos con `?incluir_anulados=1` y la UI los muestra
   atenuados, con "Anulado por X: motivo".
7. **Hueco preexistente que se cierra:** `DELETE /api/admin/infra/camaras/pendientes/{id}` (`camaras.py:~2074`) borraba
   físicamente los ingresos por la cascada del ORM. Ahora debe bloquear si la cámara tiene ingresos, con el mismo criterio que
   `camara_botella_delete_service._bloqueo_camara`.

## Restricciones

- Worktree propio, `ready` y luego `integrate`. Base de dev en 127.0.0.1:5433; **la 5432 nunca**.
- La migración es aditiva (columnas nullable), así que aplicarla en la base de dev compartida antes de integrar no rompe el
  código que corre en los contenedores. Se aplica con el lease `db:migrations`.
- Errores: `web/app/errores.py` (`NoEncontrado`, `DatoInvalido`, `Conflicto`, `error_interno`) y sesión vía `Depends(usuario_admin)`.
- Ninguna ruta existente cambia. Las rutas nuevas sí regeneran el contrato (`REGENERAR_CONTRATO_RUTAS=1`), y el diff del JSON
  debe ser sólo las rutas nuevas.
- SPA: skills `frontend-spa-architecture` y `nocturne-token-compliance`; `npm run type-check` en verde.

### Task 1: migración, modelo y filtro de anulados en todos los lectores

- Migración `db/alembic/versions/20261023_01_ingresos_anulacion_y_mover.py` (`down_revision = "20261021_01"`), con las columnas
  de las decisiones 1 y 2, `downgrade()` completo y la convención del repo (encabezado de 3 líneas, docstring con Revision ID).
  - Verificar que `ADD COLUMN` sobre `ingresos_correcciones` no choque con su trigger.
  - Aplicarla en dev (5433) con el lease `db:migrations`, y comprobar `upgrade`, `downgrade` y `upgrade` otra vez.
- Modelo: columnas en `Ingreso` y en `IngresoCorreccion`, más el helper `Ingreso.vigente()`.
- Aplicar el filtro de vigentes en todos los lectores marcados "Sí":
  - `camara_estado_service.get_camara_estado_contexto` (~188-199);
  - `protection_service._determinar_estado_restauracion` (~733-740);
  - `ingreso_service.registrar_movimiento_ingreso`, camino egreso (~118-129);
  - `ingreso_service.registrar_egreso_historico` (~209-221);
  - `ingreso_correccion_service.resolver_contexto_hilo`, nivel 1 (~327-357);
  - `ingreso_correccion_service._ingresos_abiertos` (~690-709);
  - `ingreso_correccion_service._procesar_forzar_egreso`, forma `#id` (~942-984): rechazar con un resultado nuevo
    `INGRESO_ANULADO` y un texto propio, sin derivar a terceros;
  - `ingreso_correccion_service.registrar_egreso_web` (~1192-1258): rechazar;
  - `ingreso_reproceso_service._ya_registrado` (~119-128): un anulado no cuenta como "ya registrado";
  - `fo_monitor/motor.py`: `detectar_ingresos` (~309-311), y `detectar_egresos` (a) y (b) (~387-407). Un vinculado anulado
    cuenta como no bloqueante para pasar a POST.
- NO filtrar en: los merges (`camara_merge_service`, `botella_merge_service`), `_bloqueo_camara` ni la marca de agua de
  `fo_monitor/motor.cargar_config`.
- Tests: por cada lector, un caso con un ingreso anulado que hoy cambiaría el resultado y con el filtro no lo cambia. Usar
  datos reales de dev con rollback donde ya haya tests `requiere_postgres_real`.
- Hueco de la decisión 7 (`camaras.py:~2074`), con su test.

### Task 2: servicio de mover y anular con auditoría

- En `core/services/ingreso_correccion_service.py` (donde ya vive `registrar_egreso_web` y la auditoría `_finalizar`), funciones
  `mover_ingreso_web(session, *, ingreso_id, camara_destino_id, cromo_botella_destino_n_id | None, motivo, usuario)` y
  `anular_ingreso_web(session, *, ingreso_id, motivo, usuario)`. Devuelven un resultado tipado con el estado del ingreso y
  escriben **una** fila en `ingresos_correcciones` por invocación, incluidos los rechazos, como el resto del módulo.
- Validaciones de la decisión 3/4: ingreso inexistente, anulado, destino inexistente, botella que no es del destino, mismo
  destino y botella, motivo corto.
- FO Monitor:
  - mover: las intervenciones abiertas vinculadas actualizan la cámara y la botella;
  - anular: las abiertas vinculadas pasan a `CANCELADA` (ver `db/models/fo_monitor.py` y las transiciones de estado en `motor.py`).
- Tests unitarios y uno real contra dev 5433 con rollback.

### Task 3: endpoints admin y listados

- `POST /api/admin/infra/ingresos/{ingreso_id}/mover` y `POST /api/admin/infra/ingresos/{ingreso_id}/anular`, en
  `web/app/routers/camaras.py` junto al egreso web. Llevan `Depends(usuario_admin)`, CSRF como el egreso web (~1690) y errores
  tipados (404/409/422). La respuesta es el ingreso serializado.
- `_serialize_camara_ingreso` (`web/app/comun.py:~160`) agrega `anulado`, `anulado_at`, `anulado_por` y `anulado_motivo`.
- `GET /api/infra/camaras/{id}/registros` y `GET /api/infra/servicios/{id}/ingresos` excluyen los anulados. Con
  `?incluir_anulados=1` y rol admin los incluyen; para un usuario común el parámetro se ignora. El `total` de servicios cuenta
  sólo los vigentes.
- Tests: 403 a usuario común (se suma solo a la introspección), CSRF, cada error, listados con y sin anulados, y el contrato
  regenerado sólo con las 2 rutas nuevas. El test de exposición sigue en verde.

### Task 4: UI de admin

- `ModalRegistros.vue`, que monta `CamaraDetailView.vue`:
  - prop `esAdmin`;
  - en cada ingreso vigente, botones "Mover" y "Anular";
  - toggle "Mostrar anulados", que recarga con `incluir_anulados=1`;
  - los anulados se ven atenuados, con "Anulado por X el <fecha>: motivo".
- `ServicioIngresosView.vue`: lo mismo en la columna de acciones, con el patrón `useSession`/`esAdmin` de `ServicioCaminoView.vue`.
- Modales nuevos, `ModalMoverIngreso.vue` y `ModalAnularIngreso.vue`, sobre la base de `ModalRegistrarEgreso.vue`.
  - Mover: buscador de cámara con `GET /api/infra/camaras/buscar` (como `ModalUnificarCamara.vue`) y un selector opcional de
    botella con `GET /api/infra/camaras/{id}/botellas` (sólo las de origen Cromo).
  - Los dos piden un motivo y se cierran con Escape y con clic en el fondo, salvo mientras se envía.
- API client: `moverIngreso` y `anularIngreso` en `web/frontend/src/api/servicioSecciones.ts`, con `requestJson`, `csrf: true`.
- Tokens Nocturne y nada de colores literales. `npm run type-check` en verde y build OK.

### Task 5: cierre

- Suite focal, ruff, type-check y build.
- Rebuild de `web` en dev (el frontend se buildea en la imagen) y curl: rutas nuevas 401 sin sesión; un usuario común recibe 403.
- `docs/db.md` (columnas y regla "toda consulta de ingreso activo filtra vigentes"), `docs/PR/2026-10-23.md` y `AGENTS.md` si
  corresponde.
