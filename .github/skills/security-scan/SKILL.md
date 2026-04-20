# Nombre de archivo: SKILL.md
# Ubicación de archivo: .github/skills/security-scan/SKILL.md
# Descripción: Skill paraguas para escaneos integrales de seguridad en LAS-FOCAS

---
name: security-scan
description: "Usar cuando haya que ejecutar una revisión integral de seguridad, correlacionar secretos, dependencias, SAST y proponer mitigaciones"
argument-hint: "Describe el alcance, por ejemplo: escaneo integral de api y deploy con foco en credenciales y red"
---

# Habilidad: Security Scan

Workflow reusable para auditorías de seguridad de punta a punta en LAS-FOCAS.

## Cuándo usar

- cuando el alcance combine código, despliegue y configuración
- cuando haya que revisar un feature nuevo antes de merge o release
- cuando se necesite un reporte único con severidad y parche sugerido

## Skills que coordina

- [dependency-audit](../dependency-audit/SKILL.md)
- [secret-detection](../secret-detection/SKILL.md)
- [sast-analysis](../sast-analysis/SKILL.md)

## Procedimiento

1. Delimitar alcance técnico: carpetas, servicios, manifests y superficies expuestas.
2. Ejecutar primero [secret-detection](../secret-detection/SKILL.md) sobre `.env`, despliegue, Docker, `Keys/` y scripts.
3. Continuar con [dependency-audit](../dependency-audit/SKILL.md) sobre `requirements*.txt`, manifests de servicios y `web/frontend/package.json` si aplica.
4. Ejecutar [sast-analysis](../sast-analysis/SKILL.md) sobre endpoints, validación de entradas, auth, subprocess, SQL y logging sensible.
5. Correlacionar hallazgos por componente, explotación posible e impacto operativo.
6. Proponer mitigación o parche mínimo por cada hallazgo importante o crítico.
7. Emitir salida final con severidad, evidencia, fix sugerido y riesgos residuales.

## Criterios de salida

- Hallazgos ordenados por `Critical`, `High`, `Medium`, `Low`.
- Secretos enmascarados; nunca completos.
- Distinción clara entre hallazgo confirmado, sospecha y recomendación.
- Cobertura declarada: qué rutas, manifiestos o servicios sí quedaron revisados.

## Guardrails

1. No asumir seguridad por ausencia de alertas automáticas en CI.
2. No repetir pasos detallados si basta con invocar la skill específica.
3. No devolver consejos genéricos sin evidencia del repo.
4. No omitir el parche sugerido cuando el hallazgo es accionable.