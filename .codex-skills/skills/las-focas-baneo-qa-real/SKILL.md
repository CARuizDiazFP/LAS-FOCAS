---
name: "las-focas-baneo-qa-real"
description: "Usar antes de ejecutar create_ban/lift_ban o cualquier prueba de cascada de estado de Camara contra datos reales (lasfocasdev-*) — resuelve el blast radius real y cómo revertir con precisión si algo sale mal"
metadata:
  short-description: "Usar antes de ejecutar create_ban/lift_ban o cualquier prueba de cascada de estado de Camara contra datos reales..."
  source: ".github/skills/baneo-qa-real/SKILL.md"
  triggers:
    - "baneo-qa-real"
    - "baneo"
    - "las-focas"
    - "cascada"
    - "camara"
    - "botella"
    - "proteccion"
    - "lift_ban"
    - "create_ban"
    - "qa"
  globs:
    - "core/services/protection_service.py"
    - "core/services/camara_estado_service.py"
    - "core/services/camara_hierarchy_service.py"
    - "core/services/botellas_unificadas_service.py"
    - "tests/test_protection_service.py"
  commands:
    []
---

# Nombre de archivo: SKILL.md
# Ubicación de archivo: .codex-skills/skills/las-focas-baneo-qa-real/SKILL.md
# Descripción: Skill portable Codex migrada desde .github/skills/baneo-qa-real/SKILL.md

# Skill portable: baneo-qa-real

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

```sql
-- Todas las cámaras que tocará create_ban/lift_ban para este servicio (no sólo el grupo objetivo)
SELECT DISTINCT c.id, c.nombre, c.estado, c.camara_padre_id
FROM app.servicios s
JOIN app.rutas_servicio rs ON rs.servicio_id = s.id
JOIN app.ruta_empalme_association rea ON rea.ruta_id = rs.id
JOIN app.empalmes e ON e.id = rea.empalme_id
JOIN app.camaras c ON c.id = e.camara_id
WHERE s.servicio_id = '<servicio_a_usar>';
```

Si el resultado incluye cámaras fuera del grupo que querés probar, elegí otro servicio más acotado o
documentá explícitamente que la prueba va a tocar más de un grupo.

### 2. Registrar el estado ANTES de cada cámara del blast radius

```sql
SELECT id, nombre, estado, camara_padre_id
FROM app.camaras
WHERE id IN (<todos los ids del paso 1>);
```

### 3. Ejecutar contra `lasfocasdev-*` únicamente

Nunca contra `lasfocas-*` (producción). Crear un usuario QA temporal si hace falta autenticación real,
y borrarlo al final.

### 4. Si el resultado final no coincide con el estado "antes" del paso 2

No hagas `UPDATE app.camaras SET estado = ...` directo. En cambio:

1. Buscá la última transición real de cada cámara afectada ANTES de tu prueba:
   ```sql
   SELECT camara_id, estado_anterior, estado_nuevo, created_at, motivo
   FROM app.camaras_estado_auditoria
   WHERE camara_id = <id>
   ORDER BY created_at DESC;
   ```
2. Reconstruí el estado correcto objetivo a partir de esa fila.
3. Aplicá la corrección vía `core.services.camara_estado_service.aplicar_estado_a_grupo()` (mismo
   mecanismo real que usa `create_ban`/`lift_ban`/`override_camara_estado_manual`), con
   `usuario="qa_fix_revert"` y un `motivo` explícito.
4. Confirmá con una consulta directa que el estado final coincide con el del paso 2.

### 5. Verificar que la cascada en sí funcionó

```sql
SELECT id, nombre, estado FROM app.camaras WHERE id = <padre> OR camara_padre_id = <padre>;
```
`estado` debe ser el mismo en TODOS los miembros del grupo durante el baneo, y cada miembro debe
volver a su propio estado real al desbanear.

## Reglas

1. **Nunca correr contra `lasfocas-*`** (producción) — sólo `lasfocasdev-*`.
2. **Nunca dar por buena una cascada sin resolver el blast radius real primero**.
3. **Restaurar siempre vía las funciones reales** (`aplicar_estado_a_grupo`), nunca `UPDATE` directo.
4. **`app.camaras_estado_auditoria` es la única fuente de verdad** del estado previo real.
5. **Usuarios QA temporales**: crear y borrar siempre al finalizar.

## Documentación relacionada

- `docs/infra.md` — sección "Jerarquía Cámara → Botellas".
- `core/services/protection_service.py` — `create_ban`/`lift_ban`, `_determinar_estado_restauracion`.
- `core/services/camara_estado_service.py` — `aplicar_estado_a_grupo`, `obtener_ultima_transicion_a_baneada`.
- `tests/test_protection_service.py` — tests de regresión (mocks; no reemplazan la verificación real).
- `las-focas-db-mcp-postgres` — sección "Jerarquía Cámara→Botella y auditoría de estado".
