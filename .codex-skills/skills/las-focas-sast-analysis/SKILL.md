---
name: "las-focas-sast-analysis"
description: "Usar cuando haya que revisar código por validación de entradas, auth, SQL, subprocess, deserialización, logging sensible, XSS/CORS o superficie de ataque"
metadata:
  short-description: "Usar cuando haya que revisar código por validación de entradas, auth, SQL, subprocess, deserialización, logging sensi..."
  source: ".agentes-comunes/skills/sast-analysis/SKILL.md"
  triggers:
    - "sast-analysis"
    - "habilidad"
    - "sast"
    - "analysis"
    - "c-digo"
    - "validaci-n"
    - "entradas"
    - "auth"
    - "sql"
    - "subprocess"
    - "deserializaci-n"
    - "logging"
    - "sensible"
    - "superficie"
    - "ataque"
  globs:
    - "api/**"
    - "web/**"
    - "core/**"
    - "modules/**"
    - "bot_telegram/**"
  commands:
    - |
      rg -n '@app\.(get|post|put|delete)|@router\.(get|post|put|delete)' api web
      rg -n 'subprocess|os\.system|shell=True|eval\(|exec\(|yaml\.load\(|pickle\.loads|text\(' core api web modules bot_telegram
      rg -n 'Authorization|SessionMiddleware|secret_key|password|token|LOG_RAW_TEXT' core api web nlp_intent bot_telegram
---

# Nombre de archivo: SKILL.md
# Ubicación de archivo: .codex-skills/skills/las-focas-sast-analysis/SKILL.md
# Descripción: Skill portable Codex migrada desde .github/skills/sast-analysis/SKILL.md

# Skill portable: sast-analysis

> Fuente original: `.agentes-comunes/skills/sast-analysis/SKILL.md`. Copia portable generada porque `.codex/` está montado como solo lectura en esta sesión.

# Habilidad: SAST Analysis

Checklist de análisis estático orientado a riesgos explotables en el código.

## Superficies prioritarias

- endpoints REST, WebSocket y handlers de bot expuestos a entrada de usuario
- autenticación, autorización, sesiones y cookies
- uso de `v-html`, sanitización de contenido y controles CORS en FastAPI
- acceso a base de datos, queries dinámicas y repositorios
- llamadas a `subprocess`, ejecución de shell, parseo de archivos y renderizado de documentos
- logs que puedan filtrar payloads, secretos o datos personales

## Procedimiento

1. Identificar entradas controladas por usuario y su recorrido hasta sinks sensibles.
2. Revisar validación y sanitización en rutas, modelos y servicios.
3. Buscar patrones de riesgo: SQL dinámico, `subprocess`, path traversal, SSRF, deserialización insegura, XSS/HTML injection y bypass de auth.
4. Verificar permisos en contenedores y acoplamiento con secretos o servicios internos cuando el código despliega o consume infraestructura.
5. Clasificar impacto y proponer parche mínimo verificable.

## Pistas de búsqueda

```bash
rg -n '@app\.(get|post|put|delete)|@router\.(get|post|put|delete)' api web
rg -n 'subprocess|os\.system|shell=True|eval\(|exec\(|yaml\.load\(|pickle\.loads|text\(' core api web modules bot_telegram
rg -n 'Authorization|SessionMiddleware|secret_key|password|token|LOG_RAW_TEXT' core api web nlp_intent bot_telegram
```

## Hallazgos típicos

- inputs sin validación fuerte antes de llegar a DB o shell
- secretos o texto sensible en logs
- contenedores o servicios con privilegios innecesarios desde código/config
- defaults inseguros para sesiones, cookies o providers externos

## Guardrails

1. No marcar como vulnerable un patrón seguro sin revisar el contexto inmediato.
2. No reducir la revisión a grep; seguir el flujo de datos hasta el sink.
3. Acompañar el hallazgo con fix sugerido o condición de explotación.
