---
name: secret-detection
description: "Usar cuando haya que buscar credenciales expuestas, secretos en .env, llaves, tokens, compose, scripts o configuraciones sensibles"
argument-hint: "Describe el objetivo, por ejemplo: revisar .env, compose, Keys y workflows por exposición de credenciales"
---

# Nombre de archivo: SKILL.md
# Ubicación de archivo: .agents/skills/secret-detection/SKILL.md
# Descripción: Skill para detectar secretos y credenciales expuestas en LAS-FOCAS (mirror Agent Skills de .agentes-comunes/skills/secret-detection/SKILL.md — fuente de verdad)

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
5. Ejecutar `./scripts/check_no_plaintext_secrets.sh` si existe y tomar su salida como gate bloqueante
   (exit real sin pipe: `bash scripts/check_no_plaintext_secrets.sh; echo "EXIT=$?"`). En `dev` da 0
   desde P26 (2026-11-02); hasta entonces daba 1 siempre por falsos positivos y enseñaba a ignorarlo.
6. Reportar exposición, alcance, vector y parche sugerido.

## Qué cuenta como literal en `check_no_plaintext_secrets.sh`

La regla de asignaciones (`POSTGRES_PASSWORD`, `SMTP_PASS`, `WEB_SECRET_KEY` y `LAS_FOCAS_API_KEY`
seguidas de `=`, y `OPENAI_API_KEY` con valor `sk-…`) decide **por asignación, no por línea** (`grep -P`
con lookahead negativo). No cuentan: valor vacío, el placeholder `cambiar_por_…` y lo que el shell
resuelve al correr —`"$(cat .secrets/…)"`, `$(…)`, `"$VAR"`, `$VAR`, `${VAR}` y la comilla invertida
(sustitución clásica; en Markdown, `` `CLAVE=` `` es un código que termina ahí)—. Un literal al lado de un
`$(…)` en la misma línea **sí** se detecta.

- Un literal falso a propósito (valor de un test) se declara en su línea con
  `# secreto-ok: <motivo>`; auditar los marcadores con `git grep -n 'secreto-ok:'`. Ejemplo real:
  `tests/test_agent_worktree.py` (`Dev_secreto_no_mostrar`, que el test busca en la salida).
- No reescribir un valor para que la regex no lo vea (concatenar la clave, partir el string): eso
  esconde el caso en vez de declararlo. Excepción: tests del propio chequeo, que arman la clave con
  `{clave}` porque cada caso es un fixture.
- No agregar rutas excluidas para silenciar una coincidencia: esconde archivos enteros.
- `tests/test_check_no_plaintext_secrets.py` corre el script contra un repo git temporal (positivos y
  negativos por cada clave). Al cambiar la regla, agregar ahí el caso nuevo y verificar que el test
  **falla con la versión anterior** del script (copiarla con `git show HEAD:…` y apuntar `SCRIPT` a ella).
- El script usa `grep -P` (GNU grep). En la shell de Claude Code `grep` puede ser una función que llama a
  `ugrep`: probar la regex con `bash -c '…'` o `/usr/bin/grep`, que es lo que ve el script.

## Comandos de referencia

```bash
rg -n --hidden --glob '!*.pyc' --glob '!node_modules/**' '(password|secret|token|api[_-]?key|authorization|bearer|private[_-]?key)'
rg -n --hidden --glob '.env*' --glob 'deploy/*.sample' '.'
rg -n --hidden 'sk-[A-Za-z0-9_-]+'
git ls-files | rg '(^|/)\.env($|\.)|Keys/|credentials|\.pem$|\.key$'
./scripts/check_no_plaintext_secrets.sh
```

## Qué confirmar antes de elevar un hallazgo

- si el valor parece real o solo placeholder
- si el archivo está trackeado por git o es exclusivamente local
- si el secreto se replica en docs, tests o pipelines

## Guardrails

1. Nunca mostrar el secreto completo en la respuesta.
2. Priorizar parche accionable: rotación, invalidación, mover a secret store o reemplazar por placeholder.
3. No tratar ejemplos explícitamente ficticios como incidente real sin evidencia adicional.
