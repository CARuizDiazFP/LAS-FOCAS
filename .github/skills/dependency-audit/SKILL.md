# Nombre de archivo: SKILL.md
# Ubicación de archivo: .github/skills/dependency-audit/SKILL.md
# Descripción: Skill para auditar dependencias Python y frontend en LAS-FOCAS

---
name: dependency-audit
description: "Usar cuando haya que revisar requirements, package.json, pip-audit, npm audit y versiones expuestas a vulnerabilidades conocidas"
argument-hint: "Describe manifests o servicios, por ejemplo: auditar requirements del repo y frontend antes de release"
---

# Habilidad: Dependency Audit

Guía para revisar dependencias vulnerables y desactualizadas en LAS-FOCAS.

## Objetivo

- identificar CVEs o paquetes con riesgo conocido
- detectar dependencias innecesarias o sin pin estricto
- sugerir upgrade, pin o mitigación temporal cuando el upgrade no sea viable

## Fuentes prioritarias

- `requirements.txt`
- `requirements-dev.txt`
- `api/requirements.txt`
- `bot_telegram/requirements.txt`
- `nlp_intent/requirements.txt`
- `office_service/requirements.txt`
- `web/frontend/package.json`

## Procedimiento

1. Inventariar manifests presentes y diferenciar runtime de desarrollo.
2. Ejecutar `pip-audit` sobre cada archivo `requirements*.txt` relevante.
3. Revisar `npm audit` en `web/frontend` cuando el alcance incluya frontend o el repo completo.
4. Verificar pins débiles, rangos abiertos o dependencias duplicadas entre servicios.
5. Clasificar impacto: ejecución remota, SSRF, XSS, fuga de secretos, DoS o cadena de suministro.
6. Sugerir cambio mínimo: versión segura, pin explícito, aislamiento temporal o compensación operativa.

## Comandos de referencia

```bash
pip-audit -r requirements.txt
pip-audit -r requirements-dev.txt
pip-audit -r api/requirements.txt
pip-audit -r bot_telegram/requirements.txt
pip-audit -r nlp_intent/requirements.txt
pip-audit -r office_service/requirements.txt
cd web/frontend && npm audit --audit-level=high
```

## Hallazgos esperados

- dependencias con CVE confirmado
- librerías sin pin estricto o con rango excesivo
- discrepancias entre manifests que compliquen el parcheo

## Guardrails

1. No recomendar `latest` como solución.
2. No sugerir upgrades mayores sin advertir posible impacto de compatibilidad.
3. No tratar dependencias de desarrollo como equivalentes a runtime sin aclararlo.