# Nombre de archivo: generar-pr-diario.prompt.md
# Ubicación de archivo: .github/prompts/generar-pr-diario.prompt.md
# Descripción: Prompt para generar automáticamente el PR diario en docs/PR/

---
name: Generar PR Diario
description: "Genera o actualiza docs/PR/YYYY-MM-DD.md con cambios del día, comandos ejecutados, impacto, riesgos y validaciones"
argument-hint: "Fecha opcional YYYY-MM-DD y contexto opcional, por ejemplo: 2026-04-16 cambios en web e infra"
agent: "agent"
---

# Generar PR Diario para LAS-FOCAS

Genera o actualiza el archivo `docs/PR/YYYY-MM-DD.md` correspondiente a la fecha indicada por el usuario. Si el usuario no indica fecha, usar la fecha actual.

## Objetivo

Documentar cambios reales del día con foco en:

- resumen ejecutivo de lo implementado
- archivos, módulos o servicios afectados
- comandos realmente ejecutados y su resultado relevante
- riesgos, impacto operativo y compatibilidad
- validación manual y próximos pasos

## Flujo de trabajo

1. Determinar la fecha objetivo en formato `YYYY-MM-DD`.
2. Revisar si ya existe `docs/PR/YYYY-MM-DD.md`.
3. Si existe, preservarlo y fusionar la nueva información sin duplicar secciones ni perder historial útil.
4. Si no existe, crearlo con encabezado obligatorio de 3 líneas.
5. Basarse en cambios reales del workspace, comandos ejecutados, tests corridos, validaciones hechas y documentación tocada.
6. Si faltan datos, explicitarlo como pendiente o no verificado. No inventar validaciones.

## Fuentes a consultar

- `git status`, `git diff --stat`, `git log --oneline` y cambios locales relevantes
- terminal activa si hay comandos recientes útiles para documentar
- archivos modificados o creados en el día
- documentación relacionada en `docs/`
- tests o validaciones efectivamente ejecutadas

## Estructura esperada del documento

Usar esta estructura base y adaptarla al contenido real del día. Si una sección no aplica, omitirla o dejarla explícitamente como no aplica.

```markdown
# Nombre de archivo: YYYY-MM-DD.md
# Ubicación de archivo: docs/PR/YYYY-MM-DD.md
# Descripción: PR diario del YYYY-MM-DD

# PR Diario - YYYY-MM-DD

## Resumen de Cambios

[Síntesis breve de los cambios más relevantes]

## Contexto y Alcance

- **Módulos afectados**: [lista concreta]
- **Objetivo**: [qué se buscó resolver]
- **Supuestos**: [si aplica]

## Cambios Realizados

- [Archivo o grupo de archivos]: [cambio realizado]
- [Endpoint, servicio o flujo]: [cambio realizado]

## Comandos Ejecutados

- `comando 1`
  - Resultado: [salida útil o efecto]
- `comando 2`
  - Resultado: [salida útil o efecto]

## Criterios de Aceptación

- [x] [criterio validado]
- [ ] [criterio pendiente]

## Impacto y Riesgos

- **Impacto operativo**: [efecto en usuario, servicio, DX o despliegue]
- **Riesgos conocidos**: [riesgo real o "Sin riesgos adicionales identificados"]
- **Seguridad y datos**: [si hay efecto sobre secretos, exposición, permisos, DB, PII]

## Compatibilidad y Migraciones

- **DB/Alembic**: [si aplica]
- **Dependencias**: [si aplica]
- **Breaking changes**: [si aplica]

## Validación Manual

- [Paso o evidencia real]
- [Paso o evidencia real]

## Próximos Pasos

- [Siguiente tarea o deuda técnica]
- [Seguimiento recomendado]
```

## Reglas obligatorias

1. Usar español técnico, concreto y sin relleno.
2. No inventar tests, comandos, despliegues ni validaciones.
3. Priorizar formato y terminología ya presentes en `docs/PR/`.
4. Incluir `## Comandos Ejecutados` cuando existan comandos relevantes en la sesión o en la tarea.
5. Incluir `## Impacto y Riesgos` siempre, aunque sea para dejar explícito que no se detectaron riesgos adicionales.
6. Si hubo migraciones, cambios de puertos, dependencias o variables de entorno, reflejarlo en compatibilidad.
7. Mantener el encabezado obligatorio de 3 líneas al inicio del archivo.
8. No incluir secretos, tokens, credenciales ni rutas sensibles.

## Criterios de calidad para la redacción

- Resumir primero y detallar después.
- Agrupar cambios por componente o flujo, no por orden accidental.
- Cuando el día incluya varias etapas, usar subtítulos por etapa solo si aclaran la lectura.
- Si existe un PR diario previo para la fecha, conservar lo útil y anexar únicamente el delta nuevo.

## Salida esperada

1. Crear o actualizar `docs/PR/YYYY-MM-DD.md`.
2. Mostrar un resumen corto con:
   - archivo actualizado
   - secciones incorporadas o fusionadas
   - riesgos o pendientes que quedaron explicitados
