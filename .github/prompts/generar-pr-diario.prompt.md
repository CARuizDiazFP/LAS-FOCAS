# Nombre de archivo: generar-pr-diario.prompt.md
# Ubicación de archivo: .github/prompts/generar-pr-diario.prompt.md
# Descripción: Prompt para generar automáticamente el PR diario en docs/PR/

---
name: Generar PR Diario
description: Genera o actualiza el documento de PR diario con los cambios realizados
mode: agent
variables:
  - name: fecha
    default: "${date:YYYY-MM-DD}"
    description: Fecha del PR en formato YYYY-MM-DD
---

# Generar PR Diario para LAS-FOCAS

Genera o actualiza el archivo `docs/PR/${fecha}.md` con los cambios realizados hoy en el proyecto.

## Instrucciones

1. **Analiza los cambios recientes** usando git:
   ```bash
   git log --oneline --since="midnight" --until="now"
   git diff --stat HEAD~10 HEAD
   ```

2. **Verifica si existe** el archivo `docs/PR/${fecha}.md`:
   - Si existe, actualízalo agregando los nuevos cambios
   - Si no existe, créalo con la estructura completa

3. **Estructura del PR diario** (obligatoria):

```markdown
# Nombre de archivo: ${fecha}.md
# Ubicación de archivo: docs/PR/${fecha}.md
# Descripción: PR diario del ${fecha}

# PR Diario - ${fecha}

## Resumen de Cambios

[Descripción de alto nivel de los cambios realizados]

## Contexto y Alcance

- **Módulos afectados**: [lista de módulos]
- **Supuestos**: [si aplica]
- **Riesgos conocidos**: [si aplica]

## Cambios Realizados

### Archivos Modificados
- [archivo 1]: [descripción breve]
- [archivo 2]: [descripción breve]

### Archivos Creados
- [archivo nuevo]: [propósito]

### Endpoints/Comandos Nuevos
- [si aplica]

## Tareas

### Realizadas
- [x] Tarea completada 1
- [x] Tarea completada 2

### Pendientes
- [ ] Tarea pendiente 1 `# TODO: descripción`

## Criterios de Aceptación

- [ ] Tests pasan: `pytest`
- [ ] Sin errores de linting
- [ ] Documentación actualizada

## Impacto en Seguridad

[Referencia a docs/Seguridad.md si hay cambios relevantes]
[Confirmar que no se exponen secretos]

## Compatibilidad y Migraciones

- **DB/Alembic**: [si hay migraciones]
- **Versiones**: [si hay cambios de dependencias]
- **Breaking changes**: [si aplica]

## Validación Manual

1. [Paso de verificación 1]
2. [Paso de verificación 2]

## Próximos Pasos

- [Siguiente tarea planificada]
```

4. **Reglas obligatorias**:
   - Encabezado de 3 líneas al inicio
   - Idioma español
   - No incluir secretos ni credenciales
   - Formato de nombre: `docs/PR/YYYY-MM-DD.md`
   - Estilo conciso y accionable

5. **Después de generar**, muestra un resumen de los cambios documentados.
