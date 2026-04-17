# Nombre de archivo: revisar-seguridad.prompt.md
# Ubicación de archivo: .github/prompts/revisar-seguridad.prompt.md
# Descripción: Prompt para auditoría de seguridad del proyecto

---
name: Revisar Seguridad
description: "Realiza una auditoría de seguridad del repo o de un subconjunto de archivos y devuelve hallazgos priorizados"
argument-hint: "Alcance y opcionalmente archivos, por ejemplo: dependencies y deploy/compose.yml"
agent: "agent"
---

# Auditoría de Seguridad - LAS-FOCAS

Realizar una revisión de seguridad del proyecto según el alcance indicado por el usuario. Si no se especifica alcance, asumir revisión general del repo.

## Objetivo

- detectar secretos expuestos, configuraciones riesgosas y dependencias vulnerables
- verificar superficies expuestas, logging sensible y validación de entradas
- devolver hallazgos primero, ordenados por severidad, con acciones sugeridas

## Entradas esperadas

- alcance: `full`, `dependencies`, `secrets`, `network`, `files` o similar
- archivos o carpetas concretas si la revisión es acotada
- contexto de despliegue si el usuario lo aporta

## Flujo de trabajo

### 1. Auditoría de dependencias

```bash
pip-audit -r requirements.txt
pip-audit -r api/requirements.txt
pip-audit -r nlp_intent/requirements.txt
pip-audit -r bot_telegram/requirements.txt
pip-audit -r office_service/requirements.txt
```

### 2. Búsqueda de secretos expuestos

```bash
grep -r -E "(password|secret|token|api_key|apikey|auth)" --include="*.py" --include="*.yml" --include="*.yaml" --include="*.json" .
grep -r -E "['\"][A-Za-z0-9_-]{20,}['\"]" --include="*.py" .
git ls-files | grep -E "\.env$"
grep -E "(\.env|secrets|credentials|\.pem|\.key)" .gitignore
```

### 3. Configuración de red y puertos

```bash
grep -A5 "ports:" deploy/compose.yml
grep -E "(expose|ports):" deploy/compose.yml
```

### 4. Permisos, usuarios y prácticas peligrosas

```bash
grep -l "USER" */Dockerfile deploy/docker/Dockerfile.*
grep -r "sudo\|chmod 777\|chown.*root" --include="*.sh" --include="*.py" .
```

### 5. Logging y datos sensibles

```bash
grep -r -E "(print\(|logger\.(info|debug|warning|error))" --include="*.py" . | head -50
grep -r "LOG_RAW_TEXT" --include="*.py" .
```

### 6. Validación de entrada y queries

```bash
grep -r "@app\.\(get\|post\|put\|delete\)" --include="*.py" -A3 . | grep -v "BaseModel\|Pydantic"
```

## Reglas obligatorias

1. Reportar hallazgos primero, ordenados por severidad.
2. Incluir archivo o componente afectado cuando sea posible.
3. No exponer secretos completos en la respuesta; enmascararlos.
4. Distinguir entre hallazgos confirmados, sospechas y recomendaciones.
5. Si no se encuentra ningún hallazgo, decirlo explícitamente y mencionar riesgos residuales o gaps de cobertura.

## Checklist de revisión

- [ ] No hay secretos expuestos en código o git
- [ ] Dependencias críticas revisadas
- [ ] Servicios internos no están expuestos indebidamente
- [ ] Logging no filtra datos sensibles
- [ ] Validación de entrada y acceso a datos revisados

## Salida esperada

1. Listar hallazgos críticos, importantes y recomendaciones.
2. Indicar evidencia o comando usado cuando aporte valor.
3. Resumir estado general y cobertura de la revisión.
4. Si aplica, proponer actualización de `docs/Seguridad.md`.
