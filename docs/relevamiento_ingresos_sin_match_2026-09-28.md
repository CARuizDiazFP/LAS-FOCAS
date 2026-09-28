# Nombre de archivo: relevamiento_ingresos_sin_match_2026-09-28.md
# Ubicación de archivo: docs/relevamiento_ingresos_sin_match_2026-09-28.md
# Descripción: Relevamiento de los 201 casos de app.ingresos_sin_match de producción, causas raíz medidas y propuesta de mejora de la búsqueda de cámaras (sin implementar)

# Relevamiento de ingresos sin match — 2026-09-28

**Estado: implementado el mismo día** (rama `fix/claude-busqueda-busqueda-camaras-sin-match`, ver
"Implementación y medición final" al final). Las secciones de diagnóstico y prototipo quedan como
registro de cómo se llegó; donde la implementación difiere de la propuesta, manda la sección final.

## Fuente y método

- **Datos**: los 201 casos de `app.ingresos_sin_match` de **producción** (168 `slack`, 18
  `tracking`, 15 `excel_camaras` —6 ya marcados revisados—), exportados read-only el 2026-09-28. Slack: 8 al 28 de septiembre.
- **Réplica de la cascada**: dev y prod tienen el mismo inventario (10.183 contra 10.182 Cámaras,
  11.072 `cromo_botellas` en ambos) y el mismo código de búsqueda (`camara_search.py` y
  `camara_botella_busqueda.py` idénticos al worker de prod). Por eso cada caso se re-ejecutó contra
  `lasfocasdev-postgres`, en transacción `READ ONLY` y dentro de `lasfocasdev-slack-baneo-worker`,
  con el mismo pipeline del listener: `extraer_nombre_camara` → `detectar_multi_bot` →
  `limpiar_ruido_operativo` → `buscar_camara_o_botella_cromo`.
- **Prototipo descartable** con las correcciones de abajo, medido de dos formas:
  1. **Recuperación**: cuántos de los 201 resuelve, revisando a mano que la cámara elegida sea la
     correcta.
  2. **Regresión (auto-recuperación)**: 1.500 nombres al azar de `app.camaras` (seed 7) buscados
     tal cual, con la condición de que cada uno se siga encontrando a sí mismo.

## Causas raíz (filas, no casos únicos)

| # | Causa | Filas | Ejemplos reales | Tipo de falla |
|---|---|---|---|---|
| A | **Nodo escrito sin la palabra "Nodo"** | 35 | `Atento`, `Quilmes`, `Barrio Norte`, `Rincón`, `Avellaneda`, `Escobar`, `La Lucila`, `Congreso`, `Santa Fe`, `Vicente López`, `Tacuari 1`, `Data Tacuari, sala1`, `Paraguay 2302` | El listener ignora los Nodos sólo si el texto contiene `nodo` (`_RE_NODO`). Confirmado por el usuario: los técnicos se la olvidan seguido |
| B | **`bot2` pegado / `Bot 1` explícito** | 26 | `Cra huergo 501 bot2`, `Cra ausol y parana bo2`, `BOT2. Cra Marcos Sastre…`, `CRA Rondeau 2988 bot 1`, `Cra monteagudo 202 bot1 y bot2` | **Bug**: `\bbot(ella)?\b` no matchea `bot2` (no hay límite de palabra entre `t` y `2`), así que `tiene_bot=False` y la cascada *descarta* justamente las botellas secundarias. `Bot 1` exige el número 1 en el nombre, pero por convención la Botella 1 es la Cámara sin prefijo. `_RE_MULTI_BOT` no reconoce `bot1 y bot2` |
| C | **Número pegado a letras** | 5 | `Cra huergo701`, `Cra. Av. 122 99B - La Plata`, `lizandro de la torre ( R197) y austria`, `Bandeja Solis1702 C.F` | **Bug**: `_filtrar_por_numeros` exige `\b<n>\b`; `r197` o `99b` no tienen límite de palabra, así que **el nombre exacto del inventario queda descartado por sí mismo** |
| D | **Duplicados en el inventario** | 15 | `Cra Libertad 991 CF` contra `BOTELLA CRITICA Cra Libertad 991 CF`; `Cra A. Frondizi 1413 Bot 2 PILAR` (dos `cromo_botellas` que sólo difieren en `BOT`/`Bot`, misma Cámara padre) | Ambigüedad aunque uno de los candidatos coincide exacto con el texto, o todos cuelgan de la misma Cámara |
| E | **Basura antes del nombre** | 5 | `me: \nCra Acevedo 396 CF - ACEVEDO 396 - …` | La primera línea del campo es `me:` (copy/paste roto); la captura extendida la une al nombre real |
| F | **Cascada Cromo sin el intento literal** | 8 | `Cra Av Santa Fe 4276 Bot 2 CF`, `Cra Av. Cabildo 451 Bot 2 C.F`, `Poste Ruta 25 y Dr Thomas de Anchorena Bot 2 PILAR` | **Bug**: el nombre existe **exacto** en `cromo_botellas`, pero `_cascada_botella_intento` sólo busca con abreviaturas expandidas (`av`→`avenida`, `dr`→`doctor`). Le falta el equivalente al Intento 4 de `buscar_camara()` |
| I | **ID de Cromo escrito a mano** | 2 | `ID DE BOTELLA : 6631457 ( TZA. FLORIDA 142)` | `6631457` es un `n_id` real de `cromo_botellas`; hoy se trata como texto |
| J | **Palabras extra o typo** | 54 | `Botella, terraza. Esmeralda 726. CF` (inventario: `Bot. 2 Tza. Esmeralda 726 C.F.`), `Cra juano manso 720`, `Cra olvando cruz 2764`, `Cra capitán bermudez 4551 (munro)`, `Calle congreso 1517 CABA` | El AND-ILIKE exige *todos* los tokens: una localidad o un descriptor (`terraza`, `fachada`, `CABA`) que no está en el nombre del inventario mata el match |
| G | **Match exacto que el prototipo resuelve sin causa específica asignada** | 2 | `ODF EDGE Calle 4 - Pilar MMR1` (tracking, ×2) | Probablemente el mismo filtro de números del punto C (`MMR1`) |
| H | **Fuera de alcance** | 13 | `Caja cto ID:1274520`, `Pon, terraza. Humberto 1° 434`, `MKT-1309429`, `… a instalar`, `nombre_botella` | Cajas de cliente, PON, número de ticket en el campo de nombre, placeholder del Excel |
| K | **Sin resolver con las propuestas** | 36 | `Cra O. CRUZ Y SANTA M. DEL BUENOS AIRES`, `Cra zepita 3101`, `Iste Chubut y ruvadavia pilar`, `Bot Poste libre del sur 1890` | Esquinas sin altura, abreviaturas no estándar, typos múltiples. Necesitan revisión manual |

## Propuesta (en orden de impacto / riesgo)

1. **Catálogo de Nodos** (A, 35 filas). Si el nombre extraído, **completo**, es un nombre de Nodo
   (opcionalmente con `sala N`/`rack N` o prefijo `data`/`dc`), se trata igual que hoy un mensaje
   con "Nodo": se ignora, no queda como sin match. El catálogo se deriva de las filas `Nodo …` de
   `app.camaras` (18 claves hoy: `atento`, `avellaneda`, `tacuari`, `paraguay 2302`, `santa fe`,
   `retiro`…) **más una lista configurable** para los que no están en el inventario (`quilmes`,
   `escobar`, `la lucila`, `barrio norte`, `rincon`, `congreso`, `vicente lopez`). La comparación es
   por igualdad del nombre entero, nunca por contenido, para que `Cra X QUILMES` siga siendo una
   cámara.
2. **Normalización de `bot`** (B). `bot2`/`bo2`/`bot.2` → `Bot 2` antes de buscar; `Bot 1`/`Botella
   1` → se quita (es la Cámara principal); `_RE_MULTI_BOT` acepta `bot1 y bot2`. **Orden
   obligatorio**: detectar multi-bot *antes* de quitar `Bot 1`. El prototipo lo hacía al revés y
   perdió la Botella 1 de `monteagudo 202 bot1 y bot2`.
3. **Filtro de números sin `\b`** (C): `(?<!\d)<n>(?!\d)` en vez de `\b<n>\b`, y separar
   `letra+número` pegados (`huergo701` → `huergo 701`).
4. **Intento literal en la cascada Cromo** (F): paridad con el Intento 4 de `buscar_camara()`.
5. **Desempate** (D). Si un candidato coincide exacto (normalizado) con el texto, gana; si todos
   los candidatos resuelven **por id** a la misma Cámara raíz, se toma esa. **Nunca por nombre**:
   el prototipo desempataba por nombre deduplicado y eligió mal entre pares duplicados `C.F`/`CF`
   (ver regresión).
6. **Prefijo basura** (E): descartar una primera línea del campo del tipo `\w{1,3}:`.
7. **ID de Cromo explícito** (I): `ID … <6-9 dígitos>` → lookup directo por `cromo_botellas.n_id`.
8. **Sugerencias en vez de auto-match** (J). Cuando nada matchea pero hay candidatos que comparten
   **todos** los números y al menos un token de calle, no registrar nada automático: incluir los
   hasta 3 mejores en la respuesta de Slack ("¿Quisiste decir…?") y guardarlos en el caso
   `IngresoSinMatch` para resolverlo con un click desde el panel. Así el typo no se convierte en un
   ingreso en la cámara equivocada.

## Resultados medidos del prototipo

**Recuperación sobre los 201 casos:**

| | Match automático | Nodo ignorado | Sugerencia (J) | Ambiguo | Sin match |
|---|---|---|---|---|---|
| Actual | 2 | — | — | 48 | 151 |
| Prototipo | 54 | 17 | 63 | 16 | 51 |

Todos los matches automáticos del prototipo se revisaron a mano y son la cámara correcta. Los 17
nodos son sólo los que hoy están en el inventario: con la lista configurable del punto 1 se suman
los 18 restantes de la causa A.

**Regresión (1.500 nombres del inventario buscándose a sí mismos):**

| | Se encuentra a sí mismo | Ambiguo / sugerencia | Sin match | Cámara incorrecta |
|---|---|---|---|---|
| Actual | 1347 | 88 | 59 | 6 |
| Prototipo | 1460 | 24 | 1 | 15 |

Los 15 "incorrectos" del prototipo son casi todos **pares duplicados del inventario**
(`Cra Madero 898 C.F` contra `Cra Madero 898 CF`, `Cra Cerrito 1098 C.F.` contra `Cra Cerrito 1098
CF`), elegidos por el desempate por nombre del punto 5. La implementación real tiene que desempatar
por id y **re-medir con este mismo arnés antes de mergear**: el criterio de aceptación es
"incorrectos ≤ actual (6)".

## Hallazgos colaterales

- **Duplicados reales de inventario que la búsqueda no puede resolver**:
  `Cra Juan Domingo Peron 498 CF` existe **4 veces** en `app.camaras` (ids 2743-2746, dos raíces).
  Mismo patrón que el conocido de `docs/decisiones.md` 2026-09-08 (pares `C.F.`/`CF`). Es un
  problema de datos, no de regex; corresponde al dashboard de Cámaras duplicadas.
- **Los casos no se reintentan solos**: una mejora de búsqueda no resuelve los 201 históricos.
  Hace falta correr "Revalidar ingreso" en cada hilo, o un reproceso por lote que use el mismo
  código (con `created_at` del caso como momento, igual que la revalidación).
- **Tracking con "Nodo" explícito** (`Nodo Escobar Rack 1 de FO`) también cae como sin match: el
  camino de tracking no aplica la exclusión de Nodos que sí aplica el listener.

## Implementación y medición final (2026-09-28)

Código: `modules/slack_baneo_notifier/camara_search.py` (preprocesamiento, filtro de números,
número de botella, multi-bot, desempate exacto, prefijo basura), `core/services/cromo/camara_botella_busqueda.py`
(intento literal, desempate de botellas, ID de Cromo, reintento sin "Bot 1", flag `desempatar`),
`core/services/nodos_catalogo.py` (nuevo), `core/services/camara_sugerencias.py` (nuevo), listener
de Slack, `infra_service` (tracking) y `camara_ingest_service` (Excel, `desempatar=False`).
Tests: `tests/test_busqueda_camaras_sin_match.py`.

### Diferencias con la propuesta

- **Catálogo de Nodos sin lista a mano**: nombres "Nodo …" de `app.cromo_odfs` (vigentes) y los de
  `app.camaras` que **empiezan** con "Nodo" — los mismos que muestran el tracking y el Path de Cromo.
  **Sólo claves sin números**: una clave con altura ("chacabuco 271") es también la dirección de
  cámaras reales ("Cra Chacabuco 271 CF"). No se quita un dígito final de la entrada ("San Martin 1
  CF" es una Cámara). Costo aceptado: "Rincón", "Paraguay 2302", "Tacuari 1" y "Santa Fe" siguen sin
  resolverse; "Quilmes" no es un Nodo del inventario. Se prefiere el error visible (sin match,
  revalidable) al silencioso (mensaje ignorado).
- **Desempates**: nunca sobre el recorte antes del guion, nunca con una gemela "CRITICA" entre las
  candidatas (el listener quita " - CRITICA" antes de buscar), y entre botellas del mismo padre sólo
  si coinciden exacto (Bot 2 y Bot 3 del mismo padre son botellas distintas y el Egreso se cierra por
  `cromo_botella_id` exacto). El baneo masivo desde Excel no desempata nunca.
- **"Bot N" exige esa botella**: la candidata tiene que tener "Bot N"; no alcanza con un "N" en otra
  parte ("Ed 2", "P2"). Un número de 1-2 dígitos tampoco se satisface con una letra delante (salvo
  "bot"). Un recorte antes del guion que pierde el "Bot N" del texto completo no se prueba.
- **ID de Cromo**: sólo botellas vigentes, y si el texto trae algo más que el ID, tiene que
  corroborarlo (un número o palabra compartida con el nombre).
- **Sugerencias sólo en la respuesta de Slack** (`Forzar ingreso <nombre>`), sin migración.
- **Tracking**: una ubicación de Nodo ya no se registra como sin match.

### Ronda de revisión

La primera versión integrable pasó el arnés de auto-recuperación pero **no** una revisión
adversarial con un arnés distinto: 3.798 entradas derivadas del inventario comparando `dev` contra
la rama, buscando transiciones "sin match/ambiguo → cámara INCORRECTA". Encontró 8 casos reales de
ese tipo (gemelas CRITICA, "P2" satisfaciendo "Bot 2", recortes que perdían la botella, desempate
entre Bot 2/Bot 3) y 5 falsos positivos de Nodo. Todos reproducidos y corregidos; cada uno tiene su
test. Lección: medir "¿se encuentra a sí mismo?" no detecta "resuelve a OTRA cámara que antes no
resolvía"; hacen falta los dos arneses.

### Medición final (arneses read-only contra `focas_dev`)

| 201 casos de prod | Match | Nodo | Sugerencia | Ambiguo | Sin match |
|---|---|---|---|---|---|
| `dev` (antes) | 2 | 6 | — | 48 | 145 |
| Rama | 45 | 31 | 66 | 12 | 47 |

Los 45 matches se revisaron uno por uno contra el texto original: todos correctos.

| Auto-recuperación (1.500 Cámaras, seed 7) | Se encuentra a sí mismo | Ambiguo | Sin match | Incorrecta |
|---|---|---|---|---|
| `dev` | 1341 | 89 | 63 | 7 |
| Rama | 1410 | 35 | 48 | 7 (los mismos 7) |

| Transiciones (3.340 entradas del inventario, seed 11) | Correctas | Sin match | Ambiguas | Incorrectas |
|---|---|---|---|---|
| `dev` | 2867 | 300 | 145 | 28 |
| Rama | 3022 | 234 | 59 | 25 |

**Nuevas incorrectas: 0.** Transiciones: ambiguo → correcta 86, sin match → correcta 67, incorrecta
→ correcta 3, correcta → sin match 1 ("Cra FFCC E/ Garay y Belbeze - E1A Bot 2": `dev` la resolvía por
el recorte que pierde el "Bot 2"; ese recorte ya no se prueba — es la misma regla que evita los 8
casos incorrectos de la revisión).

Latencia por búsqueda: mediana 110 → 120 ms, máximo 181 → 222 ms.

**Los casos históricos no se reprocesan solos** — ver "Reproceso por lote" abajo.

## Reproceso por lote (2026-09-28)

`scripts/ingresos_reprocesar_sin_match.py` → `core/services/ingreso_reproceso_service.py`. Reglas
(docstring del servicio): sólo casos de Slack pendientes; mismo pipeline que el listener en vivo;
Nodo → `revisado=true`; siempre `INGRESO` real (el baneo de hoy no es evidencia del pasado, criterio
de "Forzar ingreso"); orden cronológico; Egreso acotado en el tiempo (`registrar_egreso_historico`:
sólo cierra un ingreso que empezó antes); sin duplicar movimientos que el hilo ya tiene; un commit por
caso; idempotente. Dry-run **exacto**: corre todo dentro de una transacción externa que se revierte.

**Ensayo** (dev, copia de los 202 casos de prod exportada el 2026-09-28 — 169 de Slack —, todo dentro
de una transacción revertida; se verificó que dev quedó igual):

| Estado | Casos |
|---|---|
| REGISTRADO | 33 (18 ingresos creados, 13 egresos que cierran su ingreso, 4 egresos huérfanos) |
| NODO (marcado revisado) | 25 |
| AMBIGUO / SIN_MATCH (sin tocar) | 11 / 100 |

Segunda corrida: 111 candidatos (los no resueltos), 0 filas nuevas. Los 4 egresos huérfanos en dev
corresponden a visitas cuyo Ingreso sí había matcheado en vivo en prod: en prod esos egresos van a
cerrar el ingreso abierto real (dev no tiene esas filas).

**Bug real encontrado por el ensayo** (y corregido en `detectar_multi_bot`): "Bot monteagudo 202 bot1
y bot2" dejaba el "Bot" genérico en el nombre de la Botella 1 → resolvía a la Bot 2, y el Egreso de la
Botella 1 cerraba el ingreso de la Bot 2. Afectaba también al listener en vivo.

**Ejecución en prod: pendiente de la alineación de prod** (paso 7 de `docs/despliegue_produccion.md`):
tiene que correr con la búsqueda nueva desplegada, dentro del contenedor.

