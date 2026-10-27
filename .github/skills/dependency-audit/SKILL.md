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

- `common-requirements.txt` → **`focas-base`**, la base de api, web, nlp_intent y todos los workers.
  Es el manifest más importante y el que más fácil se olvida. Hasta el 2026-10-26 ni la CI ni esta
  skill lo auditaban, así que `redis` y `asyncpg` nunca pasaron por `pip-audit`.
- `api/requirements.txt`, `web/requirements.txt` y
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
docker run --rm -v "$PWD":/w:ro -v "$OUT":/out -w /w --entrypoint sh python:3.11-slim-bookworm -c '
  pip install -q pip-audit==2.7.3
  for f in common-requirements.txt requirements.txt requirements-dev.txt api/requirements.txt \
           web/requirements.txt office_service/requirements.txt \
           modules/*/requirements.txt; do
    pip-audit -r "$f" -f json --progress-spinner off > "/out/$(echo $f | tr / _).json"
    echo "$f rc=$?"
  done'
# resumen: paquete, versión, cantidad de vulns y "mínima que cierra todas" = máximo, entre los CVEs,
# del menor fix_version de cada uno (leer los JSON con python)
cd web/frontend && npm audit --omit=dev && npm audit
```

`rc=1` significa que hay hallazgos, no que falló la herramienta. `nlp_intent/requirements.txt` no tiene
paquetes y no hace falta auditarlo. El `-w /w` es obligatorio: sin él, el glob `modules/*/requirements.txt`
se expande en `/` del contenedor, no matchea y los cuatro workers **no se auditan** (`rc=2`, JSON vacío).
Pasó el 2026-10-26 con la receta anterior, que hacía `cd /w` recién dentro del loop.

**Auditar también lo que corre en las imágenes.** `pip-audit -r` resuelve las transitivas a las versiones de
hoy, pero una imagen vieja conserva las que tenía al construirse. El 2026-10-26, la imagen del bot de Telegram (de cuatro
días antes, ya retirada) tenía `certifi` y `urllib3` vulnerables que ningún requirements mostraba:

```bash
OUT=<scratchpad>/audit_img; mkdir -p "$OUT"
for i in web api nlp_intent office cromo_worker slack_baneo_worker botellas_recalculo_worker fo_monitor_worker; do
  docker run --rm --entrypoint pip lasfocasdev-$i:latest freeze | grep -v '^-e\|@ file' > "$OUT/$i.txt"
done
docker run --rm -v "$OUT":/w -w /w --entrypoint sh python:3.11-slim-bookworm -c '
  pip install -q pip-audit==2.7.3
  for f in *.txt; do pip-audit -r "$f" --no-deps --disable-pip -f json --progress-spinner off > "${f%.txt}.json"; done'
```

**Antes de cambiar un pin, verificar que los manifests se puedan instalar juntos.** La CI instala
`requirements.txt`, `common-requirements.txt`, `api`, `web`, `requirements-dev.txt` y
`modules/cromo_worker` en un solo `pip install`. Del 2026-10-26 (pins de P06) a P15 no se pudo resolver:
`requirements.txt` fijaba `slack_sdk==3.33.5` mientras `requirements-dev.txt` traía `slack_bolt==1.30.0`
(exige `slack_sdk>=3.38`) y los workers usaban 3.45.0. Probar el `pip install` combinado en un contenedor 3.11.

## Validar una subida de versiones: suite actual vs. nueva, en contenedor 3.11

El `.venv` del host (3.13) no sirve para esto. El método es correr la suite dos veces en
`python:3.11.16-slim-bookworm` (misma base que `focas-base`): una con el árbol de `origin/dev` y otra con
el de la rama. Las dos instalan los pins de la línea de la CI y escriben `--junitxml`. Las fallas nuevas
son las que fallan en la nueva y no en la vieja; los errores de entorno se repiten en las dos y se
cancelan. Real 2026-10-26, P15: 4231 passed en ambas y 0 nuevas. Los 88 errores comunes eran tests de
tooling git, porque la imagen slim no trae `git`.

```bash
git archive origin/dev | tar -x -C <scratchpad>/src_base          # árbol viejo
git ls-files -z | tar --null -T - -cf - | tar -x -C <scratchpad>/src_new   # árbol de la rama
# por cada árbol (de a uno: ver disco abajo):
docker run --rm -v <src>:/src -v <out>:/out --entrypoint sh python:3.11.16-slim-bookworm -c '
  cd /src && pip install -q -r common-requirements.txt -r requirements.txt -r api/requirements.txt \
    -r web/requirements.txt -r requirements-dev.txt \
    -r modules/cromo_worker/requirements.txt
  LLM_PROVIDER=heuristic pytest -q -p no:cacheprovider --junitxml=/out/junit.xml > /out/pytest.log 2>&1'
# comparar los dos junit.xml por classname::name con python (pass/skip/failure/error)
```

- **Disco**: cada contenedor de la suite ocupa ~1,1 GB mientras corre. En este host (40 GB, prod incluido)
  correr las dos suites y un build en paralelo lo llenó en medio del cierre de otra sesión (ver
  `disk-analysis`). Hay que correr de a uno y mirar `df -h /` antes de cada corrida.
- Con las imágenes ya reconstruidas, el humo y los `rmi` del final siguen la receta de `docker-rebuild`
  ("Probar una `focas-base` nueva sin pisar `focas-base:latest`").
- Repetir el `pip-audit` **después** de subir los pins. GitHub y PyPI pueden fijar distinto el fix del
  mismo CVE: con CVE-2025-67221, PyPI daba orjson 3.11.5 y GHSA-hx9q-6w63-j58v daba 3.11.6, y el segundo
  aviso apareció recién en la auditoría final.

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
5. No tratar dependencias de desarrollo como equivalentes a runtime sin aclararlo.
6. Un paquete que hoy llega como transitiva y se sube por un CVE se fija **explícito** en el manifest
   (p. ej. `starlette` bajo `fastapi`): si no, el próximo rebuild puede resolver otra versión.
7. Al subir fastapi, mirar si cambia `router.routes`: desde 0.137 es un árbol y unos 20 tests lo recorren
   como lista plana. Por eso P15 (2026-10-26) se quedó en 0.136.1, que ya admite starlette 1.x.