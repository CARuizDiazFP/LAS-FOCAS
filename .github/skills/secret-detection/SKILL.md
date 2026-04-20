# Nombre de archivo: SKILL.md
# Ubicación de archivo: .github/skills/secret-detection/SKILL.md
# Descripción: Skill para detectar secretos y credenciales expuestas en LAS-FOCAS

---
name: secret-detection
description: "Usar cuando haya que buscar credenciales expuestas, secretos en .env, llaves, tokens, compose, scripts o configuraciones sensibles"
argument-hint: "Describe el objetivo, por ejemplo: revisar .env, compose, Keys y workflows por exposición de credenciales"
---

# Habilidad: Secret Detection

Workflow enfocado en detectar material sensible expuesto o mal gestionado.

## Prioridades

- archivos `.env`, `.env.*`, `deploy/env.sample` y variables embebidas
- `deploy/compose.yml`, Dockerfiles y scripts de bootstrap
- directorios `Keys/`, `scripts/`, `.github/workflows/` y configuraciones de servicios
- tokens, claves API, passwords, certificados, bearer tokens y secretos MCP

## Procedimiento

1. Buscar archivos sensibles versionados y comparar con políticas del repo.
2. Detectar patrones de secreto en código, YAML, JSON, scripts y documentación.
3. Revisar si el secreto está en ejemplo seguro o en valor real reusable.
4. Verificar si existe mitigación: `.gitignore`, secret store, rotación o variable vacía por defecto.
5. Reportar exposición, alcance, vector y parche sugerido.

## Comandos de referencia

```bash
rg -n --hidden --glob '!*.pyc' --glob '!node_modules/**' '(password|secret|token|api[_-]?key|authorization|bearer|private[_-]?key)'
rg -n --hidden --glob '.env*' --glob 'deploy/*.sample' '.'
rg -n --hidden 'sk-[A-Za-z0-9_-]+'
git ls-files | rg '(^|/)\.env($|\.)|Keys/|credentials|\.pem$|\.key$'
```

## Qué confirmar antes de elevar un hallazgo

- si el valor parece real o solo placeholder
- si el archivo está trackeado por git o es exclusivamente local
- si el secreto se replica en docs, tests o pipelines

## Guardrails

1. Nunca mostrar el secreto completo en la respuesta.
2. Priorizar parche accionable: rotación, invalidación, mover a secret store o reemplazar por placeholder.
3. No tratar ejemplos explícitamente ficticios como incidente real sin evidencia adicional.