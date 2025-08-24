# Nombre de archivo: ci.md
# Ubicación de archivo: docs/ci.md
# Descripción: Detalle del flujo de integración continua con GitHub Actions

## Flujo de CI

El proyecto ejecuta un flujo de **integración continua** mediante GitHub Actions. Este flujo se activa en cada **push** y **pull request** e incluye los siguientes pasos:

1. **Checkout** del repositorio.
2. **Instalación de dependencias** definidas en `requirements.txt`.
3. **Auditoría de dependencias** con `pip-audit`.
4. Ejecución de las **pruebas** con `pytest` generando reporte de cobertura.
5. **Carga** del archivo `coverage.xml` como artefacto de la ejecución.
6. Análisis de estilo y calidad de código con **`ruff`**.
7. Construcción de las imágenes Docker de **API** y **Web**.

Además, de forma manual puede activarse un job `trivy-scan` que recompila las imágenes y las analiza con `trivy` en busca de vulnerabilidades.

La finalidad es garantizar que el código pase las pruebas automatizadas y cumpla las reglas de estilo antes de integrarse en la rama principal.

## Pruebas en contenedores

El job `build-images` compila las imágenes `las-focas-api:ci` y `las-focas-web:ci` usando `docker build`. Este paso detecta de forma temprana errores en los `Dockerfile` y asegura que los servicios puedan ejecutarse en contenedores.

## Reportes y políticas de bloqueo

- **`pip-audit`** genera un listado de dependencias vulnerables junto con la severidad y el identificador de cada CVE. Cualquier vulnerabilidad detectada provoca el fallo del job `test`, bloqueando el merge hasta que se actualicen las dependencias afectadas.
- **`trivy`** muestra vulnerabilidades del sistema base y de los paquetes presentes en las imágenes. El job `trivy-scan` es opcional y está marcado con `continue-on-error`, por lo que sus hallazgos no detienen el flujo de CI. Se recomienda corregir las vulnerabilidades críticas y volver a ejecutar el análisis.
