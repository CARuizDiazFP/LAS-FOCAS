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

Qué corre en cada imagen (ver la cabecera de `common-requirements.txt`):

- `common-requirements.txt` → **`focas-base`**, la base de api, web, bot, nlp_intent y todos los workers.
  Es el manifest más importante y el que más fácil se olvida. Hasta el 2026-10-26 ni la CI ni esta
  skill lo auditaban, así que `redis` y `asyncpg` nunca pasaron por `pip-audit`.
- `api/requirements.txt`, `web/requirements.txt`, `bot_telegram/requirements.txt` y
  `modules/*/requirements.txt` → se instalan encima de `focas-base` en el Dockerfile de cada servicio.
- `office_service/requirements.txt` → imagen propia, con LibreOffice.
- `requirements.txt` (raíz) y `requirements-dev.txt` → sólo el venv local y la CI; ningún Dockerfile los usa.
- `web/frontend/package.json`
- Inventario real: `grep -rn "requirements\|pip install" deploy/docker/*.Dockerfile */Dockerfile`. Ahí aparecen
  también los paquetes instalados inline (hoy sólo el bloque `pip install` de `deploy/docker/base.Dockerfile`).

## Procedimiento

1. Inventariar manifests presentes y diferenciar runtime de desarrollo.
2. Ejecutar `pip-audit` sobre cada archivo `requirements*.txt` relevante.
3. Revisar `npm audit` en `web/frontend` cuando el alcance incluya frontend o el repo completo.
4. Verificar pins débiles, rangos abiertos o dependencias duplicadas entre servicios.
5. Clasificar impacto: ejecución remota, SSRF, XSS, fuga de secretos, DoS o cadena de suministro.
6. Sugerir cambio mínimo: versión segura, pin explícito, aislamiento temporal o compensación operativa.

## Comandos de referencia

**Correr `pip-audit` en un contenedor Python 3.11 y no en el `.venv`.** El venv es Python 3.13, el único
intérprete del host, y las imágenes son 3.11. `pip-audit -r` instala los pins para resolver dependencias
transitivas, y asyncpg 0.29.0, pandas 2.2.2, pyproj 3.6.1 y psycopg-binary 3.2.1 no tienen wheel cp313. Usar
**JSON por archivo** y resumir después: la salida en tabla tiene una línea por CVE (hubo 63 sólo en
`common-requirements.txt`), así que un `| tail` la trunca y se pierden paquetes enteros. Pasó el
2026-10-26 y hubo que repetir la corrida.

```bash
OUT=<scratchpad>/audit; mkdir -p "$OUT"
docker run --rm -v "$PWD":/w:ro -v "$OUT":/out --entrypoint sh python:3.11-slim-bookworm -c '
  pip install -q pip-audit==2.7.3
  for f in common-requirements.txt requirements.txt requirements-dev.txt api/requirements.txt \
           web/requirements.txt bot_telegram/requirements.txt office_service/requirements.txt \
           modules/*/requirements.txt; do
    (cd /w && pip-audit -r "$f" -f json --progress-spinner off > "/out/$(echo $f | tr / _).json")
    echo "$f rc=$?"
  done'
# resumen: paquete, versión, cantidad de vulns y fix mínimo/máximo por archivo (leer los JSON con python)
cd web/frontend && npm audit --audit-level=high
```

`rc=1` significa que hay hallazgos, no que falló la herramienta. `nlp_intent/requirements.txt` no tiene
paquetes y no hace falta auditarlo.

## Hallazgos esperados

- dependencias con CVE confirmado
- librerías sin pin estricto o con rango excesivo
- discrepancias entre manifests que compliquen el parcheo

## Guardrails

1. No recomendar `latest` como solución.
2. No sugerir upgrades mayores sin advertir posible impacto de compatibilidad.
3. Un pin se fija en la versión que **ya corre** en la imagen (`docker run --rm --entrypoint pip <imagen> list`),
   no en la última publicada: pasar de un rango a un pin no debe cambiar el comportamiento. Subir la versión es
   otro cambio, con su propia validación.
4. No reinstalar el `.venv` compartido para "alinearlo" con las imágenes sin preguntar: lo usan todas las
   sesiones, y con Python 3.13 algunos pins de las imágenes no se pueden instalar (decisión del usuario,
   2026-10-26: no se reinstala, el drift queda documentado en la cabecera de `requirements.txt`).
3. No tratar dependencias de desarrollo como equivalentes a runtime sin aclararlo.