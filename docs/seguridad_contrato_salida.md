# Nombre de archivo: seguridad_contrato_salida.md
# Ubicación de archivo: docs/seguridad_contrato_salida.md
# Descripción: Contrato unificado de salida para auditorías de seguridad del ecosistema agéntico

# Contrato Unificado de Salida de Seguridad

## Objetivo

Definir un formato único para reportar resultados de seguridad desde prompts y skills, reduciendo drift semántico entre `security-scan` y `revisar-seguridad`.

## Estructura obligatoria del reporte

1. Resumen ejecutivo:
   - alcance auditado
   - estado general (sin hallazgos críticos / con hallazgos críticos)
2. Hallazgos por severidad:
   - `Critical`
   - `High`
   - `Medium`
   - `Low`
3. Cobertura:
   - rutas/servicios revisados
   - rutas/servicios fuera de alcance
4. Riesgo residual:
   - riesgos abiertos luego de mitigaciones propuestas
5. Plan de mitigación priorizado:
   - acción
   - responsable sugerido
   - urgencia

## Estructura de cada hallazgo

Cada hallazgo debe incluir:

1. ID: `SEC-YYYYMMDD-<n>`.
2. Severidad: `Critical|High|Medium|Low`.
3. Evidencia:
   - archivo/ruta
   - comando o validación usada
4. Impacto:
   - seguridad
   - operativo
5. Mitigación mínima sugerida.
6. Estado:
   - `Confirmado`
   - `Sospecha`
   - `Recomendación`

## Reglas de consistencia

1. Hallazgos ordenados de mayor a menor severidad.
2. Nunca exponer secretos completos; siempre enmascarar.
3. No mezclar hallazgos confirmados con hipótesis sin etiquetar.
4. Si no hay hallazgos, declarar explícitamente “sin hallazgos críticos/high” y detallar gaps de cobertura.

## Formato sugerido (plantilla)

```markdown
## Resumen ejecutivo
- Alcance:
- Estado:

## Hallazgos
### Critical
- [SEC-YYYYMMDD-1] Título
  - Evidencia:
  - Impacto:
  - Mitigación:
  - Estado:

### High
- ...

### Medium
- ...

### Low
- ...

## Cobertura
- Revisado:
- Fuera de alcance:

## Riesgo residual
- ...

## Plan de mitigación priorizado
1. ...
2. ...
```
