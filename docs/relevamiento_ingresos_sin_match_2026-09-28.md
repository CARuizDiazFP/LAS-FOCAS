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
multi-bot, desempate exacto, prefijo basura), `core/services/cromo/camara_botella_busqueda.py`
(intento literal, desempate de botellas, ID de Cromo, reintento sin "Bot 1"),
`core/services/nodos_catalogo.py` (nuevo), `core/services/camara_sugerencias.py` (nuevo), listener
de Slack y `infra_service` (tracking). Tests: `tests/test_busqueda_camaras_sin_match.py`.

**Diferencias con la propuesta:**

- **Catálogo de Nodos sin lista a mano.** Sale de los nombres "Nodo …" de `app.cromo_odfs` (vigentes)
  y `app.camaras` — los mismos que muestran el tracking y el Path de Cromo. 57 claves en dev.
  "Quilmes" **no** es un Nodo del inventario (los ODFs "… QUILMES" son de clientes), así que sigue
  cayendo como genérico. Para no convertir una calle en Nodo, "sin número final" sólo aplica a
  números cortos o nombres con artículo: "Nodo Mitre 3821" no genera la clave "mitre", y "Nodo Sta Fe
  4965" no genera "santa fe" — por eso "Santa Fe" solo (2 filas) sigue sin resolverse. Se prefirió el
  error visible (sin match) al silencioso (mensaje ignorado).
- **El desempate no se aplica al prefijo antes del guion** (hallazgo de la primera medición real, ver
  abajo): un recorte que coincide exacto con otra cámara no prueba nada.
- **Sugerencias sólo en la respuesta de Slack**, con la instrucción de usar `Forzar ingreso <nombre>`;
  no se guardan en `IngresoSinMatch` (no hizo falta migración).
- **Tracking**: una ubicación de Nodo ya no se registra como sin match (mismo criterio que Slack).

**Medición con el código real** (arnés read-only contra `focas_dev`, mismo pipeline que el listener;
muestra de regresión = 1.500 Cámaras ordenadas por id, seed 7, idéntica para ambos lados):

| 201 casos de prod | Match | Nodo | Sugerencia | Ambiguo | Sin match |
|---|---|---|---|---|---|
| `dev` (antes) | 2 | 6 | — | 48 | 145 |
| Rama | 51 | 35 | 59 | 8 | 48 |

| Regresión (1.500) | Se encuentra a sí mismo | Ambiguo | Sin match | Cámara incorrecta |
|---|---|---|---|---|
| `dev` (antes) | 1341 | 89 | 63 | 7 |
| Rama, 1ª medición | 1439 | 34 | 15 | **12** |
| Rama, final | **1444** | 34 | 15 | **7** |

La 1ª medición violó el criterio de aceptación ("incorrectos ≤ actual"): las 5 nuevas venían del
desempate exacto aplicado al prefijo antes del guion ("terraza Viamonte 898- Piso 4 C.F." → "terraza
Viamonte 898"). Corregido y cubierto por un test que falla si se reintroduce. Los 7 incorrectos
finales son **exactamente los mismos 7** que ya tenía `dev` (duplicados del inventario del tipo
"Cra. Conde 802 C.F." / "Cra Conde 802 CF").

Latencia por búsqueda (6 textos × 3 vueltas contra dev): mediana 110 → 120 ms, máximo 181 → 222 ms.

**Los 201 casos históricos no se reprocesan solos**: siguen en `ingresos_sin_match` hasta que alguien
responda "Revalidar ingreso" en cada hilo (o se haga un reproceso por lote, no implementado).

