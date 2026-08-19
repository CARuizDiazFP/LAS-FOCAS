# Nombre de archivo: slack_app_cables.md
# Ubicación de archivo: docs/slack_app_cables.md
# Descripción: Bot de Slack de verificación de Cables/Servicios de Cromo — los 3 comandos especificados, implementados y desplegados en dev

# Bot de Slack — Verificación de Cables y Servicios

> **Estado (2026-08-13): los 3 comandos IMPLEMENTADOS y desplegados en dev.** `@Registrador de
> Ingresos a Camara` **es** `modules/slack_baneo_notifier/` — hay dos instancias de esta misma app
> (prod: contenedor `lasfocas-slack-baneo-worker`; dev: `lasfocasdev-slack-baneo-worker`, credenciales
> propias en `.secrets/Dev_slack_bot_token_v1.txt`/`Dev_slack_app_token_v1.txt`), no dos Slack Apps
> de dominios distintos. No hay ni hubo una app separada `@sandy02` en este repositorio con handler
> propio — esa referencia de una versión anterior de este documento era una hipótesis incorrecta.

## Dónde vive

`modules/slack_baneo_notifier/cable_info.py` (parsers + lookups + formato de respuesta) +
`IngresoListener._handle_app_mention`/`_handle_cable_buffer` en
`modules/slack_baneo_notifier/listener.py` — handler `@app.event("app_mention")` agregado a la MISMA
`App` de Slack Bolt que ya escucha `message` para los ingresos técnicos (mismo
`SLACK_BOT_TOKEN`/`SLACK_APP_TOKEN`, mismo daemon thread arrancado en `worker.py`). Dominio de datos
distinto del resto del módulo (`app.cromo_cables`/`app.cromo_tubos`/`app.cromo_pelos`/
`app.cromo_botellas` en vez de `app.camaras`/`IncidenteBaneo`), pero mismo proceso.

Reusa (en versión síncrona) los servicios de sólo lectura ya existentes de Cromo en vez de duplicar
lógica de negocio: `core/services/cromo/verificador.py::servicios_por_tubo_sync` (gemela síncrona de
`servicios_por_tubo`, misma SQL) y `core/services/cromo/detalle.py::pelos_de_tubo_sync` (mismo
patrón que `obtener_detalle_cable`, acotado a un tubo). Ambas reusan las mismas consultas `text()` que
ya corren sus gemelas async — `session.execute(text(...))` funciona igual en `Session` que en
`AsyncSession`, sólo cambia el `await`.

Tests: `tests/test_slack_cable_info.py` (35 casos: parsers, lookups, resolución de extremos y de
buffer, formateo de respuestas, handlers completos con mocks). Verificado además contra
`lasfocasdev-postgres` real (no sólo mocks) con cables y buffers reales conocidos. Desplegado: rebuild
+ `up -d --force-recreate` de `lasfocasdev-slack-baneo-worker` (nunca el de prod) tras cada cambio,
log confirma conexión Socket Mode real sin errores.

## `@bot Info cable <nombre>` — implementado

Responde con la información básica de un Cable de Cromo: capacidad, propietario, jerarquía, y el
nombre real de la Botella en cada extremo.

**Hallazgo real que resolvió el mapeo de código** (2026-08-13, disparado por un mensaje real del
usuario: `Info cable F-VFL-IND`): el "código de cable" que el técnico escribe **es directamente
`cromo_cables.nombre`** — no un código externo en otro sistema, no `cromo_cables.id_legacy` (ese
campo es sólo un número interno de Cromo, sin relación con el formato `"F-XXX-YYY"`). Verificado
contra `lasfocasdev-postgres`: `nombre` es prácticamente único (1 solo par duplicado real en todo el
dataset, `"F-ALV-2335"`, sobre ~32.782 cables vigentes) — un match exacto case-insensitive resuelve
el `n_id` en la enorme mayoría de los casos.

`cromo_cables.extremo_a_nombre`/`extremo_b_nombre` (los campos crudos) no son confiables — confirmado
de nuevo con este ejemplo real: `extremo_b_nombre` venía **vacío** (`at.37` nunca llega desde Cromo,
mismo hallazgo que la Etapa 9c de `docs/modulo_ingesta_cromo.md`). El nombre real de la Botella en
cada extremo se resuelve por separado, vía `cromo_botellas.nombre` a partir de `extremo_a_n_id`/
`extremo_b_n_id` — `cable_info.py::_resolver_nombre_extremo`.

**Ejemplo real** (n_id 6613293):
```
📡 Cable *F-VFL-IND* (n_id 6613293)
• Capacidad: 72-BRUG
• Propietario: Metrotel
• Jerarquía: Troncal
• Extremo A: Cra M de Justo e Independencia CF Bot 2
• Extremo B: Cra Alicia Moreau de Justo 1210 CF
```

**Casos manejados**:
- 1 match → responde la info completa (arriba).
- 0 matches → `":warning: No encontré ningún cable vigente con el código *<nombre>*."`
- 2+ matches (el único caso real conocido, `"F-ALV-2335"`) → pide precisar por `n_id`, no adivina.

## `@bot Verificar cable <nombre> B<N>` — implementado

Servicios matcheados dentro de un Cable y un Buffer específico.

**Hallazgo real que resolvió "BN"** (2026-08-13, confirmado explícitamente por el usuario, no
inferido del dato): un técnico referencia el buffer por **número secuencial humano** ("B1", "B2",
"Buffer 3" — nunca por color, aunque Cromo también trackea color en `cromo_tubos.nombre_color`, ej.
"AZ"/"NR"/"VR"/"MR"/"GR"/"BL"). "B1" = primer buffer físico = `cromo_tubos.orden = 0` (la columna
arranca en 0 en los datos reales, confirmado contra 2 cables reales con 6 buffers cada uno) — mapeo
`orden = numero_humano - 1`.

**Ejemplo real** (F-VFL-IND, B1 = buffer color AZ):
```
🔍 Cable *F-VFL-IND* / Buffer *B1* (AZ)
3 servicio(s) encontrado(s):
• 61942 — Banco Comafi SA (Activo)
• 61942 — Banco Comafi SA (Activo)
• 106595 — BANCO MACRO SA (Activo)
```

**Reutiliza**: `core/services/cromo/verificador.py::servicios_por_tubo_sync` (mismos datos que
`GET /api/infra/cromo/tubos/{n_id}/servicios`/`VerificadorCromoView.vue`, sólo los pelos CON match).

**Casos manejados**: cable no encontrado/ambiguo (mismo criterio que "Info cable"); buffer sin
servicios matcheados (`"Sin servicios matcheados en este buffer."`); número de buffer fuera de rango
(responde cuántos buffers tiene realmente el cable, ej. `"tiene 6 buffer(es) registrados (B1 a B6)"`
— no un genérico "no encontrado").

## `@bot Info cable <nombre> B<N>` — implementado

Listado completo de los pelos de ese buffer (matcheados o no) — a diferencia de "Verificar cable",
muestra TODOS los pelos, y para los que no están libres pero tampoco se identificó cliente/cable,
detalla la descripción cruda (`servicio_raw`).

**Ejemplo real** (mismo cable/buffer, 12 pelos — nótese que la mayoría de los pelos con texto crudo
NO matchean contra un servicio real, hallazgo ya documentado en la Etapa 9 de
`docs/modulo_ingesta_cromo.md`):
```
📋 Cable *F-VFL-IND* / Buffer *B1* (AZ) — 12 pelo(s)
• Pelo 1: No se identifica cliente/cable — "TLS 23856 - Trunk Florida 470 - Chile 460"
• Pelo 2: 106595 — BANCO MACRO SA (Activo)
• Pelo 3: No se identifica cliente/cable — "PFLO1 S2 L4"
...
• Pelo 11: 61942 — Banco Comafi SA (Activo)
• Pelo 12: 61942 — Banco Comafi SA (Activo)
```

**Reutiliza**: `core/services/cromo/detalle.py::pelos_de_tubo_sync` (mismo patrón de
`obtener_detalle_cable`, acotado a un tubo — nunca N+1, una sola query con `LEFT JOIN` a
`cromo_servicio_match`/`servicios`). Distingue 3 casos por pelo (`_describir_pelo`):
1. Con servicio matcheado → nombre de servicio + cliente + estado.
2. Sin `servicio_raw` → genuinamente libre (`"Pelo N: Libre"`).
3. Con `servicio_raw` pero sin match → `"No se identifica cliente/cable — \"<crudo>\""` (pedido
   explícito de la spec original). Hereda el gap de clasificación ya documentado (Etapa 9): texto
   crudo tipo "libre"/"cortado" que debería ser estado `LIBRE` pero quedó `INDETERMINADO` en la
   ingesta — fuera de alcance de este comando, es un fix de `parser.py`/`ingesta.py`.

## Parser de comandos

`cable_info.py` tiene dos parsers, probados en ese orden por el listener (`_handle_app_mention`):
1. `extraer_comando_cable_buffer` — `"(Verificar|Info) cable <nombre> (B|Buffer)\s*<N>"`, case
   insensitive, tolera "B1"/"B 1"/"Buffer 1". Si matchea, dispara `_handle_cable_buffer`.
2. `extraer_comando_info_cable` — `"Info cable <nombre>"` sin sufijo. Deliberadamente "goloso"
   (toma todo el resto de la línea como nombre) — por eso se intenta **después** del parser de
   buffer, nunca antes, o se comería el "B<N>" como si fuera parte del nombre del cable.

Una mención que no matchea ninguno de los dos se ignora silenciosamente (no hay todavía un mensaje de
"comando no reconocido" — evita interferir con otras menciones al mismo bot que no sean estos
comandos).

## Identidad del bot y despliegue (hallazgo operativo, 2026-08-13)

Al probar "Info cable" por primera vez en el canal real, el bot no respondió — la causa real, en dos
capas:
1. El evento llegó a Slack como `message` (channel_type `group`, canal `C08UB8ML3LP`), **no** como
   `app_mention` — visible en el log real del contenedor (`on_message invoked`, nunca
   `on_app_mention`). El `app_mention` bot event SÍ estaba correctamente suscripto en la Slack App;
   el App-Level Token (`Dev_slack_app_token_v1.txt`) necesitó regenerarse/actualizarse para que la
   conexión Socket Mode empezara a recibirlo — el Bot Token (identidad del bot, `registrador_de_ingres`
   / bot_id `B0B345MCXF1`) nunca cambió, sólo el App Token.
2. El mismo mensaje, procesado por el handler viejo de ingresos (`_handle_message`, que sí corrió),
   fue ignorado por su propio filtro de canal (`config_servicios.slack_channels`) — comportamiento
   correcto de ESE handler, sin relación con el comando de cables.

**Lección**: tener el scope OAuth `app_mentions:read` no alcanza — hace falta además el App-Level
Token correcto para que Socket Mode reciba ese tipo de evento. Verificar con el log real de conexión
(`auth.test`/eventos entrantes), no sólo con la lista de scopes.

## Referencias

- `docs/modulo_ingesta_cromo.md` — módulo de ingesta y verificador de servicios sobre `app.cromo_*`.
- `docs/infra.md` — jerarquía Cámara/Botella legado (dominio distinto de Cromo, mismo bot de Slack).
- `.github/skills/cromo-diagnostico-real` — metodología obligatoria para validar cualquier supuesto
  de mapeo/parseo contra el sistema real de Cromo antes de declararlo funcional; así se resolvieron
  los dos gaps de mapeo de este documento (nombre de cable, número de buffer).
