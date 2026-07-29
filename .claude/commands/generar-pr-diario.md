# Nombre de archivo: generar-pr-diario.md
# Ubicación de archivo: .claude/commands/generar-pr-diario.md
# Descripción: Comando Claude Code para generar o actualizar el PR diario en docs/PR/

Genera o actualiza el archivo `docs/PR/YYYY-MM-DD.md`. Argumento opcional: $ARGUMENTS (fecha YYYY-MM-DD y/o contexto de cambios; por defecto usa la fecha actual).

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
5. Basarse en cambios reales del workspace: comandos ejecutados, tests corridos, validaciones hechas y documentación tocada.
6. Si faltan datos, explicitarlo como pendiente o no verificado. No inventar validaciones.

## Fuentes a consultar

```bash
git status
git diff --stat
git log --oneline -10
```

También: archivos modificados o creados en el día, documentación relacionada en `docs/`, tests o validaciones efectivamente ejecutadas.

## Estructura esperada del documento

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

## Cambios Realizados
- [Archivo o grupo de archivos]: [cambio realizado]

## Comandos Ejecutados
- `comando`
  - Resultado: [salida útil o efecto]

## Criterios de Aceptación
- [x] [criterio validado]
- [ ] [criterio pendiente]

## Impacto y Riesgos
- **Impacto operativo**: [efecto en usuario, servicio o despliegue]
- **Riesgos conocidos**: [riesgo real o "Sin riesgos adicionales identificados"]
- **Seguridad y datos**: [si hay efecto sobre secretos, permisos, DB o PII]

## Compatibilidad y Migraciones
- **DB/Alembic**: [si aplica]
- **Dependencias**: [si aplica]
- **Breaking changes**: [si aplica]

## Validación Manual
- [Paso o evidencia real]

## Próximos Pasos
- [Siguiente tarea o deuda técnica]
```

## Reglas obligatorias

1. Usar español técnico, concreto y sin relleno.
2. No inventar tests, comandos, despliegues ni validaciones.
3. Incluir `## Impacto y Riesgos` siempre, aunque sea para confirmar que no hay riesgos adicionales.
4. Si hubo migraciones, puertos, dependencias o variables de entorno, reflejarlo en compatibilidad.
5. No incluir secretos, tokens, credenciales ni rutas sensibles.
6. Si existe un PR diario previo para la fecha, conservar lo útil y anexar solo el delta nuevo.

## Salida esperada

1. Crear o actualizar `docs/PR/YYYY-MM-DD.md`.
2. Mostrar un resumen corto: archivo actualizado, secciones incorporadas o fusionadas, riesgos o pendientes explicitados.
