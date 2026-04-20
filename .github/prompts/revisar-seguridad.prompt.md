# Nombre de archivo: revisar-seguridad.prompt.md
# Ubicación de archivo: .github/prompts/revisar-seguridad.prompt.md
# Descripción: Prompt para auditoría proactiva de seguridad del proyecto

---
name: Revisar Seguridad
description: "Realiza una auditoría safe-by-design del repo o de un subconjunto de archivos con foco en secretos, dependencias, SAST y parches sugeridos"
argument-hint: "Define alcance y foco, por ejemplo: full con prioridad en .env, deploy/compose.yml y rutas FastAPI"
agent: "security"
---

# Auditoría de Seguridad - LAS-FOCAS

Realizar una revisión de seguridad del proyecto según el alcance indicado por el usuario. Si no se especifica alcance, asumir revisión integral del repo con enfoque proactivo y safe-by-design.

## Objetivo

- detectar secretos expuestos, configuraciones riesgosas y dependencias vulnerables
- revisar código con enfoque SAST sobre inputs, auth, queries, logging y ejecución de procesos
- devolver hallazgos primero, ordenados por severidad, con parche o mitigación sugerida

## Entradas esperadas

- alcance: `full`, `dependencies`, `secrets`, `network`, `files` o similar
- archivos o carpetas concretas si la revisión es acotada
- contexto de despliegue si el usuario lo aporta
- criticidad operativa del componente si el usuario la conoce

## Flujo de trabajo

### 1. Delimitar superficie de ataque

- identificar servicios, rutas, scripts, manifests y configuraciones tocadas
- marcar si hay exposición nueva: endpoint, websocket, variable sensible, servicio publicado o credencial
- priorizar `.env`, `deploy/compose.yml`, Dockerfiles, `Keys/`, `.github/workflows/` y autenticación/sesiones

### 2. Detección de secretos y credenciales

```bash
rg -n --hidden --glob '!*.pyc' --glob '!node_modules/**' '(password|secret|token|api[_-]?key|authorization|bearer|private[_-]?key)'
git ls-files | rg '(^|/)\.env($|\.)|Keys/|credentials|\.pem$|\.key$'
```

### 3. Auditoría de dependencias

```bash
pip-audit -r requirements.txt
pip-audit -r requirements-dev.txt
pip-audit -r api/requirements.txt
pip-audit -r nlp_intent/requirements.txt
pip-audit -r bot_telegram/requirements.txt
pip-audit -r office_service/requirements.txt
cd web/frontend && npm audit --audit-level=high
```

### 4. SAST de código y sanitización

```bash
rg -n '@app\.(get|post|put|delete)|@router\.(get|post|put|delete)' api web
rg -n 'subprocess|os\.system|shell=True|eval\(|exec\(|yaml\.load\(|pickle\.loads' core api web modules bot_telegram
rg -n 'Authorization|SessionMiddleware|secret_key|password|token|LOG_RAW_TEXT' core api web nlp_intent bot_telegram
```

### 5. Hardening de contenedores, red y base de datos

```bash
rg -n 'ports:|expose:|privileged:|user:|read_only:|no-new-privileges|cap_drop' deploy/compose.yml deploy/docker api/Dockerfile office_service/Dockerfile
rg -n 'chmod 777|sudo|chown.*root' scripts deploy .
```

### 6. Correlación y parche sugerido

- correlacionar hallazgos entre código, configuración y despliegue
- proponer fix concreto: rotación, pin de versión, validación adicional, cambio de permisos o cierre de puertos
- distinguir hallazgo confirmado, sospecha y recomendación

## Tabla de severidad

| Severidad | Criterio orientativo | Acción esperada |
|---|---|---|
| Critical | Secreto real expuesto, RCE, bypass de auth, servicio sensible publicado | Parche o mitigación inmediata |
| High | Validación insuficiente en sink sensible, dependencia con exploit viable, privilegios excesivos | Corregir antes de merge o release |
| Medium | Configuración insegura compensable, logging riesgoso, pin débil | Plan de corrección priorizado |
| Low | Mejora preventiva o deuda técnica sin explotación clara | Registrar y calendarizar |

## Reglas obligatorias

1. Reportar hallazgos primero, ordenados por severidad.
2. Incluir archivo o componente afectado cuando sea posible.
3. No exponer secretos completos en la respuesta; enmascararlos.
4. Distinguir entre hallazgos confirmados, sospechas y recomendaciones.
5. Si el hallazgo es importante o crítico, sugerir parche o mitigación mínima.
6. Si no se encuentra ningún hallazgo, decirlo explícitamente y mencionar riesgos residuales o gaps de cobertura.

## Checklist de revisión

- [ ] No hay secretos expuestos en código o git
- [ ] Dependencias críticas revisadas
- [ ] Inputs sensibles revisados con enfoque SAST
- [ ] Servicios internos no están expuestos indebidamente
- [ ] Logging no filtra datos sensibles
- [ ] Validación de entrada, auth y acceso a datos revisados
- [ ] Cada hallazgo relevante incluye parche o mitigación sugerida

## Salida esperada

1. Listar hallazgos críticos, importantes, medios y bajos.
2. Indicar evidencia o comando usado cuando aporte valor.
3. Proponer parche o mitigación por cada hallazgo importante o crítico.
4. Resumir estado general y cobertura de la revisión.
5. Si aplica, proponer actualización de `docs/Seguridad.md`.