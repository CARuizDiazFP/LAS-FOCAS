# Nombre de archivo: SKILL.md
# Ubicación de archivo: .github/skills/repo-update/SKILL.md
# Descripción: Habilidad para actualizar el repositorio con análisis, documentación y commit

---
name: Repo Update
description: Procedimiento completo para actualizar el repositorio incluyendo análisis, documentación, PR diario, commit y push
trigger: actualizar repo
---

# Habilidad: Actualizar Repositorio

Procedimiento estándar para subir cambios al repositorio de LAS-FOCAS.

> **Rama por defecto**: `main`. Usar otra rama solo si se solicita explícitamente.

## Activación

Esta skill se ejecuta cuando el usuario indica **"actualizar repo"** o variantes similares.

---

## Paso 1: Analizar Cambios Realizados

Revisar qué archivos fueron modificados, creados o eliminados.

```bash
# Ver estado actual del repositorio
git status

# Ver cambios detallados
git diff --stat

# Ver archivos modificados (staged y unstaged)
git diff --name-status

# Ver últimos commits si hay alguno pendiente de push
git log origin/main..HEAD --oneline
```

**Acción del agente**:
- Identificar todos los archivos modificados
- Categorizar cambios por módulo/dominio (api, bot, core, db, modules, web, etc.)
- Detectar archivos nuevos que requieran encabezado de 3 líneas

---

## Paso 2: Verificar Documentación

Constatar que los cambios estén correctamente documentados.

### Checklist de documentación

| Tipo de cambio | Documentación requerida |
|----------------|------------------------|
| Nuevo endpoint API | `docs/api.md` |
| Cambio en bot Telegram | `docs/bot.md` |
| Modificación de modelos DB | `docs/db.md` |
| Cambios en chatbot/MCP | `docs/chatbot.md`, `docs/mcp.md` |
| Nuevos informes | `docs/informes/` |
| Cambios de seguridad | `docs/Seguridad.md` |
| Decisiones técnicas | `docs/decisiones.md` |
| Panel web | `docs/web.md` |
| Office service | `docs/office_service.md` |

**Acción del agente**:
- Revisar si los archivos de documentación pertinentes están actualizados
- Si faltan actualizaciones, realizarlas antes de continuar
- Verificar que funciones públicas tengan docstrings

---

## Paso 3: Documentar en PR Diario

Crear o actualizar el archivo de PR diario en `docs/PR/YYYY-MM-DD.md`.

**Referencia**: Usar el prompt `.github/prompts/generar-pr-diario.prompt.md`

### Estructura obligatoria del PR diario

```markdown
# Nombre de archivo: YYYY-MM-DD.md
# Ubicación de archivo: docs/PR/YYYY-MM-DD.md
# Descripción: PR diario del YYYY-MM-DD

# PR Diario - YYYY-MM-DD

## Resumen de Cambios
[Descripción breve]

## Contexto y Alcance
- **Módulos afectados**: [lista]
- **Supuestos**: [si aplica]
- **Riesgos conocidos**: [si aplica]

## Cambios Realizados

### Archivos Modificados
- [archivo]: [descripción]

### Archivos Creados
- [archivo]: [propósito]

## Tareas

### Realizadas
- [x] Tarea 1
- [x] Tarea 2

### Pendientes
- [ ] Tarea pendiente

## Criterios de Aceptación
- [ ] Tests pasan: `pytest`
- [ ] Sin errores de linting
- [ ] Documentación actualizada

## Impacto en Seguridad
[Confirmar que no se exponen secretos]
```

**Acción del agente**:
- Verificar si existe `docs/PR/YYYY-MM-DD.md` con la fecha actual
- Si existe, actualizar agregando los nuevos cambios
- Si no existe, crear con la estructura completa

---

## Paso 4: Commit con Mensaje Descriptivo

Realizar commit con mensaje claro y descriptivo.

### Formato de mensaje de commit

```
[módulo] descripción breve del cambio

- Detalle 1
- Detalle 2
```

### Ejemplos de buenos mensajes

```bash
# Cambio en un módulo específico
git commit -m "[api] agregar endpoint de health check para monitoreo"

# Cambios en múltiples módulos
git commit -m "[core/bot] mejorar manejo de errores en flujos de chat

- Agregar retry con backoff en llamadas a OpenAI
- Mejorar logging de errores en handlers"

# Documentación
git commit -m "[docs] actualizar documentación de endpoints API"

# Fix
git commit -m "[fix] corregir validación de fechas en informes SLA"
```

### Comandos

```bash
# Agregar todos los cambios
git add .

# O agregar archivos específicos
git add <archivo1> <archivo2>

# Commit
git commit -m "[módulo] mensaje descriptivo"
```

**Acción del agente**:
- Construir mensaje de commit basado en los cambios analizados
- Incluir módulos afectados en prefijo
- Ser específico pero conciso

---

## Paso 5: Push a la Rama

Subir los cambios al repositorio remoto.

```bash
# Push a main (por defecto)
git push origin main

# Push a otra rama si se especificó
git push origin <nombre-rama>

# Si la rama es nueva
git push -u origin <nombre-rama>
```

**Acción del agente**:
- Ejecutar push a `main` por defecto
- Usar otra rama SOLO si el usuario lo solicita explícitamente
- Verificar que el push sea exitoso

---

## Flujo Completo de Ejemplo

```bash
# 1. Analizar cambios
git status
git diff --stat

# 2. Verificar documentación (manual/agente)

# 3. PR diario ya actualizado

# 4. Commit
git add .
git commit -m "[core/mcp] agregar nueva herramienta de búsqueda de infraestructura

- Implementar MCP tool para búsqueda en PostgreSQL
- Agregar tests unitarios
- Actualizar documentación de MCP"

# 5. Push
git push origin main
```

---

## Notas Importantes

- **Encabezado de 3 líneas**: Todo archivo nuevo debe incluirlo
- **Tests**: Idealmente ejecutar `pytest` antes del commit
- **Secretos**: NUNCA commitear credenciales, tokens o contraseñas
- **Rama main**: Es la rama por defecto. Solo usar otra si se solicita

---

## Troubleshooting

### Conflictos al hacer push

```bash
# Traer cambios remotos primero
git pull --rebase origin main

# Resolver conflictos si los hay
# Luego reintentar push
git push origin main
```

### Deshacer último commit (no pusheado)

```bash
# Mantener cambios en staging
git reset --soft HEAD~1

# Descartar cambios completamente
git reset --hard HEAD~1
```

### Ver historial de commits

```bash
git log --oneline -10
git log --graph --oneline --all
```
