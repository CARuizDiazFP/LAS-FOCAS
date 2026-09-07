# Nombre de archivo: SKILL.md
# Ubicación de archivo: .agentes-comunes/skills/baneo-qa-real/SKILL.md
# Descripción: Skill para probar el Protocolo de Protección (baneo/cascada de estado) contra datos reales sin causar drift no controlado

---
name: baneo-qa-real
description: "Usar antes de ejecutar create_ban/lift_ban o cualquier prueba de cascada de estado de Camara contra datos reales (lasfocasdev-*) — resuelve el blast radius real y cómo revertir con precisión si algo sale mal"
argument-hint: "Describe qué cascada de estado querés probar, por ejemplo: verificar que banear una Botella propaga a toda la Cámara"
---

# Skill: QA real del Protocolo de Protección (Baneo)

## Por qué existe esta skill

Al verificar contra datos reales (no mocks) la cascada de baneo de la jerarquía Cámara→Botella
(2026-08-10), un servicio elegido "cualquiera" para la prueba resultó pasar por **13 cámaras reales en
3 grupos distintos**, no sólo el grupo objetivo que se quería probar. El `lift_ban` de cierre de la
prueba tocó 8 cámaras de otros 2 grupos no relacionados: 5 quedaron `LIBRE` habiendo estado
`DETECTADA`, y 3 quedaron `LIBRE` habiendo estado `BANEADA` por un motivo independiente y anterior
(una de ellas por un baneo real de un admin, del 2026-07-27, sin ningún incidente activo que lo
respaldara). Se detectó comparando contra `app.camaras_estado_auditoria` (nunca hubiera aparecido con
mocks — requiere el estado real pre-existente de una DB real) y se revirtió reconstruyendo el estado
exacto previo desde esa misma tabla. La causa raíz resultó ser además un bug real preexistente en la
lógica de restauración (`_determinar_estado_restauracion` sólo sabía volver a `LIBRE`/`OCUPADA`), que
la cascada de grupo simplemente amplificó de 1 cámara a N por cada `lift_ban`.

**Regla general**: `create_ban`/`lift_ban` resuelven las cámaras afectadas dinámicamente
(`Servicio → RutaServicio → Empalme → Camara`, sin FK fija) — la ruta completa de un servicio real casi
nunca coincide con "sólo el grupo que quiero probar". Antes de mutar estado real, hay que conocer el
blast radius real.

## Cómo probar una cascada de estado de forma segura

### 1. Resolver el blast radius COMPLETO antes de mutar nada

No asumas que un servicio de prueba sólo toca el grupo objetivo. Resolvé la ruta física completa —
**dos queries, no una**: `get_camaras_for_servicio` (Refactor baneos, 2026-08-23) resuelve por DOS
caminos independientes (legacy y Cromo), y el blast radius real es la UNIÓN de ambos.

```sql
-- 1a. Camino legacy: cámaras vía Servicio→RutaServicio→Empalme.camara_id→Camara
SELECT DISTINCT c.id, c.nombre, c.estado, c.camara_padre_id
FROM app.servicios s
JOIN app.rutas_servicio rs ON rs.servicio_id = s.id
JOIN app.ruta_empalme_association rea ON rea.ruta_id = rs.id
JOIN app.empalmes e ON e.id = rea.empalme_id
JOIN app.camaras c ON c.id = e.camara_id
WHERE s.servicio_id = '<servicio_a_usar>';
```

```sql
-- 1b. Camino Cromo: cámaras vía Servicio→CromoServicioMatch→CromoPelo→CromoCable→
-- CromoBotella.camara_id→Camara (mismo join que camara_ids_por_servicio_sync,
-- core/services/cromo/verificador.py) — un servicio cuya infraestructura sólo se conoce por la
-- ingesta de Cromo Red (sin trackings legacy cargados) NO aparece en la query 1a, pero
-- create_ban/lift_ban SÍ lo banean desde este fix. Omitir esta query subestima el blast radius real.
SELECT DISTINCT c.id, c.nombre, c.estado, c.camara_padre_id
FROM app.servicios s
JOIN app.cromo_servicio_match m ON m.servicio_id = s.id
JOIN app.cromo_pelos p ON p.n_id = m.pelo_n_id
JOIN app.cromo_cables ca ON ca.n_id = p.cable_n_id
JOIN app.cromo_botellas b ON b.n_id = ca.extremo_a_n_id OR b.n_id = ca.extremo_b_n_id
JOIN app.camaras c ON c.id = b.camara_id
WHERE s.servicio_id = '<servicio_a_usar>' AND b.camara_id IS NOT NULL;
```

El blast radius completo es la UNIÓN de los `id` de ambas queries (podés correrlas por separado y
comparar, o combinarlas con `UNION` si preferís un solo resultado). Si el resultado incluye cámaras
fuera del grupo que querés probar, elegí otro servicio más acotado o documentá explícitamente que la
prueba va a tocar más de un grupo.

### 2. Registrar el estado ANTES de cada cámara del blast radius

```sql
SELECT id, nombre, estado, camara_padre_id
FROM app.camaras
WHERE id IN (<todos los ids del paso 1>);
```

Guardá esto textualmente (no de memoria) — es lo único que te permite confirmar después que revertiste
bien.

### 3. Ejecutar contra `lasfocasdev-*` únicamente

Nunca contra `lasfocas-*` (producción). Crear un usuario QA temporal si hace falta autenticación real,
y borrarlo al final (nunca dejar usuarios de prueba en la DB).

### 4. Si el resultado final no coincide con el estado "antes" del paso 2

No hagas `UPDATE app.camaras SET estado = ...` directo — eso es exactamente el hueco de seguridad que
`aplicar_estado_a_grupo()` fue creado para cerrar (pierde auditoría y puede desincronizar el grupo).
En cambio:

1. Para cada cámara con estado incorrecto, buscá su última transición real ANTES de tu prueba:
   ```sql
   SELECT camara_id, estado_anterior, estado_nuevo, created_at, motivo
   FROM app.camaras_estado_auditoria
   WHERE camara_id = <id>
   ORDER BY created_at DESC;
   ```
2. Reconstruí el estado correcto objetivo a partir de esa fila (no de memoria/suposición).
3. Aplicá la corrección vía `core.services.camara_estado_service.aplicar_estado_a_grupo()` (mismo
   mecanismo real que usa `create_ban`/`lift_ban`/`override_camara_estado_manual` — nunca un `UPDATE`
   directo), con `usuario="qa_fix_revert"` y un `motivo` explícito que diga que es una reversión de
   prueba QA.
4. Confirmá con una consulta directa que el estado final coincide con el del paso 2.

### 5. Verificar que la cascada en sí funcionó (no sólo que revertiste bien)

Para el grupo objetivo específico, confirmar antes/durante/después:
```sql
SELECT id, nombre, estado FROM app.camaras WHERE id = <padre> OR camara_padre_id = <padre>;
```
`estado` debe ser el mismo en TODOS los miembros del grupo durante el baneo (cascada bidireccional
completa), y cada miembro debe volver a su propio estado real (no necesariamente igual entre sí) al
desbanear.

## Reglas

1. **Nunca correr contra `lasfocas-*`** (producción) — sólo `lasfocasdev-*`.
2. **Nunca dar por buena una cascada sin resolver el blast radius real primero** — un servicio de
   prueba "cualquiera" puede tocar grupos no relacionados.
3. **Restaurar siempre vía las funciones reales** (`aplicar_estado_a_grupo`), nunca `UPDATE` directo a
   `Camara.estado` — se pierde auditoría y se puede desincronizar el grupo.
4. **`app.camaras_estado_auditoria` es la única fuente de verdad** del estado previo real de una
   cámara — `camara.estado` ya está sobreescrito en el momento en que hay algo que revertir.
5. **Usuarios QA temporales**: crear y borrar siempre al finalizar, nunca dejarlos en la DB.

## Documentación relacionada

- `docs/infra.md` — sección "Jerarquía Cámara → Botellas", incluye el hallazgo del bug de
  restauración y su fix.
- `core/services/protection_service.py` — `create_ban`/`lift_ban`, `get_camaras_for_servicio` (camino
  legacy + Cromo, Refactor baneos 2026-08-23), `_camara_tiene_otro_baneo_activo`,
  `_determinar_estado_restauracion`.
- `core/services/cromo/verificador.py` — `camara_ids_por_servicio_sync`/`servicio_ids_por_camaras_sync`,
  el join Cromo que alimenta el paso 1b de arriba.
- `core/services/camara_estado_service.py` — `aplicar_estado_a_grupo`, `obtener_ultima_transicion_a_baneada`.
- `tests/test_protection_service.py` — tests de regresión del bug de restauración y de la resolución
  mixta legacy+Cromo (mocks; no reemplazan la verificación contra datos reales que describe esta skill).
- `.github/skills/db-mcp-postgres/SKILL.md` — sección "Jerarquía Cámara→Botella y auditoría de estado".
