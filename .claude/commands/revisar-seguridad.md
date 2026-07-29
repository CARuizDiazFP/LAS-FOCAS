# Nombre de archivo: revisar-seguridad.md
# Ubicación de archivo: .claude/commands/revisar-seguridad.md
# Descripción: Comando Claude Code para auditoría proactiva de seguridad

Realiza una auditoría de seguridad del proyecto. Argumento opcional: $ARGUMENTS (alcance y foco; por ejemplo: "full con prioridad en .env y rutas FastAPI"; por defecto: revisión integral).

## Objetivo

- detectar secretos expuestos, configuraciones riesgosas y dependencias vulnerables
- revisar código con enfoque SAST sobre inputs, auth, queries, logging y ejecución de procesos
- devolver hallazgos ordenados por severidad con parche o mitigación sugerida

## Flujo de trabajo

### 1. Delimitar superficie de ataque

- identificar servicios, rutas, scripts, manifests y configuraciones tocadas
- priorizar `.env`, `deploy/compose.yml`, Dockerfiles, `Keys/`, `.github/workflows/`, `.claude/` y autenticación/sesiones

### 2. Detección de secretos y credenciales

```bash
rg -n --hidden --glob '!*.pyc' --glob '!node_modules/**' '(password|secret|token|api[_-]?key|authorization|bearer|private[_-]?key)'
git ls-files | rg '(^|/)\.env($|\.)|Keys/|credentials|\.pem$|\.key$'
```

### 3. Auditoría de dependencias

```bash
source .venv/bin/activate
pip-audit -r requirements.txt
pip-audit -r requirements-dev.txt
pip-audit -r api/requirements.txt
pip-audit -r nlp_intent/requirements.txt
pip-audit -r bot_telegram/requirements.txt
pip-audit -r office_service/requirements.txt
cd web/frontend && npm audit --audit-level=high
```

### 4. SAST de código

```bash
rg -n '@app\.(get|post|put|delete)|@router\.(get|post|put|delete)' api web
rg -n 'subprocess|os\.system|shell=True|eval\(|exec\(|yaml\.load\(|pickle\.loads' core api web modules bot_telegram
rg -n 'Authorization|SessionMiddleware|secret_key|password|token|LOG_RAW_TEXT' core api web nlp_intent bot_telegram
```

### 5. Hardening de contenedores y red

```bash
rg -n 'ports:|expose:|privileged:|user:|read_only:|no-new-privileges|cap_drop' deploy/compose.yml
rg -n 'chmod 777|sudo|chown.*root' scripts deploy .
```

### 6. Correlación y parche sugerido

- Correlacionar hallazgos entre código, configuración y despliegue
- Proponer fix concreto: rotación, pin de versión, validación adicional, cambio de permisos
- Distinguir hallazgo confirmado, sospecha y recomendación

## Tabla de severidad

| Severidad | Criterio | Acción |
|---|---|---|
| Critical | Secreto real expuesto, RCE, bypass de auth | Parche inmediato |
| High | Validación insuficiente, dependencia con exploit viable | Corregir antes de merge |
| Medium | Configuración insegura compensable, logging riesgoso | Plan priorizado |
| Low | Mejora preventiva sin explotación clara | Registrar y calendarizar |

## Reglas obligatorias

1. Reportar hallazgos ordenados por severidad.
2. Incluir archivo o componente afectado cuando sea posible.
3. No exponer secretos completos; enmascararlos.
4. Distinguir entre hallazgos confirmados, sospechas y recomendaciones.
5. Si no se encuentra ningún hallazgo, decirlo explícitamente y mencionar gaps de cobertura.

## Checklist de revisión

- [ ] No hay secretos expuestos en código o git
- [ ] Dependencias críticas revisadas
- [ ] Inputs sensibles revisados con enfoque SAST
- [ ] Servicios internos no están expuestos indebidamente
- [ ] Logging no filtra datos sensibles
- [ ] Validación de entrada, auth y acceso a datos revisados

## Salida esperada

1. Hallazgos críticos, altos, medios y bajos listados.
2. Evidencia o comando usado cuando aporte valor.
3. Parche o mitigación por cada hallazgo importante o crítico.
4. Estado general y cobertura de la revisión.
5. Propuesta de actualización de `docs/Seguridad.md` si aplica.

## Skills de referencia

Ver detalle en: `security-scan`, `secret-detection`, `dependency-audit`, `sast-analysis` en `.github/skills/`.
