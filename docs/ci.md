# Nombre de archivo: ci.md
# Ubicación de archivo: docs/ci.md
# Descripción: Detalle del flujo de integración continua con GitHub Actions

## Flujo de CI

El proyecto ejecuta un flujo de **integración continua** mediante GitHub Actions. Este flujo se activa en cada **push** y **pull request** e incluye los siguientes pasos:

1. **Checkout** del repositorio.
2. **Instalación de dependencias** definidas en `requirements.txt`.
3. Ejecución de las **pruebas** con `pytest` generando reporte de cobertura.
4. **Carga** del archivo `coverage.xml` como artefacto de la ejecución.
5. Análisis de estilo y calidad de código con **`ruff`**.

La finalidad es garantizar que el código pase las pruebas automatizadas y cumpla las reglas de estilo antes de integrarse en la rama principal.
